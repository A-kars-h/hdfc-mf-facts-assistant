"""Reciprocal rank fusion: ordering behaviour and score hygiene."""

from __future__ import annotations

import pytest

from src.ragbot.core.config import Settings
from src.ragbot.core.models import RetrievedChunk
from src.ragbot.retrieval.fusion import RRF_K, fuse, rrf_score
from src.ragbot.retrieval.hits import Hit

FETCHED = "2026-01-01T00:00:00+00:00"


def _chunk(chunk_id: str, *, return_heavy: bool = False):
    from src.ragbot.core.models import Chunk

    return Chunk(
        chunk_id=chunk_id,
        page_id="hdfc-equity",
        scheme="HDFC Equity Fund - Direct Growth",
        category="Flexi Cap",
        source_url="https://groww.in/mutual-funds/hdfc-equity",
        fetched_at=FETCHED,
        text="Expense ratio 0.77%",
        token_count=8,
        content_hash="h",
        return_heavy=return_heavy,
    )


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _dense(chunk_id: str, rank: int, score: float = 0.5) -> Hit:
    return Hit(
        chunk=_chunk(chunk_id), dense_score=score, dense_rank=rank
    )


def _sparse(chunk_id: str, rank: int, score: float = 5.0) -> Hit:
    return Hit(chunk=_chunk(chunk_id), sparse_score=score, sparse_rank=rank)


# --- the RRF formula ----------------------------------------------------


def test_rrf_k_is_60():
    assert RRF_K == 60


def test_rrf_score_is_the_documented_formula():
    assert rrf_score([1]) == pytest.approx(1 / 61)
    assert rrf_score([1, 1]) == pytest.approx(2 / 61)
    assert rrf_score([3, 7]) == pytest.approx(1 / 63 + 1 / 67)


def test_better_rank_scores_higher():
    assert rrf_score([1]) > rrf_score([2]) > rrf_score([10])


def test_agreement_beats_a_single_strong_hit():
    """The point of fusion: found by both retrievers at modest ranks beats found
    by one at rank 1."""
    both = rrf_score([2, 2])
    single_top = rrf_score([1])
    assert both > single_top


def test_dense_scores_are_far_outside_the_fused_range():
    """Fused scores are ~0.02 and cosines are ~0.5. They are not comparable, and
    the gate may only use the latter."""
    assert rrf_score([1]) < 0.1
    assert 0.1 < 0.72 < 1.0


# --- fusion ordering ----------------------------------------------------


def test_agreement_chunk_rises_to_the_top():
    result = fuse(
        [_dense("a", 1), _dense("b", 2), _dense("c", 3)],
        [_sparse("b", 1), _sparse("c", 2), _sparse("a", 5)],
        settings=_settings(),
    )
    # 'b' is rank 2 dense + rank 1 sparse, which outscores 'a' at rank 1 dense only.
    assert result[0].chunk_id == "b"
    assert result[0].fused_rank == 1


def test_ranks_are_contiguous_and_one_based():
    result = fuse(
        [_dense(str(i), i) for i in range(1, 8)],
        [_sparse(str(i), i) for i in range(1, 8)],
        top_k=5,
        settings=_settings(),
    )
    assert [c.fused_rank for c in result] == [1, 2, 3, 4, 5]
    assert len(result) == 5


def test_top_k_is_respected():
    dense = [_dense(str(i), i) for i in range(1, 21)]
    assert len(fuse(dense, [], top_k=5, settings=_settings())) == 5
    assert len(fuse(dense, [], top_k=3, settings=_settings())) == 3


def test_empty_inputs_return_empty():
    assert fuse([], [], settings=_settings()) == []
    assert fuse([_dense("a", 1)], [], settings=_settings())[0].chunk_id == "a"
    assert fuse([], [_sparse("a", 1)], settings=_settings())[0].chunk_id == "a"


def test_ordering_is_deterministic_for_tied_scores():
    """RRF values come from a small set of rationals, so ties are common. Without
    a stable tie-break the output would depend on dict insertion order."""
    dense = [_dense(c, 1) for c in ("c", "a", "b", "d")]
    first = [c.chunk_id for c in fuse(dense, [], settings=_settings())]
    second = [c.chunk_id for c in fuse(dense, [], settings=_settings())]
    assert first == second == sorted(first), "ties must break on chunk_id"


# --- the gate-visible field must survive fusion -------------------------


def test_fusion_never_modifies_dense_score():
    """`dense_score` is the only field the gate may read, so fusion must pass it
    through untouched."""
    dense = [_dense("a", 1, score=0.61), _dense("b", 2, score=0.22)]
    sparse = [_sparse("b", 1)]
    result = fuse(dense, sparse, settings=_settings())
    by_id = {c.chunk_id: c for c in result}
    assert by_id["a"].dense_score == pytest.approx(0.61)
    assert by_id["b"].dense_score == pytest.approx(0.22)


def test_sparse_only_hit_keeps_its_bm25_score():
    result = fuse([], [_sparse("z", 1, score=7.25)], settings=_settings())
    assert result[0].sparse_score == pytest.approx(7.25)
    assert result[0].dense_score == pytest.approx(-1.0), (
        "unresolved dense must fail closed, not fabricate a passable score"
    )


def test_no_fused_score_is_exposed_on_the_result():
    """`RetrievedChunk` has no fused-score field by design; assert the model
    cannot grow one silently."""
    fields = set(RetrievedChunk.model_fields)
    assert "fused_score" not in fields
    assert "score" not in fields
    assert fields == {
        "chunk", "dense_score", "fused_rank", "sparse_score",
    }


# --- return-heavy deprioritisation -------------------------------------


def test_return_heavy_chunks_are_deprioritised_not_dropped():
    """Phase 0 measured 17% return/NAV content. It must rank lower without being
    deleted: it is still a fact the page states."""
    # A return-heavy chunk at the better rank, and a plain chunk just behind it.
    # Ranks 1 and 2 differ by ~1.7%, so a 0.9 penalty is enough to flip them -
    # which is the whole point: the nudge changes ordering, not content.
    dense = [
        Hit(chunk=_chunk("rh", return_heavy=True), dense_score=0.5, dense_rank=1),
        _dense("plain", 2),
    ]
    baseline = fuse(dense, [], settings=_settings(return_heavy_penalty=1.0))
    assert [c.chunk_id for c in baseline] == ["rh", "plain"]

    penalised = fuse(dense, [], settings=_settings(return_heavy_penalty=0.9))
    assert [c.chunk_id for c in penalised] == ["plain", "rh"], (
        "the penalty must actually reorder, not merely be present"
    )
    assert len(penalised) == 2, "return-heavy content must stay retrievable"


def test_penalty_of_one_is_a_no_op():
    dense = [_dense("a", 1)]
    with_penalty = fuse(
        dense, [], settings=_settings(return_heavy_penalty=1.0)
    )
    assert with_penalty[0].chunk_id == "a"


def test_penalty_does_not_change_dense_score():
    """The deprioritisation is ordering-only. If it could move a score, it could
    change what the gate sees, which is forbidden."""
    dense = [
        _dense("a", 1, score=0.55),
        Hit(chunk=_chunk("b", return_heavy=True), dense_score=0.44, dense_rank=2),
    ]
    result = fuse(dense, [], settings=_settings(return_heavy_penalty=0.5))
    assert {c.chunk_id: c.dense_score for c in result} == {
        "a": pytest.approx(0.55), "b": pytest.approx(0.44)
    }
