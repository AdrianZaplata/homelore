# 02 — Inline extraction on write

**What to build:** When a user tells Homelore something ("Ana mentioned she wants to learn pottery"), the system immediately understands *who and what* it's about: `remember` now runs extraction inline, deriving Entities (with alias resolution to existing entities — "Ana"/"my wife" are one person), Relations (open-string labels, no ontology), and SpecialDates, and persists them as derived, rebuildable indexes per ADR 0001.

Extraction runs against Claude Haiku 4.5 behind the `Extractor` interface, with a deterministic fake for tests. Resilience is part of the behavior: if extraction fails, the Memory is still saved and marked for retry, and the tool reports success with a note. With no API key set, `remember` fails with a clear message telling the user what to configure — while `recall` keeps working.

**Blocked by:** 01 — Walking skeleton.

**Status:** done

- [x] `remember` derives Entities, Relations, and SpecialDates inline; a fact recorded is immediately present in the derived indexes
- [x] Aliases resolve to existing Entities across memories; entity identity is never hand-modeled
- [x] Extraction failure still persists the Memory and marks it for retry; nothing is lost
- [x] Missing API key: `remember` errors with clear guidance; keyless read paths keep working
- [x] Service-seam tests cover all of the above with the fake Extractor; unit suite remains keyless
