"""Dense retrieval over the Chroma collection.

The only thing this module is trusted to produce is a RAW COSINE SIMILARITY. Not
an RRF score, not a normalised rank, not a rescaled 0-1 "confidence". The
confidence gate thresholds this value, and that only works because it is on the
same scale the model produced (architecture §5.2, FR-13).

Chroma stores vectors in a ``cosine``-space HNSW index and returns
``distances``, where distance = ``1 - cosine_similarity``. Converting is
mandatory: a raw cosine distance of 0.18 is a similarity of 0.82, so reading the
distance as if it were a similarity would push a strong match below any sensible
threshold and silently refuse correct answers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from ..core.config import Settings, get_settings
from ..ingest.embedder import Embedder
from .hits import Hit, hydrate

log = logging.getLogger(__name__)

# Cosine similarity lives in [-1, 1]. Used when the dense side produced no hits
# at all, so that `raw_dense_max` is below any real threshold and the gate fails
# closed. Chosen over -inf because GateDecision.raw_dense_max is serialised to
# JSON and -inf is not valid JSON.
NO_DENSE_MATCH = -1.0

# Over-fetch factor for the dense leg. RRF needs depth from both retrievers to
# disagree productively; asking Chroma for exactly top_k gives fusion nothing to
# fuse and silently degrades to dense-only.
DENSE_OVERFETCH = 4


@dataclass
class DenseResult:
    hits: list[Hit] = field(default_factory=list)
    raw_dense_max: float = NO_DENSE_MATCH
    query_vector: list[float] = field(default_factory=list)


def cosine_similarity_from_distance(distance: float) -> float:
    """Chroma cosine distance -> similarity, clamped to the valid range."""
    return max(-1.0, min(1.0, 1.0 - float(distance)))


def _rows(got: dict, key: str) -> list:
    """First row of a Chroma list-of-lists query result, tolerating absence.

    Returns an empty list rather than None so the caller's index arithmetic
    (`i < len(...)`) stays simple.
    """
    value = got.get(key)
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if not len(value):
        return []
    first = value[0]
    if first is None:
        return []
    if isinstance(first, np.ndarray):
        return first.tolist()
    return list(first)


class DenseRetriever:
    def __init__(
        self,
        settings: Settings | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedder = embedder or Embedder(self.settings.embedding_model)

    # --- store access ---

    @property
    def collection(self):
        # Imported through Writer so there is exactly one place that knows how the
        # collection is opened (path, name, cosine space).
        from ..ingest.writer import Writer

        return Writer(self.settings, self.embedder).collection

    # --- querying ---

    def query_vector(self, question: str) -> list[float]:
        return self.embedder.embed_one(question, label="query")

    def search(
        self,
        question: str,
        *,
        n_results: int | None = None,
    ) -> DenseResult:
        """Top-N dense matches, plus the raw maximum similarity."""
        vector = self.query_vector(question)
        n = n_results or (self.settings.top_k * DENSE_OVERFETCH)
        collection = self.collection

        if collection.count() == 0:
            log.warning("dense search against an empty collection; run ingest first")
            return DenseResult([], NO_DENSE_MATCH, vector)

        got = collection.query(
            query_embeddings=[vector],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )
        # Chroma returns a list-of-lists for a single query. `or` fallbacks are
        # avoided for any field that may come back as an ndarray (see score_ids).
        ids = _rows(got, "ids")
        docs = _rows(got, "documents")
        metas = _rows(got, "metadatas")
        dists = _rows(got, "distances")

        hits: list[Hit] = []
        best = NO_DENSE_MATCH
        for i, chunk_id in enumerate(ids):
            meta = metas[i] if i < len(metas) else None
            if not meta:
                continue
            score = cosine_similarity_from_distance(dists[i]) if i < len(dists) else NO_DENSE_MATCH
            try:
                chunk = hydrate(str(chunk_id), str(docs[i] or ""), dict(meta))
            except Exception as exc:  # noqa: BLE001
                # One malformed row must not fail the whole query.
                log.warning("skipping unhydratable chunk %s: %s", chunk_id, exc)
                continue
            hits.append(
                Hit(
                    chunk=chunk,
                    dense_score=score,
                    dense_rank=i + 1,  # Chroma returns rows best-first.
                )
            )
            best = max(best, score)

        return DenseResult(hits, best if hits else NO_DENSE_MATCH, vector)

    def score_ids(
        self, vector: list[float], ids: list[str]
    ) -> dict[str, float]:
        """Exact cosine similarity for specific stored chunks.

        Used to give BM25-only hits a REAL dense score. Those hits have no dense
        rank - Chroma did not return them - but the CLI prints a dense score for
        every candidate and the audit trail should not contain invented numbers.
        Leaving `dense_score` as None would be honest but unhelpful; putting 0.0
        would be dishonest. Computing it is cheap: these are a handful of ids.
        """
        ids = [i for i in dict.fromkeys(ids)]
        if not ids:
            return {}
        got = self.collection.get(ids=ids, include=["embeddings"])
        # NOT `or []`. With numpy installed, Chroma returns `embeddings` as an
        # ndarray, and a truth test on a multi-element array raises. Checked with
        # `is None` for that reason.
        raw = got.get("embeddings")
        embeddings = [] if raw is None else raw
        out: dict[str, float] = {}
        for chunk_id, embedding in zip(got.get("ids") or [], embeddings):
            if embedding is None:
                continue
            # Both sides are unit vectors (normalize_embeddings=True), so the dot
            # product IS the cosine similarity. Same identity fusion relies on.
            out[str(chunk_id)] = sum(a * b for a, b in zip(vector, embedding))
        return out
