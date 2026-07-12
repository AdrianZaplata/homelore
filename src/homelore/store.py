import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Self

import sqlite_vec

from homelore.domain import Memory

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL,
    event_date TEXT,
    embedding BLOB NOT NULL
);
"""


@dataclass(frozen=True)
class SearchHit:
    memory: Memory
    similarity: float


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
            "SELECT id, text, author, created_at, event_date,"
            " 1 - vec_distance_cosine(embedding, ?) AS similarity"
            " FROM memories ORDER BY similarity DESC",
            (sqlite_vec.serialize_float32(query_embedding),),
        ).fetchall()
        return [
            SearchHit(
                memory=Memory(
                    id=row[0],
                    text=row[1],
                    author=row[2],
                    created_at=datetime.fromisoformat(row[3]),
                    event_date=date.fromisoformat(row[4]) if row[4] is not None else None,
                ),
                similarity=row[5],
            )
            for row in rows
        ]
