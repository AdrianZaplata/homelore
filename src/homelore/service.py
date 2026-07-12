import logging
from datetime import date

from homelore.domain import Memory, RecalledMemory, RememberResult
from homelore.ports import Clock, Embedder, Extractor
from homelore.store import MemoryStore

_RECENCY_WEIGHT = 0.1
_RECENCY_HALF_LIFE_DAYS = 365.0

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
