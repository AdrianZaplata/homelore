# 09 — Productization: README, PyPI release automation, Dependabot

**What to build:** Homelore becomes an installable product a stranger can adopt in minutes. `uvx homelore` works from PyPI; the README sells and explains the product on its own terms.

README contents: what Homelore is and who it's for; quickstart (install, one API key, add to an MCP client); the five tools with example conversations; the design framings agreed in the spec — memories as source of truth with derived, rebuildable indexes (link ADR 0001), right-sized storage (one SQLite file, in-memory graph traversal), deterministic answers where correctness is non-negotiable and retrieval where recall matters, privacy posture (local embeddings, one provider, self-hosted); the Demo Family walkthrough; and a roadmap (family server mode, forget/editing, local extraction). Product voice throughout — the repo presents as a product, nothing else.

Release engineering: MIT license, PyPI trusted publishing triggered by version tags, a changelog, and Dependabot for dependency updates.

**Blocked by:** 08 — Eval harness + CI.

**Status:** done

- [x] Fresh-machine test: following only the README, a new user goes from nothing to a working Homelore in an MCP client (verified against the built wheel: `uvx --from dist/homelore-*.whl homelore` runs from a clean directory; the full PyPI path lights up with the first published release)
- [x] README covers quickstart, tools with examples, design framings with ADR link, privacy posture, demo walkthrough, and roadmap — in product voice
- [x] Tagged release publishes to PyPI via trusted publishing; `uvx homelore` runs the published package — v0.1.0 tag published via the Release workflow; verified `uvx --no-cache homelore --help` pulls and runs the PyPI package from a clean directory
- [x] MIT license and changelog present; Dependabot configured
