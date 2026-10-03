"""Startup index bootstrap, and the refusal it used to masquerade as.

The bug these pin
-----------------
`data/chroma/` and `data/bm25.pkl` are gitignored build artifacts, so a deployed
process started with an empty collection. `DenseRetriever.search()` logged a
warning and returned the `NO_DENSE_MATCH` sentinel; the gate read that as "no
page resembles this question"; the orchestrator returned Refusal B. Every factual
question was refused with a confident "That is outside what I can answer" while
opinion, out-of-scope and source-list questions kept working, because those three
never read the index. Nothing had been searched, and the message claimed the
corpus had been searched and come up empty.

Two things therefore have to hold, and they are separate failures:

1. The index gets built at startup, from the committed `data/raw` HTML, offline.
2. If it cannot be built, that surfaces as a deployment error - never as a
   refusal, and never as a low similarity score.

A test that only covered (1) would pass while the app still answered "not in the
corpus" whenever the build failed, which is the case that matters.

The fake embedder is used throughout so the whole thing runs in-process in
seconds; these tests are about control flow, not about score magnitudes.
"""

from __future__ import annotations

import pytest

from src.ragbot.core.config import Settings, reset_settings_cache
from src.ragbot.core.errors import IndexUnavailableError, RagbotError
from src.ragbot.ingest import bootstrap
from src.ragbot.ingest.bootstrap import (
    ACTION_BUILT,
    ACTION_NONE,
    ensure_index,
    probe_index,
)
from src.ragbot.ingest.pipeline import IngestReport
from tests.fixtures import PAGE_HTML, corpus_yaml
from tests.fixtures.fake_embedder import FakeEmbedder


# The structural fixture cleans to well under 1500 chars, so the pipeline
# threshold is lowered to match. It must match on BOTH sides: load_corpus
# rejects drift, which is the point of that check.
FIXTURE_MIN_CHARS = 400


@pytest.fixture
def project(tmp_path):
    """An isolated project with raw HTML but deliberately NO index.

    This is the deployment's starting state: `data/raw` is committed, the
    derived index is not.
    """
    pages = {f"page-{i}": PAGE_HTML for i in range(3)}
    (tmp_path / "config").mkdir()
    (tmp_path / "raw").mkdir()
    (tmp_path / "config" / "corpus.yaml").write_text(
        corpus_yaml(list(pages), FIXTURE_MIN_CHARS), encoding="utf-8"
    )
    for pid, html in pages.items():
        (tmp_path / "raw" / f"{pid}.html").write_text(html, encoding="utf-8")

    reset_settings_cache()
    return Settings(
        _env_file=None,
        corpus_path=tmp_path / "config" / "corpus.yaml",
        raw_dir=tmp_path / "raw",
        chroma_path=tmp_path / "chroma",
        bm25_path=tmp_path / "bm25.pkl",
        manifest_path=tmp_path / "manifest.json",
        min_extract_chars=FIXTURE_MIN_CHARS,
    )


# --- the probe -----------------------------------------------------------


def test_probe_reports_both_artifacts_missing_in_a_fresh_clone(project: Settings):
    """A clone has the corpus HTML and none of the index. Say so precisely."""
    assert not project.chroma_dir.exists()
    assert not project.bm25_file.exists()

    missing = probe_index(project)

    assert len(missing) == 2
    assert any("chroma" in m for m in missing)
    assert any("bm25" in m for m in missing)


def test_probe_reports_nothing_once_both_artifacts_exist(project: Settings):
    ensure_index(project, embedder=FakeEmbedder())

    assert probe_index(project) == []


def test_probe_treats_a_zero_byte_bm25_pickle_as_missing(project: Settings):
    """A truncated file is not an index. Treating it as one is how a partial
    write becomes a confidently-wrong deployment."""
    project.chroma_dir.mkdir(parents=True)
    (project.chroma_dir / bootstrap.CHROMA_MARKER).write_bytes(b"sqlite")
    project.bm25_file.write_bytes(b"")

    assert any("bm25" in m for m in probe_index(project))


def test_probe_treats_an_empty_chroma_directory_as_missing(project: Settings):
    """`PersistentClient` creates the directory on a read, so the directory
    existing proves nothing. The sqlite file is the real marker."""
    project.chroma_dir.mkdir(parents=True)

    assert any("chroma" in m for m in probe_index(project))


def test_probe_costs_no_model_load(project: Settings, monkeypatch: pytest.MonkeyPatch):
    """The common path is two stat calls.

    If this ever started constructing an Embedder, every process start would pay
    a 90 MB model load to answer a question `stat` can answer - and on the local
    path, where the index already exists, that would be pure regression.
    """

    def explode(*a, **k):  # pragma: no cover - the assertion is the failure
        raise AssertionError("probe_index constructed an Embedder")

    monkeypatch.setattr(bootstrap, "Embedder", explode)
    monkeypatch.setattr(
        "src.ragbot.ingest.pipeline.Embedder", explode, raising=True
    )

    assert probe_index(project)  # returns without touching the embedder


