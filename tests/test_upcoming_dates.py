"""The `upcoming_dates` answer path (ticket 04).

Date questions are answered by exact query over the derived SpecialDate
index — never by retrieval. The fake embedder maps only the remembered texts,
so any vector search in the answer path would fail loudly.
"""

from datetime import UTC, date, datetime
from pathlib import Path

from conftest import make_keyless_service, make_service
from homelore.domain import ExtractedSpecialDate, Extraction

BIRTHDAY_NOTE = "Mia's birthday is August 3rd"
UNIT = [1.0, 0.0, 0.0]

# conftest.NOW is 2026-07-12.


def test_a_date_in_the_window_is_returned_from_the_index(tmp_path: Path) -> None:
    service, _ = make_service(
        tmp_path,
        vectors={BIRTHDAY_NOTE: UNIT},
        extractions={
            BIRTHDAY_NOTE: Extraction(
                special_dates=(
                    ExtractedSpecialDate(entity="Mia", label="birthday", month=8, day=3),
                )
            )
        },
    )
    service.remember(BIRTHDAY_NOTE, author="Adrian")

    [upcoming] = service.upcoming_dates(days=30)

    assert upcoming.entity == "Mia"
    assert upcoming.label == "birthday"
    assert upcoming.occurs_on == date(2026, 8, 3)


def test_window_is_inclusive_of_today_and_the_last_day(tmp_path: Path) -> None:
    """Today is 2026-07-12, so days=30 covers through 2026-08-11: a same-day
    occurrence and one on the last day are in; one day past the window and a
    date that already passed this year (next occurrence next July) are out."""
    note = "family dates roundup"
    service, _ = make_service(
        tmp_path,
        vectors={note: UNIT},
        extractions={
            note: Extraction(
                special_dates=(
                    ExtractedSpecialDate(entity="Mia", label="name day", month=7, day=12),
                    ExtractedSpecialDate(entity="Ana", label="birthday", month=8, day=11),
                    ExtractedSpecialDate(entity="Leo", label="birthday", month=8, day=12),
                    ExtractedSpecialDate(entity="Adrian", label="birthday", month=7, day=11),
                )
            )
        },
    )
    service.remember(note, author="Adrian")

    upcoming = service.upcoming_dates(days=30)

    assert [(u.entity, u.occurs_on) for u in upcoming] == [
        ("Mia", date(2026, 7, 12)),
        ("Ana", date(2026, 8, 11)),
    ]


def test_a_january_date_surfaces_in_a_december_query(tmp_path: Path) -> None:
    """Leo was born January 5th, 2020: queried from December 2026, his
    birthday recurs on 2027-01-05, and the age he turns counts from the
    occurrence's year, not the query's."""
    note = "Leo's birthday is January 5th"
    service, clock = make_service(
        tmp_path,
        vectors={note: UNIT},
        extractions={
            note: Extraction(
                special_dates=(
                    ExtractedSpecialDate(entity="Leo", label="birthday", month=1, day=5, year=2020),
                )
            )
        },
    )
    service.remember(note, author="Ana")
    clock.now = datetime(2026, 12, 20, 10, 0, 0, tzinfo=UTC)

    [upcoming] = service.upcoming_dates(days=30)

    assert upcoming.occurs_on == date(2027, 1, 5)
    assert upcoming.years == 7


def test_a_leap_day_date_falls_on_february_28_in_non_leap_years(tmp_path: Path) -> None:
    note = "Sam was born on leap day 2020"
    service, clock = make_service(
        tmp_path,
        vectors={note: UNIT},
        extractions={
            note: Extraction(
                special_dates=(
                    ExtractedSpecialDate(
                        entity="Sam", label="birthday", month=2, day=29, year=2020
                    ),
                )
            )
        },
    )
    service.remember(note, author="Adrian")
    clock.now = datetime(2027, 2, 1, 10, 0, 0, tzinfo=UTC)

    [upcoming] = service.upcoming_dates(days=30)

    assert upcoming.occurs_on == date(2027, 2, 28)
    assert upcoming.years == 7


def test_a_known_first_year_yields_the_age_or_anniversary_count(tmp_path: Path) -> None:
    """Mia was born 2019-08-03, so on 2026-08-03 she turns 7; the wedding was
    in 2011, so 2026 is the 15th anniversary. A date with no year has no
    count — better absent than guessed."""
    note = "dates with years"
    service, _ = make_service(
        tmp_path,
        vectors={note: UNIT},
        extractions={
            note: Extraction(
                special_dates=(
                    ExtractedSpecialDate(entity="Mia", label="birthday", month=8, day=3, year=2019),
                    ExtractedSpecialDate(
                        entity="Ana", label="wedding anniversary", month=7, day=20, year=2011
                    ),
                    ExtractedSpecialDate(entity="Leo", label="name day", month=7, day=15),
                )
            )
        },
    )
    service.remember(note, author="Adrian")

    upcoming = service.upcoming_dates(days=30)

    assert [(u.entity, u.years) for u in upcoming] == [
        ("Leo", None),
        ("Ana", 15),
        ("Mia", 7),
    ]


def test_upcoming_dates_works_with_no_api_key_set(tmp_path: Path) -> None:
    """The tool reads a derived index — no extraction, and no vector search
    either: the keyless service's embedder maps no texts, so any embedding in
    the answer path would fail loudly."""
    writer, _ = make_service(
        tmp_path,
        vectors={BIRTHDAY_NOTE: UNIT},
        extractions={
            BIRTHDAY_NOTE: Extraction(
                special_dates=(
                    ExtractedSpecialDate(entity="Mia", label="birthday", month=8, day=3, year=2019),
                )
            )
        },
    )
    writer.remember(BIRTHDAY_NOTE, author="Adrian")

    keyless, _ = make_keyless_service(tmp_path, vectors={})
    [upcoming] = keyless.upcoming_dates(days=30)

    assert (upcoming.entity, upcoming.occurs_on, upcoming.years) == ("Mia", date(2026, 8, 3), 7)


def test_the_same_date_asserted_by_several_memories_appears_once(tmp_path: Path) -> None:
    """Two memories assert Mia's birthday and only one knows the birth year;
    the answer is one occurrence, with the year-derived age kept."""
    with_year = "Mia was born August 3rd, 2019"
    service, _ = make_service(
        tmp_path,
        vectors={BIRTHDAY_NOTE: UNIT, with_year: UNIT},
        extractions={
            BIRTHDAY_NOTE: Extraction(
                special_dates=(
                    ExtractedSpecialDate(entity="Mia", label="birthday", month=8, day=3),
                )
            ),
            with_year: Extraction(
                special_dates=(
                    ExtractedSpecialDate(entity="Mia", label="birthday", month=8, day=3, year=2019),
                )
            ),
        },
    )
    service.remember(BIRTHDAY_NOTE, author="Adrian")
    service.remember(with_year, author="Ana")

    [upcoming] = service.upcoming_dates(days=30)

    assert (upcoming.entity, upcoming.occurs_on, upcoming.years) == ("Mia", date(2026, 8, 3), 7)
