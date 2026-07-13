# Homelore

**Self-hosted family memory for the assistant you already use.**

[![PyPI](https://img.shields.io/pypi/v/homelore)](https://pypi.org/project/homelore/)
[![CI](https://github.com/AdrianZaplata/homelore/actions/workflows/ci.yml/badge.svg)](https://github.com/AdrianZaplata/homelore/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Families accumulate a huge amount of small, precious knowledge — shoe sizes,
birthdays, who said what at the lake house, what a child wants to learn next —
and it lives nowhere. When you need it ("what size shoes does Mia wear
*now*?"), you either can't find it or find a stale version. General-purpose
assistants can't help because they know nothing about your family, and no one
wants to hand their family's private life to a hosted memory startup.

Homelore fixes this without adding a single new app to your life. It runs as
an [MCP](https://modelcontextprotocol.io) server on your own machine: you tell
your assistant things in passing ("remember that Mia moved up to size 32") and
ask it things later, and Homelore supplies the memory. Everything lives in one
SQLite file you own.

## Quickstart

You need [uv](https://docs.astral.sh/uv/) and one API key
([Anthropic](https://console.anthropic.com/), used only to understand new
memories — see [Privacy](#privacy)). Homelore runs anywhere `uvx` runs; no
install step needed.

**Claude Code:**

```sh
claude mcp add homelore --scope user -- uvx homelore serve
```

**Claude Desktop** (or any MCP client that takes a JSON config) — add to
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "homelore": {
      "command": "uvx",
      "args": ["homelore", "serve"],
      "env": { "ANTHROPIC_API_KEY": "sk-ant-..." }
    }
  }
}
```

`ANTHROPIC_API_KEY` must reach the server: pass it in the client config as
above, or export it in the environment the client starts from. Then just talk
to your assistant:

> **You:** Remember that Mia moved up to shoe size 32.
> **Assistant:** Saved it.

That's the whole workflow. The first start downloads a small local embedding
model (one-time); after that, retrieval works offline.

Your memories live in a single SQLite file (in your user data directory by
default; set `HOMELORE_DB_PATH` or pass `--db-path` to move it). Backup is
copying one file.

## The five tools

Your assistant picks the right tool from your phrasing — you never name them.

**`remember`** — save anything worth keeping, told in passing. Each memory is
stored with a timestamp and your name, and a past event can carry the date it
happened rather than the date you typed it:

> **You:** Remember that last summer we scattered wildflower seeds along the
> back fence — that was around June 10th.
> **Assistant:** Saved, dated June 10, 2025.

**`recall`** — specific questions, answered from your memories with
provenance, so you can judge how fresh the answer is. Changing facts return
their latest value:

> **You:** What size shoes does Mia wear?
> **Assistant:** Size 32 — you recorded "Mia moved up to shoe size 32" on
> July 13, 2026. (That supersedes the size 31 note from January.)

**`profile`** — everything known about one person, place, or thing, reachable
by any name the family uses ("Ana", "my wife", "grandma" — same person):

> **You:** Who is Noor?
> **Assistant:** Noor is one of Freya's best friends. She has a serious nut
> allergy (Espen noted it in October 2025), her mom shared a nut-free
> brownie recipe, and she's already invited to the dinosaur dig birthday…

**`upcoming_dates`** — birthdays, anniversaries, and other special dates in a
window. This answer is computed from a deterministic index, never search: it
is exact and complete, with ages and anniversary years worked out for you:

> **You:** Any family dates in the next few weeks?
> **Assistant:** Two: your wedding anniversary — 14 years — on December
> 30th, and Freya turns 8 on January 2nd.

**`reflect`** — broad questions no single memory can answer, synthesized
across your whole history and grounded in the actual memories:

> **You:** What themes keep coming up with the kids this year?
> **Assistant:** Water, mostly — Otto's swim club took off, from first lap
> to a regionals medal. And Freya's fox phase turned into a general animal
> obsession once Waffle arrived…

## How it's built

**Memories are the source of truth.** Every memory is an append-only entry —
text, timestamp, author — that the system never rewrites; newer facts
supersede older ones at retrieval time, not by editing history. Everything
else — the entity/relation graph, the dates index, the community summaries —
is a *derived, disposable index*: it can be dropped and rebuilt from the
memories at any time, so an extraction bug can never corrupt family history,
and every improvement to extraction retroactively benefits your existing data
(`homelore reindex --full`). This is the load-bearing design decision; the
full reasoning is in [ADR 0001](docs/adr/0001-graph-as-derived-index.md).

**Right-sized storage.** A family's memory is precious, not big. Everything —
memory log, vector index, graph, dates, summaries — lives in one SQLite file,
and graph traversal happens in memory. No database server, no vector-store
service, nothing to operate.

**Deterministic where correctness is non-negotiable, retrieval where recall
matters.** Date questions are answered by exact query over a structured index
— a missed birthday because a search "happened to miss" is not acceptable.
Open-ended questions go through hybrid retrieval: vector search over memories,
expanded through the graph neighborhood, ranked with recency awareness so a
superseded fact loses to its successor.

**Graceful degradation.** If the extraction model is unreachable, your memory
is still saved and marked for retry — an outage never loses family history.
Without an API key, everything already stored keeps answering; only writing
new memories and rebuilding summaries need the key, and they say so clearly.

### Privacy

- **Self-hosted:** all family data is a single SQLite file on your machine.
  Nothing is synced anywhere.
- **Local embeddings:** vector search runs on a local ONNX model. Your
  questions are never sent to a cloud service, and retrieval works offline.
- **One provider, one direction:** exactly one API key (Anthropic), used to
  extract structure from new memories and to write summaries. That is the
  complete list of what leaves your machine.

## Try it with the Demo Family

The repository ships with the Demo Family — Maren, Espen, their kids Otto and
Freya, Farmor Ingrid, and Waffle the dog — 55 fictional memories spanning two
and a half years, so you can try the full experience without using real
family data.

```sh
export ANTHROPIC_API_KEY=sk-ant-...
uvx homelore demo                # builds ./homelore-demo.db from the fixtures
```

Point your MCP client at it (e.g. `claude mcp add homelore-demo -- uvx
homelore serve --db-path /path/to/homelore-demo.db`) and ask:

- *"What is Noor allergic to?"* — precise recall with provenance.
- *"Who is Ingrid?"* — a profile assembled across aliases ("Farmor").
- *"Whose birthdays are coming up?"* — exact dates, ages computed (Ingrid is
  a leap-day baby; Homelore gets that right).
- *"How did Otto's swimming year go?"* — synthesis across a dozen memories.

The demo builds into its own file, deliberately never your real database.

## The CLI

The same operations, without a chat in front of them:

```sh
homelore serve                # run the MCP server over stdio
homelore import memories.jsonl   # bulk-seed from existing notes (one JSON object per line)
homelore reindex              # retry failed extractions, heal the indexes
homelore reindex --full       # re-extract everything (after extraction improvements)
homelore demo                 # build the Demo Family instance
```

The import format is one JSON object per line: `text`, `author`, and optional
`created_at` / `event_date`. Imported memories go through the same write path
as ones told to the assistant. `reindex` only ever rebuilds derived indexes —
it never touches the memories themselves, and it's safe to interrupt and
re-run.

## Roadmap

- **Family server mode** — Streamable HTTP transport with authentication, so
  the whole family shares one memory from every device.
- **Forgetting and editing** — deliberate removal and correction semantics
  for a store that is otherwise append-only.
- **Local extraction** — the extractor is already behind a small interface;
  a fully local backend (e.g. Ollama) would make Homelore need zero API keys.

## Development

```sh
git clone https://github.com/AdrianZaplata/homelore && cd homelore
uv sync
uv run pytest          # keyless and deterministic — no API key, no model downloads
uv run ruff check . && uv run pyright
uv run python -m homelore.evals   # retrieval-quality scorecard (needs an API key)
```

The test suite runs against fake extraction/embedding adapters and a real
SQLite database. Retrieval quality is measured, not guessed: the eval harness
builds the Demo Family with real adapters and scores a 50-question golden set
per tool.

## License

[MIT](LICENSE).
