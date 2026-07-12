"""Graph-expanded recall and alias-merged profiles (ticket 03).

All behavior is exercised through the service seam: fake embedder vectors
control similarity order, the fake extractor supplies the graph, and a real
temp-file SQLite store holds everything.
"""

import sqlite3
from datetime import timedelta
from pathlib import Path

from conftest import NOW, FixedClock, make_service
from homelore.domain import ExtractedEntity, ExtractedRelation, Extraction
from homelore.service import HomeloreService

MIA_QUERY = "what's going on with Mia at school?"
MIA_SCHOOL = "Mia started at Northside Elementary this fall"
BAKE_SALE = "Northside Elementary is holding a bake sale on Friday"
FICUS = "Ana repotted the ficus"


def test_graph_expansion_recalls_a_relationally_connected_memory(tmp_path: Path) -> None:
    """The bake-sale memory never mentions Mia, so it is less similar to the
    query than the unrelated ficus memory — pure vector search at limit=2
    would return the ficus. The shared Northside Elementary entity is what
    must pull it in."""
    service, _ = make_service(
        tmp_path,
        vectors={
            MIA_QUERY: [1.0, 0.0, 0.0],
            MIA_SCHOOL: [0.9, 0.4359, 0.0],
            BAKE_SALE: [0.2, 0.9798, 0.0],
            FICUS: [0.35, 0.0, 0.9367],
        },
        extractions={
            MIA_SCHOOL: Extraction(
                entities=(
                    ExtractedEntity(name="Mia"),
                    ExtractedEntity(name="Northside Elementary"),
                ),
                relations=(
                    ExtractedRelation(
                        subject="Mia", label="attends", object="Northside Elementary"
                    ),
                ),
            ),
            BAKE_SALE: Extraction(entities=(ExtractedEntity(name="Northside Elementary"),)),
            FICUS: Extraction(
                entities=(ExtractedEntity(name="Ana"), ExtractedEntity(name="ficus")),
                relations=(ExtractedRelation(subject="Ana", label="repotted", object="ficus"),),
            ),
        },
    )
    service.remember(MIA_SCHOOL, author="Adrian")
    service.remember(BAKE_SALE, author="Ana")
    service.remember(FICUS, author="Adrian")

    results = service.recall(MIA_QUERY, limit=2)

    assert [r.memory.text for r in results] == [MIA_SCHOOL, BAKE_SALE]


def test_graph_expansion_traverses_relations_one_hop(tmp_path: Path) -> None:
    """The bake-sale memory shares no entity with the top hit ("Mia had a
    great week" mentions only Mia); it is reachable only across the
    Mia —attends→ Northside Elementary relation from a third memory. It must
    still outrank the more query-similar but unconnected ficus memory."""
    great_week = "Mia had a great week"
    service, _ = make_service(
        tmp_path,
        vectors={
            MIA_QUERY: [1.0, 0.0, 0.0],
            great_week: [0.9, 0.4359, 0.0],
            MIA_SCHOOL: [0.1, 0.995, 0.0],
            BAKE_SALE: [0.05, 0.9987, 0.0],
            FICUS: [0.2, 0.0, 0.9798],
        },
        extractions={
            great_week: Extraction(entities=(ExtractedEntity(name="Mia"),)),
            MIA_SCHOOL: Extraction(
                entities=(
                    ExtractedEntity(name="Mia"),
                    ExtractedEntity(name="Northside Elementary"),
                ),
                relations=(
                    ExtractedRelation(
                        subject="Mia", label="attends", object="Northside Elementary"
                    ),
                ),
            ),
            BAKE_SALE: Extraction(entities=(ExtractedEntity(name="Northside Elementary"),)),
            FICUS: Extraction(
                entities=(ExtractedEntity(name="Ana"), ExtractedEntity(name="ficus"))
            ),
        },
    )
    service.remember(MIA_SCHOOL, author="Adrian")
    service.remember(BAKE_SALE, author="Ana")
    service.remember(FICUS, author="Adrian")
    service.remember(great_week, author="Ana")

    results = service.recall(MIA_QUERY, limit=3)

    assert [r.memory.text for r in results] == [great_week, MIA_SCHOOL, BAKE_SALE]


def test_superseded_fact_ranks_below_its_successor_despite_graph_support(tmp_path: Path) -> None:
    """Both shoe-size memories mention Mia, so each graph-supports the other
    equally — the bonus must not prop up the stale value; recency decides."""
    old_fact = "Mia wears shoe size 30"
    new_fact = "Mia moved up to shoe size 32"
    query = "what size shoes does Mia wear?"
    same_vector = [1.0, 0.0, 0.0]
    service, clock = make_service(
        tmp_path,
        vectors={old_fact: same_vector, new_fact: same_vector, query: same_vector},
        extractions={
            old_fact: Extraction(
                entities=(ExtractedEntity(name="Mia"),),
                relations=(ExtractedRelation(subject="Mia", label="wears_shoe_size", object="30"),),
            ),
            new_fact: Extraction(
                entities=(ExtractedEntity(name="Mia"),),
                relations=(ExtractedRelation(subject="Mia", label="wears_shoe_size", object="32"),),
            ),
        },
    )
    service.remember(old_fact, author="Adrian")
    clock.advance(timedelta(days=400))
    service.remember(new_fact, author="Ana")

    results = service.recall(query)

    assert [r.memory.text for r in results] == [new_fact, old_fact]


