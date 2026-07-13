# Changelog

All notable changes to Homelore are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Homelore adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-07-13

The first release: a self-hosted family memory over MCP.

### Added

- MCP stdio server with five tools: `remember`, `recall`, `profile`,
  `upcoming_dates`, and `reflect`.
- Append-only memory log in a single SQLite file; every memory carries a
  timestamp, an author, and optionally the date the event happened.
- Inline extraction on write (Claude Haiku) into derived, rebuildable
  indexes: an entity/relation graph, a deterministic special-dates index,
  and lazily refreshed community summaries (ADR 0001).
- Hybrid local retrieval: vector search over local embeddings expanded
  through the graph, with recency-aware ranking so changing facts return
  their latest value.
- CLI: `homelore serve`, `homelore import` (bulk memories file),
  `homelore reindex [--full]`, and `homelore demo` (build the fictional
  Demo Family into a runnable instance).
- Graceful degradation: memories persist even when extraction fails, and
  read paths keep working without an API key.
- Demo Family fixtures with a 50-question golden set and an eval harness
  (`python -m homelore.evals`) scoring recall, profile resolution, date
  exactness, and reflect faithfulness.

[Unreleased]: https://github.com/AdrianZaplata/homelore/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AdrianZaplata/homelore/releases/tag/v0.1.0
