"""The eval harness: the golden set scored against a real Demo Family build.

One command — ``python -m homelore.evals`` — builds a fresh demo instance with
the real adapters (Anthropic extractor, local embedder), runs every golden
pair through the application service seam, and prints a per-tool scorecard
with each failing question listed. Prompt and ranking changes are measured
here instead of guessed. The exit status is gated on per-tool quality floors
(FLOORS): red means a tool regressed below its measured frontier, not that a
known-hard question is still hard.

Metrics, per the golden pair's tool:

- ``recall`` — recall@k: the fraction of expected memories among the top hits.
- ``profile`` — pass/fail: the name resolves to the same entity as the
  expected name (identity, not canonical-name string), the profile connects
  each expected relation's endpoints, and the expected memories are present.
  Relation labels are open strings (CONTEXT.md), so an expected relation's
  label documents intent while scoring checks the connection, endpoints
  resolved through the same alias machinery users go through.
- ``upcoming_dates`` — exactness: every expected occurrence, nothing else, in
  order. No partial credit.
- ``reflect`` — LLM-judged faithfulness: is the synthesis grounded in the
  underlying memories?
"""

import json
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any, Protocol

import anthropic

from homelore.demo import (
    GoldenPair,
    GoldenProfile,
    GoldenRecall,
    GoldenReflect,
    GoldenUpcomingDates,
    demo_golden,
    demo_memories,
)
from homelore.domain import CommunitySummary
from homelore.service import HomeloreService

K = 5
"""Recall questions score against the top K hits — the assistant's default."""

FLOORS = {
    "recall": 0.85,
    "profile": 0.80,
    "upcoming_dates": 0.83,
    "reflect": 0.87,
}
"""Each tool's quality floor: the measured frontier, moved up as it improves.

Every failing question is still listed — the scorecard is the signal — but
the run's exit status turns red only when a tool's mean score falls below its
floor. Red means regression; the known-hard questions above the floor are the
frontier the golden set exists to keep in view."""


