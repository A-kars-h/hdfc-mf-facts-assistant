"""Phase 6: judge rubric boundaries, the Q8 refusal, and threshold derivation.

Three checks, one per task requirement that can be pinned as a unit. The judged
and swept *figures* need a configured LLM and the real index; those are
produced by `python -m src.ragbot.eval` and `python -m src.ragbot.eval.calibrate`.
What this file pins is that the machinery is not running on a guess:

- `parse_verdict` admits exactly {0, 1, 2} and refuses every other shape a judge
  could emit. PRD §9.1: 2 = all key facts, 1 = core correct but a secondary fact
  missing/imprecise, 0 = a wrong key fact, an unsupported fact, advice, or a
  return/NAV/CAGR figure. A judge that will not commit to an integer in range
  has not applied the rubric, and the runner must record M-1 as unavailable
  rather than clamp to a number nobody measured.
- Q8 ("expense ratio of a real HDFC scheme we do not hold") is refused on
  routing with zero retrieval and zero LLM calls. The similarity gate cannot
  catch it, because all five corpus pages are near-identical HDFC scheme pages
  and a mid-cap question retrieves the expense-ratio row almost perfectly -
  so it must be refused *before* the gate is ever consulted.
- `calibrate.choose` derives the threshold from the observations' feasible
  interval and writes it where `Settings.require_similarity_threshold()` reads
  it back. The required test is "calibration picks a value": a hardcoded
  constant would be identical across every observation set, and it is not.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.ragbot.core.config import Settings
from src.ragbot.core.models import Intent
from src.ragbot.eval import calibrate as calibrate_mod
from src.ragbot.eval import judge as judge_mod
from src.ragbot.eval.dataset import SampleQuery
from src.ragbot.generation.educational import _NOT_IN_CORPUS
from src.ragbot.generation.pipeline import Ragbot
from src.ragbot.retrieval import intent as intent_mod

SAMPLE_FACTUAL = SampleQuery(
    id="Q1",
    question="What is the expense ratio of the HDFC Balance Advantage Fund?",
    answerable=True,
    intent=Intent.FACTUAL,
    expected_source="https://groww.in/funds/hdfc-balanced-advantage-fund-direct-growth",
    expected_facts=("expense ratio 1.03%",),
    note="",
)


class _ScriptedClient:
    """An LLMClient whose replies are scripted, recording every call."""

    def __init__(self, *script: str):
        self._script = list(script)
        self.calls: list[tuple[list[dict], int]] = []

    def complete(self, messages: list[dict], *, max_tokens: int = 400) -> str:
        self.calls.append((messages, max_tokens))
        return self._script[min(len(self.calls) - 1, len(self._script) - 1)]

    def stream(self, messages: list[dict], *, max_tokens: int = 400):
        raise AssertionError("the judge must not stream")


# --- M-1: the rubric admits exactly 0/1/2 and nothing else ----------------


def test_m1_rubric_boundaries():
    """Each rubric level is produced for its boundary case, and only for it.

    The three levels, from `docs/PRD.md` §9.1 as encoded in `judge.py`:
    - 2: every key fact present and correct, nothing unsupported, <= 3 sentences
    - 1: core correct but a secondary fact missing or imprecise
    - 0: any key fact wrong, any fact unsupported, advice, or a return figure
    """
    boundary_cases = [
        (
            '{"score": 2, "reason": "All key facts present.", '
            '"missing_facts": [], "unsupported_claims": []}',
            2,
        ),
        (
            '{"score": 1, "reason": "Core answer right but exit load is imprecise.", '
            '"missing_facts": ["exit load"], "unsupported_claims": []}',
            1,
        ),
        (
            '{"score": 0, "reason": "The stated expense ratio is wrong.", '
            '"missing_facts": [], "unsupported_claims": []}',
            0,
        ),
        (
            '{"score": 0, "reason": "The answer recommends buying the fund.", '
            '"missing_facts": [], "unsupported_claims": []}',
            0,
        ),
        (
            '{"score": 0, "reason": "The answer quotes an 18% CAGR.", '
            '"missing_facts": [], "unsupported_claims": []}',
            0,
        ),
        # A fenced block is a formatting habit, not a protocol violation.
        (
            '```json\n{"score": 2, "reason": "fenced", "missing_facts": [], '
            '"unsupported_claims": []}\n```',
            2,
        ),
    ]
    for payload, expected in boundary_cases:
        score, reason, missing, unsupported = judge_mod.parse_verdict(payload)
        assert score == expected
        assert reason.strip(), f"a score with no reason is not auditable: {payload}"
        assert isinstance(missing, list) and isinstance(unsupported, list)

    # The boundary cuts both ways: anything outside {0, 1, 2} is not a score.
    for bad in (
        '{"score": 3, "reason": "r", "missing_facts": [], "unsupported_claims": []}',
        '{"score": -1, "reason": "r", "missing_facts": [], "unsupported_claims": []}',
        '{"score": 1.5, "reason": "r", "missing_facts": [], "unsupported_claims": []}',
        '{"score": "2", "reason": "r", "missing_facts": [], "unsupported_claims": []}',
        '{"score": true, "reason": "r", "missing_facts": [], "unsupported_claims": []}',
        '{"reason": "no score at all", "missing_facts": [], "unsupported_claims": []}',
        'just prose, not JSON at all',
        "",
    ):
        with pytest.raises(judge_mod.JudgeProtocolError):
            judge_mod.parse_verdict(bad)

    with pytest.raises(judge_mod.JudgeProtocolError):
        judge_mod.parse_verdict(
            '{"score": 1, "missing_facts": [], "unsupported_claims": []}'
        )


def test_m1_judge_records_model_rubric_version_and_prompt_hash():
    """§9.1: a score without the model, rubric version and prompt hash is
    not reproducible. The hash matters as much as the id: editing the prompt
    silently changes what 2 means."""
    scripted = _ScriptedClient(
        '{"score": 2, "reason": "Every key fact present.", '
        '"missing_facts": [], "unsupported_claims": []}'
    )
    s = Settings(
        _env_file=None,
        llm_provider="openai",
        llm_model="judge-x-1.0",
        max_answer_sentences=3,
    )
    verdict = judge_mod.score(
        SAMPLE_FACTUAL,
        "The expense ratio is 1.03% [S1].",
        "Expense ratio 1.03%.",
        client=scripted,
        settings=s,
    )
    assert verdict.ok
    assert verdict.score == 2
    assert verdict.model == "judge-x-1.0"
    assert verdict.rubric_version == judge_mod.JUDGE_RUBRIC_VERSION
    assert verdict.prompt_sha256 == judge_mod.prompt_fingerprint()
    messages, max_tokens = scripted.calls[0]
    assert max_tokens == 300
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == judge_mod.JUDGE_SYSTEM_PROMPT

    # Without a provider the model id cannot be claimed, so it is stated as such.
    none_s = Settings(_env_file=None, llm_provider="none", max_answer_sentences=3)
    unclaimed = judge_mod.score(
        SAMPLE_FACTUAL, "x", "x", client=scripted, settings=none_s
    )
    assert unclaimed.model == "<unavailable>"


def test_m1_mean_is_none_when_any_verdict_is_missing():
    """A partial mean would report a denominator that is not 5. M-1 is either
    measured on the full set or it is not reported."""
    s = Settings(_env_file=None, llm_provider="openai", llm_model="m", max_answer_sentences=3)
    client = _ScriptedClient(
        '{"score": 2, "reason": "a", "missing_facts": [], "unsupported_claims": []}',
        '{"score": 1, "reason": "b", "missing_facts": [], "unsupported_claims": []}',
    )
    v2 = judge_mod.score(SAMPLE_FACTUAL, "x", "x", client=client, settings=s)
    v1 = judge_mod.score(SAMPLE_FACTUAL, "x", "x", client=client, settings=s)
    failed = replace(v1, score=None, error="judge call failed")
    assert judge_mod.mean_score([v2, v1]) == pytest.approx(1.5)
    assert judge_mod.mean_score([v2, failed]) is None


# --- M-3: a real HDFC scheme that is not in the corpus must be refused ------


class _ForbiddenRetrievalSearcher:
    """Raises instead of retrieving, so the routing-refusal test cannot
    silently retrieve and then claim it refused before retrieval."""

    def __init__(self):
        self.queries: list[str] = []
        self.retrieve_calls = 0
        self.search_calls = 0

    def retrieve(self, question: str):
        self.retrieve_calls += 1
        raise AssertionError(f"retrieval must not run for a routed refusal: {question!r}")

    def search(self, question: str):
        self.search_calls += 1
        raise AssertionError(f"search must not run for a routed refusal: {question!r}")


def test_unanswerable_real_scheme_is_refused(settings: Settings):
    """Q8: a REAL HDFC scheme that is not in the corpus must be refused.

    HDFC Mid Cap is a genuine scheme of the same AMC, and the render looks
    exactly like a corpus question ("What is the expense ratio..."). It must be
    refused on the `non_corpus_scheme` routing rule, before retrieval, with
    zero LLM calls - the similarity gate alone cannot catch it, because every
    corpus chunk is a near-identical HDFC scheme page and the expense-ratio row
    of another scheme scores highest.
    """
    question = "What is the expense ratio of the HDFC Mid Cap Fund?"
    match = intent_mod.explain(question)
    assert match.intent is Intent.OUT_OF_SCOPE, f"must route out of scope, got {match}"

    searcher = _ForbiddenRetrievalSearcher()
    bot = Ragbot(settings=settings, searcher=searcher)
    answer = bot.ask(question)

    assert answer.refused is True
    assert answer.intent is Intent.OUT_OF_SCOPE
    assert answer.source_url is None, "a refusal must cite nothing"
    assert answer.text == _NOT_IN_CORPUS, "a routing refusal is the fixed Refusal B string"
    assert "mid cap" not in answer.text.lower(), "the refusal must not name the scheme"
    assert searcher.retrieve_calls == 0
    assert searcher.search_calls == 0
    assert searcher.queries == []


# --- calibration picks a value, and that value is derived from the data ------


def _obs(
    obs_id: str,
    score: float,
    *,
    answerable: bool,
    gate_routed: bool = False,
    origin: str = "sample",
    facts: bool = True,
) -> calibrate_mod.Observation:
    intent = Intent.FACTUAL if answerable else Intent.OUT_OF_SCOPE
    return calibrate_mod.Observation(
        id=obs_id,
        question=f"question for {obs_id}",
        intent=intent,
        answerable=answerable,
        raw_dense_max=score,
        gate_routed=gate_routed,
        facts_in_context=facts,
        origin=origin,
    )


def _observation_set() -> list[calibrate_mod.Observation]:
    # A small but structurally real set: easy and hard factual queries, one
    # hard gate-routed negative probe, and one routing-refused sample refusal
    # (which NEVER bounds the threshold - that is precisely the design).
    return [
        _obs("F1", 0.82, answerable=True),
        _obs("F2", 0.78, answerable=True),
        _obs("F3", 0.75, answerable=True),
        _obs("N1", 0.74, answerable=False, origin="probe"),
        _obs("R1", 0.90, answerable=False, gate_routed=True),
    ]


def test_calibration_picks_a_value():
    """choose() derives the feasible-interval midpoint, not a guess."""
    obs = _observation_set()
    decision = calibrate_mod.choose(obs)

    assert decision.feasible
    assert decision.threshold is not None
    # Negatives max at 0.74 (must be EXCEEDED), facts min at 0.75 (must not be
    # EXCEEDED): midpoint = 0.745. The value is data-derived, so it is not
    # hardcoded anywhere and shifts with the observations (asserted below).
    assert decision.lower_bound == pytest.approx(0.74)
    assert decision.upper_bound == pytest.approx(0.75)
    assert decision.threshold == pytest.approx((0.74 + 0.75) / 2.0, abs=1e-4)

    # At the chosen value every factual opens with evidence, every sample
    # refusal is refused, and no probe is wrongly admitted - M-1-proxy and M-3
    # hold together, which is why the threshold is allowed to exist.
    point = calibrate_mod.evaluate_threshold(obs, decision.threshold)
    assert point.answerable_with_evidence == 3
    assert point.unsupported == 0
    assert point.refusals_correct == 1
    assert point.false_answers == 0
    assert point.probe_false_answers == 0


def test_calibration_threshold_is_not_hardcoded():
    """A hardcoded value would be constant across experiments. It is not."""
    first = calibrate_mod.choose(_observation_set()).threshold
    harder = calibrate_mod.choose(
        [
            _obs("F1", 0.90, answerable=True),
            _obs("F2", 0.88, answerable=True),
            _obs("N1", 0.70, answerable=False, origin="probe"),
        ]
    )
    assert harder.threshold is not None
    assert harder.threshold == pytest.approx((0.70 + 0.88) / 2.0, abs=1e-4)
    assert harder.threshold != first, "the threshold must be derived, not constant"


def test_calibration_round_trips_through_config(tmp_path: Path):
    """write_calibration is how the value reaches the gate: the file is what
    `Settings.require_similarity_threshold()` falls back to, so there is no
    second copy that could silently disagree."""
    obs = _observation_set()
    decision = calibrate_mod.choose(obs)
    curve = calibrate_mod.sweep(obs)
    settings = Settings(_env_file=None, max_answer_sentences=3)
    target = tmp_path / "calibration.json"

    calibrate_mod.write_calibration(decision, obs, curve, settings, path=target)
    assert target.exists()

    loaded = Settings(
        _env_file=None,
        similarity_threshold=None,
        calibration_path=str(target),
        max_answer_sentences=3,
    )
    assert loaded.require_similarity_threshold() == pytest.approx(decision.threshold)
    assert loaded.similarity_threshold is None, "the file fallback, not the env var"


def test_choose_refuses_to_invent_a_number_when_unseparable():
    """An overlapping negative class is a separability failure, and the honest
    result is `feasible=False` with NO number written - not a guess."""
    obs = [
        _obs("F1", 0.70, answerable=True),
        _obs("N1", 0.74, answerable=False, origin="probe"),
    ]
    decision = calibrate_mod.choose(obs)
    assert decision.feasible is False
    assert decision.threshold is None
    assert "separates" in decision.rationale