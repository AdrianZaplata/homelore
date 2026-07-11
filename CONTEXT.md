# Context

Glossary of domain terms. Implementation details do not belong here.

## Terms

### Memory
The canonical unit of stored knowledge: a free-text note with a timestamp and an author. Memories are the source of truth — everything else in the system can be rebuilt from them. A memory is never destructively rewritten by the system; newer memories supersede older ones at retrieval time.

### Entity
A person, place, thing, or concept mentioned in memories (e.g. a family member, a hobby, a location). Entities are *extracted* from memories by the system, never hand-modeled. An entity's identity spans aliases ("Ana", "my wife" → the same entity).

### Relation
A labeled connection between two entities, extracted from memories (e.g. Ana —interested_in→ pottery). Relation labels are open strings, not a fixed ontology.

### Graph Index
The set of extracted entities and relations. It is a *derived, disposable index* over memories: it can be dropped and rebuilt from the memories at any time, and losing it loses no data.

### SpecialDate
A structured, recurring date tied to an entity (birthday, anniversary, school event). Extracted from memories into a deterministic index — date questions are answered by exact query, never by retrieval. Like the graph, it is derived and rebuildable.

### Community
A cluster of closely connected entities in the graph (e.g. everything around one child: their school, friends, hobbies). Communities are detected automatically, not hand-defined.

### Community Summary
An LLM-written synthesis of one community's memories. Community summaries answer *global* questions ("how has our year been?") that no single memory can. They are refreshed lazily when the graph beneath them has changed.

### Demo Family
The fictional family whose memories ship with the public repository as seed data. Serves as the runnable demo and the test fixtures. No real family data ever appears in the repository.