class AdjustableClock:
    """The harness's clock: date questions are asked as of their pair's fixed
    day, everything else as of the instant the harness was started with."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@dataclass(frozen=True)
class Verdict:
    """A faithfulness judgement: unfaithful verdicts say why."""

    faithful: bool
    reason: str


class FaithfulnessJudge(Protocol):
    """Judges whether the reflect material answers a question faithfully.

    ``memories`` is the full fixture corpus the summaries synthesize;
    ``must_draw_on`` are the memories a faithful answer draws on.
    """

    def judge(
        self,
        question: str,
        summaries: Sequence[CommunitySummary],
        memories: Sequence[str],
        must_draw_on: Sequence[str],
    ) -> Verdict: ...


@dataclass(frozen=True)
class QuestionScore:
    """One golden pair's outcome: 1.0 is a clean pass; anything less carries
    the reason in ``detail``. Only recall gives partial credit."""

    tool: str
    question: str
    score: float
    detail: str = ""


@dataclass(frozen=True)
class Scorecard:
    scores: tuple[QuestionScore, ...]

    def failures(self) -> tuple[QuestionScore, ...]:
        return tuple(score for score in self.scores if score.score < 1.0)

    def tools(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(score.tool for score in self.scores))

    def mean(self, tool: str) -> float:
        scores = [score.score for score in self.scores if score.tool == tool]
        return sum(scores) / len(scores)

    def breached_floors(self) -> tuple[str, ...]:
        """Tools whose mean fell below their FLOORS entry — the red-run
        criterion. A tool without a floor must be perfect."""
        return tuple(tool for tool in self.tools() if self.mean(tool) < FLOORS.get(tool, 1.0))


def run_evals(
    service: HomeloreService,
    clock: AdjustableClock,
    judge: FaithfulnessJudge,
    pairs: Sequence[GoldenPair],
    sources: Sequence[str],
    k: int = K,
) -> Scorecard:
    """Run every golden pair through the service seam and score it.

    ``sources`` is the fixture memories' text — the ground the judge checks
    reflect answers against. A grounding substring that matches no source is
    a golden-set bug and raises rather than silently judging on nothing.
    """
    asked_at = clock.now
    scores: list[QuestionScore] = []
    for pair in pairs:
        clock.now = asked_at
        scores.append(_score(service, clock, judge, pair, sources, k))
    clock.now = asked_at
    return Scorecard(scores=tuple(scores))


def _score(
    service: HomeloreService,
    clock: AdjustableClock,
    judge: FaithfulnessJudge,
    pair: GoldenPair,
    sources: Sequence[str],
    k: int,
) -> QuestionScore:
    if isinstance(pair, GoldenRecall):
        return _score_recall(service, pair, k)
    if isinstance(pair, GoldenProfile):
        return _score_profile(service, pair)
    if isinstance(pair, GoldenUpcomingDates):
        return _score_upcoming_dates(service, clock, pair)
    return _score_reflect(service, judge, pair, sources)


def _score_recall(service: HomeloreService, pair: GoldenRecall, k: int) -> QuestionScore:
    texts = [hit.memory.text for hit in service.recall(pair.question, limit=k)]
    missing = [
        expected for expected in pair.expect_memories if not any(expected in text for text in texts)
    ]
    return QuestionScore(
        tool="recall",
        question=pair.question,
        score=1.0 - len(missing) / len(pair.expect_memories),
        detail=f"missing from the top {k}: {', '.join(repr(m) for m in missing)}"
        if missing
        else "",
    )


def _score_profile(service: HomeloreService, pair: GoldenProfile) -> QuestionScore:
    def fail(detail: str) -> QuestionScore:
        return QuestionScore(tool="profile", question=pair.question, score=0.0, detail=detail)

    def canonical(name: str) -> str:
        resolved = service.profile(name)
        return name if resolved is None else resolved.entity.name

    profile = service.profile(pair.name)
    if profile is None:
        return fail(f"{pair.name!r} resolves to no entity")
    if profile.entity.name != canonical(pair.expect_entity):
        return fail(
            f"{pair.name!r} resolved to {profile.entity.name!r}, not {pair.expect_entity!r}"
        )
    connected = {
        frozenset((supported.relation.subject, supported.relation.object))
        for supported in profile.relations
    }
    if missing := [
        relation
        for relation in pair.expect_relations
        if frozenset((canonical(relation.subject), canonical(relation.object))) not in connected
    ]:
        return fail(
            "no relation connects " + "; ".join(f"{r.subject!r} and {r.object!r}" for r in missing)
        )
    memory_texts = [memory.text for memory in profile.memories]
    if missing_memories := [
        expected
        for expected in pair.expect_memories
        if not any(expected in text for text in memory_texts)
    ]:
        return fail(f"missing memories: {', '.join(repr(m) for m in missing_memories)}")
    return QuestionScore(tool="profile", question=pair.question, score=1.0)


def _score_upcoming_dates(
    service: HomeloreService, clock: AdjustableClock, pair: GoldenUpcomingDates
) -> QuestionScore:
    clock.now = datetime.combine(pair.as_of, time(10, 0), tzinfo=UTC)
    actual = tuple(service.upcoming_dates(days=pair.days))
    if actual == pair.expect:
        return QuestionScore(tool="upcoming_dates", question=pair.question, score=1.0)
    return QuestionScore(
        tool="upcoming_dates",
        question=pair.question,
        score=0.0,
        detail=f"expected {pair.expect}, got {actual}",
    )


def _score_reflect(
    service: HomeloreService,
    judge: FaithfulnessJudge,
    pair: GoldenReflect,
    sources: Sequence[str],
) -> QuestionScore:
    must_draw_on = [_resolve_grounding(expected, sources) for expected in pair.expect_grounded_in]
    verdict = judge.judge(pair.question, service.reflect(), sources, must_draw_on)
    return QuestionScore(
        tool="reflect",
        question=pair.question,
        score=1.0 if verdict.faithful else 0.0,
        detail="" if verdict.faithful else verdict.reason,
    )


def _resolve_grounding(expected: str, sources: Sequence[str]) -> str:
    for text in sources:
        if expected in text:
            return text
    raise ValueError(f"grounding substring matches no fixture memory: {expected!r}")


_METRICS = {
    "recall": f"recall@{K}",
    "profile": "pass rate",
    "upcoming_dates": "exactness",
    "reflect": "faithfulness",
}


def format_scorecard(scorecard: Scorecard) -> str:
    """The per-tool scorecard against its floor, every failing question
    listed with its reason, and the floor verdict the exit status follows."""
    lines: list[str] = []
    for tool in scorecard.tools():
        scores = [score for score in scorecard.scores if score.tool == tool]
        clean = sum(1 for score in scores if score.score == 1.0)
        lines.append(
            f"  {tool:<15} {_METRICS[tool]:<13} {clean}/{len(scores)} clean"
            f"   mean {scorecard.mean(tool):.2f} (floor {FLOORS.get(tool, 1.0):.2f})"
        )
    if failures := scorecard.failures():
        lines += ["", f"{len(failures)} failures:"]
        for failure in failures:
            lines += [f"  {failure.tool}: {failure.question}", f"    {failure.detail}"]
    else:
        lines += ["", f"All {len(scorecard.scores)} questions clean."]
    if breached := scorecard.breached_floors():
        lines += [
            "",
            "Below the floor: "
            + ", ".join(
                f"{tool} ({scorecard.mean(tool):.2f} < {FLOORS.get(tool, 1.0):.2f})"
                for tool in breached
            ),
        ]
    else:
        lines += ["", "Every tool at or above its floor."]
    return "\n".join(lines)


_JUDGE_MODEL = "claude-opus-4-8"

_JUDGE_SYSTEM = """\
You judge the faithfulness of Homelore's reflect material: community summaries \
synthesized from a family's memories, offered as the basis for answering one \
global question.

