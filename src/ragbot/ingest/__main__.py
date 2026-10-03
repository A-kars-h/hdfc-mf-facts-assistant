"""`python -m src.ragbot.ingest` - run the ingestion pipeline.

Exits non-zero if any page fails. A partial ingest is a failed ingest: with five
pages, four is a corpus that quietly lacks a whole scheme.
"""

from __future__ import annotations

import argparse
import sys

from ..core.config import env_summary, get_settings
from ..core.logging import setup_logging
from .pipeline import run_ingest


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.ragbot.ingest",
        description="Clean, chunk, embed and index the 5 HDFC scheme pages.",
    )
    p.add_argument(
        "--reindex", action="store_true",
        help="Ignore the manifest and re-embed every page.",
    )
    p.add_argument(
        "--fetch", action="store_true",
        help="Re-download data/raw/*.html before ingesting.",
    )
    p.add_argument("--log-level", default="INFO")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.log_level)

    settings = get_settings()
    print("configuration")
    for key, value in env_summary().items():
        print(f"  {key:22} {value}")
    print()

    try:
        report = run_ingest(
            settings, refresh=args.fetch, reindex=args.reindex
        )
    except Exception as exc:  # noqa: BLE001
        print(f"\nFATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("per-page results")
    print(f"  {'page_id':18} {'chunks':>7}  {'fetched_at':20} status")
    for record in report.pages:
        status = "skipped (unchanged)" if record.page_id in report.skipped else "embedded"
        print(
            f"  {record.page_id:18} {record.chunks:>7}  "
            f"{record.fetched_at.strftime('%Y-%m-%d %H:%M'):20} {status}"
        )
    for page_id, err in report.failures.items():
        print(f"  {page_id:18} {'-':>7}  {'-':20} FAILED: {err}", file=sys.stderr)

    print()
    print(f"  pages embedded : {len(report.embedded_pages)}")
    print(f"  pages skipped  : {len(report.skipped)}")
    print(f"  pages failed   : {len(report.failures)}")
    print(f"  chunks in index: {report.total_chunks}")
    print(f"  manifest       : {settings.manifest_file}")
    print(f"  chroma         : {settings.chroma_dir}")
    print(f"  bm25           : {settings.bm25_file}")

    if report.failures:
        print(
            f"\n{len(report.failures)} page(s) failed. A partial corpus is not a "
            f"corpus - fix the cause and re-run.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
