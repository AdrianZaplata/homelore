"""The memories file: the bulk-import format, one JSON memory per line.

Each line holds ``text`` and ``author``, plus optional ``created_at`` (ISO
datetime; taken as UTC when no timezone is given) and ``event_date`` (ISO
date). Blank lines are skipped.
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

from homelore.domain import MemoryDraft


def read_memories_file(path: Path) -> list[MemoryDraft]:
    """Parse the memories file into drafts, rejecting the first bad line with
    its line number — nothing is half-imported from a malformed file."""
    drafts: list[MemoryDraft] = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            drafts.append(_parse_line(line))
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError(f"{path}, line {number}: {error}") from error
    return drafts


def _parse_line(line: str) -> MemoryDraft:
    parsed: Any = json.loads(line)
    if not isinstance(parsed, dict):
        raise ValueError("expected a JSON object")
    record = cast(dict[str, Any], parsed)
    known = {"text", "author", "created_at", "event_date"}
    if unknown := set(record) - known:
        raise ValueError(f"unknown fields: {', '.join(sorted(unknown))}")
    for field in ("text", "author"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise ValueError(f"missing or empty '{field}'")
    return MemoryDraft(
        text=record["text"],
        author=record["author"],
        created_at=_parse_created_at(record.get("created_at")),
        event_date=date.fromisoformat(record["event_date"]) if "event_date" in record else None,
    )


def _parse_created_at(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("'created_at' must be an ISO datetime string")
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
