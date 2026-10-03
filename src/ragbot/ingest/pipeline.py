"""Ingestion pipeline: raw HTML -> cleaned blocks -> chunks -> indexes.

The orchestration lives here rather than in `__main__.py` so tests can run the
whole thing in-process, and so a failure in one page is reported per page rather
than collapsing the run (FR-2 says a thin page is a hard failure, not a warning
to be swallowed - but the other four pages should still be reported).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from ..core.config import Settings, get_settings, load_corpus
from ..core.errors import EmptyPageError
from ..core.models import Chunk, PageRecord
from .chunker import chunk_page, summarise
from .clean import check_not_empty, parse_file
from .embedder import Embedder
from .fetch import ensure_raw_pages
from .writer import Writer

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    pages: list[PageRecord] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    embedded_pages: list[str] = field(default_factory=list)
    total_chunks: int = 0
    stats: dict[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failures


def run_ingest(
    settings: Settings | None = None,
    *,
    refresh: bool = False,
    reindex: bool = False,
    embedder: Embedder | None = None,
) -> IngestReport:
    """Build or update the index. Idempotent."""
    settings = settings or get_settings()
    corpus = load_corpus(settings)
    pages = corpus["pages"]
    report = IngestReport()

    raw = ensure_raw_pages(pages, settings, refresh=refresh)
    raw_by_id = {r.page_id: r for r in raw}

    embedder = embedder or Embedder(settings.embedding_model)
    writer = Writer(settings, embedder)
    writer.check_dim()  # fail fast on a model change

    previous = None if reindex else writer.read_manifest()
    previous_by_page = (
        {p.page_id: p for p in previous.pages} if previous else {}
    )

    all_chunks: dict[str, list[Chunk]] = {}

    for page in pages:
        page_id = str(page["page_id"])
        try:
            parsed = parse_file(
                raw_by_id[page_id].path,
                page_id=page_id,
                scheme=str(page["scheme"]),
                category=str(page["category"]),
                source_url=str(page["source_url"]),
                fetched_at=raw_by_id[page_id].fetched_at,
            )
            check_not_empty(parsed, settings.min_extract_chars)

            content_hash = parsed.content_hash
            prior = previous_by_page.get(page_id)
            unchanged = (
                prior is not None
                and prior.content_hash == content_hash
                and not reindex
            )

            if unchanged:
                # No embed call at all. This is the whole point of hashing the
                # cleaned text: a re-run must not re-embed the corpus.
                report.skipped.append(page_id)
                stored = [c for c in writer.all_chunks() if c["meta"].get("page_id") == page_id]
                log.info("page %s unchanged; skipping embed (chunks=%d)", page_id, len(stored))
                all_chunks[page_id] = []
                report.pages.append(
                    PageRecord(
                        page_id=page_id,
                        scheme=str(page["scheme"]),
                        category=str(page["category"]),
                        source_url=str(page["source_url"]),
                        fetched_at=parsed.fetched_at,
                        chunks=prior.chunks,
                        content_hash=content_hash,
                    )
                )
                continue

            chunks = chunk_page(
                parsed,
                size=settings.chunk_size,
                overlap=settings.chunk_overlap,
                tokenizer=embedder.tokenizer,
                scheme=str(page["scheme"]),
                drop_return_heavy=settings.drop_return_only_chunks,
            )
            if not chunks:
                raise EmptyPageError(page_id, 0, settings.min_extract_chars)

            # Replace this page's chunks, never append: stale chunks from a
            # previous version of the text would keep answering questions.
            writer.delete_page(page_id)
            writer.add_chunks(chunks)

            all_chunks[page_id] = chunks
            report.embedded_pages.append(page_id)
            stats = summarise(chunks)
            report.pages.append(
                PageRecord(
                    page_id=page_id,
                    scheme=str(page["scheme"]),
                    category=str(page["category"]),
                    source_url=str(page["source_url"]),
                    fetched_at=parsed.fetched_at,
                    chunks=len(chunks),
                    content_hash=content_hash,
                )
            )
            log.info(
                "page %s embedded chunks=%d mean_tokens=%s return_heavy=%d",
                page_id, stats["chunks"], stats["mean_tokens"], stats["return_heavy"],
            )

        except Exception as exc:  # noqa: BLE001 - reported per page, not swallowed
            report.failures[page_id] = f"{type(exc).__name__}: {exc}"
            log.error("page %s FAILED: %s", page_id, exc)
    # Purge pages removed from corpus.yaml, so the index cannot answer for a
    # scheme the corpus no longer claims to cover.
    known = {str(p["page_id"]) for p in pages}
    orphans = writer.all_page_ids() - known
    for orphan in sorted(orphans):
        writer.delete_page(orphan)
        log.warning("purged orphan page %s (no longer in corpus.yaml)", orphan)

    # Rebuild BM25 over everything now in the store.
    final_chunks: list[Chunk] = []
    for record in report.pages:
        if record.page_id in all_chunks and all_chunks[record.page_id]:
            final_chunks.extend(all_chunks[record.page_id])
    if len(final_chunks) < len(report.pages):
        final_chunks = _chunks_from_store(writer, known)

    writer.build_bm25(final_chunks)

    report.total_chunks = writer.count()
    report.stats = {
        "return_heavy": sum(
            1 for c in final_chunks if c.return_heavy
        ),
        "mean_tokens": (
            round(sum(c.token_count for c in final_chunks) / len(final_chunks), 1)
            if final_chunks
            else 0
        ),
        "max_tokens": max((c.token_count for c in final_chunks), default=0),
    }

    # The manifest MUST be written on every run, including runs where every page
    # was skipped: it is the idempotency key for the *next* run. Omitting this
    # means the following run finds no manifest, re-embeds the entire corpus,
    # and the hash-skip never engages at all.
    writer.write_manifest(
        report.pages,
        totals={
            "pages": len(report.pages),
            "chunks": report.total_chunks,
            "failed": len(report.failures),
            "skipped": len(report.skipped),
        },
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    return report


def _chunks_from_store(writer: Writer, page_ids: set[str]) -> list[Chunk]:
    """Reconstruct Chunk objects from the store, for pages skipped as unchanged.

    Needed because BM25 must cover the whole corpus, not just the pages that
    happened to change in this run.
    """
    out: list[Chunk] = []
    for row in writer.all_chunks():
        if row["meta"].get("page_id") not in page_ids:
            continue
        m = row["meta"]
        try:
            out.append(
                Chunk(
                    chunk_id=row["chunk_id"],
                    page_id=str(m["page_id"]),
                    scheme=str(m["scheme"]),
                    category=str(m["category"]),
                    source_url=str(m["source_url"]),
                    fetched_at=datetime.fromisoformat(str(m["fetched_at"])),
                    text=row["text"],
                    token_count=int(m.get("token_count", 0)),
                    content_hash=str(m.get("content_hash", "")),
                    section=m.get("section") or None,
                    char_start=int(m.get("char_start", 0)),
                    char_end=int(m.get("char_end", 0)),
                    return_heavy=bool(m.get("return_heavy", False)),
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("skipping unreadable stored chunk %s: %s", row["chunk_id"], exc)
    return out

