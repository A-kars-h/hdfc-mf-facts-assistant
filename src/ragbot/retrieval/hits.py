"""Pre-fusion candidate types.

`RetrievedChunk` (core.models) is deliberately post-fusion: it requires a
`fused_rank`. Dense and sparse retrieval both run BEFORE fusion, so neither can
honestly produce one. Fabricating a rank at retrieval time - dense hits are
"ranked 1..n" too - would blur exactly the distinction the contract draws, so
pre-fusion candidates use `Hit` instead.

`Hit.dense_score` is Optional because a BM25-only hit has no cosine score yet.
It is NOT filled with a sentinel like 0.0: a fabricated 0.0 is
indistinguishable from a real poor match, and the CLI prints these numbers for a
human to read. `search.py` resolves the true score for sparse-only hits before
fusion, so every value that reaches the gate is real.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..core.models import Chunk


@dataclass(frozen=True)
class Hit:
    """One candidate, pre-fusion, from either retriever."""

    chunk: Chunk
    dense_score: float | None = None
    sparse_score: float | None = None
    dense_rank: int | None = None
    sparse_rank: int | None = None

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id

    def with_dense(self, score: float, rank: int | None = None) -> Hit:
        return replace(self, dense_score=score, dense_rank=rank)


def parse_timestamp(value) -> datetime:
    """Parse an ISO-8601 timestamp on Python 3.10.

    `datetime.fromisoformat` only learned to accept a trailing 'Z' in 3.11. On
    the 3.10 interpreter this project targets, '...Z' raises ValueError even
    though it is perfectly valid ISO-8601 and is what most HTTP producers emit.
    Values written by this project carry '+00:00' and parse directly, so the
    swap is a no-op for them and a rescue for everything else.
    """
    from datetime import datetime

    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def hydrate(chunk_id: str, text: str, meta: dict) -> Chunk:
    """Rebuild a `Chunk` from a Chroma row.

    Chroma metadata is lossy: it stores scalars only, so `fetched_at` comes back
    as an ISO string and absent values as empty strings. Reconstructing the real
    model here means the rest of the phase works against `Chunk` - which
    validates its own source_url - instead of against raw dicts.
    """
    from datetime import datetime

    return Chunk(
        chunk_id=str(chunk_id),
        page_id=str(meta.get("page_id", "")),
        scheme=str(meta.get("scheme", "")),
        category=str(meta.get("category", "")),
        source_url=str(meta.get("source_url", "")),
        fetched_at=parse_timestamp(meta["fetched_at"]),
        text=str(text),
        token_count=int(meta.get("token_count", 0) or 0),
        content_hash=str(meta.get("content_hash", "")),
        section=str(meta.get("section") or "") or None,
        char_start=int(meta.get("char_start", 0) or 0),
        char_end=int(meta.get("char_end", 0) or 0),
        return_heavy=bool(meta.get("return_heavy", False)),
    )
