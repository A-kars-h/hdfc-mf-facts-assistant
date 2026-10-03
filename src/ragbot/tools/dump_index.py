"""Dump the indexed chunks and their embedding vectors as plain text files.

Why this exists
---------------
An embedding index is opaque by construction. `data/chroma/` is 20 MB of binary
that cannot answer the questions that actually matter during a build:

    - is the right text in the index, or did ingestion drop it?
    - is the embedding for that text the embedding of the text I think it is?
    - is the vector unit-length, or has something silently rescaled it?
    - which chunks are the 27% cross-page duplicates (OQ-3)?

So this writes plain `.txt` that can be read, diffed and grepped. It reads the
SAME Chroma collection the retriever reads, so what it prints is what retrieval
sees - not a re-embedding that might disagree.

Two files, deliberately
-----------------------
    artifacts/chunks.txt       the text that was indexed, with its provenance
    artifacts/embeddings.txt   the vector for each of those chunks

Split rather than combined because they answer different questions and are
useful at different moments. `chunks.txt` is ~470 KB and readable end to end,
which is what you want when asking "did ingestion keep the right text". The
vector file is ~5 MB and is only useful next to the text, because a 384-number
row means nothing on its own.

The vector file therefore repeats a short text preview per block, so every
vector stays attached to the text it came from and the two files can be
cross-referenced by `chunk_id`.

Usage
-----
    python -m src.ragbot.tools.dump_index                  # both default files
    python -m src.ragbot.tools.dump_index --only chunks
    python -m src.ragbot.tools.dump_index --only embeddings --nd 4
    python -m src.ragbot.tools.dump_index --out-dir build/
    python -m src.ragbot.tools.dump_index --max-chunks 20  # peek at the first 20

Integrity checks are in the header of BOTH files, because a vector dump is only
trustworthy if the numbers are sane, and a chunk dump is only trustworthy if the
counts are. Every check is computed from the stored data rather than asserted:
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ..core.config import get_settings
from ..ingest.writer import COLLECTION, Writer

DEFAULT_OUT_DIR = Path("artifacts")
CHUNKS_NAME = "chunks.txt"
EMBEDDINGS_NAME = "embeddings.txt"

#: 8 per line keeps a 384-value vector to 48 lines - readable in a diff, and
#: narrow enough not to wrap on a standard terminal.
VALUES_PER_LINE = 8

#: Rounding is for display only. Stored values are float32 (~7 significant
#: decimal digits), so 6 dp is lossless and avoids printing binary noise such as
#: 0.30000001192092896.
DEFAULT_DP = 6

RULE = "=" * 100
THIN = "-" * 100
THICK = "#" * 100


# --- data -----------------------------------------------------------------


def collect() -> dict:
    """Pull every chunk, its text, its metadata and its vector from Chroma."""
    collection = Writer(get_settings()).collection

    got = collection.get(include=["documents", "metadatas", "embeddings"])
    embeddings = got["embeddings"]
    if embeddings is None:
        raise SystemExit(
            "chroma returned no embeddings. Re-run ingestion:\n"
            "  python -m src.ragbot.ingest"
        )

    rows = []
    for i, chunk_id in enumerate(got["ids"]):
        meta = dict(got["metadatas"][i] or {})
        rows.append(
            {
                "chunk_id": chunk_id,
                "page_id": meta.get("page_id", "?"),
                "scheme": meta.get("scheme", "?"),
                "section": meta.get("section", "?"),
                "category": meta.get("category", "?"),
                "source_url": meta.get("source_url", "?"),
                "fetched_at": meta.get("fetched_at", "?"),
                "return_heavy": meta.get("return_heavy", False),
                "token_count": meta.get("token_count", 0),
                "char_start": meta.get("char_start", 0),
                "char_end": meta.get("char_end", 0),
                "content_hash": meta.get("content_hash", ""),
                "text": got["documents"][i] or "",
                "vector": [float(v) for v in embeddings[i]],
            }
        )

    return {"collection": collection.name, "count": collection.count(), "rows": rows}


# --- shared header ---------------------------------------------------------


def _source_files() -> list[tuple[str, str, int]]:
    """(role, relative path, size) for every file these dumps derive from."""
    rows: list[tuple[str, str, int]] = []
    candidates = [
        ("ingest manifest", Path("artifacts/manifest.json")),
        ("chroma metadata", Path("data/chroma/chroma.sqlite3")),
        ("bm25 index", Path("data/bm25.pkl")),
    ]
    candidates += [("chroma vectors (HNSW)", p) for p in sorted(Path("data/chroma").glob("*/data_level0.bin"))]
    candidates += [("raw extracted text", p) for p in sorted(Path("data/raw").glob("*.txt"))]

    for role, path in candidates:
        if path.exists():
            rows.append((role, str(path), path.stat().st_size))
    return rows


def _manifest() -> dict:
    path = Path("artifacts/manifest.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def integrity(rows: list[dict]) -> list[str]:
    """Checks computed from the stored data. Each line says PASS, FAIL or NOTE."""
    if not rows:
        return ["FAIL  collection is empty - no chunks to check"]

    out: list[str] = []

    dims = {len(r["vector"]) for r in rows}
    if len(dims) == 1:
        out.append(f"PASS  every vector has the same dimensionality: {dims.pop()}")
    else:
        out.append(f"FAIL  mixed vector dimensions: {sorted(dims)}")

    norms = [sum(v * v for v in r["vector"]) ** 0.5 for r in rows if r["vector"]]
    if norms:
        lo, hi = min(norms), max(norms)
        # all-MiniLM-L6-v2 emits L2-normalised vectors, so this sits at 1.0.
        # A wide spread means something rescaled or truncated them.
        verdict = "PASS" if 0.99 <= lo and hi <= 1.01 else "WARN"
        out.append(
            f"{verdict}  L2 norm min={lo:.6f} max={hi:.6f} "
            f"mean={statistics.fmean(norms):.6f} (expected ~1.000000)"
        )

    empty = [r for r in rows if not r["text"].strip()]
    out.append(f"{'PASS' if not empty else 'FAIL'}  empty/whitespace chunk text: {len(empty)}")
    for r in empty[:5]:
        out.append(f"        - {r['chunk_id']}  {r['scheme']!r}")

    no_url = [r for r in rows if not str(r["source_url"]).startswith("http")]
    out.append(
        f"{'PASS' if not no_url else 'FAIL'}  chunks with a non-http source_url: {len(no_url)}"
    )

    by_text: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        by_text[r["text"].strip()].append(r["chunk_id"])
    exact = {t: ids for t, ids in by_text.items() if t and len(ids) > 1}
    out.append(
        f"{'PASS' if not exact else 'NOTE'}  byte-identical chunk text: {len(exact)} groups, "
        f"{sum(len(v) - 1 for v in exact.values())} redundant copies"
    )

    # OQ-3 cross-page boilerplate, measured the way Phase 3 measured it.
    #
    # The naive measure - dedupe on exact text - reports ZERO, which is wrong and
    # misleading. Every chunk is prefixed with its own "SCHEME (section)", so two
    # chunks carrying identical boilerplate differ in their first few characters
    # and never collide. The redundancy is invisible unless that prefix is
    # stripped first.
    #
    # Stripping the leading parenthesised prefix reproduces the documented figure
    # exactly (92 bodies / 326 copies / 27%), which is the evidence this is the
    # right normalisation rather than one tuned to hit a number.
    prefix = re.compile(r"^[^()]*\([^)]*\)")
    cross: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        body = re.sub(r"\s+", " ", prefix.sub(" ", r["text"])).strip().lower()
        if body:
            cross[body].add(r["page_id"])
    shared = {b: p for b, p in cross.items() if len(p) > 1}
    redundant = sum(len(p) - 1 for p in shared.values())
    out.append(
        f"NOTE  OQ-3 cross-page boilerplate: {len(shared)} distinct bodies appear on more "
        f"than one page, accounting for {redundant} redundant copies "
        f"({100.0 * redundant / len(rows):.1f}% of {len(rows)} chunks)"
    )
    for body, pages in sorted(shared.items(), key=lambda kv: -len(kv[1]))[:5]:
        out.append(f"        x{len(pages)} pages {sorted(pages)}  {body[:68]!r}")

    per_page: dict[str, int] = defaultdict(int)
    for r in rows:
        per_page[r["page_id"]] += 1
    out.append(f"NOTE  chunks per page: {dict(sorted(per_page.items()))}")

    return out


def _header(data: dict, *, title: str, file_role: str, companion: str, dp: int,
            shown: int, with_vectors: bool) -> list[str]:
    settings = get_settings()
    manifest = _manifest()
    rows = data["rows"]

    out = [RULE, title, RULE]
    out.append(f"generated_at        {datetime.now(timezone.utc).isoformat()}")
    out.append(f"this file            {file_role}")
    out.append(f"companion file       {companion}")
    out.append(f"collection           {data['collection']}")
    out.append(f"chroma count         {data['count']}")
    out.append(f"chunks in this file  {shown} of {len(rows)}")
    out.append(f"vectors in this file {'yes' if with_vectors else 'no'}")
    out.append(f"vector precision     {dp} dp (display only; stored is float32)")
    out.append("")

    out += [THIN, "EMBEDDING MODEL", THIN]
    out.append(f"  model             {manifest.get('embedding_model', settings.embedding_model)}")
    out.append(f"  dimension         {manifest.get('embedding_dim', 'unknown')}")
    out.append(f"  chunk_size        {manifest.get('chunk_size', 'unknown')} chars")
    out.append(f"  chunk_overlap     {manifest.get('chunk_overlap', 'unknown')} chars")
    out.append(f"  amc               {manifest.get('amc', 'unknown')}")
    out.append(f"  plan variant      {manifest.get('plan_variant', 'unknown')}")
    out.append("")

    out += [THIN, "SOURCE FILES  (what these dumps were derived from)", THIN]
    for role, path, size in _source_files():
        out.append(f"  {size:>12,}  {role:<26} {path}")
    out.append("")

    out += [THIN, "INTEGRITY CHECKS  (computed from the stored data, not asserted)", THIN]
    out += [f"  {line}" for line in integrity(rows)]
    out.append("")
    return out


# --- file 1: chunks --------------------------------------------------------


def render_chunks(data: dict, *, dp: int, max_chunks: int | None) -> str:
    rows = data["rows"]
    shown_rows = rows if not max_chunks else rows[:max_chunks]

    out = _header(
        data,
        title="RAGBOT - INDEXED CHUNKS (text and provenance)",
        file_role=CHUNKS_NAME,
        companion=EMBEDDINGS_NAME + "  (same chunk_ids, with vectors)",
        dp=dp,
        shown=len(shown_rows),
        with_vectors=False,
    )

    out += [THIN, "CHUNKS  (grouped by source page)", THIN, ""]

    by_page: dict[str, list[dict]] = defaultdict(list)
    for r in shown_rows:
        by_page[r["page_id"]].append(r)

    for page_id in sorted(by_page):
        page_rows = by_page[page_id]
        first = page_rows[0]
        out += [
            THICK,
            f"PAGE  {page_id}",
            f"  scheme        {first['scheme']}",
            f"  category      {first['category']}",
            f"  source_url    {first['source_url']}",
            f"  fetched_at    {first['fetched_at']}",
            f"  chunks        {len(page_rows)}"
            + (f" (truncated from {len([r for r in rows if r['page_id'] == page_id])})"
               if max_chunks and len(page_rows) < len([r for r in rows if r['page_id'] == page_id])
               else ""),
            THICK,
            "",
        ]
        for n, r in enumerate(page_rows, start=1):
            out += [
                f"  [{page_id} #{n}]  chunk_id={r['chunk_id']}",
                f"    section      {r['section']}",
                f"    chars        {r['char_start']}..{r['char_end']}",
                f"    tokens       {r['token_count']}",
                f"    return_heavy {r['return_heavy']}",
                f"    content_hash {r['content_hash'][:32]}...",
                f"    text ({len(r['text'])} chars):",
            ]
            out += [f"      | {line}" for line in (r["text"].splitlines() or [""])]
            out.append("")

    if max_chunks and len(rows) > max_chunks:
        out.append(f"  ... truncated at --max-chunks={max_chunks} of {len(rows)}")
        out.append("")

    out += [RULE, "END", RULE]
    return "\n".join(out) + "\n"


# --- file 2: embeddings ----------------------------------------------------


def _vector_block(vec: list[float], dp: int) -> str:
    lines = []
    for start in range(0, len(vec), VALUES_PER_LINE):
        row = vec[start : start + VALUES_PER_LINE]
        lines.append(f"    [{start:>3}] " + " ".join(f"{v:.{dp}f}" for v in row))
    return "\n".join(lines)


def render_embeddings(data: dict, *, dp: int, max_chunks: int | None) -> str:
    rows = data["rows"]
    shown_rows = rows if not max_chunks else rows[:max_chunks]

    out = _header(
        data,
        title="RAGBOT - EMBEDDING VECTORS (one block per indexed chunk)",
        file_role=EMBEDDINGS_NAME,
        companion=CHUNKS_NAME + "  (same chunk_ids, with full text)",
        dp=dp,
        shown=len(shown_rows),
        with_vectors=True,
    )
    out += [
        THIN,
        "VECTORS",
        THIN,
        "  Each block is one chunk's stored vector, 8 values per line, in stored order.",
        "  A short text preview is included so the vector is never orphaned from the",
        "  text it encodes - match on chunk_id to read the full text in " + CHUNKS_NAME + ".",
        "",
    ]

    for i, r in enumerate(shown_rows, start=1):
        norm = sum(v * v for v in r["vector"]) ** 0.5
        out += [
            f"  [{i}/{len(shown_rows)}]  chunk_id={r['chunk_id']}",
            f"    page_id     {r['page_id']}",
            f"    scheme      {r['scheme']}",
            f"    section     {r['section']}",
            f"    dim         {len(r['vector'])}",
            f"    L2 norm     {norm:.6f}",
            f"    text[:100]  {r['text'][:100]!r}",
            _vector_block(r["vector"], dp),
            "",
        ]

    if max_chunks and len(rows) > max_chunks:
        out.append(f"  ... truncated at --max-chunks={max_chunks} of {len(rows)}")
        out.append("")

    out += [RULE, "END", RULE]
    return "\n".join(out) + "\n"


# --- cli -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.ragbot.tools.dump_index",
        description="Write indexed chunks and their embeddings to two text files.",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="output directory"
    )
    parser.add_argument(
        "--only",
        choices=("chunks", "embeddings", "all"),
        default="all",
        help="write just one of the two files (default: both)",
    )
    parser.add_argument("--nd", type=int, default=DEFAULT_DP, help="decimals for vector values")
    parser.add_argument("--max-chunks", type=int, default=None, help="only dump the first N chunks")
    args = parser.parse_args(argv)

    data = collect()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    jobs = {
        "chunks": (CHUNKS_NAME, lambda: render_chunks(data, dp=args.nd, max_chunks=args.max_chunks)),
        "embeddings": (EMBEDDINGS_NAME, lambda: render_embeddings(data, dp=args.nd, max_chunks=args.max_chunks)),
    }
    wanted = list(jobs) if args.only == "all" else [args.only]

    for key in wanted:
        name, build = jobs[key]
        path = args.out_dir / name
        path.write_text(build(), encoding="utf-8")
        print(f"wrote {path}  ({path.stat().st_size:,} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