# --- ensure_index: the happy paths ---------------------------------------


def test_ensure_index_builds_from_committed_raw_html(project: Settings):
    """The regression for the deployment bug: no index, so build one."""
    status = ensure_index(project, embedder=FakeEmbedder())

    assert status.action == ACTION_BUILT
    assert status.chunks > 0
    assert probe_index(project) == []
    assert project.chroma_dir.joinpath(bootstrap.CHROMA_MARKER).is_file()
    assert project.bm25_file.is_file()


def test_ensure_index_is_a_no_op_when_the_index_already_exists(
    project: Settings, monkeypatch: pytest.MonkeyPatch
):
    """Local behaviour must be untouched: an existing index means zero work.

    Asserted by making `run_ingest` explode rather than by checking a flag, so
    this fails if the fast path ever starts calling it.
    """
    ensure_index(project, embedder=FakeEmbedder())
    before = sorted(p.name for p in project.chroma_dir.iterdir())
    bm25_before = project.bm25_file.read_bytes()

    def explode(*a, **k):  # pragma: no cover - the assertion is the failure
        raise AssertionError("ensure_index re-ingested an existing index")

    monkeypatch.setattr(bootstrap, "run_ingest", explode)

    status = ensure_index(project, embedder=FakeEmbedder())

    assert status.action == ACTION_NONE
    assert "nothing to do" in status.summary()
    assert sorted(p.name for p in project.chroma_dir.iterdir()) == before
    assert project.bm25_file.read_bytes() == bm25_before


def test_ensure_index_is_idempotent_across_calls(project: Settings):
    """A restarted process must not rebuild a good index."""
    first = ensure_index(project, embedder=FakeEmbedder())
    second = ensure_index(project, embedder=FakeEmbedder())

    assert first.action == ACTION_BUILT
    assert second.action == ACTION_NONE


def test_ensure_index_does_not_reach_the_network(
    project: Settings, monkeypatch: pytest.MonkeyPatch
):
    """`data/raw` is committed, so the bootstrap must work offline.

    A deployment that cannot reach Groww still has the exact bytes its citations
    point at, so a fetch attempt here would turn a working deployment into a
    broken one whenever egress is restricted.
    """

    def explode(*a, **k):  # pragma: no cover - the assertion is the failure
        raise AssertionError("the bootstrap tried to fetch over the network")

    monkeypatch.setattr("src.ragbot.ingest.fetch.httpx.Client", explode)
    monkeypatch.setattr("src.ragbot.ingest.fetch._fetch_one", explode)

    assert ensure_index(project, embedder=FakeEmbedder()).action == ACTION_BUILT


# --- ensure_index: failure must be loud ----------------------------------


def test_an_ingest_exception_becomes_a_deployment_error(
    project: Settings, monkeypatch: pytest.MonkeyPatch
):
    def boom(*a, **k):
        raise RuntimeError("embedding model unavailable")

    monkeypatch.setattr(bootstrap, "run_ingest", boom)

    with pytest.raises(IndexUnavailableError) as excinfo:
        ensure_index(project, embedder=FakeEmbedder())

    assert "embedding model unavailable" in str(excinfo.value)


def test_a_per_page_failure_becomes_a_deployment_error(
    project: Settings, monkeypatch: pytest.MonkeyPatch
):
    """`run_ingest` deliberately reports per-page failures instead of raising.

    That is right for a CLI run, where you want the other four pages reported.
    It is wrong for a startup path, where a partial index must not be treated as
    a corpus. So the report is inspected here and turned into an error.
    """
    monkeypatch.setattr(
        bootstrap,
        "run_ingest",
        lambda *a, **k: IngestReport(
            pages=[], failures={"page-0": "EmptyPageError: too thin"}, total_chunks=0
        ),
    )

    with pytest.raises(IndexUnavailableError) as excinfo:
        ensure_index(project, embedder=FakeEmbedder())

    message = str(excinfo.value)
    assert "page-0" in message
    assert "EmptyPageError" in message


def test_a_zero_chunk_result_becomes_a_deployment_error(
    project: Settings, monkeypatch: pytest.MonkeyPatch
):
    """A clean run that stored nothing is still a broken deployment."""
    monkeypatch.setattr(
        bootstrap,
        "run_ingest",
        lambda *a, **k: IngestReport(pages=[], failures={}, total_chunks=0),
    )

    with pytest.raises(IndexUnavailableError) as excinfo:
        ensure_index(project, embedder=FakeEmbedder())

    assert "0 chunks" in str(excinfo.value)


