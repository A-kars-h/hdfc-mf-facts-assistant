"""End-to-end ingestion: idempotency, provenance, failure handling.

Uses the fake embedder so the whole pipeline runs in-process in seconds. The
real model is covered in `test_embedder_gate.py`; re-embedding 1,200 chunks per
assertion would make this file too slow to run before every change.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.ragbot.core.config import Settings, reset_settings_cache
from src.ragbot.ingest.pipeline import run_ingest
from tests.fixtures import PAGE_HTML, THIN_HTML, corpus_yaml
from tests.fixtures.fake_embedder import FakeEmbedder


# The structural fixture cleans to well under 1500 chars, so the pipeline
# threshold is lowered to match. It must match on BOTH sides: load_corpus
# rejects drift, which is the point of that check.
FIXTURE_MIN_CHARS = 400

# Used for the FR-2 test, where the point is that a real threshold rejects a
# genuinely thin page.
REAL_MIN_CHARS = 1500

# Sits between THIN_HTML (95 chars) and PAGE_HTML (733 chars) so one page passes
# and one fails - the actual distinction the FR-2 test needs to make.
SPLIT_MIN_CHARS = 500


def _project(tmp_path, pages: dict[str, str], page_ids: list[str],
             min_extract_chars: int = FIXTURE_MIN_CHARS):
    """Build an isolated project: config, raw HTML, and settings pointing at it."""
    (tmp_path / "config").mkdir()
    (tmp_path / "raw").mkdir()
    (tmp_path / "config" / "corpus.yaml").write_text(
        corpus_yaml(page_ids, min_extract_chars), encoding="utf-8"
    )
    for pid, html in pages.items():
        (tmp_path / "raw" / f"{pid}.html").write_text(html, encoding="utf-8")

    reset_settings_cache()
    settings = Settings(
        _env_file=None,
        corpus_path=tmp_path / "config" / "corpus.yaml",
        raw_dir=tmp_path / "raw",
        chroma_path=tmp_path / "chroma",
        bm25_path=tmp_path / "bm25.pkl",
        manifest_path=tmp_path / "manifest.json",
        min_extract_chars=min_extract_chars,
    )
    return settings


@pytest.fixture
def three_pages(tmp_path):
    pages = {f"page-{i}": PAGE_HTML for i in range(3)}
    return _project(tmp_path, pages, list(pages))


# --- idempotency (Done-when) -------------------------------------------


def test_double_run_leaves_chunk_count_identical(three_pages, tmp_path):
    first = run_ingest(three_pages, embedder=FakeEmbedder())
    assert first.ok
    assert first.total_chunks > 0

    second = run_ingest(three_pages, embedder=FakeEmbedder())
    assert second.ok
    assert second.total_chunks == first.total_chunks
    assert second.skipped == ["page-0", "page-1", "page-2"]
    assert second.embedded_pages == []


def test_second_run_makes_no_embed_calls(three_pages):
    """Hash-skip exists so a re-run does not re-embed the corpus."""
    embedder = FakeEmbedder()
    run_ingest(three_pages, embedder=embedder)
    calls_after_first = embedder.embed_calls

    run_ingest(three_pages, embedder=embedder)
    assert embedder.embed_calls == calls_after_first, "unchanged pages were re-embedded"


def test_no_duplicate_chunk_ids(three_pages):
    from src.ragbot.ingest.writer import Writer

    run_ingest(three_pages, embedder=FakeEmbedder())
    run_ingest(three_pages, embedder=FakeEmbedder())

    writer = Writer(three_pages, FakeEmbedder())
    rows = writer.all_chunks()
    ids = [r["chunk_id"] for r in rows]
    assert len(ids) == len(set(ids))


def test_changed_page_is_replaced_not_appended(tmp_path):
    """Stale chunks from an older version of the text must not survive: they
    would keep answering questions about facts that no longer exist."""
    pages = {"page-0": PAGE_HTML}
    settings = _project(tmp_path, pages, ["page-0"])
    first = run_ingest(settings, embedder=FakeEmbedder())
    baseline = first.total_chunks

    (tmp_path / "raw" / "page-0.html").write_text(
        PAGE_HTML.replace("0.77%", "0.99%"), encoding="utf-8"
    )
    second = run_ingest(settings, embedder=FakeEmbedder())

    assert "page-0" in second.embedded_pages
    assert second.total_chunks == baseline, "replaced, not appended"

    from src.ragbot.ingest.writer import Writer

    texts = [r["text"] for r in Writer(settings, FakeEmbedder()).all_chunks()]
    assert any("0.99%" in t for t in texts)
    assert not any("0.77%" in t for t in texts)


def test_removed_page_is_purged(tmp_path):
    settings = _project(tmp_path, {"page-0": PAGE_HTML, "page-1": PAGE_HTML},
                        ["page-0", "page-1"])
    assert run_ingest(settings, embedder=FakeEmbedder()).total_chunks > 0

    # Drop page-1 from the corpus but leave its HTML on disk.
    (tmp_path / "config" / "corpus.yaml").write_text(
        corpus_yaml(["page-0"], FIXTURE_MIN_CHARS), encoding="utf-8"
    )
    report = run_ingest(settings, embedder=FakeEmbedder())

    from src.ragbot.ingest.writer import Writer

    assert Writer(settings, FakeEmbedder()).all_page_ids() == {"page-0"}


# --- provenance (Done-when) --------------------------------------------


def test_every_stored_chunk_has_correct_provenance(three_pages):
    from src.ragbot.ingest.writer import Writer

    run_ingest(three_pages, embedder=FakeEmbedder())
    rows = Writer(three_pages, FakeEmbedder()).all_chunks()
    assert rows

    for row in rows:
        meta = row["meta"]
        pid = meta["page_id"]
        assert pid == "page-0" or pid in ("page-1", "page-2")
        assert meta["source_url"] == f"https://groww.in/mutual-funds/{pid}"
        assert meta["scheme"]
        assert meta["category"] == "Flexi Cap"
        # fetched_at must be per-page and parseable, not a global stamp.
        assert datetime.fromisoformat(meta["fetched_at"]).tzinfo is not None
        assert meta["char_end"] >= meta["char_start"]
        assert meta["content_hash"]


def test_manifest_records_embedding_dim_and_model(three_pages, tmp_path):
    run_ingest(three_pages, embedder=FakeEmbedder())
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["embedding_dim"] == 384
    assert manifest["embedding_model"]
    assert manifest["chunk_size"] == 200
    assert manifest["chunk_overlap"] == 40
    assert manifest["totals"]["pages"] == 3
    assert manifest["totals"]["chunks"] > 0
    assert len(manifest["pages"]) == 3
    for page in manifest["pages"]:
        assert page["content_hash"]
        assert page["fetched_at"]


def test_manifest_is_valid_against_the_model(three_pages, tmp_path):
    from src.ragbot.core.models import PageManifest

    run_ingest(three_pages, embedder=FakeEmbedder())
    manifest = PageManifest.model_validate_json(
        (tmp_path / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.embedding_dim == 384
    assert manifest.total_chunks > 0


def test_fetched_at_is_per_page_not_global(tmp_path):
    """A global timestamp makes 'Last updated from sources:' untrue."""
    import os
    import time

    settings = _project(tmp_path, {"page-0": PAGE_HTML, "page-1": PAGE_HTML},
                        ["page-0", "page-1"])
    # Age page-0's file so the two pages genuinely differ.
    old = time.time() - 86_400 * 3
    os.utime(tmp_path / "raw" / "page-0.html", (old, old))

    report = run_ingest(settings, embedder=FakeEmbedder())
    by_id = {p.page_id: p.fetched_at for p in report.pages}
    assert by_id["page-0"] < by_id["page-1"]
    assert (by_id["page-1"] - by_id["page-0"]).days >= 2


# --- failure handling ---------------------------------------------------


def test_thin_page_fails_the_run_but_others_still_report(tmp_path):
    pages = {"page-0": PAGE_HTML, "page-thin": THIN_HTML}
    settings = _project(tmp_path, pages, ["page-0", "page-thin"], SPLIT_MIN_CHARS)

    report = run_ingest(settings, embedder=FakeEmbedder())
    assert not report.ok
    assert "page-thin" in report.failures
    assert "EmptyPageError" in report.failures["page-thin"]
    assert "page-0" in [p.page_id for p in report.pages]
    # The message must name the threshold that was actually applied, so an
    # operator can tell a threshold problem from a fetch problem.
    assert str(SPLIT_MIN_CHARS) in report.failures["page-thin"]


def test_failed_page_is_not_written_to_the_index(tmp_path):
    pages = {"page-0": PAGE_HTML, "page-thin": THIN_HTML}
    settings = _project(tmp_path, pages, ["page-0", "page-thin"], SPLIT_MIN_CHARS)
    run_ingest(settings, embedder=FakeEmbedder())

    from src.ragbot.ingest.writer import Writer

    assert Writer(settings, FakeEmbedder()).all_page_ids() == {"page-0"}


def test_oversized_chunk_fails_the_ingest(tmp_path):
    """The truncation gate must abort the build, not truncate.

    Verified end-to-end: a page whose blocks cannot be reduced below the
    embedder ceiling raises, and the page is reported as failed.
    """
    settings = _project(tmp_path, {"page-0": PAGE_HTML}, ["page-0"])
    tiny_ceiling = FakeEmbedder(max_seq_length=12)
    report = run_ingest(settings, embedder=tiny_ceiling)
    assert not report.ok
    assert "page-0" in report.failures


def test_empty_corpus_is_rejected(tmp_path):
    from src.ragbot.core.errors import CorpusConfigError

    (tmp_path / "config").mkdir()
    (tmp_path / "raw").mkdir()
    (tmp_path / "config" / "corpus.yaml").write_text("amc: X\npages: []\n", encoding="utf-8")
    reset_settings_cache()
    settings = Settings(
        _env_file=None,
        corpus_path=tmp_path / "config" / "corpus.yaml",
        raw_dir=tmp_path / "raw",
        chroma_path=tmp_path / "chroma",
        bm25_path=tmp_path / "bm25.pkl",
        manifest_path=tmp_path / "manifest.json",
    )
    with pytest.raises(CorpusConfigError, match="no 'pages'"):
        run_ingest(settings, embedder=FakeEmbedder())


# --- indexes ------------------------------------------------------------


def test_bm25_index_is_written_and_covers_every_chunk(three_pages, tmp_path):
    run_ingest(three_pages, embedder=FakeEmbedder())
    payload = (tmp_path / "bm25.pkl").read_bytes()
    assert payload

    import pickle

    from src.ragbot.ingest.writer import Writer

    data = pickle.loads(payload)
    assert data["tokenizer"] == "ragbot.v1"
    assert len(data["chunk_ids"]) == Writer(three_pages, FakeEmbedder()).count()


def test_bm25_survives_a_skipped_run(three_pages, tmp_path):
    """BM25 must cover skipped pages too, or sparse search silently goes stale."""
    import pickle

    run_ingest(three_pages, embedder=FakeEmbedder())
    first = len(pickle.loads((tmp_path / "bm25.pkl").read_bytes())["chunk_ids"])
    run_ingest(three_pages, embedder=FakeEmbedder())
    second = len(pickle.loads((tmp_path / "bm25.pkl").read_bytes())["chunk_ids"])
    assert first == second > 0


def test_reindex_forces_reembedding(three_pages):
    embedder = FakeEmbedder()
    run_ingest(three_pages, embedder=embedder)
    before = embedder.embed_calls
    report = run_ingest(three_pages, embedder=embedder, reindex=True)
    assert report.embedded_pages == ["page-0", "page-1", "page-2"]
    assert embedder.embed_calls > before
