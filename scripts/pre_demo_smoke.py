"""Pre-demo smoke: exercise the exact call a starter button makes.

`AppTest` proves the script renders; it does not prove the live server can run a
real session with the real orchestrator, the 90 MB embedding model and the real
LLM provider. This does: it calls `Ragbot.ask_with_evidence` - the single product
function `ui/app.py` calls - with each of the three starter questions.

Read-only. Touches no index, no config and no threshold.
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
from src.ragbot.ui.app import EXAMPLE_QUESTIONS  # noqa: E402


def main() -> int:
    setup_logging()
    settings = Settings()
    lines = [
        f"threshold in force: {settings.require_similarity_threshold()}",
        f"provider: {settings.llm_provider} / {settings.llm_model}",
        "-" * 78,
    ]
    print(lines[0])
    print(lines[1])

    bot = Ragbot(settings=settings)
    failures = 0
    for question in EXAMPLE_QUESTIONS:
        started = time.perf_counter()
        try:
            answer, chunks = bot.ask_with_evidence(question)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            line = f"[FAIL] {question}\n       {type(exc).__name__}: {exc}"
            lines.append(line)
            print("[FAIL]", question)
            print("      ", type(exc).__name__, exc)
            continue
        ms = (time.perf_counter() - started) * 1000
        state = "REFUSED" if answer.refused else "ANSWERED"
        block = [
            f"[ ok ] ({ms:7.0f} ms) {state}  chunks={len(chunks)}",
            f"       Q: {question}",
            f"       A: {answer.text}",
            f"       source={answer.source_url}",
            f"       last_updated={answer.last_updated}",
        ]
        if answer.educational_link_missing:
            block.append("       educational link: none (education_links.yml is empty)")
        block.append("-" * 78)
        lines.extend(block)
        print(f"[ ok ] ({ms:7.0f} ms) {state}  chunks={len(chunks)}")

    summary = (
        "all three starters answered"
        if not failures
        else f"{failures} starter(s) FAILED"
    )
    lines.append(summary)
    # Written as UTF-8: the Windows console is cp1252 and cannot print the rupee
    # sign, which appears in a correct answer.
    report = ROOT / "artifacts" / "pre_demo_smoke.txt"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary)
    print(f"full output: {report}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())