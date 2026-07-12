"""Inline extraction on write: remember derives the graph and date indexes.

All behavior is exercised through the service seam with the fake Extractor;
no test touches tables or a real model.
"""

from pathlib import Path

import pytest

from conftest import make_failing_extraction_service, make_keyless_service, make_service
from homelore.domain import (
    ExtractedEntity,
    ExtractedRelation,
    ExtractedSpecialDate,
    Extraction,
    Relation,
    SpecialDate,
)
from homelore.service import MissingApiKeyError

POTTERY_MEMORY = "Ana mentioned she wants to learn pottery"
UNIT_VECTOR = [1.0, 0.0, 0.0]


def test_remember_derives_entities_and_relations_inline(tmp_path: Path) -> None:
    service, _ = make_service(
        tmp_path,
        vectors={POTTERY_MEMORY: UNIT_VECTOR},
        extractions={
            POTTERY_MEMORY: Extraction(
                entities=(ExtractedEntity(name="Ana"), ExtractedEntity(name="pottery")),
                relations=(
                    ExtractedRelation(subject="Ana", label="interested_in", object="pottery"),
                ),
            )
        },
    )

    result = service.remember(POTTERY_MEMORY, author="Adrian")

    assert result.extraction_pending is False
    assert [entity.name for entity in result.entities] == ["Ana", "pottery"]
    assert result.relations == (Relation(subject="Ana", label="interested_in", object="pottery"),)


def test_aliases_resolve_to_the_same_entity_across_memories(tmp_path: Path) -> None:
    wife_memory = "my wife said the pottery class starts in September"
    service, _ = make_service(
        tmp_path,
        vectors={POTTERY_MEMORY: UNIT_VECTOR, wife_memory: UNIT_VECTOR},
        extractions={
            POTTERY_MEMORY: Extraction(entities=(ExtractedEntity(name="Ana"),)),
            # The extractor recognized "my wife" as the known entity Ana.
            wife_memory: Extraction(
                entities=(ExtractedEntity(name="Ana", aliases=("my wife",)),),
                relations=(
                    ExtractedRelation(subject="my wife", label="attends", object="pottery class"),
                ),
            ),
        },
    )
    first = service.remember(POTTERY_MEMORY, author="Adrian")

    second = service.remember(wife_memory, author="Adrian")

    [ana_before] = first.entities
    ana_after = next(entity for entity in second.entities if entity.name == "Ana")
    assert ana_after.id == ana_before.id
    assert "my wife" in ana_after.aliases
    # The relation is recorded against the canonical name, not the alias.
    assert second.relations[0].subject == "Ana"


def test_entity_identity_survives_reopening_even_when_named_by_alias(tmp_path: Path) -> None:
    wheel_memory = "my wife found a used pottery wheel"
    vectors = {POTTERY_MEMORY: UNIT_VECTOR, wheel_memory: UNIT_VECTOR}
    first_session, _ = make_service(
        tmp_path,
        vectors,
        extractions={
            POTTERY_MEMORY: Extraction(
                entities=(ExtractedEntity(name="Ana", aliases=("my wife",)),)
            )
        },
    )
    [ana] = first_session.remember(POTTERY_MEMORY, author="Adrian").entities

    second_session, _ = make_service(
        tmp_path,
        vectors,
        # The extractor emitted the alias as the entity's name this time.
        extractions={wheel_memory: Extraction(entities=(ExtractedEntity(name="my wife"),))},
    )
    result = second_session.remember(wheel_memory, author="Adrian")

    [entity] = result.entities
    assert entity.id == ana.id
    assert entity.name == "Ana"


def test_remember_derives_special_dates_against_the_canonical_entity(tmp_path: Path) -> None:
    birthday_memory = "Mia was born on March 3rd, 2018"
    service, _ = make_service(
        tmp_path,
        vectors={birthday_memory: UNIT_VECTOR},
        extractions={
            birthday_memory: Extraction(
                entities=(ExtractedEntity(name="Mia"),),
                special_dates=(
                    ExtractedSpecialDate(entity="Mia", label="birthday", month=3, day=3, year=2018),
                ),
            )
        },
    )

    result = service.remember(birthday_memory, author="Ana")

    assert result.special_dates == (
        SpecialDate(entity="Mia", label="birthday", month=3, day=3, year=2018),
    )


def test_extraction_failure_still_saves_the_memory_and_flags_the_retry(tmp_path: Path) -> None:
    service, _ = make_failing_extraction_service(tmp_path, vectors={POTTERY_MEMORY: UNIT_VECTOR})

    result = service.remember(POTTERY_MEMORY, author="Adrian")

    assert result.extraction_pending is True
    assert result.entities == ()
    [recalled] = service.recall(POTTERY_MEMORY)
    assert recalled.memory.text == POTTERY_MEMORY


def test_without_api_key_remember_fails_with_guidance_but_recall_works(tmp_path: Path) -> None:
    vectors = {POTTERY_MEMORY: UNIT_VECTOR}
    keyed, _ = make_service(tmp_path, vectors)
    keyed.remember(POTTERY_MEMORY, author="Adrian")

    keyless, _ = make_keyless_service(tmp_path, vectors)

    with pytest.raises(MissingApiKeyError, match="ANTHROPIC_API_KEY"):
        keyless.remember("anything new", author="Adrian")
    [recalled] = keyless.recall(POTTERY_MEMORY)
    assert recalled.memory.text == POTTERY_MEMORY
