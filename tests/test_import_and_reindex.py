"""Bulk import and reindex: seeding from existing notes and rebuilding the
derived indexes from the memory log (ADR 0001's concrete guarantee).

All behavior is exercised through the service seam with the fake extractor;
no test touches tables or a real model.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from conftest import (
    make_failing_extraction_service,
    make_keyless_service,
    make_service,
    make_service_with_extractor,
)
from homelore.domain import (
    Entity,
    ExtractedEntity,
    ExtractedRelation,
    ExtractedSpecialDate,
    Extraction,
    ImportResult,
    MemoryDraft,
    ReindexResult,
    Relation,
)
from homelore.memories_file import read_memories_file
from homelore.service import HomeloreService, MissingApiKeyError

SHOE_MEMORY = "Mia moved up to size 32 shoes"
POTTERY_MEMORY = "Ana mentioned she wants to learn pottery"

POTTERY_EXTRACTION = Extraction(
    entities=(ExtractedEntity(name="Ana", aliases=("my wife",)), ExtractedEntity(name="pottery")),
    relations=(ExtractedRelation(subject="Ana", label="interested_in", object="pottery"),),
)

BIRTHDAY_MEMORY = "Mia was born on March 3rd, 2018"
BIRTHDAY_EXTRACTION = Extraction(
    entities=(ExtractedEntity(name="Mia"),),
    special_dates=(
        ExtractedSpecialDate(entity="Mia", label="birthday", month=3, day=3, year=2018),
    ),
)


def test_imported_memories_are_retrievable_like_any_other(tmp_path: Path) -> None:
    service, clock = make_service(
        tmp_path,
        vectors={SHOE_MEMORY: [1.0, 0.0, 0.0], POTTERY_MEMORY: [0.0, 1.0, 0.0]},
    )
    drafts = [
        MemoryDraft(
            text=SHOE_MEMORY,
            author="Ana",
            created_at=datetime(2025, 11, 2, 9, 0, tzinfo=UTC),
        ),
        MemoryDraft(text=POTTERY_MEMORY, author="Adrian"),
    ]

    result = service.import_memories(drafts)

    assert result == ImportResult(imported=2, extraction_pending=0)
    [shoes] = service.recall(SHOE_MEMORY, limit=1)
    assert shoes.memory.author == "Ana"
    assert shoes.memory.created_at == datetime(2025, 11, 2, 9, 0, tzinfo=UTC)
    [pottery] = service.recall(POTTERY_MEMORY, limit=1)
    assert pottery.memory.author == "Adrian"
    # A draft without an explicit timestamp is recorded as of import time.
    assert pottery.memory.created_at == clock.now


def test_import_extracts_inline_and_anchors_event_dates(tmp_path: Path) -> None:
    service, _ = make_service(
        tmp_path,
        vectors={POTTERY_MEMORY: [1.0, 0.0, 0.0]},
        extractions={POTTERY_MEMORY: POTTERY_EXTRACTION},
    )

    service.import_memories(
        [MemoryDraft(text=POTTERY_MEMORY, author="Adrian", event_date=date(2025, 6, 1))]
    )

    profile = service.profile("Ana")
    assert profile is not None
    [supported] = profile.relations
    assert supported.relation == Relation(subject="Ana", label="interested_in", object="pottery")
    [memory] = profile.memories
    assert memory.happened_on == date(2025, 6, 1)


def test_import_survives_extraction_failure_and_reports_pending(tmp_path: Path) -> None:
    service, _ = make_failing_extraction_service(
        tmp_path,
        vectors={SHOE_MEMORY: [1.0, 0.0, 0.0], POTTERY_MEMORY: [0.0, 1.0, 0.0]},
    )

    result = service.import_memories(
        [
            MemoryDraft(text=SHOE_MEMORY, author="Ana"),
            MemoryDraft(text=POTTERY_MEMORY, author="Adrian"),
        ]
    )

    assert result == ImportResult(imported=2, extraction_pending=2)
    [recalled] = service.recall(SHOE_MEMORY, limit=1)
    assert recalled.memory.text == SHOE_MEMORY


def test_import_without_api_key_fails_with_guidance_before_saving(tmp_path: Path) -> None:
    vectors = {SHOE_MEMORY: [1.0, 0.0, 0.0]}
    keyless, _ = make_keyless_service(tmp_path, vectors)

    with pytest.raises(MissingApiKeyError, match="ANTHROPIC_API_KEY"):
        keyless.import_memories([MemoryDraft(text=SHOE_MEMORY, author="Ana")])

    assert keyless.recall(SHOE_MEMORY) == []


def test_reindex_heals_a_memory_whose_extraction_failed(tmp_path: Path) -> None:
    vectors = {POTTERY_MEMORY: [1.0, 0.0, 0.0]}
    broken, _ = make_failing_extraction_service(tmp_path, vectors)
    assert broken.remember(POTTERY_MEMORY, author="Adrian").extraction_pending is True

    healed_session, _ = make_service(
        tmp_path, vectors, extractions={POTTERY_MEMORY: POTTERY_EXTRACTION}
    )
    result = healed_session.reindex()

    assert result == ReindexResult(reextracted=1, failed=0)
    profile = healed_session.profile("Ana")
    assert profile is not None
    [supported] = profile.relations
    assert supported.relation == Relation(subject="Ana", label="interested_in", object="pottery")


def test_healing_leaves_already_extracted_memories_untouched(tmp_path: Path) -> None:
    vectors = {POTTERY_MEMORY: [1.0, 0.0, 0.0]}
    original, _ = make_service(tmp_path, vectors, extractions={POTTERY_MEMORY: POTTERY_EXTRACTION})
    original.remember(POTTERY_MEMORY, author="Adrian")

    improved_session, _ = make_service(
        tmp_path,
        vectors,
        # The extractor now reads a teaching angle into the same memory.
        extractions={
            POTTERY_MEMORY: Extraction(
                entities=(ExtractedEntity(name="Ana"), ExtractedEntity(name="pottery")),
                relations=(
                    ExtractedRelation(subject="Ana", label="wants_to_teach", object="pottery"),
                ),
            )
        },
    )
    result = improved_session.reindex()

    assert result == ReindexResult(reextracted=0, failed=0)
    profile = improved_session.profile("Ana")
    assert profile is not None
    [supported] = profile.relations
    assert supported.relation.label == "interested_in"


def test_full_reindex_applies_improved_extraction_to_existing_memories(tmp_path: Path) -> None:
    vectors = {POTTERY_MEMORY: [1.0, 0.0, 0.0]}
    original, _ = make_service(tmp_path, vectors, extractions={POTTERY_MEMORY: POTTERY_EXTRACTION})
    original.remember(POTTERY_MEMORY, author="Adrian")

    improved_session, _ = make_service(
        tmp_path,
        vectors,
        extractions={
            POTTERY_MEMORY: Extraction(
                entities=(ExtractedEntity(name="Ana"), ExtractedEntity(name="pottery")),
                relations=(
                    ExtractedRelation(subject="Ana", label="wants_to_learn", object="pottery"),
                ),
            )
        },
    )
    result = improved_session.reindex(full=True)

    assert result == ReindexResult(reextracted=1, failed=0)
    profile = improved_session.profile("Ana")
    assert profile is not None
    [supported] = profile.relations
    assert supported.relation.label == "wants_to_learn"


def test_full_reindex_restores_equivalent_query_results(tmp_path: Path) -> None:
    vectors = {POTTERY_MEMORY: [1.0, 0.0, 0.0], BIRTHDAY_MEMORY: [0.0, 1.0, 0.0]}
    extractions = {POTTERY_MEMORY: POTTERY_EXTRACTION, BIRTHDAY_MEMORY: BIRTHDAY_EXTRACTION}
    service, _ = make_service(tmp_path, vectors, extractions)
    service.remember(POTTERY_MEMORY, author="Adrian")
    service.remember(BIRTHDAY_MEMORY, author="Ana")
    before = _query_snapshot(service)

    rebuilt_session, _ = make_service(tmp_path, vectors, extractions)
    rebuilt_session.reindex(full=True)

    assert _query_snapshot(rebuilt_session) == before


def _query_snapshot(service: HomeloreService) -> tuple[object, ...]:
    """Every retrieval mode's answers — what a rebuild must preserve."""
    return (
        service.recall(POTTERY_MEMORY),
        service.profile("my wife"),
        service.profile("Mia"),
        service.upcoming_dates(days=365),
        service.reflect(),
    )


