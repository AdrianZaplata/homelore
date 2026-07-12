# 04 — `upcoming_dates` tool

**What to build:** A user asks "what family dates are coming up?" and gets an exact, complete answer — never a retrieval guess. The `upcoming_dates` MCP tool queries the deterministic SpecialDate index over a date window: recurring dates (birthdays, anniversaries) expand into their next occurrences, year boundaries are handled correctly, and each result includes what the occasion is, whose it is, when it falls, and the computed age or anniversary count.

The tool works keyless (it reads a derived index; no extraction involved) and uses the injected clock so "upcoming" is testable.

**Blocked by:** 02 — Inline extraction on write.

**Status:** done

- [x] `upcoming_dates` returns every SpecialDate in the requested window — exact query, no vector search anywhere in the path
- [x] Recurrence expands correctly across year boundaries (e.g. a January birthday queried in December)
- [x] Results include the person/entity, occasion label, date of next occurrence, and age/years count where applicable
- [x] Works with no API key set
- [x] Service-seam tests cover window edges, same-day occurrences, year-boundary recurrence, and age computation via the injected clock
