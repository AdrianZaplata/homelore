from datetime import date, timedelta
from pathlib import Path

from conftest import NOW, make_service

SHOE_QUERY = "what size shoes does Mia wear?"
SHOE_MEMORY = "Mia moved up to shoe size 32"
POTTERY_MEMORY = "Ana mentioned she wants to learn pottery"


def test_remember_records_text_author_and_timestamp(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path, vectors={"Mia moved up to shoe size 32": [1.0, 0.0, 0.0]})

    memory = service.remember("Mia moved up to shoe size 32", author="Adrian")

    assert memory.text == "Mia moved up to shoe size 32"
    assert memory.author == "Adrian"
    assert memory.created_at == NOW
    assert memory.event_date is None


def test_recall_ranks_by_similarity_and_carries_provenance(tmp_path: Path) -> None:
    service, _ = make_service(
        tmp_path,
        vectors={
            SHOE_MEMORY: [0.9, 0.1, 0.0],
            POTTERY_MEMORY: [0.0, 1.0, 0.0],
            SHOE_QUERY: [1.0, 0.0, 0.0],
        },
    )
    service.remember(POTTERY_MEMORY, author="Adrian")
    service.remember(SHOE_MEMORY, author="Ana")

    results = service.recall(SHOE_QUERY)

    assert [r.memory.text for r in results] == [SHOE_MEMORY, POTTERY_MEMORY]
    top = results[0].memory
    assert top.author == "Ana"
    assert top.created_at == NOW
    assert results[0].score > results[1].score


def test_recall_prefers_newer_memory_when_similarity_ties(tmp_path: Path) -> None:
    old_fact = "Mia wears shoe size 30"
    new_fact = "Mia wears shoe size 32"
    same_vector = [1.0, 0.0, 0.0]
    service, clock = make_service(
        tmp_path,
        vectors={old_fact: same_vector, new_fact: same_vector, SHOE_QUERY: same_vector},
    )
    service.remember(old_fact, author="Adrian")
    clock.advance(timedelta(days=400))
    service.remember(new_fact, author="Adrian")

    results = service.recall(SHOE_QUERY)

    assert [r.memory.text for r in results] == [new_fact, old_fact]


def test_recency_does_not_override_a_clear_relevance_gap(tmp_path: Path) -> None:
    service, clock = make_service(
        tmp_path,
        vectors={
            SHOE_MEMORY: [0.9, 0.1, 0.0],
            POTTERY_MEMORY: [0.0, 1.0, 0.0],
            SHOE_QUERY: [1.0, 0.0, 0.0],
        },
    )
    service.remember(SHOE_MEMORY, author="Ana")
    clock.advance(timedelta(days=1000))
    service.remember(POTTERY_MEMORY, author="Adrian")

    results = service.recall(SHOE_QUERY)

    assert [r.memory.text for r in results] == [SHOE_MEMORY, POTTERY_MEMORY]


def test_event_date_override_is_kept_and_returned_with_provenance(tmp_path: Path) -> None:
    lake_house = "we spent a week at the lake house and Mia learned to swim"
    service, _ = make_service(
        tmp_path, vectors={lake_house: [1.0, 0.0, 0.0], "lake house?": [1.0, 0.0, 0.0]}
    )
    service.remember(lake_house, author="Adrian", event_date=date(2025, 7, 20))

    [result] = service.recall("lake house?")

    assert result.memory.event_date == date(2025, 7, 20)
    assert result.memory.author == "Adrian"


def test_recency_is_anchored_to_the_event_date_not_the_recording_time(tmp_path: Path) -> None:
    last_summer = "last summer Mia tried windsurfing at the lake"
    this_week = "Mia tried windsurfing again this week"
    same_vector = [1.0, 0.0, 0.0]
    service, _ = make_service(
        tmp_path,
        vectors={last_summer: same_vector, this_week: same_vector, "windsurfing?": same_vector},
    )
    # Both recorded today, but one describes an event from a year ago.
    service.remember(last_summer, author="Adrian", event_date=date(2025, 7, 10))
    service.remember(this_week, author="Adrian")

    results = service.recall("windsurfing?")

    assert [r.memory.text for r in results] == [this_week, last_summer]


def test_memories_survive_reopening_the_same_file(tmp_path: Path) -> None:
    vectors = {SHOE_MEMORY: [1.0, 0.0, 0.0], SHOE_QUERY: [1.0, 0.0, 0.0]}
    first, _ = make_service(tmp_path, vectors)
    first.remember(SHOE_MEMORY, author="Ana")

    reopened, _ = make_service(tmp_path, vectors)
    [result] = reopened.recall(SHOE_QUERY)

    assert result.memory.text == SHOE_MEMORY
    assert result.memory.author == "Ana"


def test_recall_respects_the_limit(tmp_path: Path) -> None:
    texts = [f"memory number {n}" for n in range(4)]
    vectors = {text: [1.0, 0.0, 0.0] for text in texts} | {"anything": [1.0, 0.0, 0.0]}
    service, _ = make_service(tmp_path, vectors)
    for text in texts:
        service.remember(text, author="Adrian")

    assert len(service.recall("anything", limit=2)) == 2


def test_recall_on_an_empty_store_returns_nothing(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path, vectors={"anything": [1.0, 0.0, 0.0]})

    assert service.recall("anything") == []