POTTERY = "Ana mentioned she wants to learn pottery"
CLASS = "my wife signed up for the pottery class"
UNIT = [1.0, 0.0, 0.0]


def _pottery_service(tmp_path: Path) -> tuple[HomeloreService, FixedClock]:
    return make_service(
        tmp_path,
        vectors={POTTERY: UNIT, CLASS: UNIT},
        extractions={
            POTTERY: Extraction(
                entities=(
                    ExtractedEntity(name="Ana", aliases=("my wife",)),
                    ExtractedEntity(name="pottery"),
                ),
                relations=(
                    ExtractedRelation(subject="Ana", label="interested_in", object="pottery"),
                ),
            ),
            CLASS: Extraction(
                entities=(ExtractedEntity(name="Ana", aliases=("my wife",)),),
                relations=(
                    ExtractedRelation(subject="my wife", label="attends", object="pottery class"),
                ),
            ),
        },
    )


def test_profile_by_alias_returns_the_merged_entity_with_relations(tmp_path: Path) -> None:
    service, clock = _pottery_service(tmp_path)
    service.remember(POTTERY, author="Adrian")
    clock.advance(timedelta(days=30))
    service.remember(CLASS, author="Adrian")

    profile = service.profile("my wife")

    assert profile is not None
    assert profile.entity.name == "Ana"
    assert "my wife" in profile.entity.aliases
    relations = {
        (sr.relation.subject, sr.relation.label, sr.relation.object) for sr in profile.relations
    }
    assert relations == {
        ("Ana", "interested_in", "pottery"),
        ("Ana", "attends", "pottery class"),
    }


def test_profile_claims_carry_their_supporting_memories_with_provenance(tmp_path: Path) -> None:
    service, clock = _pottery_service(tmp_path)
    service.remember(POTTERY, author="Adrian")
    clock.advance(timedelta(days=30))
    service.remember(CLASS, author="Ana")

    profile = service.profile("Ana")

    assert profile is not None
    interested_in = next(sr for sr in profile.relations if sr.relation.label == "interested_in")
    [supporting] = interested_in.memories
    assert supporting.text == POTTERY
    assert supporting.author == "Adrian"
    assert supporting.happened_on == NOW.date()
    # Every memory mentioning Ana, newest first.
    assert [m.text for m in profile.memories] == [CLASS, POTTERY]


def test_profile_of_an_unknown_name_is_none(tmp_path: Path) -> None:
    service, _ = _pottery_service(tmp_path)
    service.remember(POTTERY, author="Adrian")

    assert service.profile("Uncle Bob") is None


def test_graph_links_from_before_the_mentions_index_are_rebuilt_on_open(tmp_path: Path) -> None:
    """Databases written before the mentions index existed carry relation rows
    but no mention rows; opening the store must backfill from them so old
    memories stay reachable through the graph (full healing is reindex's job)."""
    service, clock = _pottery_service(tmp_path)
    service.remember(POTTERY, author="Adrian")
    clock.advance(timedelta(days=30))
    service.remember(CLASS, author="Adrian")
    # Arrange the legacy state directly: this test simulates a database written
    # by an older version, which no public operation can produce.
    with sqlite3.connect(tmp_path / "homelore.db") as connection:
        connection.execute("DELETE FROM mentions")

    reopened, _ = _pottery_service(tmp_path)
    profile = reopened.profile("my wife")

    assert profile is not None
    assert [m.text for m in profile.memories] == [CLASS, POTTERY]


def test_a_claim_asserted_by_several_memories_merges_with_all_its_support(tmp_path: Path) -> None:
    again = "Ana brought up pottery again at dinner"
    service, _ = make_service(
        tmp_path,
        vectors={POTTERY: UNIT, again: UNIT},
        extractions={
            POTTERY: Extraction(
                entities=(ExtractedEntity(name="Ana"),),
                relations=(
                    ExtractedRelation(subject="Ana", label="interested_in", object="pottery"),
                ),
            ),
            again: Extraction(
                entities=(ExtractedEntity(name="Ana"),),
                relations=(
                    ExtractedRelation(subject="Ana", label="interested_in", object="pottery"),
                ),
            ),
        },
    )
    service.remember(POTTERY, author="Adrian")
    service.remember(again, author="Ana")

    profile = service.profile("Ana")

    assert profile is not None
    [interested_in] = [sr for sr in profile.relations if sr.relation.label == "interested_in"]
    assert [m.text for m in interested_in.memories] == [POTTERY, again]
