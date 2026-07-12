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


@dataclass(frozen=True)
class Entity:
    """A person, place, thing, or concept extracted from memories.

    Identity spans aliases: "Ana" and "my wife" are one entity. ``name`` is the
    canonical name; it is never hand-modeled.
    """

    id: int
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Relation:
    """A labeled connection between two entities, by canonical name.

    Labels are open strings, not a fixed ontology.
    """

    subject: str
    label: str
    object: str


@dataclass(frozen=True)
class SpecialDate:
    """A recurring date tied to an entity (birthday, anniversary, school event).

    ``year`` is the year of the first occurrence when known (e.g. birth year),
    enabling age computation.
    """

    entity: str
    label: str
    month: int
    day: int
    year: int | None = None


@dataclass(frozen=True)
class UpcomingDate:
    """One occurrence of a SpecialDate falling in a queried window.

    ``years`` is the age turned or the anniversary number, when the
    first-occurrence year is known.
    """

    entity: str
    label: str
    occurs_on: date
    years: int | None = None


@dataclass(frozen=True)
class SupportedRelation:
    """A relation together with the memories asserting it — the provenance a
    reader needs to judge how fresh and trustworthy the claim is."""

    relation: Relation
    memories: tuple[Memory, ...]


@dataclass(frozen=True)
class Profile:
    """Everything known about one entity: its alias-merged identity, its
    relations each with supporting memories, and every memory mentioning it
    (newest happening first)."""

    entity: Entity
    relations: tuple[SupportedRelation, ...]
    memories: tuple[Memory, ...]


@dataclass(frozen=True)
class CommunitySummary:
    """One community's LLM-written synthesis, with the entities it covers.

    Grounded in the community's memories, it answers global questions
    ("how has our year been?") that no single memory can."""

    entities: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class ExtractedEntity:
    """An entity as the extractor saw it: ``name`` should be the canonical name
    of an existing entity when the mention refers to one already known."""

    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtractedRelation:
    subject: str
    label: str
    object: str


@dataclass(frozen=True)
class ExtractedSpecialDate:
    entity: str
    label: str
    month: int
    day: int
    year: int | None = None


@dataclass(frozen=True)
class Extraction:
    """What one memory yielded: the extractor's raw view, before the store
    resolves names against entities it already knows."""

    entities: tuple[ExtractedEntity, ...] = ()
    relations: tuple[ExtractedRelation, ...] = ()
    special_dates: tuple[ExtractedSpecialDate, ...] = ()


@dataclass(frozen=True)
class MemoryDraft:
    """A memory not yet stored: what bulk import reads from a memories file.

    ``created_at`` is when the note was originally written, when known;
    a draft without one is recorded as of import time.
    """

    text: str
    author: str
    created_at: datetime | None = None
    event_date: date | None = None


@dataclass(frozen=True)
class ImportResult:
    """How a bulk import went: every draft counted in ``imported`` is safely
    stored; ``extraction_pending`` of them await an extraction retry."""

    imported: int
    extraction_pending: int


@dataclass(frozen=True)
class ReindexResult:
    """How a reindex went: ``reextracted`` memories re-derived their facts;
    ``failed`` ones stay flagged for retry, so re-running finishes the job."""

    reextracted: int
    failed: int


@dataclass(frozen=True)
class RememberResult:
    """The saved memory plus everything derived from it, so a caller sees what
    the system understood. ``extraction_pending`` means extraction failed, the
    memory is safe, and derivation will be retried."""

    memory: Memory
    entities: tuple[Entity, ...] = ()
    relations: tuple[Relation, ...] = ()
    special_dates: tuple[SpecialDate, ...] = ()
    extraction_pending: bool = False