def test_reindex_brings_the_community_layer_current(tmp_path: Path) -> None:
    vectors = {POTTERY_MEMORY: [1.0, 0.0, 0.0]}
    service, _ = make_service(tmp_path, vectors, extractions={POTTERY_MEMORY: POTTERY_EXTRACTION})
    service.remember(POTTERY_MEMORY, author="Adrian")

    service.reindex(full=True)

    # Serving summaries needs no key, so a fresh keyless session reflecting
    # proves reindex rebuilt the community layer rather than leaving it stale.
    keyless, _ = make_keyless_service(tmp_path, vectors)
    [community] = keyless.reflect()
    assert POTTERY_MEMORY in community.summary


class InterruptingExtractor:
    """Simulates Ctrl-C landing mid-reindex: the first extraction succeeds,
    the next one is interrupted."""

    def __init__(self, extractions: dict[str, Extraction]) -> None:
        self._extractions = extractions
        self._calls = 0

    def extract(self, text: str, known_entities: Sequence[Entity]) -> Extraction:
        self._calls += 1
        if self._calls > 1:
            raise KeyboardInterrupt
        return self._extractions.get(text, Extraction())


def test_interrupted_reindex_loses_nothing_and_rerunning_completes_it(tmp_path: Path) -> None:
    vectors = {POTTERY_MEMORY: [1.0, 0.0, 0.0], BIRTHDAY_MEMORY: [0.0, 1.0, 0.0]}
    extractions = {POTTERY_MEMORY: POTTERY_EXTRACTION, BIRTHDAY_MEMORY: BIRTHDAY_EXTRACTION}
    original, _ = make_service(tmp_path, vectors, extractions)
    original.remember(POTTERY_MEMORY, author="Adrian")
    original.remember(BIRTHDAY_MEMORY, author="Ana")
    before = _query_snapshot(original)

    interrupted_session, _ = make_service_with_extractor(
        tmp_path, vectors, InterruptingExtractor(extractions)
    )
    with pytest.raises(KeyboardInterrupt):
        interrupted_session.reindex(full=True)

    # Both memories survived the interruption.
    texts = {hit.memory.text for hit in interrupted_session.recall(POTTERY_MEMORY, limit=2)}
    assert texts == {POTTERY_MEMORY, BIRTHDAY_MEMORY}

    # Re-running (healing suffices) picks up exactly the unfinished work and
    # converges to the same state an uninterrupted rebuild reaches.
    resumed_session, _ = make_service(tmp_path, vectors, extractions)
    assert resumed_session.reindex() == ReindexResult(reextracted=1, failed=0)
    assert _query_snapshot(resumed_session) == before

    # Once converged, another run is a no-op: reindex is idempotent.
    assert resumed_session.reindex() == ReindexResult(reextracted=0, failed=0)
    assert _query_snapshot(resumed_session) == before


