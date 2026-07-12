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
class RememberResult:
    """The saved memory plus everything derived from it, so a caller sees what
    the system understood. ``extraction_pending`` means extraction failed, the
    memory is safe, and derivation will be retried."""

    memory: Memory
    entities: tuple[Entity, ...] = ()
    relations: tuple[Relation, ...] = ()
    special_dates: tuple[SpecialDate, ...] = ()
    extraction_pending: bool = False
