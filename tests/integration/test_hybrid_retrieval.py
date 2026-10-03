"""Hybrid retrieval against the real, built index.

These need `python -m src.ragbot.ingest` to have run. They use the real
embedding model on purpose: the claims being tested are about score magnitudes
and rank behaviour, and a fake embedder's hash vectors would make any assertion
about cosine similarity meaningless.

Excluded by default via the `integration` marker when the index is absent.
"""

from __future__ import annotations

import pytest

from src.ragbot.core.config import Settings, get_settings
from src.ragbot.core.errors import NotCalibratedError
from src.ragbot.core.models import Intent
from src.ragbot.retrieval import gate as gate_mod
from src.ragbot.retrieval.dense import NO_DENSE_MATCH, cosine_similarity_from_distance
from src.ragbot.retrieval.search import HybridSearcher

pytestmark = pytest.mark.integration


# Phase 6 committed artifacts/calibration.json; these tests assert the
# PRE-calibration contract ("search() raises when uncalibrated"), so the file
# fallback must never satisfy them.
_ABSENT_CALIBRATION = "artifacts/__no_calibration__.json"


def _settings(**kw) -> Settings:
    kw.setdefault("calibration_path", _ABSENT_CALIBRATION)
    return get_settings().model_copy(update=kw)


def _searcher(**kw) -> HybridSearcher:
    return HybridSearcher(_settings(**kw))


def _require_index() -> None:
    s = get_settings()
    if not s.manifest_file.exists() or not s.bm25_file.exists():
        pytest.skip(
            "index not built; run `python -m src.ragbot.ingest` before these tests"
        )


@pytest.fixture(scope="module")
def searcher() -> HybridSearcher:
    _require_index()
    # Threshold +inf closes the gate so retrieval is exercised without a
    # calibrated value. Calibration is Phase 6; the gate's own refusal
    # behaviour is covered in tests/unit/test_gate.py.
    return _searcher(similarity_threshold=float("inf"))


# --- the spec's required test ------------------------------------------


def test_hybrid_beats_dense_on_a_numeric_query(searcher: HybridSearcher):
    """At least one BM25-only result reaches the final top-k.

    A bare numeric query is the case where dense retrieval is weakest: "Rs. 500"
    embeds to a direction, not a value, so the dense ranking cannot reliably put
    the chunk that literally contains ₹500 first. BM25 matches the token.
    """
    result = searcher.search("Rs. 500")

    assert result.candidates, "expected candidates"
    bm25_only = result.bm25_only_ids
    assert bm25_only, (
        "hybrid search produced nothing dense retrieval missed - the sparse leg "
        "is not contributing"
    )
    assert any(
        "500" in c.chunk.text for c in result.candidates if c.chunk_id in bm25_only
    ), "the BM25-only contribution should be the chunk containing the figure"


# --- intent routing happens BEFORE retrieval ---------------------------


def test_opinion_question_never_embeds_or_retrieves(searcher: HybridSearcher):
    """The safety property: advice is refused on routing, having touched nothing.

    These pages match "Should I buy HDFC Equity?" strongly, so a gate could not
    catch it. Asserting on the OUTCOME (no candidates, no hits) is the only way
    to prove nothing was retrieved.
    """
    result = searcher.search("Should I buy HDFC Equity Fund for 5 years?")

    assert result.intent is Intent.OPINION
    assert result.candidates == []
    assert result.dense_hits == []
    assert result.sparse_hits == []
    assert result.raw_dense_max == NO_DENSE_MATCH
    assert result.found_answer is False
    assert result.decision.reason == "intent:opinion"


def test_out_of_scope_question_never_retrieves(searcher: HybridSearcher):
    result = searcher.search("What is the expense ratio of Kotak Flexi Cap?")
    assert result.intent is Intent.OUT_OF_SCOPE
    assert result.dense_hits == []
    assert result.sparse_hits == []
    assert result.decision.reason == "intent:out_of_scope"


def test_factual_question_does_retrieve(searcher: HybridSearcher):
    result = searcher.search("What is the minimum SIP for HDFC ELSS?")
    assert result.intent is Intent.FACTUAL
    assert result.dense_hits and result.candidates


# --- raw dense score semantics -----------------------------------------


def test_cosine_distance_conversion():
    """Chroma returns cosine DISTANCE. Reading it as a similarity would push a
    strong match below any sensible threshold."""
    assert cosine_similarity_from_distance(0.0) == pytest.approx(1.0)
    assert cosine_similarity_from_distance(0.2) == pytest.approx(0.8)
    assert cosine_similarity_from_distance(1.0) == pytest.approx(0.0)
    assert cosine_similarity_from_distance(2.0) == pytest.approx(-1.0), "clamped"


