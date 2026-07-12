"""The Demo Family: the fictional family whose memories ship with the
repository as seed data (see CONTEXT.md). No real family data appears here.

Three fixtures live alongside this module:

- ``memories.jsonl`` — the memories file the demo build imports, written to
  exercise the hard cases: facts superseded over time, one person under many
  aliases, answers needing several memories, dates at year boundaries, and
  graph structure that clusters into distinct communities.
- ``extractions.json`` — the hand-authored ground-truth extraction of every
  memory, keyed by its exact text. It drives the keyless fixture build the
  unit suite runs the deterministic golden pairs against.
- ``golden.jsonl`` — ~50 golden question/answer pairs covering the four query
  tools: recall, profile, upcoming_dates, and reflect. ``remember`` is covered
  by the build itself — every fixture memory flows through the same write
  path. Pairs marked ``keyless`` have deterministic answers and run in the
  unit suite; the full set is the eval harness's material.
"""

import json
from dataclasses import dataclass
from datetime import date
from importlib import resources
from typing import Any, cast

from homelore.domain import (
    ExtractedEntity,
    ExtractedRelation,
    ExtractedSpecialDate,
    Extraction,
    MemoryDraft,
    Relation,
    UpcomingDate,
)
from homelore.memories_file import read_memories_file


@dataclass(frozen=True)
class GoldenRecall:
    """A recall question; the top hits must include every expected memory,
    matched by substring of the memory text."""

    question: str
    expect_memories: tuple[str, ...]
    keyless: bool


@dataclass(frozen=True)
class GoldenProfile:
    """A profile lookup: ``name`` (often an alias) must resolve to the
    expected entity and carry the expected relations and memories."""

    question: str
    name: str
    expect_entity: str
    expect_relations: tuple[Relation, ...]
    expect_memories: tuple[str, ...]
    keyless: bool


@dataclass(frozen=True)
class GoldenUpcomingDates:
    """A date-window question asked as of a fixed day; the answer is exact —
    every expected occurrence, nothing else, in order."""

    question: str
    as_of: date
    days: int
    expect: tuple[UpcomingDate, ...]
    keyless: bool


@dataclass(frozen=True)
class GoldenReflect:
    """A global question; a faithful answer draws on the memories these
    substrings identify. Judged by the eval harness, never keyless."""

    question: str
    expect_grounded_in: tuple[str, ...]
    keyless: bool


GoldenPair = GoldenRecall | GoldenProfile | GoldenUpcomingDates | GoldenReflect


def demo_memories() -> list[MemoryDraft]:
    """The Demo Family's memories file, parsed into importable drafts."""
    with resources.as_file(resources.files(__name__) / "memories.jsonl") as path:
        return read_memories_file(path)


def demo_extractions() -> dict[str, Extraction]:
    """The ground-truth extraction of each fixture memory, keyed by its text."""
    parsed: Any = json.loads(_read("extractions.json"))
    records = cast(dict[str, dict[str, Any]], parsed)
    return {text: _extraction(record) for text, record in records.items()}


def demo_golden() -> tuple[GoldenPair, ...]:
    """The golden Q/A pairs, rejecting the first malformed line by number."""
    pairs: list[GoldenPair] = []
    for number, line in enumerate(_read("golden.jsonl").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            pairs.append(_parse_pair(line))
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError(f"golden.jsonl, line {number}: {error}") from error
    return tuple(pairs)


def _read(filename: str) -> str:
    return (resources.files(__name__) / filename).read_text()


def _extraction(record: dict[str, Any]) -> Extraction:
    if unknown := set(record) - {"entities", "relations", "special_dates"}:
        raise ValueError(f"unknown extraction fields: {', '.join(sorted(unknown))}")
    return Extraction(
        entities=tuple(
            ExtractedEntity(name=entity["name"], aliases=tuple(entity["aliases"]))
            for entity in record.get("entities", ())
        ),
        relations=tuple(
            ExtractedRelation(
                subject=relation["subject"], label=relation["label"], object=relation["object"]
            )
            for relation in record.get("relations", ())
        ),
        special_dates=tuple(
            ExtractedSpecialDate(
                entity=special["entity"],
                label=special["label"],
                month=special["month"],
                day=special["day"],
                year=special.get("year"),
            )
            for special in record.get("special_dates", ())
        ),
    )


def _parse_pair(line: str) -> GoldenPair:
    parsed: Any = json.loads(line)
    if not isinstance(parsed, dict):
        raise ValueError("expected a JSON object")
    record = cast(dict[str, Any], parsed)
    parsers = {
        "recall": _recall_pair,
        "profile": _profile_pair,
        "upcoming_dates": _upcoming_dates_pair,
        "reflect": _reflect_pair,
    }
    tool = record.get("tool")
    if tool not in parsers:
        raise ValueError(f"unknown tool: {tool!r}")
    return parsers[tool](record)


def _expect_fields(record: dict[str, Any], fields: set[str]) -> None:
    expected = fields | {"tool", "question", "keyless"}
    if record.keys() != expected:
        raise ValueError(f"fields must be exactly {sorted(expected)}, got {sorted(record.keys())}")


def _recall_pair(record: dict[str, Any]) -> GoldenRecall:
    _expect_fields(record, {"expect_memories"})
    return GoldenRecall(
        question=record["question"],
        expect_memories=tuple(record["expect_memories"]),
        keyless=record["keyless"],
    )


def _profile_pair(record: dict[str, Any]) -> GoldenProfile:
    _expect_fields(record, {"name", "expect_entity", "expect_relations", "expect_memories"})
    return GoldenProfile(
        question=record["question"],
        name=record["name"],
        expect_entity=record["expect_entity"],
        expect_relations=tuple(
            Relation(subject=r["subject"], label=r["label"], object=r["object"])
            for r in record["expect_relations"]
        ),
        expect_memories=tuple(record["expect_memories"]),
        keyless=record["keyless"],
    )


def _upcoming_dates_pair(record: dict[str, Any]) -> GoldenUpcomingDates:
    _expect_fields(record, {"as_of", "days", "expect"})
    return GoldenUpcomingDates(
        question=record["question"],
        as_of=date.fromisoformat(record["as_of"]),
        days=record["days"],
        expect=tuple(
            UpcomingDate(
                entity=u["entity"],
                label=u["label"],
                occurs_on=date.fromisoformat(u["occurs_on"]),
                years=u.get("years"),
            )
            for u in record["expect"]
        ),
        keyless=record["keyless"],
    )


def _reflect_pair(record: dict[str, Any]) -> GoldenReflect:
    _expect_fields(record, {"expect_grounded_in"})
    return GoldenReflect(
        question=record["question"],
        expect_grounded_in=tuple(record["expect_grounded_in"]),
        keyless=record["keyless"],
    )
