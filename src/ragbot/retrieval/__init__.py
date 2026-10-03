"""Phase 3: intent, hybrid retrieval, fusion, and the confidence gate.

No LLM runs here. The output of this package is a ranked, gated candidate set
plus the intent that produced it - which is everything Phase 4 needs to decide
whether to answer, refuse with an educational link, or refuse as out of corpus.
"""

from .dense import NO_DENSE_MATCH, DenseRetriever, DenseResult, cosine_similarity_from_distance
from .fusion import RRF_K, fuse, rrf_score
from .gate import decide, decide_for_intent
from .hits import Hit, hydrate
from .intent import Intent, IntentMatch, classify, explain, is_performance_claim
from .search import HybridSearcher, SearchResult
from .sparse import SparseIndexError, SparseRetriever, SparseResult

__all__ = [
    "classify",
    "explain",
    "is_performance_claim",
    "Intent",
    "IntentMatch",
    "DenseRetriever",
    "DenseResult",
    "cosine_similarity_from_distance",
    "NO_DENSE_MATCH",
    "SparseRetriever",
    "SparseResult",
    "SparseIndexError",
    "fuse",
    "rrf_score",
    "RRF_K",
    "decide",
    "decide_for_intent",
    "Hit",
    "hydrate",
    "HybridSearcher",
    "SearchResult",
]
