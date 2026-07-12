# 06 — Bulk import + `reindex` CLI

**What to build:** A self-hoster seeds Homelore from existing notes and maintains it over time. Two CLI commands:

- **Import**: read a file of memories (with dates and authors) and ingest them through the same write path as `remember`, in bulk.
- **Reindex**: re-run extraction and rebuild every derived structure (Graph Index, SpecialDates, community layer) from the memory log — the concrete guarantee behind ADR 0001. Supports healing mode (only memories whose extraction failed or is pending) and full-rebuild mode. Interrupt-safe and idempotent: re-running after an interruption converges to the same state, and the memory log is never modified.

**Blocked by:** 02 — Inline extraction on write.

**Status:** done

- [x] Import ingests a memories file in bulk through the standard write path; imported memories are retrievable like any other
- [x] Reindex rebuilds all derived indexes from memories alone: dropping every derived table then reindexing restores equivalent query results
- [x] Healing mode retries only failed/pending extractions; full mode re-extracts everything
- [x] Interrupting a reindex loses no memories; re-running completes the job (idempotent)
- [x] Service-seam tests cover import, full rebuild equivalence, healing, and idempotence with the fake extractor
