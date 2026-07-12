from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Memory:
    """The canonical unit of stored knowledge: a free-text note with provenance.

    ``event_date`` anchors the memory to when it happened, when that differs
    from when it was recorded (``created_at``).
    """

    id: int
    text: str
    author: str
    created_at: datetime
    event_date: date | None = None

    @property
    def happened_on(self) -> date:
        return self.event_date if self.event_date is not None else self.created_at.date()


@dataclass(frozen=True)
class RecalledMemory:
    memory: Memory
    score: float
