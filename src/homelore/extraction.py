import json
from collections.abc import Sequence
from typing import Any

import anthropic

from homelore.domain import (
    Entity,
    ExtractedEntity,
    ExtractedRelation,
    ExtractedSpecialDate,
    Extraction,
)

MODEL = "claude-haiku-4-5"

_SYSTEM = """\
You extract structured family knowledge from one memory note written by a family member.

Return:
- entities: the people, places, things, or concepts the memory is about. Resolve every \
mention against the known-entities list: if a mention refers to a known entity (by its \
canonical name or any alias, e.g. "my wife" when Ana is known to be the wife), use that \
entity's canonical name as `name` and record the mention under `aliases`. Only introduce \
a new entity when the mention matches nothing known.
- relations: labeled connections between two extracted or known entities. Labels are \
free-form snake_case strings chosen to fit the memory (e.g. interested_in, attends, \
parent_of) — there is no fixed vocabulary.
- special_dates: recurring dates tied to an entity (birthday, anniversary, school event) \
with month and day, plus the year of first occurrence when stated (e.g. birth year).

Extract only what the text supports; empty lists are fine. Never invent dates or people.
"""

_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "aliases"],
                "additionalProperties": False,
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "label": {"type": "string"},
                    "object": {"type": "string"},
                },
                "required": ["subject", "label", "object"],
                "additionalProperties": False,
            },
        },
        "special_dates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "label": {"type": "string"},
                    "month": {"type": "integer"},
                    "day": {"type": "integer"},
                    "year": {"type": ["integer", "null"]},
                },
                "required": ["entity", "label", "month", "day", "year"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["entities", "relations", "special_dates"],
    "additionalProperties": False,
}


class ClaudeExtractor:
    """Extraction against Claude Haiku 4.5 with schema-constrained JSON output.

    Errors (API failures, refusals, malformed output) propagate — the service
    treats any failure as retryable, never as data loss.
    """

    def __init__(self) -> None:
        self._client = anthropic.Anthropic()

    def extract(self, text: str, known_entities: Sequence[Entity]) -> Extraction:
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA}},
            messages=[{"role": "user", "content": _prompt(text, known_entities)}],
        )
        raw = next(block.text for block in response.content if block.type == "text")
        data = json.loads(raw)
        return Extraction(
            entities=tuple(
                ExtractedEntity(name=entity["name"], aliases=tuple(entity["aliases"]))
                for entity in data["entities"]
            ),
            relations=tuple(
                ExtractedRelation(
                    subject=relation["subject"],
                    label=relation["label"],
                    object=relation["object"],
                )
                for relation in data["relations"]
            ),
            special_dates=tuple(
                ExtractedSpecialDate(
                    entity=special_date["entity"],
                    label=special_date["label"],
                    month=special_date["month"],
                    day=special_date["day"],
                    year=special_date["year"],
                )
                for special_date in data["special_dates"]
            ),
        )


def _prompt(text: str, known_entities: Sequence[Entity]) -> str:
    if known_entities:
        lines = "\n".join(
            f"- {entity.name}"
            + (f" (aliases: {', '.join(entity.aliases)})" if entity.aliases else "")
            for entity in known_entities
        )
        known = f"Known entities:\n{lines}"
    else:
        known = "Known entities: none yet."
    return f"{known}\n\nMemory:\n{text}"
