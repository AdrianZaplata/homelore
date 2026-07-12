import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Self

import sqlite_vec

from homelore.domain import (
    Entity,
    Extraction,
    Memory,
    Relation,
    SpecialDate,
    SupportedRelation,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL,
    event_date TEXT,
    embedding BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entity_aliases (
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    alias TEXT NOT NULL,
    UNIQUE (entity_id, alias)
);
CREATE TABLE IF NOT EXISTS relations (
    memory_id INTEGER NOT NULL REFERENCES memories(id),
    subject_id INTEGER NOT NULL REFERENCES entities(id),
    label TEXT NOT NULL,
    object_id INTEGER NOT NULL REFERENCES entities(id),
    UNIQUE (memory_id, subject_id, label, object_id)
);
CREATE TABLE IF NOT EXISTS special_dates (
    memory_id INTEGER NOT NULL REFERENCES memories(id),
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    label TEXT NOT NULL,
    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    day INTEGER NOT NULL CHECK (day BETWEEN 1 AND 31),
    year INTEGER,
    UNIQUE (memory_id, entity_id, label, month, day)
);
CREATE TABLE IF NOT EXISTS mentions (
    memory_id INTEGER NOT NULL REFERENCES memories(id),
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    UNIQUE (memory_id, entity_id)
);
CREATE TABLE IF NOT EXISTS extraction_retries (
    memory_id INTEGER PRIMARY KEY REFERENCES memories(id)
);
"""

# Memories extracted before the mentions table existed have relation and date
# rows but no mention rows; rebuild what those imply so they stay reachable
# through the graph. Idempotent, so it simply runs on every open.
_BACKFILL_MENTIONS = """
INSERT OR IGNORE INTO mentions (memory_id, entity_id)
    SELECT memory_id, subject_id FROM relations
    UNION SELECT memory_id, object_id FROM relations
    UNION SELECT memory_id, entity_id FROM special_dates;
"""


_MEMORY_COLUMNS = (
    "memories.id, memories.text, memories.author, memories.created_at, memories.event_date"
)


def _memory_from_row(row: tuple[int, str, str, str, str | None]) -> Memory:
    return Memory(
        id=row[0],
        text=row[1],
        author=row[2],
        created_at=datetime.fromisoformat(row[3]),
        event_date=date.fromisoformat(row[4]) if row[4] is not None else None,
    )


@dataclass(frozen=True)
class DerivedFacts:
    """What one memory contributed to the derived indexes, names resolved."""

    entities: tuple[Entity, ...]
    relations: tuple[Relation, ...]
    special_dates: tuple[SpecialDate, ...]


@dataclass(frozen=True)
class SearchHit:
    memory: Memory
    similarity: float


class GraphIndex:
    """The Graph Index loaded into memory for traversal: which entities each
    memory mentions, and which entities relations connect.

    Derived and disposable per ADR 0001; family-scale, so whole-graph loads
    are cheap.
    """

    def __init__(
        self,
        mentions: Iterable[tuple[int, int]],
        edges: Iterable[tuple[int, int]],
    ) -> None:
        self._entities_by_memory: dict[int, set[int]] = defaultdict(set)
        self._memories_by_entity: dict[int, set[int]] = defaultdict(set)
        self._neighbors: dict[int, set[int]] = defaultdict(set)
        for memory_id, entity_id in mentions:
            self._entities_by_memory[memory_id].add(entity_id)
            self._memories_by_entity[entity_id].add(memory_id)
        for subject_id, object_id in edges:
            self._neighbors[subject_id].add(object_id)
            self._neighbors[object_id].add(subject_id)

    def connected_memories(self, memory_id: int) -> frozenset[int]:
        """Other memories mentioning anything in this memory's entity
        neighborhood — its entities plus everything one relation away."""
        neighborhood = set(self._entities_by_memory.get(memory_id, ()))
        for entity_id in tuple(neighborhood):
            neighborhood |= self._neighbors.get(entity_id, set())
        memories: set[int] = set()
        for entity_id in neighborhood:
            memories |= self._memories_by_entity.get(entity_id, set())
        return frozenset(memories - {memory_id})


class MemoryStore:
    """Append-only memory log with vector search, in a single SQLite file."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def open(cls, path: Path) -> Self:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
        connection.executescript(_SCHEMA)
        with connection:
            connection.execute(_BACKFILL_MENTIONS)
        return cls(connection)

    def add(
        self,
        text: str,
        author: str,
        created_at: datetime,
        event_date: date | None,
        embedding: list[float],
    ) -> Memory:
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO memories (text, author, created_at, event_date, embedding)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    text,
                    author,
                    created_at.isoformat(),
                    event_date.isoformat() if event_date is not None else None,
                    sqlite_vec.serialize_float32(embedding),
                ),
            )
        memory_id = cursor.lastrowid
        assert memory_id is not None
        return Memory(
            id=memory_id, text=text, author=author, created_at=created_at, event_date=event_date
        )

    def search(self, query_embedding: list[float]) -> list[SearchHit]:
        """All memories with their similarity to the query, most similar first.

        A full scan: right-sized for a single family's data volume, and it lets
        recall rerank exactly instead of guessing a candidate pool.
        """
        rows = self._connection.execute(
            f"SELECT {_MEMORY_COLUMNS},"
            " 1 - vec_distance_cosine(embedding, ?) AS similarity"
            " FROM memories ORDER BY similarity DESC",
            (sqlite_vec.serialize_float32(query_embedding),),
        ).fetchall()
        return [SearchHit(memory=_memory_from_row(row), similarity=row[5]) for row in rows]

    def list_entities(self) -> list[Entity]:
        aliases: dict[int, list[str]] = defaultdict(list)
        for entity_id, alias in self._connection.execute(
            "SELECT entity_id, alias FROM entity_aliases ORDER BY rowid"
        ):
            aliases[entity_id].append(alias)
        return [
            Entity(id=row[0], name=row[1], aliases=tuple(aliases[row[0]]))
            for row in self._connection.execute("SELECT id, name FROM entities ORDER BY id")
        ]

    def save_extraction(self, memory_id: int, extraction: Extraction) -> DerivedFacts:
        """Fold one memory's extraction into the derived indexes, atomically.

        An extracted name matching an existing entity's canonical name or alias
        (case-insensitively) is that entity; other mentions of it become
        aliases. Names appearing only as relation or date endpoints become bare
        entities — a mention is a mention.
        """
        with self._connection:
            resolver = _EntityResolver(self._connection)
            for extracted in extraction.entities:
                resolver.register(extracted.name, extracted.aliases)
            relations: list[Relation] = []
            for extracted_relation in extraction.relations:
                subject_id = resolver.register(extracted_relation.subject)
                object_id = resolver.register(extracted_relation.object)
                self._connection.execute(
                    "INSERT OR IGNORE INTO relations (memory_id, subject_id, label, object_id)"
                    " VALUES (?, ?, ?, ?)",
                    (memory_id, subject_id, extracted_relation.label, object_id),
                )
                relations.append(
                    Relation(
                        subject=resolver.canonical_name(subject_id),
                        label=extracted_relation.label,
                        object=resolver.canonical_name(object_id),
                    )
                )
            special_dates: list[SpecialDate] = []
            for extracted_date in extraction.special_dates:
                entity_id = resolver.register(extracted_date.entity)
                self._connection.execute(
                    "INSERT OR IGNORE INTO special_dates"
                    " (memory_id, entity_id, label, month, day, year)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        memory_id,
                        entity_id,
                        extracted_date.label,
                        extracted_date.month,
                        extracted_date.day,
                        extracted_date.year,
                    ),
                )
                special_dates.append(
                    SpecialDate(
                        entity=resolver.canonical_name(entity_id),
                        label=extracted_date.label,
                        month=extracted_date.month,
                        day=extracted_date.day,
                        year=extracted_date.year,
                    )
                )
            for entity_id in resolver.touched:
                self._connection.execute(
                    "INSERT OR IGNORE INTO mentions (memory_id, entity_id) VALUES (?, ?)",
                    (memory_id, entity_id),
                )
            self._connection.execute(
                "DELETE FROM extraction_retries WHERE memory_id = ?", (memory_id,)
            )
        entities_by_id = {entity.id: entity for entity in self.list_entities()}
        return DerivedFacts(
            entities=tuple(entities_by_id[entity_id] for entity_id in resolver.touched),
            relations=tuple(relations),
            special_dates=tuple(special_dates),
        )

    def find_entity(self, name: str) -> Entity | None:
        """The entity ``name`` refers to, resolved with the exact same
        name-and-alias matching that extraction resolves against."""
        entity_id = _EntityResolver(self._connection).resolve(name)
        if entity_id is None:
            return None
        return next(entity for entity in self.list_entities() if entity.id == entity_id)

    def relations_about(self, entity_id: int) -> tuple[SupportedRelation, ...]:
        """Every relation the entity takes part in, as subject or object, each
        with the memories asserting it, in first-asserted order."""
        names = {
            row[0]: row[1] for row in self._connection.execute("SELECT id, name FROM entities")
        }
        rows = self._connection.execute(
            f"SELECT relations.subject_id, relations.label, relations.object_id,"
            f" {_MEMORY_COLUMNS}"
            " FROM relations JOIN memories ON memories.id = relations.memory_id"
            " WHERE ? IN (relations.subject_id, relations.object_id)"
            " ORDER BY relations.rowid",
            (entity_id,),
        ).fetchall()
        supporting: dict[Relation, list[Memory]] = {}
        for row in rows:
            relation = Relation(subject=names[row[0]], label=row[1], object=names[row[2]])
            supporting.setdefault(relation, []).append(_memory_from_row(row[3:]))
        return tuple(
            SupportedRelation(relation=relation, memories=tuple(memories))
            for relation, memories in supporting.items()
        )

    def memories_mentioning(self, entity_id: int) -> tuple[Memory, ...]:
        """Memories that mention the entity, newest happening first."""
        rows = self._connection.execute(
            f"SELECT {_MEMORY_COLUMNS} FROM memories"
            " JOIN mentions ON mentions.memory_id = memories.id"
            " WHERE mentions.entity_id = ?",
            (entity_id,),
        ).fetchall()
        memories = [_memory_from_row(row) for row in rows]
        memories.sort(key=lambda memory: (memory.happened_on, memory.id), reverse=True)
        return tuple(memories)

    def list_special_dates(self) -> tuple[SpecialDate, ...]:
        """The deterministic date index: every special date, deduplicated
        across the memories asserting it, in no particular order. A year known
        to any memory is kept; should memories disagree, the greatest wins."""
        rows = self._connection.execute(
            "SELECT entities.name, special_dates.label, special_dates.month,"
            " special_dates.day, MAX(special_dates.year)"
            " FROM special_dates JOIN entities ON entities.id = special_dates.entity_id"
            " GROUP BY special_dates.entity_id, special_dates.label,"
            " special_dates.month, special_dates.day"
        ).fetchall()
        return tuple(
            SpecialDate(entity=row[0], label=row[1], month=row[2], day=row[3], year=row[4])
            for row in rows
        )

    def load_graph(self) -> GraphIndex:
        return GraphIndex(
            mentions=self._connection.execute("SELECT memory_id, entity_id FROM mentions"),
            edges=self._connection.execute("SELECT subject_id, object_id FROM relations"),
        )

    def mark_extraction_pending(self, memory_id: int) -> None:
        """Flag a memory whose extraction failed, so reindex can heal it."""
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO extraction_retries (memory_id) VALUES (?)", (memory_id,)
            )


