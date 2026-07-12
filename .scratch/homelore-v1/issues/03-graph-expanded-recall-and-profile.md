# 03 — Graph-expanded `recall` + `profile` tool

**What to build:** Retrieval becomes GraphRAG-local. When a user asks a specific question, `recall` goes beyond vector similarity: vector hits → collect the Entities they mention → expand the graph neighborhood (Graph Index loaded into memory for traversal) → gather supporting memories for those entities → rank with recency-aware scoring so changing facts return their latest value (newest shoe size beats the old one). Results keep full provenance.

A new `profile` MCP tool answers "who is X?": given any alias, return the entity's alias-merged graph neighborhood (relations, connected entities) plus the memories supporting each claim — a person at a glance.

**Blocked by:** 02 — Inline extraction on write.

**Status:** done

- [x] `recall` retrieves relevant memories that pure vector search misses when the connection is relational (graph expansion demonstrably adds recall)
- [x] Superseded facts rank below their successors; the current value wins for "what is X's Y?" questions
- [x] `profile` accepts any alias and returns the merged entity with relations and supporting memories with provenance
- [x] `profile` is exposed over MCP with a description that routes "who is…" questions to it
- [x] Service-seam tests cover graph expansion, supersession, and alias-merged profiles with fake extractor/embedder
