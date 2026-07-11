# Spec: Homelore v1

Status: ready-for-agent

## Problem Statement

Families accumulate a huge amount of small, precious knowledge — shoe sizes, birthdays, who said what at the lake house, what a child wants to learn next — and it lives nowhere. It's scattered across chat threads, half-remembered conversations, and one partner's head. When you need it ("what size shoes does Mia wear *now*?", "what did Ana say she wanted for her birthday?"), you either can't find it or find a stale version. General-purpose assistants can't help because they know nothing about your family, and no one wants to hand their family's private life to a hosted memory startup.

## Solution

Homelore is a self-hosted family memory system that lives inside the assistant you already use. It runs as an MCP server over stdio: you tell your assistant things in passing ("remember that Mia moved up to size 32") and ask it things later, and Homelore supplies the memory. Memories are stored as an append-only log in a single SQLite file on your own machine; everything sent to a cloud model is limited to extraction calls against one API (Anthropic), and vector search runs on local embeddings, so retrieval works offline.

On top of the raw Memories, Homelore derives — and can always rebuild (see ADR 0001) — a Graph Index of Entities and Relations, a deterministic SpecialDate index, and Community Summaries, giving three retrieval modes: precise recall of specific memories, exact answers about recurring dates, and synthesized reflection across the whole family history.

## User Stories

1. As a family member, I want to tell my assistant something in passing and have it remembered, so that capturing family knowledge takes zero extra effort.
2. As a family member, I want each Memory stored with a timestamp and my name as author, so that we later know who recorded what and when.
3. As a family member, I want to record a memory about a past event with an explicit date ("last summer we…"), so that the memory is anchored to when it happened, not when I typed it.
4. As a family member, I want to ask specific questions ("what's Mia's shoe size?") and get the current answer, so that changing facts return their latest value rather than a stale one.
5. As a family member, I want retrieved answers to show the underlying memories with their dates and authors, so that I can judge how fresh and trustworthy the answer is.
6. As a family member, I want to refer to people by any of their names ("Ana", "my wife", "mama") and get the same person, so that I don't have to remember a canonical name.
7. As a family member, I want to ask "who is X?" and get everything known about them — their connections and the memories behind them, so that I can catch up on a person at a glance.
8. As a family member, I want to ask "what dates are coming up?" and get an exact, complete list of birthdays, anniversaries, and events in the window, so that I never miss one because a search happened to miss.
9. As a family member, I want recurring dates to include how old someone turns or how many years an anniversary marks, so that I don't do calendar math.
10. As a family member, I want to ask broad reflective questions ("how has our year been?", "what themes keep coming up with the kids?") and get a synthesized answer, so that the system is a family chronicle, not just a lookup table.
11. As a family member, I want reflective answers to be grounded in my actual memories rather than invented, so that I can trust the synthesis.
12. As a family member, I want a fact I just recorded to be immediately findable — including via graph and date queries — so that the system never feels behind.
13. As a family member, I want my memory saved even when the extraction step fails, so that a model outage never loses family history.
14. As a family member, I want gift-idea signals ("Ana mentioned she wants to learn pottery") retrievable months later, so that gift-giving gets easier over time.
15. As a self-hoster, I want all family data in a single SQLite file on my own machine, so that backup is copying one file and privacy is under my control.
16. As a self-hoster, I want vector search to run on local embeddings, so that queries work offline and my questions are never sent to a cloud service.
17. As a self-hoster, I want the system to need exactly one API key (Anthropic, for extraction), so that setup is minimal and my data is shared with at most one provider.
18. As a self-hoster, I want to install and run the server with standard Python tooling (a published package, runnable via uvx), so that adding it to my MCP client takes minutes.
19. As a self-hoster, I want a bulk-import CLI command, so that I can seed the system from existing notes without dictating them one by one.
20. As a self-hoster, I want a reindex CLI command that rebuilds every derived structure from my memories, so that improvements to extraction benefit my existing data and failed extractions are healed.
21. As a self-hoster, I want reindexing to be safe to interrupt and re-run, so that maintenance never endangers the memory log.
22. As a self-hoster, I want a clear error when the API key is missing for operations that need it, while read operations keep working, so that a config problem degrades gracefully.
23. As an evaluator of the product, I want a fictional Demo Family with fixtures I can build into a runnable instance, so that I can try the full experience without using real family data.
24. As a contributor, I want the extraction and embedding providers behind small interfaces, so that alternative backends (e.g. fully local extraction) can be added without touching the core.
25. As a contributor, I want a keyless, deterministic test suite, so that I can develop and validate changes without an API key or spending money.
26. As a maintainer, I want an eval harness with golden questions over the Demo Family, so that retrieval-quality regressions are caught when prompts or ranking change.
27. As a maintainer, I want the eval suite runnable both locally and in CI (secret-gated, non-blocking), so that quality is measured continuously without gating fork contributions.
28. As a maintainer, I want automated releases to PyPI and automated dependency updates, so that the product stays shippable with low overhead.

## Implementation Decisions

All domain vocabulary per `CONTEXT.md`; the derived-index architecture is governed by ADR 0001 (memories are the source of truth; graph, dates, and communities are rebuildable indexes).

