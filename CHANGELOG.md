# Changelog

All notable changes to Homelore are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Homelore adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A `.env` file in the working directory now configures the server
  (`ANTHROPIC_API_KEY`, `HOMELORE_DB_PATH`), so the key can live in a
  git-ignored file next to the database instead of inline in MCP client
  config. Variables already set in the environment take precedence.

## [0.2.0] - 2026-07-16

### Changed

- The database now defaults to `homelore.db` in the current working
  directory instead of the platformdirs user data directory, so an MCP
  client launched inside a project keeps that project's memories next to
  it. `--db-path` and `$HOMELORE_DB_PATH` still take precedence.

  **Migration note:** an existing database in the old location (e.g.
  `%LOCALAPPDATA%\homelore\homelore\homelore.db` on Windows,
  `~/.local/share/homelore/homelore.db` on Linux) is not picked up
  automatically — copy it into your project folder, or set
  `HOMELORE_DB_PATH` to keep using it. Clients that launch servers from a
  system directory (e.g. Claude Desktop) should set `HOMELORE_DB_PATH` or
  `--db-path` explicitly.

### Removed

- The `platformdirs` dependency, no longer needed.

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

[Unreleased]: https://github.com/AdrianZaplata/homelore/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/AdrianZaplata/homelore/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/AdrianZaplata/homelore/releases/tag/v0.1.0
