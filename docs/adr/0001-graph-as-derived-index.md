# 0001. The graph is a derived index, not the primary store

Date: 2026-07-11
Status: accepted

## Context

The system uses GraphRAG-style retrieval: an entity/relation graph augments vector
search over memories. There were two candidate architectures:

1. **Graph as primary store** — memories are decomposed into graph facts at write
   time; the original text is secondary.
2. **Graph as derived index** — raw memories (text + timestamp + author) are the
   canonical store; the graph is extracted from them and can be rebuilt at any
   time.

Extraction is performed by an LLM and will have bugs, and extraction quality will
improve over the project's lifetime. The data being stored is irreplaceable
personal family history.

## Decision

Memories are the source of truth. The entity/relation graph is a disposable,
rebuildable index derived from them. Dropping the graph loses no data; improving
the extraction pipeline means re-running it over the memory log.

## Consequences

- Extraction bugs can never corrupt or lose family data — worst case is a bad
  index, fixed by re-extraction.
- Entity resolution and relation labeling can be iterated on freely.
- Retrieval must be hybrid (vector search over memories + graph traversal),
  since the graph alone is not guaranteed complete.
- Extraction runs inline during the write: a stored fact is immediately
  reachable via graph and date indexes. If extraction fails, the memory is
  still saved and marked for retry; the `reindex` command re-runs extraction
  and heals or rebuilds the indexes.
