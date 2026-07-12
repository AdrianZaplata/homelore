"""Test doubles for the service seam: fake embedder and fixed clock.

Tests construct the real service with a real temp-file SQLite store; only the
system boundaries (embedding model, wall clock) are faked.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

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


class FixedClock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def make_service(
    tmp_path: Path, vectors: dict[str, list[float]]
) -> tuple[HomeloreService, FixedClock]:
    clock = FixedClock()
    store = MemoryStore.open(tmp_path / "homelore.db")
    return HomeloreService(store=store, embedder=FakeEmbedder(vectors), clock=clock), clock
