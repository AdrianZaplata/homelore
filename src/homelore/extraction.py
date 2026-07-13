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
    Memory,
    Relation,
)

MODEL = "claude-haiku-4-5"

_SYSTEM = """\
You extract structured family knowledge from one memory note written by a family member. \
The note's header says who wrote it and when — use both: the author grounds first-person \
mentions ("my wife", written by Espen, is whoever the known relations say Espen is married \
to), and the dates ground relative references ("a year ago on December 27th", "turned \
seven today").

Return:
- entities: the people, places, things, or concepts the memory is about. Resolve every \
mention against the known entities and relations: a mention that refers to a known entity \
— by canonical name, by alias, or through the author and a known relation — is that \
entity. Use its canonical name as `name` and record this memory's differing mentions \
under `aliases`. Only introduce a new entity when the mention matches nothing known.
  A new entity's canonical name is the shortest name that identifies it by itself: \
"Ruth", not "Coach Ruth"; "Dolphins", not "the Dolphins swim club". Record the longer \
forms as aliases, and record a kinship or title word the family uses on its own \
("Farmor") as another alias.
- relations: labeled connections between two extracted or known entities. Labels are \
free-form snake_case strings chosen to fit the memory (e.g. interested_in, attends, \
parent_of) — there is no fixed vocabulary. Record the connections a reader of each \
person's profile would expect to find there: where they live, what they are into, what \
they belong to, who they know. The known lists exist to resolve mentions, not to \
deduplicate: record every relation this note supports even when a matching one is \
already known — re-assertion is how a fact stays current. Name an interest or hobby by \
its plain noun ("beekeeping", "dinosaurs").
- special_dates: dates the family will mark every year, each tied to a person, pet, or \
place the family knows: birthdays, wedding anniversaries, a pet's gotcha day. Label each \
the way the family says it ("birthday", "wedding anniversary", "gotcha day"). A shared \
date belongs to each person it is about — a wedding anniversary is one entry per spouse. \
Set month and day only when the note states them or they follow from the note's own \
dates; when an event is never pinned to a month and day, return null for both and the \
entry will be dropped rather than guessed. Set year to the year the occasion first \
happened — the birth, the wedding, the day the pet came home — when stated or computable, \
else null; mind the arithmetic on ordinals: a "second gotcha day" in a note written in \
2025 means the pet came home in 2023. Birthdays, wedding anniversaries, and gotcha days \
always qualify; any other date qualifies only when the note shows the family marking it \
every year. Public holidays (Valentine's Day, New Year's Eve) and one-off milestones (a \
lost tooth, starting school) never qualify. When unsure, leave the date out.

Extract what the text states or clearly implies; empty lists are fine. Never guess \
names, dates, or years the note does not support.
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
                    "month": {"type": ["integer", "null"]},
                    "day": {"type": ["integer", "null"]},
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
    """Extraction against Claude Haiku 4.5 with schema-constrained JSON output,
    at temperature 0 so repeated builds extract the same facts.

    A special date the model could not pin to a month and day arrives with
    nulls (the schema allows it exactly so the model never has to invent a
    date) and is dropped here.

    Errors (API failures, refusals, malformed output) propagate — the service
    treats any failure as retryable, never as data loss.
    """

    def __init__(self) -> None:
        self._client = anthropic.Anthropic()

    def extract(
        self,
        memory: Memory,
        known_entities: Sequence[Entity],
        known_relations: Sequence[Relation],
    ) -> Extraction:
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=2048,
            temperature=0.0,
            system=_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA}},
            messages=[
                {"role": "user", "content": _prompt(memory, known_entities, known_relations)}
            ],
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
                if special_date["month"] is not None and special_date["day"] is not None
            ),
        )


def _prompt(
    memory: Memory, known_entities: Sequence[Entity], known_relations: Sequence[Relation]
) -> str:
    if known_entities:
        lines = "\n".join(
            f"- {entity.name}"
            + (f" (aliases: {', '.join(entity.aliases)})" if entity.aliases else "")
            for entity in known_entities
        )
        known = f"Known entities:\n{lines}"
    else:
        known = "Known entities: none yet."
    if known_relations:
        lines = "\n".join(
            f"- {relation.subject} {relation.label} {relation.object}"
            for relation in known_relations
        )
        known += f"\n\nKnown relations:\n{lines}"
    else:
        known += "\n\nKnown relations: none yet."
    header = f"Memory, written by {memory.author} on {memory.created_at.date().isoformat()}"
    if memory.event_date is not None:
        header += f", about events of {memory.event_date.isoformat()}"
    return f"{known}\n\n{header}:\n{memory.text}"
