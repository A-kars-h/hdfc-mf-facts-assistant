"""Reciprocal rank fusion.

RRF combines rankings without needing score calibration, which is exactly why it
is safe here and exactly why its output must never be thresholded. The fused
value is a sum of 1/(k + rank) terms: it is dimensionless, it depends on how many
retrievers ran and how deep they went, and two corpora with identical content
produce different numbers. A "similarity" of 0.032 means nothing.

So `fuse()` returns `RetrievedChunk`s carrying `fused_rank` and never returns the
score. The score exists, is computed, and is used to sort - then discarded. The
`dense_score` field on each result is untouched by fusion, because the
confidence gate must read the retriever's own cosine, not this.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from ..core.config import Settings, get_settings
from ..core.models import RetrievedChunk
from .hits import Hit

log = logging.getLogger(__name__)

# architecture §5.2. Constant 60 - the value the retrieval design is specified
# with. Not tuned per corpus, and never used as a threshold.
RRF_K = 60


def rrf_score(ranks: list[int], k: int = RRF_K) -> float:
    """Σ 1/(k + rank) over the ranks a chunk achieved. Ranks are 1-based.

    A chunk found by both retrievers beats a chunk found by one at the same rank,
    which is the entire point: agreement between a dense and a sparse retriever
    is much stronger evidence than either alone.
    """
    return sum(1.0 / (k + r) for r in ranks)


def _return_heavy_penalty(settings: Settings) -> float:
    value = float(getattr(settings, "return_heavy_penalty", 1.0))
    # Clamped rather than trusted: a penalty >= 1 would mean "no penalty" and a
    # value < 0 would reverse the intended ordering.
    return max(0.0, min(1.0, value))


def fuse(
    dense_hits: list[Hit],
    sparse_hits: list[Hit],
    *,
    top_k: int | None = None,
    k: int | None = None,
    settings: Settings | None = None,
) -> list[RetrievedChunk]:
    """Fuse both rankings into a single ordered candidate list.

    Return-heavy chunks are DEPRIORITISED, never dropped. Phase 0 measured 17% of
    the corpus as return/NAV figures, and the assistant must not state them
    (FR-20). Two separate controls handle that, deliberately:

    - the OUTPUT performance screen, which is the real guarantee, and
    - this ordering nudge, which keeps return tables from crowding out fee and
      minimum facts for questions that have nothing to do with performance.

    Dropping them at retrieval would delete genuine page content and make the
    assistant unable to say "this page reports returns over these periods", which
    is a fact. Ranking them lower keeps the content reachable.
    """
    settings = settings or get_settings()
    top = top_k if top_k is not None else settings.top_k
    kk = k if k is not None else settings.rrf_k
    penalty = _return_heavy_penalty(settings)

    # chunk_id -> the hit, and the ranks it achieved. A chunk can appear in both
    # lists, so union first and record both ranks.
    merged: dict[str, Hit] = {}
    ranks: dict[str, list[int]] = defaultdict(list)

    for hit in dense_hits:
        if hit.chunk_id not in merged:
            merged[hit.chunk_id] = hit
        if hit.dense_rank is not None:
            ranks[hit.chunk_id].append(hit.dense_rank)

    for hit in sparse_hits:
        if hit.chunk_id not in merged:
            merged[hit.chunk_id] = hit
        if hit.sparse_rank is not None:
            ranks[hit.chunk_id].append(hit.sparse_rank)

    if not merged:
        return []

    # score, tie-break key, id. The id tie-break matters: without it, two chunks
    # with identical scores (common, since RRF values come from a small set of
    # integers) would order by dict insertion, making output non-deterministic
    # across runs and tests.
    scored: list[tuple[float, str, str]] = []
    for chunk_id, hit in merged.items():
        score = rrf_score(ranks[chunk_id], kk)
        if penalty < 1.0 and hit.chunk.return_heavy:
            score *= penalty
        scored.append((score, chunk_id, hit.chunk.scheme))
    scored.sort(key=lambda row: (-row[0], row[1]))

    log.debug(
        "fused %d dense + %d sparse -> %d unique, returning %d (penalty=%.2f)",
        len(dense_hits), len(sparse_hits), len(merged), top, penalty,
    )

    fused: list[RetrievedChunk] = []
    for position, (_score, chunk_id, _scheme) in enumerate(scored[:top], start=1):
        hit = merged[chunk_id]
        # dense_score is carried through UNCHANGED. Fusion must not write to the
        # one field the gate is allowed to read.
        #
        # The -1.0 fallback is a FAIL-CLOSED default, not a "no match" sentinel
        # that could be mistaken for a score: cosine similarity cannot go below
        # -1, so an unresolved value can only ever make the gate refuse. In the
        # real pipeline search.py resolves every sparse-only hit's true cosine
        # before calling this, so it never fires; it exists so calling fuse()
        # directly cannot fabricate a passable number.
        dense = hit.dense_score if hit.dense_score is not None else -1.0
        fused.append(
            RetrievedChunk(
                chunk=hit.chunk,
                dense_score=dense,
                sparse_score=hit.sparse_score,
                fused_rank=position,
            )
        )
    return fused
