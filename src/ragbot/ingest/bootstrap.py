"""Build the retrieval index at startup when it is not already there.

Why this exists
---------------
`data/chroma/` and `data/bm25.pkl` are gitignored - correctly, because they are
derived artifacts and a committed index is a 20 MB diff that rots. But that
decision has a consequence nobody wrote down: **a clone of this repository has no
index at all**, only the committed `data/raw/*.html` it is built from.

That is fine for a laptop, where `make ingest` is step 2 of the documented
setup. It is not fine for a deployed app, which runs `streamlit run` and nothing
else. The deployed process therefore started with an empty Chroma collection,
retrieval returned the `NO_DENSE_MATCH` sentinel, the gate read that as "no page
resembles this question", and every factual question was refused with the
out-of-corpus message - while opinion, out-of-scope and source-list questions
kept behaving correctly, because those three never touch the index. The app
looked alive and was answering nothing.

So the deployment needs the setup step the README already documents, run on its
behalf. That is all this module is.

Three properties it holds to
-----------------------------
1. **A no-op when the index exists.** The probe is filesystem-only - two `stat`
   calls. It never constructs an `Embedder`, so the common path costs no model
   load and cannot fail for embedding reasons. Local development is unaffected.
2. **Offline.** `run_ingest` calls `ensure_raw_pages`, which reuses
   `data/raw/*.html` when present. In a deployment those files are committed, so
   the bootstrap never reaches the network.
3. **Loud on failure.** A partial ingest, a zero-chunk result, or an index that
   is still missing afterwards all raise `IndexUnavailableError`. The whole point
   is that "no index" must never again be reportable as "not in the corpus".

It deliberately does NOT touch the threshold, the chunker, fusion or the gate.
The retrieval design is unchanged; this only makes sure it is running against a
populated index instead of an empty one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..core.config import Settings, get_settings
from ..core.errors import IndexUnavailableError
from .embedder import Embedder
from .pipeline import run_ingest

log = logging.getLogger(__name__)

#: The file ChromaDB always writes into its persist directory. Checking for it
#: rather than for the directory itself distinguishes "never indexed" from
#: "indexed and then emptied", because `PersistentClient` happily creates the
#: directory on a read.
CHROMA_MARKER = "chroma.sqlite3"

ACTION_NONE = "none"
ACTION_BUILT = "built"
ACTION_FAILED = "failed"


@dataclass
class IndexStatus:
    """What `ensure_index` found and what it did about it."""

    action: str = ACTION_NONE
    chunks: int = 0
    #: Absolute paths of the artifacts that were missing and are now expected.
    rebuilt: list[str] = field(default_factory=list)
    pages_embedded: list[str] = field(default_factory=list)
    pages_skipped: list[str] = field(default_factory=list)

    @property
    def built(self) -> bool:
        return self.action == ACTION_BUILT

    def summary(self) -> str:
        if self.action == ACTION_NONE:
            return "index present; nothing to do"
        if self.action == ACTION_BUILT:
            return (
                f"index built at startup ({self.chunks} chunks, "
                f"{len(self.pages_embedded)} page(s) embedded, "
                f"{len(self.pages_skipped)} unchanged)"
            )
        return "index bootstrap failed"


def _chroma_present(chroma_dir: Path) -> bool:
    """True when a Chroma persist directory holds a real store, not just a dir."""
    return (chroma_dir / CHROMA_MARKER).is_file()


def _bm25_present(bm25_file: Path) -> bool:
    """True when the BM25 pickle exists and is not a zero-byte stub."""
    return bm25_file.is_file() and bm25_file.stat().st_size > 0


def probe_index(settings: Settings | None = None) -> list[str]:
    """Names of the missing index artifacts. Empty means the index is usable.

    Filesystem only, by design: this runs on the startup path where an expensive
    import or a model load would be paid on every process start to answer a
    question `stat` can answer.
    """
    settings = settings or get_settings()
    missing: list[str] = []
    if not _chroma_present(settings.chroma_dir):
        missing.append(f"chroma index ({settings.chroma_dir})")
    if not _bm25_present(settings.bm25_file):
        missing.append(f"bm25 index ({settings.bm25_file})")
    return missing


def ensure_index(
    settings: Settings | None = None,
    *,
    embedder: Embedder | None = None,
) -> IndexStatus:
    """Guarantee a populated retrieval index, building it from `data/raw` if absent.

    Returns an `IndexStatus`. Raises `IndexUnavailableError` if the index is
    missing and cannot be built - never returns quietly with an empty corpus,
    because a caller that cannot tell "no index" from "no match" will report a
    deployment fault as a confident refusal.
    """
    settings = settings or get_settings()
    missing = probe_index(settings)
    if not missing:
        log.info("retrieval index present at %s; skipping bootstrap", settings.chroma_dir)
        return IndexStatus(action=ACTION_NONE)

    log.warning(
        "retrieval index incomplete (%s); building it from %s",
        "; ".join(missing),
        settings.raw_dir_abs,
    )

    try:
        report = run_ingest(settings, embedder=embedder)
    except Exception as exc:  # noqa: BLE001 - re-raised as a deployment error
        raise IndexUnavailableError(
            f"the index was missing and the bootstrap ingest did not complete "
            f"({type(exc).__name__}: {exc}).",
            remediation="Check that data/raw/*.html is present and readable, then "
            "redeploy. Run `python -m src.ragbot.ingest` locally to see the "
            "per-page failure.",
        ) from exc

    if not report.ok:
        detail = "; ".join(f"{page}: {why}" for page, why in sorted(report.failures.items()))
        raise IndexUnavailableError(
            f"the index was missing and the bootstrap ingest failed on "
            f"{len(report.failures)} page(s): {detail}",
            remediation="The committed data/raw HTML for those pages is unusable. "
            "Restore it, then redeploy.",
        )

    if report.total_chunks <= 0:
        raise IndexUnavailableError(
            "the index was missing and the bootstrap ingest produced 0 chunks.",
            remediation="The corpus is defined in config/corpus.yaml; check that its "
            "pages still yield text above min_extract_chars.",
        )

    # Re-probe rather than trusting the report: the thing that matters is whether
    # the artifacts a later process will look for are on disk, not what the
    # in-memory report believes it wrote.
    still_missing = probe_index(settings)
    if still_missing:
        raise IndexUnavailableError(
            f"the bootstrap ingest reported {report.total_chunks} chunks but "
            f"{'; '.join(still_missing)} is still absent.",
            remediation="The persist directory is probably not writable in this "
            "environment.",
        )

    log.info(
        "retrieval index built at startup: %d chunks from %d page(s)",
        report.total_chunks,
        len(report.pages),
    )
    return IndexStatus(
        action=ACTION_BUILT,
        chunks=report.total_chunks,
        rebuilt=missing,
        pages_embedded=list(report.embedded_pages),
        pages_skipped=list(report.skipped),
    )


__all__ = [
    "ACTION_BUILT",
    "ACTION_FAILED",
    "ACTION_NONE",
    "CHROMA_MARKER",
    "IndexStatus",
    "ensure_index",
    "probe_index",
]