def test_raw_dense_max_equals_the_best_dense_hit(searcher: HybridSearcher):
    result = searcher.search("What is the benchmark of HDFC Small Cap Fund?")
    best = max(h.dense_score for h in result.dense_hits)
    assert result.raw_dense_max == pytest.approx(best)
    assert result.decision.raw_dense_max == pytest.approx(best)


def test_dense_scores_are_cosine_not_distance(searcher: HybridSearcher):
    """A cosine distance of 0.18 is a similarity of 0.82. Every stored dense
    score must be on the similarity side of that."""
    result = searcher.search("What is the exit load on HDFC Equity Fund?")
    assert result.dense_hits
    for hit in result.dense_hits:
        assert -1.0 <= hit.dense_score <= 1.0
    # A good factual match scores well above the ~0.2 a raw distance would give.
    assert result.raw_dense_max > 0.3


def test_gate_reads_the_same_value_search_exposes(searcher: HybridSearcher):
    result = searcher.search("What is the minimum SIP for HDFC ELSS?")
    decision = gate_mod.decide(
        result.candidates, result.raw_dense_max, settings=searcher.settings
    )
    assert decision.raw_dense_max == result.decision.raw_dense_max
    assert decision.found_answer == result.decision.found_answer


# --- candidates carry real numbers -------------------------------------


def test_every_candidate_has_a_real_dense_score(searcher: HybridSearcher):
    """No sentinel -1.0 in practice: sparse-only hits get their true cosine."""
    result = searcher.search("Rs. 500")
    for c in result.candidates:
        assert c.dense_score > -1.0, (
            f"{c.chunk_id} kept the fail-closed sentinel; its stored vector "
            f"should have been resolvable"
        )


def test_sparse_only_candidates_carry_a_bm25_score(searcher: HybridSearcher):
    result = searcher.search("Rs. 500")
    for c in result.candidates:
        if c.chunk_id in result.bm25_only_ids:
            assert c.sparse_score is not None and c.sparse_score > 0


def test_candidates_carry_citable_provenance(searcher: HybridSearcher):
    result = searcher.search("What is the minimum SIP for HDFC ELSS?")
    for c in result.candidates:
        assert c.source_url.startswith("https://groww.in/mutual-funds/")
        assert c.chunk.scheme
        assert c.chunk.fetched_at.tzinfo is not None


# --- the specific facts the corpus promises ----------------------------


def test_the_minimum_sip_is_ranked_first(searcher: HybridSearcher):
    """The ELSS minimum SIP, which Phase 0 verified on the page.

    This one is asserted at rank 1 deliberately: "Rs. 500" is a rare string that
    only the ELSS fact row carries, so nothing else can compete for it.
    """
    result = searcher.search("What is the minimum SIP for HDFC ELSS?")
    assert "500" in result.candidates[0].chunk.text


@pytest.mark.parametrize(
    "question,expected",
    [
        ("What is the expense ratio of HDFC Equity Fund?", "0.77"),
        ("What is the expense ratio of HDFC ELSS Tax Saver Fund?", "1.21"),
        ("What is the expense ratio of HDFC Small Cap Fund?", "0.78"),
    ],
)
def test_the_expense_ratio_is_in_the_top_k(
    searcher: HybridSearcher, question: str, expected: str
):
    """The expense ratio must be RETRIEVABLE, not necessarily ranked first.

    Rank 1 is deliberately not asserted here. Each page carries the same
    boilerplate glossary:

        Expense ratio: A fee payable to a mutual fund house for managing your
        mutual fund investments. ...

    That chunk repeats the query term twice, so BM25 ranks it first (18.45 vs
    16.31) even though the real fact row wins the dense leg (0.8713 vs 0.8696).
    RRF then does exactly what it is specified to do:

        glossary  1/(60+2) + 1/(60+1) = 0.032522   <- rank 1
        fact row  1/(60+1) + 1/(60+6) = 0.031545   <- rank 2

    This is a property of the corpus and of RRF, not a defect in either, so the
    test pins what the phase actually promises: the value reaches the caller
    inside the top_k that Phase 4 reads. See the boilerplate-duplication note in
    docs/implementation.md - the glossary is repeated on all five pages and is
    worth collapsing there.
    """
    result = searcher.search(question)
    texts = [c.chunk.text for c in result.candidates]
    assert any(expected in t for t in texts), (
        f"{expected!r} absent from all {len(texts)} candidates; "
        f"top was {texts[0][:160]!r}"
    )


