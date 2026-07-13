# 08 — Eval harness + secret-gated CI workflow

**What to build:** The maintainer runs one command and gets a scorecard of retrieval quality, so prompt and ranking changes are measured instead of guessed. The harness runs the golden Q/A set through the application service seam with the real adapters (Anthropic extractor, local embedder) against a freshly built Demo Family instance, and reports:

- recall@k for `recall` questions (were the expected memories retrieved?)
- exactness for `upcoming_dates` questions (exact match, no partial credit)
- LLM-judged faithfulness for `reflect` answers (is the synthesis grounded in the underlying memories?)

A second CI workflow runs the harness on pushes to main and on manual dispatch, using a repository-secret API key. It is non-blocking by design: regressions surface as visible workflow results to investigate, not as PR gates (fork PRs can't see secrets, and LLM-judged metrics are too noisy to gate on).

**Blocked by:** 07 — Demo Family fixtures + golden set.

**Status:** done

- [x] One command builds the demo instance, runs all golden pairs, and prints a per-tool scorecard with per-question failures listed
- [x] Metrics: recall@k, date exactness, and LLM-judge faithfulness are all reported
- [x] Eval CI workflow runs on main and manual dispatch, secret-gated, non-blocking for PRs
- [x] The keyless unit-test workflow remains unaffected and green
