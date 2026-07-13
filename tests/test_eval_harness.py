"""The eval harness (ticket 08): the golden set scored through the service seam.

The scoring core runs keyless here against the fake-extracted fixture build —
the same instance the demo-family suite uses. The real harness (``python -m
homelore.evals``) wires this core to the real adapters and an LLM judge; only
the judge is faked here.
"""

from collections.abc import Sequence

import pytest

from conftest import NOW, FakeExtractor, FakeSummarizer, HashingEmbedder
from homelore.demo import (
    GoldenProfile,
    GoldenRecall,
    GoldenReflect,
    GoldenUpcomingDates,
    demo_extractions,
    demo_golden,
    demo_memories,
)
from homelore.domain import CommunitySummary
from homelore.evals import (
    AdjustableClock,
    QuestionScore,
    Scorecard,
    Verdict,
    format_scorecard,
    run_evals,
)
from homelore.service import HomeloreService
from homelore.store import MemoryStore

GOLDEN = demo_golden()
SOURCES = tuple(draft.text for draft in demo_memories())


class ApprovingJudge:
    """Judges every synthesis faithful, recording what it was asked to judge."""

    def __init__(self) -> None:
        self.questions: list[str] = []
        self.must_draw_on: list[tuple[str, ...]] = []

    def judge(
        self,
        question: str,
        summaries: Sequence[CommunitySummary],
        memories: Sequence[str],
        must_draw_on: Sequence[str],
    ) -> Verdict:
        self.questions.append(question)
        self.must_draw_on.append(tuple(must_draw_on))
        return Verdict(faithful=True, reason="")


class RefusingJudge:
    """Judges every synthesis unfaithful, with a reason the scorecard must keep."""

    def judge(
        self,
        question: str,
        summaries: Sequence[CommunitySummary],
        memories: Sequence[str],
        must_draw_on: Sequence[str],
    ) -> Verdict:
        return Verdict(faithful=False, reason="claims a prize the memories never mention")


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> tuple[HomeloreService, AdjustableClock]:
    """The fake-extracted Demo Family build, evaluated as of the suite's NOW."""
    clock = AdjustableClock(NOW)
    service = HomeloreService(
        store=MemoryStore.open(tmp_path_factory.mktemp("evals") / "homelore.db"),
        embedder=HashingEmbedder(),
        extractor=FakeExtractor(demo_extractions()),
        summarizer=FakeSummarizer(),
        clock=clock,
    )
    result = service.import_memories(demo_memories())
    assert result.extraction_pending == 0
    return service, clock


@pytest.fixture(scope="module")
def scorecard(demo: tuple[HomeloreService, AdjustableClock]) -> Scorecard:
    service, clock = demo
    return run_evals(service, clock, ApprovingJudge(), GOLDEN, SOURCES)


def test_every_golden_pair_gets_exactly_one_score(scorecard: Scorecard) -> None:
    assert [s.question for s in scorecard.scores] == [pair.question for pair in GOLDEN]


def test_date_questions_are_answered_exactly(scorecard: Scorecard) -> None:
    date_scores = [s for s in scorecard.scores if s.tool == "upcoming_dates"]
    assert len(date_scores) == sum(isinstance(p, GoldenUpcomingDates) for p in GOLDEN)
    assert all(s.score == 1.0 and s.detail == "" for s in date_scores)


def test_keyless_recall_and_profile_pairs_pass(scorecard: Scorecard) -> None:
    keyless = {
        pair.question
        for pair in GOLDEN
        if isinstance(pair, GoldenRecall | GoldenProfile) and pair.keyless
    }
    scores = [s for s in scorecard.scores if s.question in keyless]
    assert len(scores) == len(keyless)
    assert all(s.score == 1.0 for s in scores)


def test_reflect_pairs_are_judged_on_their_grounding_memories(
    demo: tuple[HomeloreService, AdjustableClock],
) -> None:
    service, clock = demo
    judge = ApprovingJudge()
    reflect_pairs = [pair for pair in GOLDEN if isinstance(pair, GoldenReflect)]

    card = run_evals(service, clock, judge, reflect_pairs, SOURCES)

    assert all(s.score == 1.0 for s in card.scores)
    assert judge.questions == [pair.question for pair in reflect_pairs]
    # The judge receives the full text of every memory the answer must draw
    # on, resolved from the golden pair's substrings.
    for pair, drawn in zip(reflect_pairs, judge.must_draw_on, strict=True):
        assert len(drawn) == len(pair.expect_grounded_in)
        for expected, text in zip(pair.expect_grounded_in, drawn, strict=True):
            assert expected in text
            assert text in SOURCES


def test_an_unfaithful_verdict_fails_the_question_with_the_judges_reason(
    demo: tuple[HomeloreService, AdjustableClock],
) -> None:
    service, clock = demo
    reflect_pairs = [pair for pair in GOLDEN if isinstance(pair, GoldenReflect)]

    card = run_evals(service, clock, RefusingJudge(), reflect_pairs, SOURCES)

    assert all(s.score == 0.0 for s in card.scores)
    assert all("never mention" in s.detail for s in card.scores)


def test_a_grounding_substring_matching_no_memory_is_a_golden_set_bug(
    demo: tuple[HomeloreService, AdjustableClock],
) -> None:
    service, clock = demo
    bogus = GoldenReflect(
        question="How was the moon landing?",
        expect_grounded_in=("no fixture memory says this",),
        keyless=False,
    )

    with pytest.raises(ValueError, match="no fixture memory says this"):
        run_evals(service, clock, ApprovingJudge(), [bogus], SOURCES)


def test_scorecard_reports_each_tool_and_lists_each_failing_question() -> None:
    card = Scorecard(
        scores=(
            QuestionScore("recall", "Where is the key?", 1.0),
            QuestionScore("recall", "Who feeds Waffle?", 0.5, "missing from the top 5: 'Otto'"),
            QuestionScore("upcoming_dates", "What is coming up?", 1.0),
            QuestionScore("reflect", "How was our year?", 0.0, "claims a prize never mentioned"),
        )
    )

    text = format_scorecard(card)

    assert "recall@5" in text and "1/2" in text
    assert "exactness" in text and "1/1" in text
    assert "faithfulness" in text and "0/1" in text
    assert "Who feeds Waffle?" in text and "missing from the top 5: 'Otto'" in text
    assert "How was our year?" in text and "claims a prize never mentioned" in text
    assert "Where is the key?" not in text.split("failures")[1]


def test_a_clean_scorecard_says_so_and_lists_nothing() -> None:
    card = Scorecard(scores=(QuestionScore("profile", "Who is Freya?", 1.0),))

    text = format_scorecard(card)

    assert "pass" in text and "1/1" in text
    assert "failures" not in text


def test_eval_main_without_a_key_explains_and_runs_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from homelore.evals import main as evals_main

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        evals_main()
