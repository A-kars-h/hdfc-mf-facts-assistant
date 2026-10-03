"""Persist chunks to ChromaDB and BM25, and write the manifest.

Idempotency is keyed on `sha256(cleaned_text)` per page (Phase 2 spec). An
unchanged page is skipped with no embed call at all, so a normal re-run costs
one parse per page and nothing else. Without that, every run re-embeds the whole
corpus - slow enough that people stop running it, and the index silently rots
between demo rehearsals.

The manifest is the contract with the UI: it carries `embedding_model` and
`embedding_dim` so a model change is DETECTED rather than degrading retrieval
into near-noise that looks like "RAG doesn't work".
"""

from __future__ import annotations

import logging
import pickle
from datetime import datetime, timezone

from ..core.config import Settings, get_settings
from ..core.errors import EmbeddingDimMismatchError
from ..core.models import Chunk, PageManifest, PageRecord
from .embedder import Embedder

log = logging.getLogger(__name__)

COLLECTION = "mf_faq"  # not "course_faqs"


class Writer:
    def __init__(self, settings: Settings | None = None, embedder: Embedder | None = None):
        self.settings = settings or get_settings()
        self.embedder = embedder or Embedder(self.settings.embedding_model)
        self._client = None
        self._collection = None

    # --- chroma ---

    @property
    def collection(self):
        if self._collection is None:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            self.settings.chroma_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(self.settings.chroma_dir),
                settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
            )
            self._collection = self._client.get_or_create_collection(
                name=COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def stored_dim(self) -> int | None:
        """Dimension of the existing index, or None if the index is new."""
        try:
            existing = self._client.get_collection(COLLECTION)
        except Exception:
            return None
        count = existing.count()
        if count == 0:
            return None
        sample = existing.peek(limit=1)
        vector = (sample or {}).get("embeddings")
        if vector is None or len(vector) == 0:
            return None
        return len(vector[0])

    def check_dim(self) -> None:
        stored = self.stored_dim()
        if stored is not None and stored != self.embedder.dim:
            raise EmbeddingDimMismatchError(stored, self.embedder.dim)

    def delete_page(self, page_id: str) -> None:
        self.collection.delete(where={"page_id": page_id})

    def add_chunks(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        vectors = self.embedder.embed(
            [c.text for c in chunks], labels=[c.chunk_id for c in chunks]
        )
        self.collection.upsert(
            ids=[c.chunk_id for c in chunks],
            embeddings=vectors,
            documents=[c.text for c in chunks],
            metadatas=[
                {
                    "page_id": c.page_id,
                    "scheme": c.scheme,
                    "category": c.category,
                    "source_url": c.source_url,
                    "fetched_at": c.fetched_at.isoformat(),
                    "section": c.section or "",
                    "token_count": int(c.token_count),
                    "content_hash": c.content_hash,
                    "char_start": int(c.char_start),
                    "char_end": int(c.char_end),
                    "return_heavy": bool(c.return_heavy),
                }
                for c in chunks
            ],
        )

    def count(self) -> int:
        return self.collection.count()

    def all_page_ids(self) -> set[str]:
        """Page ids currently present in the index, for orphan purging."""
        got = self.collection.get(include=["metadatas"])
        metadatas = got.get("metadatas") or []
        return {str(m["page_id"]) for m in metadatas if m and m.get("page_id")}

    def all_chunks(self) -> list[dict]:
        """Every stored chunk, for rebuilding BM25 and the manifest."""
        got = self.collection.get(include=["documents", "metadatas"])
        ids = got.get("ids") or []
        docs = got.get("documents") or []
        metas = got.get("metadatas") or []
        out: list[dict] = []
        for i, chunk_id in enumerate(ids):
            meta = metas[i] if i < len(metas) else {}
            doc = docs[i] if i < len(docs) else ""
            if not meta:
                continue
            out.append({"chunk_id": str(chunk_id), "text": str(doc), "meta": dict(meta)})
        return out

    # --- bm25 ---

    def build_bm25(self, chunks: list[Chunk]) -> None:
        """Persist a BM25 index over every chunk in the store.

        Rebuilt from scratch each run: it is milliseconds of work, and a stale
        sparse index is far more expensive to debug than to recreate.
        """
        from rank_bm25 import BM25Okapi

        from ..core.text import TOKENIZER_VERSION, tokenize

        corpus = [c.text for c in chunks]
        if not corpus:
            log.warning("no chunks; skipping BM25 build")
            return

        # The tokenizer is imported from core.text, NOT defined here. The pickle
        # built below is read back by retrieval/sparse.py, and two copies of this
        # regex are two chances to query a differently-tokenised index and get
        # quietly wrong rankings.
        tokenised = [tokenize(t) for t in corpus]
        self.settings.bm25_file.parent.mkdir(parents=True, exist_ok=True)
        with self.settings.bm25_file.open("wb") as fh:
            pickle.dump(
                {
                    "bm25": BM25Okapi(tokenised),
                    "chunk_ids": [c.chunk_id for c in chunks],
                    "texts": corpus,
                    "tokenizer": TOKENIZER_VERSION,
                },
                fh,
            )
        log.info("bm25 index written chunks=%d path=%s", len(chunks), self.settings.bm25_file)

    def load_bm25(self) -> dict | None:
        if not self.settings.bm25_file.exists():
            return None
        with self.settings.bm25_file.open("rb") as fh:
            return pickle.load(fh)

    # --- manifest ---

    def read_manifest(self) -> PageManifest | None:
        path = self.settings.manifest_file
        if not path.exists():
            return None
        try:
            return PageManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.warning("manifest unreadable (%s); treating as absent", exc)
            return None

    def write_manifest(
        self,
        records: list[PageRecord],
        *,
        totals: dict[str, int],
        chunk_size: int,
        chunk_overlap: int,
    ) -> PageManifest:
        manifest = PageManifest(
            generated_at=datetime.now(timezone.utc),
            amc="HDFC Asset Management",
            embedding_model=self.settings.embedding_model,
            embedding_dim=self.embedder.dim,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            pages=records,
            totals=totals,
        )
        path = self.settings.manifest_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        log.info("manifest written path=%s pages=%d chunks=%d",
                 path, len(records), manifest.total_chunks)
        return manifest
