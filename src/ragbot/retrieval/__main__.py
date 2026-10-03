"""CLI: ``python -m src.ragbot.retrieval "<question>"``.

Prints intent, every candidate's scheme / section / raw dense score / BM25 score
/ fused rank / text prefix, and the gate decision. The point of the CLI is
inspectability: every number it prints is one the gate actually reads, so a
wrong answer can be diagnosed without a debugger.

On an UNCALIBRATED corpus the gate raises `NotCalibratedError` - by design, since
Phase 6 has not derived a threshold yet. The CLI reports that state explicitly
instead of crashing, so retrieval can still be demonstrated and reviewed, and the
missing threshold is visible rather than papered over with a made-up number.
"""

from __future__ import annotations

import argparse
import logging
import sys

from ..core.config import get_settings
from ..core.errors import NotCalibratedError
from ..core.logging import setup_logging
from ..core.models import Intent
from ..safety import pii
from . import gate
from .intent import explain, is_performance_claim
from .search import HybridSearcher, SearchResult

RULE = "-" * 96
PREFIX_CHARS = 150


def _use_utf8() -> None:
    """Make stdout UTF-8 so the rupee sign and em dashes survive.

    The corpus contains '₹500' on almost every chunk, and a Windows console
    defaults to a legacy codepage, so the numbers that matter would render as
    '?' without this.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass  # A redirected/non-tty stream. Not worth failing over.


def _short(text: str, limit: int = PREFIX_CHARS) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _fmt_score(value: float | None) -> str:
    return "     -  " if value is None else f"{value:8.4f}"


def render(result: SearchResult, *, include_gate: bool = True) -> str:
    lines: list[str] = [RULE, f"question : {result.question}", RULE]

    perf = "yes" if result.performance_claim else "no"
    lines.append(f"intent   : {result.intent.value}")
    lines.append(f"  matched rule    : {result.intent_match.rule}")
    lines.append(f"  needs fallback  : {result.intent_match.needs_fallback}")
    lines.append(f"  perf claim?     : {perf}")
    if result.intent_match.needs_fallback:
        lines.append(
            "  (no rule matched; defaulted to factual so the gate and the Phase 4 "
            "output screens decide)"
        )

    if result.intent is Intent.CORPUS_SOURCES:
        lines.append("")
        lines.append(
            "retrieval skipped: this intent is answered from config/corpus.yaml, "
            "the same file the pages were fetched from."
        )
        lines.append(
            "  No chunk describes the corpus, so there is nothing for a similarity "
            "score to be evidence about."
        )
    elif result.intent is not Intent.FACTUAL:
        lines.append("")
        lines.append(
            "retrieval skipped: this intent is refused on routing, before any "
            "embedding or ranking."
        )
        lines.append(
            "  It is NOT gated on similarity - advice questions match this corpus "
            "strongly,"
        )
        lines.append("  which is exactly why the gate must not be what catches them.")
    else:
        lines.append("")
        lines.append(
            f"retrieval : {len(result.dense_hits)} dense hits, "
            f"{len(result.sparse_hits)} BM25 hits"
        )
        if not result.sparse_available:
            lines.append("  WARNING: no BM25 index found; sparse leg inactive")
        lines.append(
            f"  raw_dense_max : {result.raw_dense_max:.4f}   "
            f"(the ONLY value the gate thresholds)"
        )
        bm25_only = result.bm25_only_ids
        lines.append(
            f"  fused         : {len(result.candidates)} candidates "
            f"({len(bm25_only)} found by BM25 only)"
        )

        lines.append("")
        header = (
            f"{'#':>2}  {'raw dense':>9}  {'bm25':>8}  {'scheme':<22}  "
            f"{'section':<24}  flags"
        )
        lines.append(header)
        lines.append("-" * 100)
        for c in result.candidates:
            flags = []
            if c.chunk_id in bm25_only:
                flags.append("BM25-only")
            if c.chunk.return_heavy:
                flags.append("return-heavy")
            lines.append(
                f"{c.fused_rank:>2}  {_fmt_score(c.dense_score)}  "
                f"{_fmt_score(c.sparse_score)}  {c.chunk.scheme[:22]:<22}  "
                f"{(c.chunk.section or '-')[:24]:<24}  {','.join(flags)}"
            )
            lines.append(f"    {_short(c.chunk.text)}")

    if not include_gate:
        return "\n".join(lines)

    lines.append("")
    lines.append(RULE)
    lines.append("gate decision")
    lines.append(RULE)
    d = result.decision
    if d is None:
        lines.append("  no decision produced")
    else:
        verdict = "ANSWER" if d.found_answer else "REFUSE"
        lines.append(f"  found_answer      : {d.found_answer}  ({verdict})")
        lines.append(f"  reason            : {d.reason}")
        lines.append(f"  raw_dense_max     : {d.raw_dense_max:.4f}")
        lines.append(f"  candidates        : {d.candidates_considered}")
        if result.threshold is not None:
            lines.append(f"  threshold         : {result.threshold:.4f}")
        else:
            lines.append("  threshold         : <UNCALIBRATED>")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.ragbot.retrieval",
        description="Hybrid retrieval + gate over the indexed corpus. No LLM.",
    )
    parser.add_argument("question", nargs="+", help="the question to retrieve for")
    parser.add_argument(
        "--show-rule", action="store_true", help="also print the raw intent rules"
    )
    args = parser.parse_args(argv)

    _use_utf8()
    setup_logging()
    settings = get_settings()
    question = " ".join(args.question)

    # This is a developer tool that takes a question on the command line and
    # echoes it to stdout. Without this scan, `python -m src.ragbot.retrieval "my
    # pan is ABCPA1234B"` would print the PAN and embed it, bypassing the gate
    # that `Ragbot.ask()` enforces. The stdout echo below is outside the logging
    # system entirely, so the log filter never sees it.
    pii_result = pii.scan(question)
    if pii_result.found:
        print(f"question : {pii_result.redacted}")
        print(f"refused  : personal data detected ({pii_result.summary()})")
        print()
        print(RULE)
        print("  Nothing was embedded, sent, or stored. Remove the personal")
        print("  details and try again.")
        return 2

    if args.show_rule:
        match = explain(question)
        print(f"question : {question}")
        print(f"intent   : {match.intent.value}  (rule={match.rule})")
        print(f"perf claim: {is_performance_claim(question)}")
        return 0

    searcher = HybridSearcher(settings)
    try:
        # Exactly one retrieval either way. `retrieve()` never raises
        # NotCalibratedError: the gate is applied here, and only when routing
        # did not already produce a decision. Checking calibration first and
        # calling `search()` in the happy path would embed and query twice.
        result = searcher.retrieve(question)
        if result.decision is None:
            try:
                result.decision = gate.decide(
                    result.candidates, result.raw_dense_max, settings=settings
                )
            except NotCalibratedError as exc:
                # A factual question on an uncalibrated corpus. Retrieval above
                # is real; the gate simply declines to rule on it.
                print(render(result, include_gate=False))
                print()
                print(RULE)
                print("gate decision")
                print(RULE)
                print("  found_answer : None")
                print("  reason       : uncalibrated")
                print(f"  {exc}")
                print()
                print("  The gate refuses to guess a threshold. Retrieval above is")
                print("  real; it must not be used to answer until Phase 6")
                print("  calibrates one.")
                return 2
        print(render(result))
        return 0
    except Exception as exc:  # noqa: BLE001
        # Actionable message, never a bare traceback (FR-15).
        print(f"retrieval failed: {exc}", file=sys.stderr)
        logging.getLogger(__name__).debug("traceback follows", exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