class _EntityResolver:
    """Resolves mentions to entity ids within one save, creating and merging
    as needed. Matching is case-insensitive over canonical names and aliases."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._ids_by_mention: dict[str, int] = {}
        self._names_by_id: dict[int, str] = {}
        self.touched: list[int] = []
        for entity_id, name in connection.execute("SELECT id, name FROM entities"):
            self._ids_by_mention[name.casefold()] = entity_id
            self._names_by_id[entity_id] = name
        for entity_id, alias in connection.execute("SELECT entity_id, alias FROM entity_aliases"):
            self._ids_by_mention.setdefault(alias.casefold(), entity_id)

    def resolve(self, mention: str) -> int | None:
        return self._ids_by_mention.get(mention.casefold())

    def register(self, name: str, aliases: tuple[str, ...] = ()) -> int:
        mentions = [name, *aliases]
        entity_id = next(
            (found for mention in mentions if (found := self.resolve(mention)) is not None),
            None,
        )
        if entity_id is None:
            cursor = self._connection.execute("INSERT INTO entities (name) VALUES (?)", (name,))
            entity_id = cursor.lastrowid
            assert entity_id is not None
            self._names_by_id[entity_id] = name
        for mention in mentions:
            key = mention.casefold()
            if key == self._names_by_id[entity_id].casefold():
                continue
            if key not in self._ids_by_mention:
                self._connection.execute(
                    "INSERT OR IGNORE INTO entity_aliases (entity_id, alias) VALUES (?, ?)",
                    (entity_id, mention),
                )
            self._ids_by_mention.setdefault(key, entity_id)
        self._ids_by_mention.setdefault(name.casefold(), entity_id)
        if entity_id not in self.touched:
            self.touched.append(entity_id)
        return entity_id

    def canonical_name(self, entity_id: int) -> str:
        return self._names_by_id[entity_id]
