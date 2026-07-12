"""Test doubles for the service seam: fake embedder, fake extractor, fixed clock.

Tests construct the real service with a real temp-file SQLite store; only the
system boundaries (embedding model, extraction model, wall clock) are faked.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from homelore.domain import Entity, Extraction, Memory
from homelore.service import HomeloreService
from homelore.store import MemoryStore

NOW = datetime(2026, 7, 12, 10, 0, 0, tzinfo=UTC)


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

    def extract(self, text: str, known_entities: Sequence[Entity]) -> Extraction:
        return self._extractions.get(text, Extraction())


class FailingExtractor:
    """An extractor whose model call always fails, for resilience tests."""

    def extract(self, text: str, known_entities: Sequence[Entity]) -> Extraction:
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


def _build(
    tmp_path: Path,
    vectors: dict[str, list[float]],
    extractor: FakeExtractor | FailingExtractor | None,
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
