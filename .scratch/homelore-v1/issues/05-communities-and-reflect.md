# 05 — Communities + `reflect` tool

**What to build:** A user asks a question no single memory can answer — "how has our year been?", "what themes keep coming up with the kids?" — and gets a grounded synthesis. This is GraphRAG-global: Communities are detected automatically over the Graph Index, each gets an LLM-written Community Summary from its memories, and the `reflect` MCP tool answers global questions from those summaries.

Freshness is lazy with change-scoped invalidation: every write marks the community layer dirty; the next `reflect` call re-clusters and re-summarizes only the communities whose membership changed before answering. Local queries never pay this cost, and there are no background workers. Summary refresh needs the API key; `reflect` over already-built summaries does not.

**Blocked by:** 03 — Graph-expanded `recall` + `profile`.

**Status:** done

- [x] Communities are detected automatically from the Graph Index; no hand-defined clusters
- [x] Community Summaries are generated from the community's memories and grounded in them (no invented facts)
- [x] Writes mark the layer dirty; the next `reflect` refreshes only changed communities, then answers; unchanged summaries are not regenerated
- [x] `reflect` is exposed over MCP with a description that routes global/synthesis questions to it and specific questions away from it
- [x] Service-seam tests cover clustering, dirty-marking, change-scoped refresh, and summary reuse with the fake extractor/summarizer
