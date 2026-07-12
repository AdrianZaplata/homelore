from datetime import date

from homelore.domain import Memory, RecalledMemory
from homelore.ports import Clock, Embedder
from homelore.store import MemoryStore

_RECENCY_WEIGHT = 0.1
_RECENCY_HALF_LIFE_DAYS = 365.0


class HomeloreService:
    """The application service: every product operation lives here.

    The MCP server and CLI are thin adapters over this class.
    """

    def __init__(self, store: MemoryStore, embedder: Embedder, clock: Clock) -> None:
        self._store = store
        self._embedder = embedder
        self._clock = clock

    def remember(self, text: str, author: str, event_date: date | None = None) -> Memory:
        [embedding] = self._embedder.embed([text])
        return self._store.add(
            text=text,
            author=author,
            created_at=self._clock(),
            event_date=event_date,
            embedding=embedding,
        )

    def recall(self, query: str, limit: int = 5) -> list[RecalledMemory]:
        [query_embedding] = self._embedder.embed([query])
        hits = self._store.search(query_embedding)
        today = self._clock().date()
        recalled = [
            RecalledMemory(memory=hit.memory, score=self._score(hit.similarity, hit.memory, today))
            for hit in hits
        ]
        recalled.sort(key=lambda r: r.score, reverse=True)
        return recalled[:limit]

    def _score(self, similarity: float, memory: Memory, today: date) -> float:
        """Similarity with a small recency bonus, so newer facts outrank
        equally relevant older ones without overriding a clear relevance gap."""
        age_days = max((today - memory.happened_on).days, 0)
        recency = 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)
        return similarity + _RECENCY_WEIGHT * recency