def test_the_expense_ratio_fact_row_is_in_the_corpus(searcher: HybridSearcher):
    """The fact row itself must exist, correctly paired.

    This is the regression test for the Phase 2 cleaner defect that Phase 3
    exposed: the exit-load modal's glossary term block ("Expense ratio" heading
    plus a prose definition) was emitted as a fact row, producing the false fact
    "Expense ratio | A fee payable to a mutual fund house ...". It outranked the
    real row, and for a while the corpus simply did not contain the number.
    """
    result = searcher.search("What is the expense ratio of HDFC Equity Fund?")
    rows = [
        c.chunk.text
        for c in result.dense_hits + result.sparse_hits
        if c.chunk.section == "Fund house"
    ]
    # Chunks are prefixed with "<scheme> (<section>) ", so match the row itself.
    assert any(t.endswith("Expense ratio | 0.77%") for t in rows)
    assert not any("Expense ratio | A fee payable" in t for t in rows)


def test_elss_is_ranked_first_for_elss_specific_facts(searcher: HybridSearcher):
    """Every chunk repeats its scheme name, so the fused ranking can be checked
    per-scheme rather than by hoping the right text appears."""
    result = searcher.search("What is the minimum SIP for HDFC ELSS?")
    assert "ELSS" in result.candidates[0].chunk.scheme


# --- ordering hygiene ---------------------------------------------------


def test_fused_ranks_are_contiguous(searcher: HybridSearcher):
    result = searcher.search("What is the AUM?")
    assert [c.fused_rank for c in result.candidates] == list(
        range(1, len(result.candidates) + 1)
    )


def test_results_are_deterministic_across_repeated_searches(
    searcher: HybridSearcher,
):
    q = "What is the exit load on HDFC Equity Fund?"
    first = [c.chunk_id for c in searcher.search(q).candidates]
    second = [c.chunk_id for c in searcher.search(q).candidates]
    assert first == second


def test_top_k_is_respected(searcher: HybridSearcher):
    for c in searcher.search("What is the expense ratio?").candidates:
        assert c.fused_rank <= get_settings().top_k


# --- retrieve() / search() split -----------------------------------------


def test_retrieve_gives_candidates_without_a_gate(searcher: HybridSearcher):
    """`retrieve()` is steps 1-5 with no gate, so an uncalibrated caller can
    still inspect real candidates. It must not fabricate a decision."""
    result = searcher.retrieve("What is the minimum SIP for HDFC ELSS?")
    assert result.candidates
    assert result.decision is None


def test_retrieve_and_search_agree_on_the_ranking(searcher: HybridSearcher):
    q = "What is the minimum SIP for HDFC ELSS?"
    assert [c.chunk_id for c in searcher.retrieve(q).candidates] == [
        c.chunk_id for c in searcher.search(q).candidates
    ]


def test_retrieve_still_refuses_non_factual_intents(searcher: HybridSearcher):
    """Routing refusal is a decision in its own right, produced without any
    threshold, so it must survive into `retrieve()` and must not be replaced by
    an 'uncalibrated' gate verdict."""
    result = searcher.retrieve("Should I buy HDFC Equity Fund for 5 years?")
    assert result.decision is not None
    assert result.decision.found_answer is False
    assert result.decision.reason == "intent:opinion"
    assert result.candidates == []


def test_search_raises_when_uncalibrated():
    """`search()` is the gated entry point and must refuse to guess, even though
    the same corpus retrieves fine through `retrieve()`."""
    _require_index()
    uncalibrated = _settings(similarity_threshold=None)
    with pytest.raises(NotCalibratedError):
        HybridSearcher(uncalibrated).search("What is the minimum SIP for HDFC ELSS?")


def test_search_answers_when_calibrated():
    _require_index()
    s = _settings(similarity_threshold=0.0)
    result = HybridSearcher(s).search("What is the minimum SIP for HDFC ELSS?")
    assert result.decision.found_answer is True
    assert result.threshold == 0.0


# --- calibration risk, recorded as an observation ----------------------


def test_raw_dense_max_varies_widely_across_factual_questions(
    searcher: HybridSearcher,
):
    """Recorded because it constrains Phase 6, not because it fails.

    Correct factual questions span a wide raw-dense range: a question naming the
    scheme and the field scores ~0.8, while a bare field name ("lock-in period")
    can score ~0.27 even though the retrieved chunk is right. A single threshold
    tuned on the easy questions will refuse the hard ones, so calibration must
    sample the hard tail and not just the mean.
    """
    easy = searcher.search("What is the benchmark of HDFC Small Cap Fund?")
    hard = searcher.search("What is the lock-in period?")

    assert easy.raw_dense_max > 0.6
    assert hard.raw_dense_max < easy.raw_dense_max
    assert hard.candidates, "the hard question must still retrieve"
