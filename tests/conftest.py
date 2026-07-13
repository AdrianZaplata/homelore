"""Test doubles for the service seam: fake embedder, fake extractor, fixed clock.

Tests construct the real service with a real temp-file SQLite store; only the
system boundaries (embedding model, extraction model, wall clock) are faked.
"""

import re
import zlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from homelore.domain import Entity, Extraction, Memory, Relation
from homelore.ports import Extractor
from homelore.service import HomeloreService
from homelore.store import MemoryStore

NOW = datetime(2026, 7, 12, 10, 0, 0, tzinfo=UTC)


class HashingEmbedder:
    """Deterministic lexical embeddings: each content word hashes to a bucket,
    so cosine similarity is word overlap. Makes retrieval over fixture-scale
    corpora work keyless — good enough for exact-memory recall, with no
    pretense of semantics. Function words are dropped: they would dominate
    short questions and drown out the words that identify a memory."""

    _DIMENSIONS = 4096
    # fmt: off
    _STOPWORDS = frozenset([
        "a", "an", "and", "are", "at", "be", "been", "did", "do", "does", "for", "from",
        "had", "has", "have", "he", "her", "his", "how", "i", "in", "is", "it", "its",
        "me", "my", "no", "not", "now", "of", "on", "or", "our", "out", "she", "so",
        "that", "the", "them", "they", "this", "to", "up", "us", "was", "we", "were",
        "what", "when", "where", "who", "why", "with", "you", "your",
    ])
    # fmt: on

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._DIMENSIONS
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            if token not in self._STOPWORDS:
                vector[zlib.crc32(token.encode()) % self._DIMENSIONS] += 1.0
        return vector


class FakeEmbedder:
    """Maps exact texts to hand-chosen vectors so similarity order is controlled.

    Unknown text is an error: every text a test embeds must be deliberate.
    """

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vectors[text] for text in texts]


class FakeExtractor:
    """Maps exact texts to canned extractions, standing in for the LLM.

    Unmapped text yields an empty extraction — a memory the extractor found
    nothing in — so tests that don't care about extraction stay quiet.
    """

    def __init__(self, extractions: dict[str, Extraction] | None = None) -> None:
        self._extractions = extractions or {}

    def extract(
        self,
        memory: Memory,
        known_entities: Sequence[Entity],
        known_relations: Sequence[Relation],
    ) -> Extraction:
        return self._extractions.get(memory.text, Extraction())


class FailingExtractor:
    """An extractor whose model call always fails, for resilience tests."""

    def extract(
        self,
        memory: Memory,
        known_entities: Sequence[Entity],
        known_relations: Sequence[Relation],
    ) -> Extraction:
        raise RuntimeError("extraction model unavailable")


class FakeSummarizer:
    """Writes deterministic summaries embedding the memory texts, numbering
    each one it writes — so reflect() results alone reveal whether a summary
    was reused (same number) or regenerated (new number)."""

    def __init__(self) -> None:
        self._written = 0

    def summarize(self, entities: Sequence[str], memories: Sequence[Memory]) -> str:
        self._written += 1
        return f"v{self._written}: " + " | ".join(memory.text for memory in memories)


class FixedClock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def make_service(
    tmp_path: Path,
    vectors: dict[str, list[float]],
    extractions: dict[str, Extraction] | None = None,
) -> tuple[HomeloreService, FixedClock]:
    return _build(tmp_path, vectors, FakeExtractor(extractions))


def make_failing_extraction_service(
    tmp_path: Path, vectors: dict[str, list[float]]
) -> tuple[HomeloreService, FixedClock]:
    return _build(tmp_path, vectors, FailingExtractor())


def make_keyless_service(
    tmp_path: Path, vectors: dict[str, list[float]]
) -> tuple[HomeloreService, FixedClock]:
    """A service configured as it is when ANTHROPIC_API_KEY is absent."""
    return _build(tmp_path, vectors, None)


def make_service_with_extractor(
    tmp_path: Path, vectors: dict[str, list[float]], extractor: Extractor
) -> tuple[HomeloreService, FixedClock]:
    """A service around a test-specific extractor (e.g. one that misbehaves)."""
    return _build(tmp_path, vectors, extractor)


def _build(
    tmp_path: Path,
    vectors: dict[str, list[float]],
    extractor: Extractor | None,
) -> tuple[HomeloreService, FixedClock]:
    clock = FixedClock()
    store = MemoryStore.open(tmp_path / "homelore.db")
    # The extractor and summarizer share one API key: both present or neither.
    service = HomeloreService(
        store=store,
        embedder=FakeEmbedder(vectors),
        extractor=extractor,
        summarizer=FakeSummarizer() if extractor is not None else None,
        clock=clock,
    )
    return service, clock
