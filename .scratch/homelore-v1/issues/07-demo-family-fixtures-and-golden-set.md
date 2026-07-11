# 07 — Demo Family fixtures + golden Q/A set + demo-db build

**What to build:** Anyone evaluating Homelore can experience it without real family data. This ticket creates the fictional Demo Family: a coherent, human-readable fixture set of memories spanning a believable family life over time, plus ~50 golden question/answer pairs, plus a build command that produces a runnable demo instance by feeding the fixtures through the import pipeline (requires an API key; nothing derived is committed to the repo).

The fixtures must deliberately encode the hard cases the system claims to handle: facts that change over time (supersession), the same person under multiple aliases, questions answerable only by synthesizing several memories, recurring dates near year boundaries, and enough graph structure to form meaningful Communities. The golden pairs cover all five tools.

**Blocked by:** 04 — `upcoming_dates`; 05 — Communities + `reflect`; 06 — Bulk import + `reindex`.

**Status:** ready-for-agent

- [ ] Demo Family fixtures are readable, coherent, wholly fictional, and span supersession, aliases, multi-memory synthesis, year-boundary dates, and clusterable structure
- [ ] ~50 golden Q/A pairs exist with expected answers/memories, covering `recall`, `profile`, `upcoming_dates`, and `reflect`
- [ ] One command builds a runnable demo database from the fixtures via the import pipeline
- [ ] No derived database or generated artifact is committed; the build is reproducible from fixtures
- [ ] A subset of golden pairs with deterministic answers (dates, exact-memory recall) runs keyless against a fake-extracted fixture build in the unit suite