def test_reindex_counts_extractions_that_fail_again_and_keeps_them_flagged(
    tmp_path: Path,
) -> None:
    vectors = {POTTERY_MEMORY: [1.0, 0.0, 0.0]}
    service, _ = make_service(tmp_path, vectors, extractions={POTTERY_MEMORY: POTTERY_EXTRACTION})
    service.remember(POTTERY_MEMORY, author="Adrian")

    still_broken, _ = make_failing_extraction_service(tmp_path, vectors)
    assert still_broken.reindex(full=True) == ReindexResult(reextracted=0, failed=1)

    healed_session, _ = make_service(
        tmp_path, vectors, extractions={POTTERY_MEMORY: POTTERY_EXTRACTION}
    )
    assert healed_session.reindex() == ReindexResult(reextracted=1, failed=0)


def test_memories_file_parses_to_drafts(tmp_path: Path) -> None:
    path = tmp_path / "memories.jsonl"
    path.write_text(
        '{"text": "Mia moved up to size 32 shoes", "author": "Ana",'
        ' "created_at": "2025-11-02T09:00:00", "event_date": "2025-10-30"}\n'
        "\n"
        '{"text": "Ana mentioned she wants to learn pottery", "author": "Adrian"}\n'
    )

    drafts = read_memories_file(path)

    assert drafts == [
        MemoryDraft(
            text=SHOE_MEMORY,
            author="Ana",
            # A timestamp without a timezone is taken as UTC.
            created_at=datetime(2025, 11, 2, 9, 0, tzinfo=UTC),
            event_date=date(2025, 10, 30),
        ),
        MemoryDraft(text=POTTERY_MEMORY, author="Adrian"),
    ]


def test_memories_file_rejects_a_bad_line_by_number(tmp_path: Path) -> None:
    path = tmp_path / "memories.jsonl"
    path.write_text('{"text": "no author given"}\n')

    with pytest.raises(ValueError, match="line 1"):
        read_memories_file(path)
