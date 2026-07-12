"""Communities and the reflect operation (ticket 05).

All behavior is exercised through the service seam: the fake extractor
supplies the graph the communities are detected from, and the fake summarizer
numbers each summary it writes so reuse versus regeneration is visible in
reflect() results alone.
"""

from collections.abc import Sequence
from pathlib import Path

import pytest

from conftest import (
    NOW,
    FakeEmbedder,
    FakeExtractor,
    FakeSummarizer,
    make_keyless_service,
    make_service,
)
from homelore.domain import ExtractedEntity, ExtractedRelation, Extraction, Memory
from homelore.service import HomeloreService, MissingApiKeyError
from homelore.store import MemoryStore

MIA_SCHOOL = "Mia started at Northside Elementary this fall"
BAKE_SALE = "Northside Elementary is holding a bake sale on Friday"
POTTERY = "Ana mentioned she wants to learn pottery"
UNIT = [1.0, 0.0, 0.0]

_VECTORS = {MIA_SCHOOL: UNIT, BAKE_SALE: UNIT, POTTERY: UNIT}
_EXTRACTIONS = {
    MIA_SCHOOL: Extraction(
        entities=(ExtractedEntity(name="Mia"), ExtractedEntity(name="Northside Elementary")),
        relations=(
            ExtractedRelation(subject="Mia", label="attends", object="Northside Elementary"),
        ),
    ),
    BAKE_SALE: Extraction(entities=(ExtractedEntity(name="Northside Elementary"),)),
    POTTERY: Extraction(
        entities=(ExtractedEntity(name="Ana"), ExtractedEntity(name="pottery")),
        relations=(ExtractedRelation(subject="Ana", label="interested_in", object="pottery"),),
    ),
}


def _two_cluster_service(
    tmp_path: Path,
    extra_vectors: dict[str, list[float]] | None = None,
    extra_extractions: dict[str, Extraction] | None = None,
) -> HomeloreService:
    """Two disjoint clusters: Mia's school life (two memories via the shared
    Northside Elementary entity) and Ana's pottery interest (one memory)."""
    service, _ = make_service(
        tmp_path,
        vectors={**_VECTORS, **(extra_vectors or {})},
        extractions={**_EXTRACTIONS, **(extra_extractions or {})},
    )
    service.remember(MIA_SCHOOL, author="Adrian")
    service.remember(BAKE_SALE, author="Ana")
    service.remember(POTTERY, author="Adrian")
    return service


def test_reflect_on_an_empty_database_returns_nothing(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path, vectors={})

    assert service.reflect() == []


def test_communities_form_from_the_graph_with_grounded_summaries(tmp_path: Path) -> None:
    """The three memories cluster into two communities without any hand-drawn
    boundary: the school memories connect through Northside Elementary, the
    pottery memory stands apart. Each summary draws only on its own cluster's
    memories — the school summary must not leak pottery, and vice versa."""
    service = _two_cluster_service(tmp_path)

    school, pottery = service.reflect()

    assert set(school.entities) == {"Mia", "Northside Elementary"}
    assert MIA_SCHOOL in school.summary
    assert BAKE_SALE in school.summary
    assert POTTERY not in school.summary
    assert set(pottery.entities) == {"Ana", "pottery"}
    assert POTTERY in pottery.summary
    assert MIA_SCHOOL not in pottery.summary


def test_reflect_without_new_writes_serves_the_same_summaries(tmp_path: Path) -> None:
    """Nothing changed, so nothing is regenerated: the fake summarizer
    numbers every summary it writes, and identical results prove the second
    reflect reused the stored layer instead of re-summarizing."""
    service = _two_cluster_service(tmp_path)

    first = service.reflect()
    second = service.reflect()

    assert second == first


def test_a_write_regenerates_only_the_community_it_touches(tmp_path: Path) -> None:
    """A new Mia memory dirties the layer, but only the school community's
    membership changed: its summary is rewritten to include the new memory,
    while the pottery community keeps its stored summary verbatim."""
    lost_tooth = "Mia lost her first tooth"
    service = _two_cluster_service(
        tmp_path,
        extra_vectors={lost_tooth: UNIT},
        extra_extractions={lost_tooth: Extraction(entities=(ExtractedEntity(name="Mia"),))},
    )
    _, pottery_before = service.reflect()

    service.remember(lost_tooth, author="Adrian")
    school_after, pottery_after = service.reflect()

    assert pottery_after == pottery_before
    assert lost_tooth in school_after.summary
    assert MIA_SCHOOL in school_after.summary


