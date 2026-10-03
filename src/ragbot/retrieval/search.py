"""Hybrid retrieval orchestration: question -> ranked, gated candidates.

This is the object Phase 4 will call. It exists as a named class rather than
being assembled in the CLI because the ORDER of operations is load-bearing:

1. Classify intent. **Before** retrieval, not after.
2. Refuse non-factual intents here, having retrieved nothing.
3. Dense + sparse independently.
4. Give every sparse-only hit a REAL cosine score.
5. Fuse into ranks.
6. Gate on the raw dense maximum, passed in from step 3.

Step 2 is not an optimisation. "Should I buy HDFC Equity for 5 years?" matches
this corpus strongly - it is a fund page full of characteristics - so an
advice-seeking question retrieves good context and sails through any similarity
threshold. Only intent detects it. Routing after retrieval would mean the advice
context was fetched, embedded, and ranked before anything noticed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..core.config import Settings, get_settings
from ..core.errors import NotCalibratedError
from ..core.models import GateDecision, Intent, RetrievedChunk
from ..ingest.embedder import Embedder
from . import gate as gate_mod
from .dense import NO_DENSE_MATCH, DenseRetriever
from .fusion import fuse
from .hits import Hit
from .intent import IntentMatch, explain, is_performance_claim
from .sparse import SparseRetriever

log = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Everything the CLI and Phase 4 need, including the audit trail."""

    question: str
    intent: Intent
    intent_match: IntentMatch
    candidates: list[RetrievedChunk] = field(default_factory=list)
    raw_dense_max: float = NO_DENSE_MATCH
    decision: GateDecision | None = None
    dense_hits: list[Hit] = field(default_factory=list)
    sparse_hits: list[Hit] = field(default_factory=list)
    sparse_available: bool = True
    performance_claim: bool = False
    threshold: float | None = None

    @property
    def found_answer(self) -> bool:
        return bool(self.decision and self.decision.found_answer)

    @property
    def bm25_only_ids(self) -> set[str]:
        """Candidate ids the dense retriever did not return.

        The evidence that hybrid search is doing something dense-only could not.
        """
        dense_ids = {h.chunk_id for h in self.dense_hits}
        return {c.chunk_id for c in self.candidates} - dense_ids

    def cited_pages(self) -> dict[str, RetrievedChunk]:
        """Best-ranked candidate per page, for the one-URL citation rule (FR-17)."""
        best: dict[str, RetrievedChunk] = {}
        for candidate in self.candidates:
            best.setdefault(candidate.chunk.page_id, candidate)
        return best


class HybridSearcher:
    def __init__(
        self,
        settings: Settings | None = None,
        embedder: Embedder | None = None,
        *,
        dense: DenseRetriever | None = None,
        sparse: SparseRetriever | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedder = embedder or Embedder(self.settings.embedding_model)
        self.dense = dense or DenseRetriever(self.settings, self.embedder)
        self.sparse = sparse or SparseRetriever(self.settings, self.embedder)

    def retrieve(self, question: str) -> SearchResult:
        """Steps 1-5: route, retrieve, score, fuse. NO gate decision.

        Split out from `search()` because the gate is the one step that can
        legitimately refuse to produce an answer: with no calibrated threshold
        it raises `NotCalibratedError`. A caller that wants to inspect the
        candidates anyway - the CLI, calibration runs - needs the retrieval
        without re-embedding the question to get it. `search()` is exactly
        `retrieve()` followed by the gate.
        """
        match = explain(question)
        result = SearchResult(
            question=question,
            intent=match.intent,
            intent_match=match,
            performance_claim=is_performance_claim(question),
        )

        # 1-2. Route first. Opinion and out-of-scope never retrieve.
        if match.intent is not Intent.FACTUAL:
            log.info("intent=%s (%s); skipping retrieval", match.intent.value, match.rule)
            result.decision = gate_mod.decide_for_intent(
                match.intent, [], NO_DENSE_MATCH, settings=self.settings
            )
            return result

        # 3. Both legs, independently.
        dense_result = self.dense.search(question)
        result.raw_dense_max = dense_result.raw_dense_max
        result.dense_hits = dense_result.hits

        sparse_result = self.sparse.search(question)
        result.sparse_hits = sparse_result.hits
        result.sparse_available = sparse_result.available

        # 4. Resolve a TRUE dense score for hits only BM25 found. A fused list
        #    prints one dense score per candidate, and an invented 0.0 there would
        #    be read as "the dense retriever scored this 0.0" when in fact it
        #    never returned the chunk at all.
        dense_ids = {h.chunk_id for h in dense_result.hits}
        sparse_only = [h for h in sparse_result.hits if h.chunk_id not in dense_ids]
        if sparse_only:
            scores = self.dense.score_ids(
                dense_result.query_vector, [h.chunk_id for h in sparse_only]
            )
            # Hit is frozen, so the resolved scores go back in as a rebuilt list
            # rather than by assignment.
            resolved: list[Hit] = []
            for hit in sparse_result.hits:
                if hit.chunk_id in dense_ids:
                    resolved.append(hit)
                    continue
                score = scores.get(hit.chunk_id)
                if score is not None:
                    resolved.append(hit.with_dense(score))
                else:
                    log.warning(
                        "no stored vector for sparse-only hit %s; it will carry the "
                        "fail-closed -1.0 dense score",
                        hit.chunk_id,
                    )
                    resolved.append(hit)
            sparse_result.hits = resolved
            result.sparse_hits = resolved

        # 5. Fuse.
        result.candidates = fuse(
            dense_result.hits,
            sparse_result.hits,
            top_k=self.settings.top_k,
            k=self.settings.rrf_k,
            settings=self.settings,
        )

        result.threshold = self._threshold_or_none()
        return result

    def search(self, question: str) -> SearchResult:
        """Retrieve, then gate. Raises `NotCalibratedError` if uncalibrated."""
        result = self.retrieve(question)
        # 6. Gate, on the raw dense maximum captured in step 3. NOT recomputed
        #    from result.candidates - that is the exact bug the separate
        #    parameter exists to prevent.
        if result.intent is Intent.FACTUAL:
            result.decision = gate_mod.decide(
                result.candidates, result.raw_dense_max, settings=self.settings
            )
        return result

    def _threshold_or_none(self) -> float | None:
        try:
            return self.settings.require_similarity_threshold()
        except NotCalibratedError:
            return None
