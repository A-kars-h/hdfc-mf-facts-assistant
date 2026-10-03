"""The confidence gate, and specifically that it reads raw dense similarity.

The tests that matter here are the ones that would fail if someone "simplified"
`decide()` to derive its threshold input from the candidate list. That refactor
looks harmless and is catastrophic: an RRF score is always small and positive, so
a cosine threshold would reject every candidate and the assistant would refuse
correct answers forever, with no error to point at.
"""

from __future__ import annotations

import pytest

from src.ragbot.core.config import Settings
from src.ragbot.core.errors import NotCalibratedError
from src.ragbot.core.models import GateDecision, RetrievedChunk
from src.ragbot.retrieval import gate as gate_mod
from src.ragbot.retrieval.dense import NO_DENSE_MATCH

FETCHED = "2026-01-01T00:00:00+00:00"


def _settings(threshold: float | None) -> Settings:
    # Phase 6 committed artifacts/calibration.json; these tests pin the
    # PRE-calibration contract, so the file fallback must not satisfy it.
    return Settings(
        _env_file=None,
        similarity_threshold=threshold,
        calibration_path="artifacts/__no_calibration__.json",
    )


def _candidate(rank: int, dense_score: float, chunk_id: str = "c1") -> RetrievedChunk:
    from src.ragbot.core.models import Chunk

    chunk = Chunk(
        chunk_id=chunk_id,
        page_id="hdfc-equity",
        scheme="HDFC Equity Fund - Direct Growth",
        category="Flexi Cap",
        source_url="https://groww.in/mutual-funds/hdfc-equity",
        fetched_at=FETCHED,
        text="Expense ratio 0.77%",
        token_count=8,
        content_hash="h",
    )
    return RetrievedChunk(
        chunk=chunk, dense_score=dense_score, fused_rank=rank, sparse_score=None
    )


# --- the spec's required test ------------------------------------------


def test_gate_uses_raw_dense_not_fused_rank():
    """Excellent fused ordering, poor raw similarity -> REFUSE.

    A candidate list sorted well and carrying a top fused rank of 1 is exactly
    what a fused score would look like if it were consulted. Only
    `raw_dense_max` decides, and here it is below the threshold.
    """
    candidates = [
        _candidate(rank=1, dense_score=0.11, chunk_id="a"),
        _candidate(rank=2, dense_score=0.09, chunk_id="b"),
        _candidate(rank=3, dense_score=0.08, chunk_id="c"),
    ]
    decision = gate_mod.decide(candidates, raw_dense_max=0.11, settings=_settings(0.50))
    assert decision.found_answer is False
    assert decision.reason == gate_mod.REASON_BELOW_THRESHOLD
    assert decision.raw_dense_max == 0.11


def test_gate_opens_on_raw_dense_alone():
    candidates = [_candidate(rank=1, dense_score=0.72)]
    decision = gate_mod.decide(candidates, raw_dense_max=0.72, settings=_settings(0.50))
    assert decision.found_answer is True
    assert decision.reason == gate_mod.REASON_OK


def test_gate_ignores_per_candidate_scores_and_uses_the_supplied_max():
    """A weak top candidate with a strong `raw_dense_max` argument passes.

    This is the mirror of the refusal test: it proves the decision follows the
    argument, not `max(c.dense_score for c in candidates)`.
    """
    candidates = [_candidate(rank=1, dense_score=0.05)]
    decision = gate_mod.decide(candidates, raw_dense_max=0.80, settings=_settings(0.50))
    assert decision.found_answer is True


def test_fused_score_values_would_never_pass_a_cosine_threshold():
    """Why the separate argument exists, demonstrated rather than asserted.

    RRF scores for a realistic result set are ~0.016-0.03. A calibrated cosine
    threshold sits around 0.4-0.6. Thresholding a fused score rejects 100% of
    results - the silent "always refuses" failure mode.
    """
    from src.ragbot.retrieval.fusion import rrf_score

    fused_scores = [rrf_score([r]) for r in (1, 2, 3, 4, 5, 10, 20)]
    assert all(s < 0.05 for s in fused_scores), fused_scores
    assert all(s < 0.45 for s in fused_scores), "a fused score must never clear a gate"


# --- no candidates ------------------------------------------------------


def test_no_candidates_never_answers_even_with_a_perfect_score():
    """A perfect dense match that was filtered downstream must not open the gate
    on its own: there is nothing to answer from."""
    decision = gate_mod.decide([], raw_dense_max=0.99, settings=_settings(0.50))
    assert decision.found_answer is False
    assert decision.reason == gate_mod.REASON_NO_CANDIDATES
    assert decision.candidates_considered == 0


def test_no_dense_match_sentinel_is_below_every_threshold():
    assert NO_DENSE_MATCH < 0.0
    decision = gate_mod.decide(
        [_candidate(1, 0.9)], raw_dense_max=NO_DENSE_MATCH, settings=_settings(0.0)
    )
    assert decision.found_answer is False, "the sentinel must fail closed"


# --- calibration guard --------------------------------------------------


def test_uncalibrated_threshold_raises_clearly():
    """Done-when: reading an uncalibrated threshold raises clearly."""
    with pytest.raises(NotCalibratedError) as exc:
        gate_mod.decide(
            [_candidate(1, 0.9)], raw_dense_max=0.9, settings=_settings(None)
        )
    message = str(exc.value)
    assert "SIMILARITY_THRESHOLD" in message
    assert "calibrate" in message.lower()
    # It must not leak a value, because there is none.
    assert "0." not in message


def test_decision_records_audit_values():
    decision = gate_mod.decide(
        [_candidate(1, 0.8), _candidate(2, 0.7)],
        raw_dense_max=0.8,
        settings=_settings(0.5),
    )
    assert isinstance(decision, GateDecision)
    assert decision.candidates_considered == 2
    assert decision.raw_dense_max == pytest.approx(0.8)


def test_threshold_boundary_is_inclusive():
    """At exactly the threshold the gate opens; a hair under it closes. Keeps
    calibration comparisons from being off-by-one ambiguous."""
    assert gate_mod.decide(
        [_candidate(1, 0.5)], raw_dense_max=0.5, settings=_settings(0.5)
    ).found_answer is True
    assert gate_mod.decide(
        [_candidate(1, 0.4999)], raw_dense_max=0.4999, settings=_settings(0.5)
    ).found_answer is False


# --- intent short-circuit ------------------------------------------------


def test_intent_decision_needs_no_threshold():
    """Opinion/out-of-scope questions are refused on routing, so they must not
    require a calibrated threshold to produce a decision."""
    from src.ragbot.core.models import Intent

    decision = gate_mod.decide_for_intent(
        Intent.OPINION, [], NO_DENSE_MATCH, settings=_settings(None)
    )
    assert decision.found_answer is False
    assert decision.reason == "intent:opinion"


def test_intent_decision_does_not_leak_thresholds():
    """Refusal B must not reveal scores (Phase 4 spec)."""
    from src.ragbot.core.models import Intent

    reason = gate_mod.decide_for_intent(
        Intent.OUT_OF_SCOPE, [], 0.0, settings=_settings(None)
    ).reason
    assert "0." not in reason