def test_a_write_touching_no_community_regenerates_nothing(tmp_path: Path) -> None:
    """A memory the extractor found nothing in belongs to no community; the
    write still dirties the layer, but re-clustering finds every community
    unchanged and every summary is reused."""
    nothing = "what a day"
    service = _two_cluster_service(tmp_path, extra_vectors={nothing: UNIT})
    before = service.reflect()

    service.remember(nothing, author="Adrian")

    assert service.reflect() == before


def test_a_memory_bridging_two_communities_merges_them(tmp_path: Path) -> None:
    """Ana volunteering at the school connects the two clusters, so the next
    reflect yields one merged community summarized across all its memories —
    the parts' stale summaries are gone."""
    volunteers = "Ana volunteers at Northside Elementary"
    service = _two_cluster_service(
        tmp_path,
        extra_vectors={volunteers: UNIT},
        extra_extractions={
            volunteers: Extraction(
                entities=(
                    ExtractedEntity(name="Ana"),
                    ExtractedEntity(name="Northside Elementary"),
                ),
                relations=(
                    ExtractedRelation(
                        subject="Ana", label="volunteers_at", object="Northside Elementary"
                    ),
                ),
            ),
        },
    )
    assert len(service.reflect()) == 2

    service.remember(volunteers, author="Adrian")
    [merged] = service.reflect()

    assert set(merged.entities) == {"Mia", "Northside Elementary", "Ana", "pottery"}
    for text in (MIA_SCHOOL, BAKE_SALE, POTTERY, volunteers):
        assert text in merged.summary


def test_reflect_over_built_summaries_needs_no_api_key(tmp_path: Path) -> None:
    """Reading is keyless: once summaries are built, a service configured
    without ANTHROPIC_API_KEY still serves them."""
    built = _two_cluster_service(tmp_path).reflect()

    keyless, _ = make_keyless_service(tmp_path, vectors=_VECTORS)

    assert keyless.reflect() == built


def test_reflect_needing_a_refresh_without_the_key_is_a_clear_error(tmp_path: Path) -> None:
    """Writes arrived since the last refresh, so answering would mean serving
    stale summaries — a keyless reflect fails with the config problem spelled
    out instead."""
    _two_cluster_service(tmp_path)  # remembered but never reflected: layer is dirty

    keyless, _ = make_keyless_service(tmp_path, vectors=_VECTORS)

    with pytest.raises(MissingApiKeyError, match="ANTHROPIC_API_KEY"):
        keyless.reflect()


def test_a_keyless_reflect_absorbs_a_write_that_changed_no_community(tmp_path: Path) -> None:
    """Only writing a new summary needs the API key — re-clustering is local.
    A dirty layer whose communities all turn out unchanged is served keyless."""
    nothing = "what a day"
    service = _two_cluster_service(tmp_path, extra_vectors={nothing: UNIT})
    before = service.reflect()
    service.remember(nothing, author="Adrian")

    keyless, _ = make_keyless_service(tmp_path, vectors=_VECTORS)

    assert keyless.reflect() == before


def test_a_write_landing_during_a_refresh_is_not_lost(tmp_path: Path) -> None:
    """The refresh spends its time in model calls, and another family member
    can remember something meanwhile. That write's community must not be
    marked current by the in-flight refresh: the next reflect regenerates it."""
    lost_tooth = "Mia lost her first tooth"

    class InterruptingSummarizer:
        """Delegates to the fake, but the first summary request triggers a
        concurrent write — a second writer landing mid-refresh."""

        def __init__(self) -> None:
            self._inner = FakeSummarizer()
            self._interrupted = False

        def summarize(self, entities: Sequence[str], memories: Sequence[Memory]) -> str:
            if not self._interrupted:
                self._interrupted = True
                service.remember(lost_tooth, author="Ana")
            return self._inner.summarize(entities, memories)

    service = HomeloreService(
        store=MemoryStore.open(tmp_path / "homelore.db"),
        embedder=FakeEmbedder({**_VECTORS, lost_tooth: UNIT}),
        extractor=FakeExtractor(
            {**_EXTRACTIONS, lost_tooth: Extraction(entities=(ExtractedEntity(name="Mia"),))}
        ),
        summarizer=InterruptingSummarizer(),
        clock=lambda: NOW,
    )
    service.remember(MIA_SCHOOL, author="Adrian")
    service.remember(BAKE_SALE, author="Ana")
    service.remember(POTTERY, author="Adrian")

    service.reflect()  # the refresh races with the mid-flight write
    summaries = service.reflect()  # and the next reflect must absorb it

    assert any(lost_tooth in community.summary for community in summaries)
