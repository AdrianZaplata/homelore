import calendar
import logging
from collections.abc import Sequence
from datetime import date, timedelta

from homelore.domain import (
    CommunitySummary,
    ImportResult,
    MemoryDraft,
    Profile,
    RecalledMemory,
    ReindexResult,
    RememberResult,
    SpecialDate,
    UpcomingDate,
)
from homelore.ports import Clock, Embedder, Extractor, Summarizer
from homelore.store import MemoryStore, SearchHit, SummarizedCommunity

_RECENCY_WEIGHT = 0.1
_RECENCY_HALF_LIFE_DAYS = 365.0
_GRAPH_WEIGHT = 0.2

_logger = logging.getLogger(__name__)


class MissingApiKeyError(Exception):
    """Raised when an operation needs the extraction model but no key is set."""


_HOW_TO_SET_KEY = (
    " Get a key at https://console.anthropic.com and set the ANTHROPIC_API_KEY"
    " environment variable, or put it in a .env file in the directory the"
    " server starts from. Recalling existing memories keeps working without it."
)

MISSING_KEY_MESSAGE = (
    "ANTHROPIC_API_KEY is not set. Homelore needs it to understand new memories"
    " (extracting people, relationships, and dates)." + _HOW_TO_SET_KEY
)

_MISSING_KEY_REFLECT_MESSAGE = (
    "ANTHROPIC_API_KEY is not set. New memories have arrived since the last"
    " reflection, and Homelore needs the key to bring its community summaries"
    " current before answering." + _HOW_TO_SET_KEY
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
        summarizer: Summarizer | None,
        clock: Clock,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._extractor = extractor
        self._summarizer = summarizer
        self._clock = clock

    def remember(self, text: str, author: str, event_date: date | None = None) -> RememberResult:
        """Append a memory and derive the graph and date indexes from it inline.

        Extraction failure never loses the memory: it is saved, flagged for
        retry, and the result says so. A missing API key is different — it is a
        config problem, so we fail before saving rather than silently pile up
        memories that need retrying.
        """
        extractor = self._require_extractor()
        [embedding] = self._embedder.embed([text])
        draft = MemoryDraft(text=text, author=author, event_date=event_date)
        return self._ingest(extractor, draft, embedding)

    def import_memories(self, drafts: Sequence[MemoryDraft]) -> ImportResult:
        """Seed from existing notes: ingest every draft through the same write
        path as remember, embeddings computed in one batch. Each memory keeps
        its draft's timestamp; extraction failures flag retries as usual."""
        extractor = self._require_extractor()
        embeddings = self._embedder.embed([draft.text for draft in drafts])
        pending = 0
        for draft, embedding in zip(drafts, embeddings, strict=True):
            pending += self._ingest(extractor, draft, embedding).extraction_pending
        return ImportResult(imported=len(drafts), extraction_pending=pending)

    def _ingest(
        self, extractor: Extractor, draft: MemoryDraft, embedding: list[float]
    ) -> RememberResult:
        memory = self._store.add(
            text=draft.text,
            author=draft.author,
            created_at=draft.created_at if draft.created_at is not None else self._clock(),
            event_date=draft.event_date,
            embedding=embedding,
        )
        try:
            extraction = extractor.extract(
                memory, self._store.list_entities(), self._store.list_relations()
            )
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

    def reindex(self, full: bool = False) -> ReindexResult:
        """Rebuild the derived indexes from the memory log (ADR 0001).

        Healing mode (the default) re-runs extraction for exactly the
        memories whose extraction failed or is pending. Full mode first drops
        every derived structure and flags all memories, so improved
        extraction reaches existing data. Either way each healed memory
        commits on its own: an interruption loses nothing, re-running picks
        up exactly the memories still flagged, and the log is never modified.
        """
        extractor = self._require_extractor()
        if full:
            self._store.reset_derived_indexes()
        reextracted = failed = 0
        for memory in self._store.pending_extractions():
            try:
                extraction = extractor.extract(
                    memory, self._store.list_entities(), self._store.list_relations()
                )
                self._store.save_extraction(memory.id, extraction)
                reextracted += 1
            except Exception:
                _logger.exception(
                    "extraction failed again for memory %d; still flagged for retry", memory.id
                )
                failed += 1
        if self._store.communities_dirty():
            self._refresh_communities()
        return ReindexResult(reextracted=reextracted, failed=failed)

    def _require_extractor(self) -> Extractor:
        if self._extractor is None:
            raise MissingApiKeyError(MISSING_KEY_MESSAGE)
        return self._extractor

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

    def upcoming_dates(self, days: int = 30) -> list[UpcomingDate]:
        """Every special-date occurrence from today through ``days`` days out,
        soonest first — an exact query over the derived date index, so the
        answer is complete, never a retrieval guess."""
        today = self._clock().date()
        end = today + timedelta(days=days)
        upcoming = [
            UpcomingDate(
                entity=special.entity,
                label=special.label,
                occurs_on=occurs_on,
                years=occurs_on.year - special.year if special.year is not None else None,
            )
            for special in self._store.list_special_dates()
            for occurs_on in _occurrences(special, today, end)
        ]
        upcoming.sort(key=lambda u: (u.occurs_on, u.entity, u.label))
        return upcoming

    def reflect(self) -> list[CommunitySummary]:
        """The material for answering global questions: one grounded summary
        per community, biggest slice of family life first.

        Freshness is lazy: writes mark the layer dirty, and a dirty layer is
        re-clustered and re-summarized here before answering — regenerating
        only communities whose membership changed. Serving already-built
        summaries needs no API key; only the refresh does."""
        if self._store.communities_dirty():
            self._refresh_communities()
        names = self._entity_names()
        saved = sorted(
            self._store.saved_communities(),
            key=lambda summarized: (
                -len(summarized.community.memory_ids),
                summarized.community.entity_ids,
            ),
        )
        return [
            CommunitySummary(
                entities=tuple(names[entity_id] for entity_id in summarized.community.entity_ids),
                summary=summarized.summary,
            )
            for summarized in saved
        ]

    def _refresh_communities(self) -> None:
        """Re-cluster the graph and bring every community's summary current,
        writing a new summary only for communities whose membership changed —
        an unchanged community keeps its existing summary verbatim.

        Clustering is local; only writing a summary needs the model, so the
        missing-key error is raised only when one must actually be written.
        The generation captured up front keeps the layer dirty if another
        write lands while the model calls run."""
        generation = self._store.community_write_generation()
        names = self._entity_names()
        existing = {
            summarized.community: summarized.summary
            for summarized in self._store.saved_communities()
        }
        refreshed: list[SummarizedCommunity] = []
        for community in self._store.load_graph().communities():
            summary = existing.get(community)
            if summary is None:
                if self._summarizer is None:
                    raise MissingApiKeyError(_MISSING_KEY_REFLECT_MESSAGE)
                summary = self._summarizer.summarize(
                    entities=[names[entity_id] for entity_id in community.entity_ids],
                    memories=self._store.memories_by_ids(community.memory_ids),
                )
            refreshed.append(SummarizedCommunity(community=community, summary=summary))
        self._store.replace_communities(tuple(refreshed), as_of_generation=generation)

    def _entity_names(self) -> dict[int, str]:
        return {entity.id: entity.name for entity in self._store.list_entities()}

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


def _occurrences(special: SpecialDate, start: date, end: date) -> list[date]:
    """The recurring date's occurrences within [start, end], in any year the
    window touches. A Feb 29 date falls on Feb 28 in non-leap years; any other
    impossible month/day is bad extracted data and raises."""
    occurrences: list[date] = []
    for year in range(start.year, end.year + 1):
        if (special.month, special.day) == (2, 29) and not calendar.isleap(year):
            occurs_on = date(year, 2, 28)
        else:
            occurs_on = date(year, special.month, special.day)
        if start <= occurs_on <= end:
            occurrences.append(occurs_on)
    return occurrences
