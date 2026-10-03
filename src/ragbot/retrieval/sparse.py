"""Sparse (BM25) retrieval over the persisted index.

BM25 is not a luxury here. The corpus is numeric facts, and the questions are
numeric lookups: "0.77%", "Rs. 500", "1.21%". Dense retrieval embeds those into
a 384-dim space where a percentage is a direction, not a value, so a question
asking for one specific figure often retrieves a page section that merely looks
topically similar. BM25 matches the literal token, which is what a factual lookup
needs.

The index is a pickle rebuilt by `python -m src.ragbot.ingest`. It is validated
here on two axes that fail silently otherwise:

1. Tokenizer version. A pickle tokenised by a different tokenizer is still a
   valid BM25 object; it just answers queries with the wrong vocabulary.
2. Chunk-id drift. If BM25 knows an id the store no longer has, that chunk is
   dropped with a warning rather than surfacing as a citation to nothing.
"""

from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass, field

from ..core.config import Settings, get_settings
from ..core.errors import RagbotError
from ..core.text import TOKENIZER_VERSION, tokenize
from ..core.models import Chunk
from ..ingest.embedder import Embedder
from .hits import Hit, hydrate

log = logging.getLogger(__name__)


class SparseIndexError(RagbotError):
    """The persisted BM25 index is missing, unreadable, or incompatible."""


@dataclass
class SparseResult:
    hits: list[Hit] = field(default_factory=list)
    available: bool = True


class SparseRetriever:
    def __init__(
        self,
        settings: Settings | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        # Held only to hand to Writer for store access. Without it, Writer builds
        # its own Embedder and the 90MB model is loaded a second time per process.
        self.embedder = embedder
        self._payload: dict | None = None
        self._loaded = False

    @property
    def payload(self) -> dict:
        if not self._loaded:
            self._payload = self._load()
            self._loaded = True
        return self._payload or {}

    def _load(self) -> dict | None:
        path = self.settings.bm25_file
        if not path.exists():
            log.warning("no BM25 index at %s; run `python -m src.ragbot.ingest`", path)
            return None
        try:
            with path.open("rb") as fh:
                data = pickle.load(fh)
        except Exception as exc:  # noqa: BLE001
            raise SparseIndexError(
                f"could not read the BM25 index at {path}: {exc}. Rebuild it with "
                f"`python -m src.ragbot.ingest --reindex`."
            ) from exc

        version = data.get("tokenizer")
        if version != TOKENIZER_VERSION:
            raise SparseIndexError(
                f"the BM25 index at {path} was built with tokenizer {version!r} but "
                f"this build uses {TOKENIZER_VERSION!r}. Querying it would return "
                f"quietly wrong rankings, so refuse. Rebuild with "
                f"`python -m src.ragbot.ingest --reindex`."
            )
        return data

    def available(self) -> bool:
        return bool(self.payload)

    def _hydrate_chunks(self) -> dict[str, Chunk]:
        """Chunk id -> Chunk, for the ids the sparse index knows about.

        Metadata lives in Chroma, not the pickle, so there is one source of truth
        for provenance. Ids present in the pickle but absent from the store are
        stale and are reported rather than silently ignored.
        """
        from ..ingest.writer import Writer

        payload = self.payload
        if not payload:
            return {}
        wanted = list(payload.get("chunk_ids") or [])
        collection = Writer(self.settings, self.embedder).collection
        if collection.count() == 0:
            return {}

        got = collection.get(ids=wanted, include=["documents", "metadatas"])
        ids = got.get("ids") or []
        docs = got.get("documents") or []
        metas = got.get("metadatas") or []

        out: dict[str, Chunk] = {}
        for i, chunk_id in enumerate(ids):
            meta = metas[i] if i < len(metas) else None
            if not meta:
                continue
            try:
                out[str(chunk_id)] = hydrate(
                    str(chunk_id), str(docs[i] or ""), dict(meta)
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("skipping unhydratable chunk %s: %s", chunk_id, exc)
                continue

        missing = set(wanted) - set(out)
        if missing:
            log.warning(
                "BM25 index knows %d chunk(s) absent from the store; dropping them",
                len(missing),
            )
        return out

    def search(self, question: str, *, top_n: int | None = None) -> SparseResult:
        """Top-N BM25 matches, with raw BM25 scores.

        A score of exactly 0.0 means the query shared no token with the chunk, so
        those rows are dropped: BM25 returns every document with a zero score
        otherwise, and "0.0 matches" in the CLI output would be noise.
        """
        payload = self.payload
        if not payload:
            return SparseResult([], available=False)

        n = top_n or self.settings.bm25_top_n
        scores = payload["bm25"].get_scores(tokenize(question))
        chunk_ids = payload.get("chunk_ids") or []

        # get_scores returns one score per document, in index order.
        scored = [(float(s), cid) for s, cid in zip(scores, chunk_ids) if float(s) > 0.0]
        if not scored:
            return SparseResult([], available=True)
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = scored[:n]

        store = self._hydrate_chunks()
        hits: list[Hit] = []
        for rank, (score, chunk_id) in enumerate(top, start=1):
            chunk = store.get(chunk_id)
            if chunk is None:
                continue
            hits.append(Hit(chunk=chunk, sparse_score=score, sparse_rank=rank))
        return SparseResult(hits, available=True)
