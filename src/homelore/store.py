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
CREATE TABLE IF NOT EXISTS communities (
    entity_ids TEXT NOT NULL,
    memory_ids TEXT NOT NULL,
    summary TEXT NOT NULL,
    PRIMARY KEY (entity_ids, memory_ids)
);
CREATE TABLE IF NOT EXISTS community_state (
    write_generation INTEGER NOT NULL,
    clean_generation INTEGER
);
"""

# One row, created on open: write_generation counts writes, clean_generation
# records the generation the community layer was last refreshed against.
_INIT_COMMUNITY_STATE = """
INSERT INTO community_state (write_generation, clean_generation)
    SELECT 0, NULL WHERE NOT EXISTS (SELECT 1 FROM community_state);
"""

_MARK_COMMUNITIES_DIRTY = "UPDATE community_state SET write_generation = write_generation + 1"

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


def _encode_ids(ids: tuple[int, ...]) -> str:
    return ",".join(str(id_) for id_ in ids)


def _decode_ids(encoded: str) -> tuple[int, ...]:
    return tuple(int(part) for part in encoded.split(","))


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


@dataclass(frozen=True)
class Community:
    """A cluster of closely connected entities plus the memories mentioning
    them. Identity is the full membership: any change to either set makes it
    a different community, whose summary must be rewritten."""

    entity_ids: tuple[int, ...]
    memory_ids: tuple[int, ...]


@dataclass(frozen=True)
class SummarizedCommunity:
    community: Community
    summary: str


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

    def communities(self) -> tuple[Community, ...]:
        """Clusters of closely connected entities: two entities connect when
        a relation links them or one memory mentions both. Connected
        components are the v1 clustering — family-scale graphs split along
        life domains, and the algorithm stays a private detail here."""
        adjacency: dict[int, set[int]] = defaultdict(set)
        for entity_id, neighbors in self._neighbors.items():
            adjacency[entity_id] |= neighbors
        for entity_ids in self._entities_by_memory.values():
            for entity_id in entity_ids:
                adjacency[entity_id] |= entity_ids - {entity_id}
        communities: list[Community] = []
        seen: set[int] = set()
        for start in sorted(set(self._memories_by_entity) | set(adjacency)):
            if start in seen:
                continue
            component = {start}
            frontier = [start]
            while frontier:
                for neighbor in adjacency[frontier.pop()]:
                    if neighbor not in component:
                        component.add(neighbor)
                        frontier.append(neighbor)
            seen |= component
            memory_ids = {
                memory_id
                for entity_id in component
                for memory_id in self._memories_by_entity.get(entity_id, ())
            }
            communities.append(
                Community(
                    entity_ids=tuple(sorted(component)),
                    memory_ids=tuple(sorted(memory_ids)),
                )
            )
        return tuple(communities)


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
            connection.execute(_INIT_COMMUNITY_STATE)
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
            self._connection.execute(_MARK_COMMUNITIES_DIRTY)
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

    def list_relations(self) -> tuple[Relation, ...]:
        """Every distinct relation with canonical endpoint names, in
        first-asserted order — the graph context extraction resolves
        first-person mentions ("my wife") against."""
        rows = self._connection.execute(
            "SELECT subject.name, relations.label, object.name"
            " FROM relations"
            " JOIN entities AS subject ON subject.id = relations.subject_id"
            " JOIN entities AS object ON object.id = relations.object_id"
            " GROUP BY relations.subject_id, relations.label, relations.object_id"
            " ORDER BY MIN(relations.rowid)"
        ).fetchall()
        return tuple(Relation(subject=row[0], label=row[1], object=row[2]) for row in rows)

    def save_extraction(self, memory_id: int, extraction: Extraction) -> DerivedFacts:
        """Fold one memory's extraction into the derived indexes, atomically.

        An extracted name matching an existing entity's canonical name or alias
        (case-insensitively) is that entity; other mentions of it become
        aliases. Names appearing only as relation or date endpoints become bare
        entities — a mention is a mention.
        """
        with self._connection:
            self._connection.execute(_MARK_COMMUNITIES_DIRTY)
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

    def memories_by_ids(self, memory_ids: tuple[int, ...]) -> tuple[Memory, ...]:
        """The given memories, oldest happening first — chronological order,
        the shape a synthesis wants to read them in."""
        placeholders = ",".join("?" for _ in memory_ids)
        rows = self._connection.execute(
            f"SELECT {_MEMORY_COLUMNS} FROM memories WHERE id IN ({placeholders})",
            memory_ids,
        ).fetchall()
        memories = [_memory_from_row(row) for row in rows]
        memories.sort(key=lambda memory: (memory.happened_on, memory.id))
        return tuple(memories)

    def communities_dirty(self) -> bool:
        """Whether the community layer must be rebuilt before it is trusted:
        writes have happened since the generation it was last refreshed
        against. A database with no memories has nothing to summarize and is
        never dirty — so a never-refreshed database that already holds
        memories (e.g. upgraded from before communities existed) correctly
        reads as dirty."""
        row = self._connection.execute(
            "SELECT EXISTS (SELECT 1 FROM memories)"
            " AND (clean_generation IS NULL OR clean_generation <> write_generation)"
            " FROM community_state"
        ).fetchone()
        return bool(row[0])

    def community_write_generation(self) -> int:
        """The current write generation — capture it before clustering and
        hand it back to replace_communities, so a write landing mid-refresh
        keeps the layer dirty instead of being silently marked current."""
        row = self._connection.execute("SELECT write_generation FROM community_state").fetchone()
        return int(row[0])

    def saved_communities(self) -> tuple[SummarizedCommunity, ...]:
        """The stored community layer: every community with its summary."""
        rows = self._connection.execute(
            "SELECT entity_ids, memory_ids, summary FROM communities"
        ).fetchall()
        return tuple(
            SummarizedCommunity(
                community=Community(entity_ids=_decode_ids(row[0]), memory_ids=_decode_ids(row[1])),
                summary=row[2],
            )
            for row in rows
        )

    def replace_communities(
        self, communities: tuple[SummarizedCommunity, ...], as_of_generation: int
    ) -> None:
        """Swap in the freshly clustered community layer, atomically — a
        failed refresh leaves the old layer and the dirty state untouched.

        The layer is clean only as of ``as_of_generation``, the write
        generation the refresh clustered from; writes that landed since keep
        it dirty for the next refresh."""
        with self._connection:
            self._connection.execute("DELETE FROM communities")
            self._connection.executemany(
                "INSERT INTO communities (entity_ids, memory_ids, summary) VALUES (?, ?, ?)",
                [
                    (
                        _encode_ids(summarized.community.entity_ids),
                        _encode_ids(summarized.community.memory_ids),
                        summarized.summary,
                    )
                    for summarized in communities
                ],
            )
            self._connection.execute(
                "UPDATE community_state SET clean_generation = ?", (as_of_generation,)
            )

    def mark_extraction_pending(self, memory_id: int) -> None:
        """Flag a memory whose extraction failed, so reindex can heal it."""
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO extraction_retries (memory_id) VALUES (?)", (memory_id,)
            )

    def reset_derived_indexes(self) -> None:
        """Drop every derived structure and flag every memory for
        re-extraction, in one transaction — the first step of a full rebuild
        (ADR 0001). The memory log is untouched; interrupting after this
        commit leaves the remaining work flagged, so healing finishes it."""
        with self._connection:
            self._connection.execute(_MARK_COMMUNITIES_DIRTY)
            derived = (
                "relations",
                "special_dates",
                "mentions",
                "entity_aliases",
                "entities",
                "communities",
            )
            for table in derived:
                self._connection.execute(f"DELETE FROM {table}")
            self._connection.execute(
                "INSERT OR IGNORE INTO extraction_retries (memory_id) SELECT id FROM memories"
            )

    def pending_extractions(self) -> tuple[Memory, ...]:
        """The memories awaiting an extraction retry, oldest recorded first —
        replaying in write order lets alias resolution meet entities in the
        same sequence the original writes did."""
        rows = self._connection.execute(
            f"SELECT {_MEMORY_COLUMNS} FROM memories"
            " JOIN extraction_retries ON extraction_retries.memory_id = memories.id"
            " ORDER BY memories.id"
        ).fetchall()
        return tuple(_memory_from_row(row) for row in rows)


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
