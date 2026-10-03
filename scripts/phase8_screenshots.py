"""Phase 8: capture what the UI actually shows, using the real answers.

This is a TEXT RENDER, not a pixel screenshot. It drives the real
`src/ragbot/ui/app.py` through Streamlit's own `AppTest` - the same harness the
project's own `tests/unit/test_ui_app.py` uses - and writes out exactly the
content a user sees.

The orchestrator is replaced with a stub that replays the answers captured from
a real eval run (`artifacts/_probe.json`), so every fact, link and date below is
real. Nothing here is invented, and no UI code is modified.

Usage:  python scripts/phase8_screenshots.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

from src.ragbot.core.models import Answer, Intent  # noqa: E402
from src.ragbot.ui import app as ui  # noqa: E402

ART = ROOT / "artifacts"
SHOTS = ART / "screenshots"
PROBE = json.loads((ART / "eval_run_capture.json").read_text(encoding="utf-8"))

BY_ID = {o["id"]: o for o in PROBE["outcomes"]}


def _real_chunks(qid: str) -> list[RetrievedChunk]:
    """A real retrieval for this question, so the inspector shows real chunks."""
    from src.ragbot.core.config import Settings
    from src.ragbot.retrieval.search import HybridSearcher

    search = HybridSearcher(Settings()).retrieve(BY_ID[qid]["question"])
    return list(search.candidates)


def _answer_for(qid: str) -> tuple[Answer, list]:
    """Rebuild the real Answer recorded by the eval run."""
    row = BY_ID[qid]
    return (
        Answer(
            intent=Intent(row["intent"]),
            text=row["text"] or "",
            source_url=row["source_url"],
            last_updated=(
                datetime.fromisoformat(row["last_updated"]) if row["last_updated"] else None
            ),
            educational_link=row["educational_link"],
            educational_link_missing=bool(row["educational_link_missing"]),
            refused=bool(row["refused"]),
            validation=row["validation"] or [],
        ),
        [],
    )


class _StubBot:
    """Replays recorded answers. Records which question it was asked."""

    def __init__(self) -> None:
        self.current = "Q3"
        self.chunks: list = []

    def ask_with_evidence(self, question: str):
        for qid, row in BY_ID.items():
            if row["question"].strip().lower() == question.strip().lower():
                self.current = qid
                answer, _ = _answer_for(qid)
                return answer, list(self.chunks)
        raise AssertionError(f"stub has no recorded answer for: {question!r}")


def render(title: str, question: str, *, chunks: list | None = None) -> str:
    """Drive the real app once and transcribe everything it rendered."""
    import src.ragbot.generation.pipeline as pipeline

    original = pipeline.Ragbot
    stub = _StubBot()
    stub.chunks = list(chunks or [])
    pipeline.Ragbot = lambda *a, **k: stub
    try:
        at = AppTest.from_file(str(Path(ui.__file__).resolve()), default_timeout=120)
        at.run()
        for button in at.button:
            if button.label.strip().lower() == question.strip().lower():
                button.click()
                at.run()
                break
        else:
            raise AssertionError(f"no starter button labelled {question!r}")
    finally:
        pipeline.Ragbot = original

    out: list[str] = []
    out.append(f"# {title}")
    out.append("")
    out.append(
        f"_Text render of the real `src/ragbot/ui/app.py`, produced by driving it through "
        f"Streamlit's `AppTest`. Answers replayed from the live eval run "
        f"({PROBE['provider']} / {PROBE['model']}), not written by hand. "
        f"Captured {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}._"
    )
    out.append("")
    out.append("---")
    out.append("")
    out.append("## What the user sees")
    out.append("")
    out.append(f"**Page title:** {at.title[0].value if at.title else '-'}")
    out.append("")
    for cap in at.caption:
        if cap.value:
            out.append(f"> {cap.value}")
            out.append("")

    out.append("### Try one of these")
    out.append("")
    for button in at.button:
        if str(button.key or "").startswith("starter::"):
            out.append(f"- `{button.label}`")
    out.append("")

    for info in at.info:
        out.append(f"**Persistent note:** {info.value}")
        out.append("")

    out.append("---")
    out.append("")
    out.append("### Conversation")
    out.append("")
    for msg in at.chat_message:
        role = "user" if msg.name == "user" else "assistant"
        out.append(f"**{role}:**")
        out.append("")
        for md in msg.markdown:
            out.append(f"> {md.value}")
            out.append("")
        for cap in msg.caption:
            if cap.value:
                out.append(f"*{cap.value}*")
                out.append("")
        for err in msg.error:
            out.append(f"ERROR: {err.value}")
            out.append("")
        for exp in msg.expander:
            out.append(f"**{exp.label}**")
            out.append("")
            for c in exp.caption:
                if c.value:
                    out.append(f"*{c.value}*")
                    out.append("")
            for md in exp.markdown:
                out.append(f"**{md.value}**")
                out.append("")
            for t in exp.text:
                out.append("```")
                out.append(t.value)
                out.append("```")
                out.append("")
    return "\n".join(out) + "\n"


def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    # One real retrieval, reused by every answered shot, so the inspector shows
    # the genuine chunk set rather than an empty stand-in.
    real = _real_chunks("Q3")
    shots = [
        ("01_welcome_and_starters.md", "Welcome, three starters, persistent disclaimer", "Q3", real),
        ("02_factual_answer_min_sip.md", "Factual answer: minimum SIP, one link, Last updated", "Q3", real),
        ("03_opinion_refusal.md", "Opinion refusal (Q6) - educational link missing, stated honestly", "Q6", None),
        ("04_out_of_corpus_refusal.md", "Out-of-corpus refusal (Q8) - HDFC Mid Cap", "Q8", None),
        ("05_chunk_inspector.md", "Chunk inspector, expanded", "Q3", real),
    ]
    for filename, title, qid, chunks in shots:
        body = render(title, BY_ID[qid]["question"], chunks=chunks)
        (SHOTS / filename).write_text(body, encoding="utf-8")
        print("wrote", filename)

    index = [
        "# Screenshots — what the UI shows",
        "",
        "**These are text renders, not images.** This machine has no browser and no",
        "screen-capture tooling, so a pixel screenshot of the running Streamlit app could",
        "not be taken without fabricating one. Instead each file below is produced by",
        "**driving the real `src/ragbot/ui/app.py`** through Streamlit's own `AppTest`",
        "— the same harness `tests/unit/test_ui_app.py` uses — and transcribing exactly",
        "what it rendered.",
        "",
        "Every answer in them is replayed from a real eval run against the live index and",
        "a live LLM (`artifacts/sample_qa.md`), so the text, the citation and the date are",
        "the product's actual output rather than a mock-up.",
        "",
        "| File | Shows |",
        "|---|---|",
    ]
    for filename, title, _qid, _c in shots:
        index.append(f"| [`{filename}`]({filename}) | {title} |")
    index += [
        "",
        "---",
        "",
        "## Still missing",
        "",
        "- **Pixel screenshots** of the running app — needs a browser.",
        "- **A ≤3-minute screen recording** — D-1's alternative, and the thing",
        "  `artifacts/demo_script.md` is written for. Needs a human at a screen.",
        "",
        "Both are reported as not done in `artifacts/prd_checklist.md` (items 28 and 35).",
        "No placeholder image has been committed in their place.",
        "",
    ]
    (SHOTS / "README.md").write_text("\n".join(index), encoding="utf-8")
    print("wrote README.md")


if __name__ == "__main__":
    main()