The material is faithful when both hold:
- Grounded: every claim in the summaries relevant to the question is supported \
by the memories provided. Nothing relevant is invented, exaggerated, or misdated.
- Sufficient: the summaries carry the information a good answer to the question \
needs, drawing on the must-draw-on memories in particular.

Judge only what bears on the question — an unrelated omission elsewhere in the \
summaries is not a failure. When unfaithful, say concretely which claim fails \
and why.
"""

_JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "faithful": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["faithful", "reason"],
    "additionalProperties": False,
}


class ClaudeJudge:
    """Faithfulness judging against Claude Opus 4.8, thinking before the
    verdict, with schema-constrained JSON output.

    Errors propagate: a judge that cannot run should fail the eval loudly,
    never pass it silently.
    """

    def __init__(self) -> None:
        self._client = anthropic.Anthropic()

    def judge(
        self,
        question: str,
        summaries: Sequence[CommunitySummary],
        memories: Sequence[str],
        must_draw_on: Sequence[str],
    ) -> Verdict:
        response = self._client.messages.create(
            model=_JUDGE_MODEL,
            max_tokens=8192,
            system=_JUDGE_SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": _JUDGE_SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": _judge_prompt(question, summaries, memories, must_draw_on),
                }
            ],
        )
        raw = next(block.text for block in response.content if block.type == "text")
        data = json.loads(raw)
        return Verdict(faithful=data["faithful"], reason=data["reason"])


def _judge_prompt(
    question: str,
    summaries: Sequence[CommunitySummary],
    memories: Sequence[str],
    must_draw_on: Sequence[str],
) -> str:
    summarized = "\n".join(
        f"- [{', '.join(summary.entities)}] {summary.summary}" for summary in summaries
    )
    return (
        f"Question:\n{question}\n\n"
        f"Community summaries (the material for the answer):\n{summarized}\n\n"
        "Memories (the ground truth):\n"
        + "\n".join(f"- {text}" for text in memories)
        + "\n\nA faithful answer must draw on these memories in particular:\n"
        + "\n".join(f"- {text}" for text in must_draw_on)
    )


_REFERENCE_NOW = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)
"""When non-date questions are asked, matching the unit suite's clock — the
fixtures' recent past stays recent, so recency scoring is reproducible."""


def main() -> None:
    """Build a fresh Demo Family instance with the real adapters, run every
    golden pair, print the scorecard. Exits nonzero only when a tool falls
    below its quality floor (FLOORS) — red means regression, while the
    known-hard questions above the floor stay listed as the frontier. Never
    gates a PR (the eval workflow does not run on pull requests)."""
    # The real-adapter imports stay inside main(): the unit suite imports
    # this module keyless, and homelore.embedding pulls in the fastembed
    # runtime at import time.
    from homelore.config import api_key_present
    from homelore.embedding import LocalEmbedder
    from homelore.extraction import ClaudeExtractor
    from homelore.service import MISSING_KEY_MESSAGE
    from homelore.store import MemoryStore
    from homelore.summarization import ClaudeSummarizer

    if not api_key_present():
        raise SystemExit(MISSING_KEY_MESSAGE)

    drafts = demo_memories()
    with tempfile.TemporaryDirectory() as tmp:
        clock = AdjustableClock(_REFERENCE_NOW)
        service = HomeloreService(
            store=MemoryStore.open(Path(tmp) / "homelore-eval.db"),
            embedder=LocalEmbedder(),
            extractor=ClaudeExtractor(),
            summarizer=ClaudeSummarizer(),
            clock=clock,
        )
        print(f"Building the demo instance: importing {len(drafts)} memories...")
        result = service.import_memories(drafts)
        if result.extraction_pending:
            print(f"{result.extraction_pending} extractions failed; retrying once...")
            healed = service.reindex()
            if healed.failed:
                print(
                    f"{healed.failed} extractions still failing —"
                    " their questions will score against an incomplete build."
                )
        print(f"Running {len(demo_golden())} golden pairs...\n")
        scorecard = run_evals(
            service, clock, ClaudeJudge(), demo_golden(), [draft.text for draft in drafts]
        )
    print(format_scorecard(scorecard))
    if scorecard.breached_floors():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