- **Language & distribution**: Python; published to PyPI as `homelore` (MIT license); package/venv management with uv; runnable via `uvx homelore`.
- **Architecture layers**: a single application service exposing the product operations, beneath (a) an MCP stdio server (official Python SDK) and (b) a CLI. Both are thin adapters; no business logic in either.
- **MCP tool surface (5 tools)**: `remember` (append a Memory; optional event-date override), `recall` (hybrid local retrieval), `profile` (everything about one Entity), `upcoming_dates` (deterministic SpecialDate query), `reflect` (global questions answered from Community Summaries). Tool routing is delegated to the client model via careful tool descriptions; the server never classifies query intent.
- **Storage**: one SQLite file holding the memory log, vector index (sqlite-vec), Entity/Relation tables, SpecialDates, Communities and their summaries, and dirty-flags. The Graph Index is loaded into memory for traversal (family-scale data).
- **Extraction**: runs inline during `remember` using Claude Haiku 4.5 behind an `Extractor` interface; emits Entities (with aliases), Relations, and SpecialDates. On extraction failure the Memory is still persisted and marked for retry; `reindex` re-runs extraction for failed/all memories and rebuilds all derived indexes.
- **Entity resolution**: extraction resolves aliases to existing Entities (the same person across "Ana"/"my wife"); identity is never hand-modeled. Relation labels are open strings — no fixed ontology.
- **Embeddings**: local model behind an `Embedder` interface (fastembed-style ONNX, no GPU); query and memory embeddings never leave the machine.
- **Local retrieval (`recall`)**: vector search over memories → collect mentioned Entities → expand graph neighborhood → gather supporting memories → rank with recency-aware scoring so superseded facts lose to their successors. Results carry provenance (memory text, event date, author).
- **Global retrieval (`reflect`)**: answered from Community Summaries. Communities are detected automatically over the Graph Index; each summary is LLM-written from the community's memories.
- **Community freshness**: writes mark the community layer dirty; the next `reflect` call re-clusters and re-summarizes only communities whose membership changed, then answers. `reindex` rebuilds all. No background workers anywhere in v1.
- **SpecialDates**: deterministic index; `upcoming_dates` is an exact date-window query with recurrence expansion — never retrieval-based.
- **Concurrency posture**: single machine, stdio transport, but the storage layer never assumes a single writer (transactional writes, author on every memory) so a served multi-device mode remains a straightforward extension.
- **Demo Family**: fictional memories as human-readable fixtures plus ~50 golden question/answer pairs. No derived database is committed; a build command produces a runnable demo instance for key-holders and CI.
- **Config**: `ANTHROPIC_API_KEY` env var; database path configurable with a sensible per-user default. Missing key blocks `remember`/`reindex`/summary-refresh with a clear message; read paths that need no extraction keep working.

## Testing Decisions

- **One seam**: the application service. Tests construct it with a fake `Extractor` (canned entities/relations/dates), a fake `Embedder` (hand-chosen vectors so similarity order is controlled), an injected clock, and a real temp-file SQLite database. Tests call the public operations and assert only on returned results — never on table contents, internal calls, or intermediate state.
- **Real SQLite everywhere**: storage is never mocked; it is fast and it is the product.
- **Behaviors covered through the seam**: supersession by recency; alias-merged profiles; graph-expanded recall beating pure vector recall; date recurrence and window edge cases (year boundary, same-day, age computation); community dirty-marking and change-scoped refresh; memory-persisted-despite-extraction-failure; reindex idempotence; bulk import.
- **MCP layer**: one smoke test that all five tools register with sane schemas; no behavioral tests through the transport.
- **Eval harness reuses the same seam** with real adapters: golden Q/A over the Demo Family measuring recall@k for `recall`, exactness for `upcoming_dates`, and LLM-judged faithfulness for `reflect`. Runs locally by command and in CI on main via a secret-gated, non-blocking workflow.
- **Prior art**: none — greenfield repo; these tests establish the house style.

## Out of Scope

- Family server mode: Streamable HTTP transport, authentication, multi-device access (roadmap phase 2).
- `forget`, editing, or deletion semantics for memories.
- Proactive notifications (e.g. birthday reminders pushed to the user).
- Any web or chat UI.
- MCP resources/prompts (tools only in v1).
- Fully local extraction (Ollama et al.) — the `Extractor` interface is the extension point, but no implementation ships in v1.
- Photo/document ingestion; text memories only.
- Scaling beyond a single family's data volume.

## Further Notes

- The public repository presents Homelore strictly as a product; fixtures use only the fictional Demo Family and no real family data ever appears in the repo.
- README should carry the design framings agreed during planning: right-sized storage (single SQLite file, in-memory graph traversal), the graph as a disposable index (link ADR 0001), deterministic answers where correctness is non-negotiable (dates) and retrieval where recall matters, and the phase-2 roadmap (family server mode, forget/editing, local extraction).
- Engineering baseline: ruff (lint+format), pyright strict, pytest; CI workflow 1 (every push/PR, keyless): lint, typecheck, unit tests; CI workflow 2 (main + manual, secret-gated): eval suite. Release automation via PyPI trusted publishing on tags; Dependabot enabled.
- The golden eval set should deliberately encode the hard cases: changing facts (shoe sizes), alias resolution, multi-memory synthesis, and year-boundary date queries.
