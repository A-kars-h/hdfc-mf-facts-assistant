"""Pre-demo question check: which questions are safe to put in a 3-minute video?

`pre_demo_smoke.py` proves the three starter buttons work. This is the wider net:
it runs a candidate list through the real orchestrator and reports, per question,
whether it was answered or refused, how long it took, and - the thing that
matters for a demo - whether the answer is an actual answer or a confident
non-answer.

A confident non-answer is the failure mode to catch. `artifacts/sample_qa.md`
records Q5 (benchmark of HDFC Balanced Advantage Fund) being ANSWERED with "The
provided corpus does not contain the benchmark..." while the benchmark is in the
corpus and the gate opened at 0.8706. Every deterministic check passed it. A
question like that will look like a bug on camera, so it is flagged here.

Read-only: touches no index, no config, no threshold.

Usage:  python scripts/demo_question_check.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ragbot.core.config import Settings  # noqa: E402
from src.ragbot.core.logging import setup_logging  # noqa: E402
from src.ragbot.generation.pipeline import Ragbot  # noqa: E402

# (label, question) - the golden set plus the questions the demo script asks by
# typing. Anything here that comes back a non-answer gets marked DO NOT DEMO.
CANDIDATES: list[tuple[str, str]] = [
    ("beat 0:25 / starter 1", "What is the minimum SIP amount for HDFC ELSS Tax Saver Fund Direct Plan Growth?"),
    ("beat 1:15 / starter 2", "Should I buy HDFC Large Cap for a 5-year goal?"),
    ("beat 2:10 / starter 3", "What is the expense ratio of the HDFC Mid Cap Fund?"),
    ("beat 1:50 / typed", "Which of these five is the best performing fund?"),
    ("alt: exit load", "What is the exit load on HDFC Small Cap Fund Direct Growth?"),
    ("alt: expense ratio", "What is the expense ratio of HDFC Large Cap Fund Direct Growth?"),
    ("alt: lock-in", "What is the lock-in period for HDFC ELSS Tax Saver Fund?"),
    ("alt: benchmark (risky)", "What is the benchmark of HDFC Balanced Advantage Fund Direct Growth?"),
    ("alt: riskometer", "What is the risk level of HDFC Small Cap Fund Direct Growth?"),
    ("alt: corpus self-description", "Which HDFC fund pages are you using?"),
]

#: Phrases that mean the model declined while still returning an ANSWER. Every
#: one of these is a non-answer the user sees as a confident reply.
NON_ANSWER_MARKERS = (
    "does not contain",
    "doesn't contain",
    "not contain",
    "no information",
    "not available in",
    "unable to find",
    "could not find",
    "cannot find",
    "insufficient information",
)


def main() -> int:
    setup_logging()
    settings = Settings()
    bot = Ragbot(settings=settings)

    lines = [
        f"threshold: {settings.require_similarity_threshold()}",
        f"provider: {settings.llm_provider} / {settings.llm_model}",
        "=" * 78,
    ]
    print(f"threshold {settings.require_similarity_threshold()} | checking {len(CANDIDATES)} questions")

    unsafe = 0
    for label, question in CANDIDATES:
        started = time.perf_counter()
        try:
            answer, chunks = bot.ask_with_evidence(question)
        except Exception as exc:  # noqa: BLE001
            unsafe += 1
            lines.append(f"[ERROR] {label}\n  Q: {question}\n  {type(exc).__name__}: {exc}")
            print(f"[ERROR] {label}: {type(exc).__name__}")
            continue
        ms = (time.perf_counter() - started) * 1000

        text = answer.text
        lowered = text.lower()
        is_non_answer = any(m in lowered for m in NON_ANSWER_MARKERS)
        verdict = "NON-ANSWER" if is_non_answer else ("REFUSED" if answer.refused else "OK")

        if is_non_answer:
            unsafe += 1

        block = [
            f"[{verdict}] ({ms:7.0f} ms) {label}",
            f"  Q: {question}",
            f"  A: {text}",
            f"  intent={answer.intent.value} refused={answer.refused} chunks={len(chunks)}",
            f"  source={answer.source_url}",
            f"  last_updated={answer.last_updated}",
        ]
        if answer.educational_link_missing:
            block.append("  educational_link: MISSING (education_links.yml is empty)")
        if is_non_answer:
            block.append("  >>> DO NOT DEMO: returned as an answer, but it declines to answer.")
        block.append("-" * 78)
        lines.extend(block)
        print(f"[{verdict:10s}] {ms:7.0f} ms  {label}")

    report = ROOT / "artifacts" / "demo_question_check.txt"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("=" * 78)
    print(f"questions flagged as unsafe to demo: {unsafe}")
    print(f"full output: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())