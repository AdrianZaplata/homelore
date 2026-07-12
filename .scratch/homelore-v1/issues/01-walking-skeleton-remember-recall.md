# 01 — Walking skeleton: `remember` → `recall` via local vector search

**What to build:** A user adds Homelore to their MCP client, tells it something worth keeping, and gets it back later by asking — the thinnest complete path through the whole system, keyless. This ticket also lays down the project scaffold and engineering baseline the rest of v1 builds on.

From the user's perspective: `remember` appends a Memory (text, timestamp, author, optional event-date override) to the single-SQLite-file store; `recall` returns the most relevant memories by local vector similarity, each with provenance (text, date, author). No extraction, no graph — pure vector retrieval.

Includes: uv-managed package (`homelore`), ruff + pyright strict + pytest, the keyless CI workflow (lint, typecheck, unit tests on every push/PR), the `Embedder` interface with a local ONNX implementation and a deterministic test fake, injected clock, and the MCP stdio server + `serve` CLI entry point as thin adapters over the application service. Tests exercise the service seam only (fake embedder, real temp SQLite).

**Blocked by:** None — can start immediately.

**Status:** done

- [x] `remember` persists a Memory with timestamp, author, and optional event date; `recall` returns relevant memories with provenance, ranked by similarity with recency awareness
- [x] Both tools are exposed over MCP stdio and registered with sane schemas (smoke test)
- [x] Embeddings are computed locally; the whole flow works with no API key set
- [x] All data lives in one SQLite file at a configurable path with a sensible per-user default
- [x] Service-seam tests pass with fake embedder + injected clock + real temp SQLite; no storage mocking, no assertions on internals
- [x] Keyless CI workflow runs lint, typecheck, and tests green
