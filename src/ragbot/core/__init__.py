"""Core contracts: config, models, errors, logging.

Everything here is deliberately dependency-light and side-effect free, so it
can be imported by any phase without triggering I/O.
"""

from .errors import (
    ChunkTooLongError,
    CorpusConfigError,
    EmbeddingDimMismatchError,
    EmptyPageError,
    MissingAPIKeyError,
    NotCalibratedError,
    PageFetchError,
    PIIDetected,
    ProviderError,
    RagbotError,
)
from .models import (
    Answer,
    Chunk,
    GateDecision,
    Intent,
    PageManifest,
    PageRecord,
    RetrievedChunk,
    count_sentences,
)

__all__ = [
    "Answer",
    "Chunk",
    "ChunkTooLongError",
    "CorpusConfigError",
    "EmbeddingDimMismatchError",
    "EmptyPageError",
    "GateDecision",
    "Intent",
    "MissingAPIKeyError",
    "NotCalibratedError",
    "PageFetchError",
    "PageManifest",
    "PageRecord",
    "PIIDetected",
    "ProviderError",
    "RagbotError",
    "RetrievedChunk",
    "count_sentences",
]
