from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol

from homelore.domain import Entity, Extraction, Memory

Clock = Callable[[], datetime]
"""Returns the current time as an aware UTC datetime."""


class Extractor(Protocol):
    """Derives entities, relations, and special dates from one memory text.

    ``known_entities`` lets the implementation resolve aliases to existing
    entities: an extracted entity naming a known entity (by canonical name or
    alias) is the same entity. May raise on failure; callers must treat a
    failure as retryable, never as data loss.
    """

    def extract(self, text: str, known_entities: Sequence[Entity]) -> Extraction: ...


class Summarizer(Protocol):
    """Writes one Community Summary from the community's memories.

    The summary must be grounded: it synthesizes what the memories say and
    invents nothing. May raise on failure; summaries are derived and
    rebuildable, so a failure never endangers data.
    """

    def summarize(self, entities: Sequence[str], memories: Sequence[Memory]) -> str: ...


class Embedder(Protocol):
    """Turns texts into vectors for similarity search.

    Implementations must be local-only: neither memory texts nor queries may
    leave the machine.
    """

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
