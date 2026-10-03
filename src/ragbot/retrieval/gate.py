"""The confidence gate (FR-13).

The one rule this module exists to enforce: **the gate reads raw dense cosine
similarity, and nothing else.**

Reciprocal rank fusion produces a scale-free number. It is not a similarity, it
depends on retrieval depth and on how many retrievers contributed, and it cannot
be calibrated. So if a fused score ever reached this comparison, the threshold
would be meaningless - and it would fail in the worst direction, because a
fused score is always small and positive, so a threshold that works on cosine
would reject everything and the assistant would refuse correct answers forever
with no visible cause.

That is why `raw_dense_max` is a separate, required argument rather than
something computed here from `candidates`. A caller cannot accidentally pass the
wrong value because there is no way to derive it from the candidate list. The
tests assert this directly: a list whose best fused rank is excellent but whose
raw dense max is low must NOT pass.

Note what the gate is NOT: it is not an answerability guarantee. "Should I buy
HDFC Equity?" retrieves strong context and passes any threshold - which is why
intent is classified before retrieval and why opinion questions never reach here.
"""

from __future__ import annotations

import logging

from ..core.config import Settings, get_settings
from ..core.models import GateDecision, RetrievedChunk
from .dense import NO_DENSE_MATCH

log = logging.getLogger(__name__)

REASON_OK = "ok"
REASON_NO_CANDIDATES = "no_candidates"
REASON_BELOW_THRESHOLD = "below_threshold"


def decide(
    candidates: list[RetrievedChunk],
    raw_dense_max: float,
    *,
    settings: Settings | None = None,
) -> GateDecision:
    """Decide whether the retrieved context is strong enough to answer from.

    `raw_dense_max` is the maximum RAW cosine similarity the dense retriever
    saw. It is passed in, never derived from `candidates`, and never replaced by
    a fused score - see the module docstring.

    Reading the threshold goes through `require_similarity_threshold()`, which
    raises `NotCalibratedError` when no calibrated value exists. That is
    deliberate: a guessed threshold does not crash, it just quietly answers
    "not in the data" to questions the corpus answers perfectly, or worse, answers
    everything. Failing loudly is the only safe behaviour.
    """
    settings = settings or get_settings()
    threshold = settings.require_similarity_threshold()

    if not candidates:
        return GateDecision(
            found_answer=False,
            reason=REASON_NO_CANDIDATES,
            raw_dense_max=raw_dense_max,
            candidates_considered=0,
        )

    if raw_dense_max < threshold:
        log.info(
            "gate closed: raw_dense_max=%.4f below threshold=%.4f",
            raw_dense_max, threshold,
        )
        return GateDecision(
            found_answer=False,
            reason=REASON_BELOW_THRESHOLD,
            raw_dense_max=raw_dense_max,
            candidates_considered=len(candidates),
        )

    log.info(
        "gate open: raw_dense_max=%.4f >= threshold=%.4f candidates=%d",
        raw_dense_max, threshold, len(candidates),
    )
    return GateDecision(
        found_answer=True,
        reason=REASON_OK,
        raw_dense_max=raw_dense_max,
        candidates_considered=len(candidates),
    )


def decide_for_intent(
    intent,
    candidates: list[RetrievedChunk],
    raw_dense_max: float,
    *,
    settings: Settings | None = None,
) -> GateDecision:
    """Closed-gate decision for a non-factual intent.

    Used when intent classification short-circuits before retrieval, so that
    opinion and out-of-scope questions produce a normal, auditable
    `GateDecision` instead of a special case the caller has to remember to
    handle. No threshold is read: these questions are not gated on similarity at
    all, they are refused on routing, and reading an uncalibrated threshold here
    would raise for a question that never needed one.
    """
    from ..core.models import Intent  # noqa: F401  (documents the expected type)

    value = str(getattr(intent, "value", intent))
    return GateDecision(
        found_answer=False,
        reason=f"intent:{value}",
        raw_dense_max=raw_dense_max,
        candidates_considered=len(candidates),
    )


__all__ = [
    "decide",
    "decide_for_intent",
    "REASON_OK",
    "REASON_NO_CANDIDATES",
    "REASON_BELOW_THRESHOLD",
]