def test_artifacts_still_missing_after_a_clean_run_is_an_error(
    project: Settings, monkeypatch: pytest.MonkeyPatch
):
    """The report is not proof.

    A run can report chunks written while the persist directory is read-only or
    mounted somewhere ephemeral. What matters is whether the files a later
    process will look for are on disk, so that is what gets re-checked.
    """
    monkeypatch.setattr(
        bootstrap,
        "run_ingest",
        lambda *a, **k: IngestReport(pages=[], failures={}, total_chunks=1193),
    )

    with pytest.raises(IndexUnavailableError) as excinfo:
        ensure_index(project, embedder=FakeEmbedder())

    assert "still absent" in str(excinfo.value)


def test_the_error_is_renderable_by_the_existing_ui_handler():
    """`_submit` catches `RagbotError` and shows `str(exc)`.

    So the deployment error reaches the user as readable text without any new UI
    code, and the app does not have to learn a second exception type.
    """
    error = IndexUnavailableError(
        "the Chroma collection is empty",
        remediation="Run `python -m src.ragbot.ingest`.",
    )

    assert isinstance(error, RagbotError)
    assert "Run `python -m src.ragbot.ingest`." in str(error)
    assert "deployment problem" in str(error)


def test_the_error_names_the_corpus_as_not_at_fault():
    """The message must not read like a refusal.

    "That is outside what I can answer" was the original defect: a deployment
    fault wearing the wording of a corpus limitation. The replacement has to say
    which of the two it is.
    """
    message = str(
        IndexUnavailableError(
            "the Chroma collection at /tmp/chroma is empty",
            remediation="Run ingest.",
        )
    )

    assert "not a question the corpus cannot answer" in message
    assert "outside what I can answer" not in message.lower()


# --- the silent-refusal fix in the retriever -----------------------------


def test_an_empty_collection_raises_instead_of_returning_a_refusal_shape(
    project: Settings,
):
    """The other half: retrieval itself must not launder an empty corpus.

    Bootstrap makes the empty state unlikely, but bootstrap can fail, be skipped
    or time out. This is the backstop that stops the failure from once again
    being reported to a person as "not in the corpus".
    """
    from src.ragbot.retrieval.dense import DenseRetriever

    project.chroma_dir.mkdir(parents=True, exist_ok=True)
    retriever = DenseRetriever(project, FakeEmbedder())

    with pytest.raises(IndexUnavailableError) as excinfo:
        retriever.search("What is the minimum SIP for HDFC ELSS?")

    message = str(excinfo.value)
    assert "empty" in message
    assert "python -m src.ragbot.ingest" in message


def test_a_fully_bootstrapped_project_can_retrieve(project: Settings):
    """End to end on the deployment's starting state.

    Before the fix this combination - intent is FACTUAL, no index present -
    produced Refusal B. Now the same starting state produces a populated index
    and real candidates, which is the whole point of the change.
    """
    from src.ragbot.retrieval.search import HybridSearcher

    ensure_index(project, embedder=FakeEmbedder())
    searcher = HybridSearcher(project)

    result = searcher.retrieve("What is the minimum investment amount?")

    assert result.candidates, "a bootstrapped index must return candidates"
    assert result.raw_dense_max > -1.0


# --- the committed manifest must not fake an index -----------------------


def test_a_manifest_without_a_store_still_embeds(project: Settings):
    """The deployment's exact starting state, at the ingest layer.

    `artifacts/manifest.json` is committed; `data/chroma/` is not. So a fresh
    deploy starts with a manifest claiming a full index and an empty store. The
    hash-skip trusted the manifest, decided all five pages were unchanged,
    embedded nothing, and reported a clean run - which is how a missing index
    could be "rebuilt" into still missing.

    Found by running the bootstrap against a real fresh clone, where this test's
    project shape is a faithful miniature.
    """
    # A manifest describing a complete index, with no store behind it.
    project.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    project.manifest_path.write_text(
        '{"pages": ['
        '{"page_id": "page-0", "scheme": "S", "category": "c", '
        '"source_url": "https://example.invalid/a", '
        '"fetched_at": "2026-01-01T00:00:00+00:00", "chunks": 3, '
        '"content_hash": "deadbeef"}'
        "]}",
        encoding="utf-8",
    )
    assert project.manifest_path.exists()
    assert not project.chroma_dir.exists()

    status = ensure_index(project, embedder=FakeEmbedder())

    assert status.action == ACTION_BUILT
    assert status.chunks > 0
    assert probe_index(project) == []


def test_idempotency_still_holds_once_a_store_exists(project: Settings):
    """The fix must not turn every ingest into a full re-embed.

    The hash-skip is the reason re-running ingest costs one parse per page. It
    only became conditional on the store holding the page, so with a real store
    present the second run must still skip every embed.
    """
    from src.ragbot.ingest.pipeline import run_ingest

    first = run_ingest(project, embedder=FakeEmbedder())
    assert first.embedded_pages, "first run must embed"

    second = run_ingest(project, embedder=FakeEmbedder())

    assert second.embedded_pages == [], "second run must not re-embed"
    assert sorted(second.skipped) == sorted(first.embedded_pages)
    assert second.total_chunks == first.total_chunks