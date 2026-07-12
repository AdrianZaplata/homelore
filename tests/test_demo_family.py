"""The Demo Family: fixtures, golden Q/A pairs, and the demo build command.

The golden pairs marked ``keyless`` have deterministic answers (dates,
exact-memory recall, alias-resolved profiles), so they run here against a
fixture build whose extraction is the hand-authored ground truth and whose
embeddings are deterministic lexical vectors — no API key, no model. The
remaining pairs are the eval harness's material (ticket 08) and are only
checked for shape here.
"""

import sys
from datetime import datetime, time, timedelta
from pathlib import Path

import pytest

from conftest import NOW, FakeExtractor, FakeSummarizer, FixedClock, HashingEmbedder
from homelore.cli import main as cli_main
from homelore.demo import (
    GoldenPair,
    GoldenProfile,
    GoldenRecall,
    GoldenReflect,
    GoldenUpcomingDates,
    demo_extractions,
    demo_golden,
    demo_memories,
)
from homelore.service import HomeloreService
from homelore.store import MemoryStore

GOLDEN = demo_golden()
KEYLESS_RECALL = [pair for pair in GOLDEN if isinstance(pair, GoldenRecall) and pair.keyless]
KEYLESS_PROFILE = [pair for pair in GOLDEN if isinstance(pair, GoldenProfile) and pair.keyless]
DATE_PAIRS = [pair for pair in GOLDEN if isinstance(pair, GoldenUpcomingDates)]


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> tuple[HomeloreService, FixedClock]:
    """The fake-extracted fixture build: every Demo Family memory imported
    through the real write path, derived indexes built from the ground-truth
    extractions."""
    clock = FixedClock()
    service = HomeloreService(
        store=MemoryStore.open(tmp_path_factory.mktemp("demo") / "homelore.db"),
        embedder=HashingEmbedder(),
        extractor=FakeExtractor(demo_extractions()),
        summarizer=FakeSummarizer(),
        clock=clock,
    )
    result = service.import_memories(demo_memories())
    assert result.extraction_pending == 0
    return service, clock


def test_fixtures_are_substantial_and_extractions_stay_in_sync() -> None:
    drafts = demo_memories()
    assert len(drafts) >= 50
    # Every memory has a ground-truth extraction, keyed by its exact text —
    # editing a fixture without updating its extraction fails here, not as a
    # silently unindexed memory.
    assert set(demo_extractions()) == {draft.text for draft in drafts}


def test_golden_set_covers_every_tool_and_the_hard_cases() -> None:
    assert len(GOLDEN) >= 50
    by_type: dict[type[GoldenPair], list[GoldenPair]] = {}
    for pair in GOLDEN:
        by_type.setdefault(type(pair), []).append(pair)
    assert {GoldenRecall, GoldenProfile, GoldenUpcomingDates, GoldenReflect} == set(by_type)
    # Date answers are exact queries, so every date pair must be keyless.
    assert all(pair.keyless for pair in DATE_PAIRS)
    # The hard cases the fixtures exist for: date windows crossing a year
    # boundary, and profiles queried by an alias, not the canonical name.
    assert any(
        pair.as_of.year != (pair.as_of + timedelta(days=pair.days)).year for pair in DATE_PAIRS
    )
    assert any(pair.name.lower() != pair.expect_entity.lower() for pair in KEYLESS_PROFILE)
    # A synthesis question needs more than one memory to answer.
    assert any(len(pair.expect_memories) > 1 for pair in GOLDEN if isinstance(pair, GoldenRecall))


@pytest.mark.parametrize("pair", KEYLESS_RECALL, ids=lambda pair: pair.question)
def test_keyless_recall_pairs_surface_their_memories(
    demo: tuple[HomeloreService, FixedClock], pair: GoldenRecall
) -> None:
    service, clock = demo
    clock.now = NOW
    texts = [hit.memory.text for hit in service.recall(pair.question, limit=5)]
    for expected in pair.expect_memories:
        assert any(expected in text for text in texts), (
            f"{expected!r} missing from the top hits: {texts}"
        )


@pytest.mark.parametrize("pair", KEYLESS_PROFILE, ids=lambda pair: pair.question)
def test_keyless_profile_pairs_resolve_and_carry_their_facts(
    demo: tuple[HomeloreService, FixedClock], pair: GoldenProfile
) -> None:
    service, _ = demo
    profile = service.profile(pair.name)
    assert profile is not None
    assert profile.entity.name == pair.expect_entity
    relations = {supported.relation for supported in profile.relations}
    for expected in pair.expect_relations:
        assert expected in relations
    memory_texts = [memory.text for memory in profile.memories]
    for expected in pair.expect_memories:
        assert any(expected in text for text in memory_texts), (
            f"{expected!r} missing from {pair.expect_entity}'s memories"
        )


@pytest.mark.parametrize("pair", DATE_PAIRS, ids=lambda pair: pair.question)
def test_date_pairs_are_answered_exactly(
    demo: tuple[HomeloreService, FixedClock], pair: GoldenUpcomingDates
) -> None:
    service, clock = demo
    clock.now = datetime.combine(pair.as_of, time(10, 0), tzinfo=NOW.tzinfo)
    assert tuple(service.upcoming_dates(days=pair.days)) == pair.expect


def test_superseded_facts_read_newest_first_in_a_profile(
    demo: tuple[HomeloreService, FixedClock],
) -> None:
    """The shoe-size chain is the fixtures' supersession case: a profile
    presents the current fact before the ones it superseded."""
    service, _ = demo
    profile = service.profile("Freya")
    assert profile is not None
    texts = [memory.text for memory in profile.memories]
    current = next(i for i, text in enumerate(texts) if "size 31" in text)
    superseded = next(i for i, text in enumerate(texts) if "size 28" in text)
    assert current < superseded


def test_demo_family_clusters_into_distinct_communities(
    demo: tuple[HomeloreService, FixedClock],
) -> None:
    service, _ = demo
    summaries = service.reflect()
    assert len(summaries) >= 3
    # Satellite clusters stay their own communities, apart from the family.
    band = next(summary for summary in summaries if "Petra" in summary.entities)
    garden = next(summary for summary in summaries if "Signe" in summary.entities)
    family = next(summary for summary in summaries if "Freya" in summary.entities)
    assert {"Freya"}.isdisjoint(band.entities)
    assert {"Freya"}.isdisjoint(garden.entities)
    assert len(family.entities) > len(band.entities)


def test_demo_build_without_a_key_explains_and_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db_path = tmp_path / "demo.db"
    monkeypatch.setattr(sys, "argv", ["homelore", "demo", "--db-path", str(db_path)])

    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        cli_main()

    assert not db_path.exists()


def test_demo_build_refuses_an_existing_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "demo.db"
    db_path.touch()
    monkeypatch.setattr(sys, "argv", ["homelore", "demo", "--db-path", str(db_path)])

    with pytest.raises(SystemExit, match="already exists"):
        cli_main()
