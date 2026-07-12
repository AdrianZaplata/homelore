from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol

Clock = Callable[[], datetime]
"""Returns the current time as an aware UTC datetime."""


class Embedder(Protocol):
    """Turns texts into vectors for similarity search.

    Implementations must be local-only: neither memory texts nor queries may
    leave the machine.
    """

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
