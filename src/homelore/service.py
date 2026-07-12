import logging
from datetime import date

from homelore.domain import Profile, RecalledMemory, RememberResult
from homelore.ports import Clock, Embedder, Extractor
from homelore.store import MemoryStore, SearchHit

_RECENCY_WEIGHT = 0.1
_RECENCY_HALF_LIFE_DAYS = 365.0
_GRAPH_WEIGHT = 0.2

_logger = logging.getLogger(__name__)


class MissingApiKeyError(Exception):
    """Raised when an operation needs the extraction model but no key is set."""


_MISSING_KEY_MESSAGE = (
    "ANTHROPIC_API_KEY is not set. Homelore needs it to understand new memories"
    " (extracting people, relationships, and dates). Get a key at"
    " https://console.anthropic.com and set the ANTHROPIC_API_KEY environment"
    " variable. Recalling existing memories keeps working without it."
)


class HomeloreService:
    """The application service: every product operation lives here.

    The MCP server and CLI are thin adapters over this class.
    """

    def __init__(
        self,
        store: MemoryStore,
        embedder: Embedder,
        extractor: Extractor | None,
        clock: Clock,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._extractor = extractor
        self._clock = clock

    def remember(self, text: str, author: str, event_date: date | None = None) -> RememberResult:
        """Append a memory and derive the graph and date indexes from it inline.

        Extraction failure never loses the memory: it is saved, flagged for
        retry, and the result says so. A missing API key is different — it is a
        config problem, so we fail before saving rather than silently pile up
        memories that need retrying.
        """
        if self._extractor is None:
            raise MissingApiKeyError(_MISSING_KEY_MESSAGE)
        [embedding] = self._embedder.embed([text])
        memory = self._store.add(
            text=text,
            author=author,
            created_at=self._clock(),
            event_date=event_date,
            embedding=embedding,
        )
        try:
            extraction = self._extractor.extract(text, self._store.list_entities())
            derived = self._store.save_extraction(memory.id, extraction)
        except Exception:
            _logger.exception("extraction failed for memory %d; marked for retry", memory.id)
            self._store.mark_extraction_pending(memory.id)
            return RememberResult(memory=memory, extraction_pending=True)
        return RememberResult(
            memory=memory,
            entities=derived.entities,
            relations=derived.relations,
            special_dates=derived.special_dates,
        )

    def recall(self, query: str, limit: int = 5) -> list[RecalledMemory]:
        """Hybrid retrieval: the top vector hits seed a graph-neighborhood
        expansion, so memories connected only relationally still surface."""
        [query_embedding] = self._embedder.embed([query])
        hits = self._store.search(query_embedding)
        support = self._graph_support(hits[:limit])
        today = self._clock().date()
        recalled = [
            RecalledMemory(
                memory=hit.memory,
                score=self._score(hit, support.get(hit.memory.id, 0.0), today),
            )
            for hit in hits
        ]
        recalled.sort(key=lambda r: r.score, reverse=True)
        return recalled[:limit]

    def profile(self, name: str) -> Profile | None:
        """Everything known about the entity ``name`` refers to, by any alias:
        the merged identity, its relations with the memories asserting each,
        and every memory mentioning it. None when the name is unknown."""
        entity = self._store.find_entity(name)
        if entity is None:
            return None
        return Profile(
            entity=entity,
            relations=self._store.relations_about(entity.id),
            memories=self._store.memories_mentioning(entity.id),
        )

    def _graph_support(self, seeds: list[SearchHit]) -> dict[int, float]:
        """How strongly the graph ties each memory to the query: the best
        similarity among seed hits whose entity neighborhood the memory
        mentions. A memory never supports itself — support means corroboration
        by a different, query-relevant memory."""
        graph = self._store.load_graph()
        support: dict[int, float] = {}
        for seed in seeds:
            if seed.similarity <= 0.0:
                continue
            for memory_id in graph.connected_memories(seed.memory.id):
                support[memory_id] = max(support.get(memory_id, 0.0), seed.similarity)
        return support

    def _score(self, hit: SearchHit, support: float, today: date) -> float:
        """Similarity with a graph-support bonus and a small recency bonus:
        relationally connected memories surface, newer facts outrank equally
        relevant older ones, and neither overrides a clear relevance gap."""
        age_days = max((today - hit.memory.happened_on).days, 0)
        recency = 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)
        return hit.similarity + _GRAPH_WEIGHT * support + _RECENCY_WEIGHT * recency
