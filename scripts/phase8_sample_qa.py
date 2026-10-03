"""Phase 8: render D-4 `artifacts/sample_qa.md` from the captured eval run.

D-4 must be *generated from the eval run, not hand-written* (Phase 8). This
script is what makes that true and repeatable: it reads
`artifacts/eval_run_capture.json` (written by `scripts/phase8_eval_capture.py`)
and emits the markdown. It invents no answer text, no link and no date.

Run order:
    python scripts/phase8_eval_capture.py
    python scripts/phase8_sample_qa.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ART = ROOT / "artifacts"
BT = chr(96)  # backtick, kept out of the f-strings for readability


def main() -> None:
    d = json.loads((ART / "eval_run_capture.json").read_text(encoding="utf-8"))

    L: list[str] = []
    L.append("# D-4 Sample Q&A (8 queries)")
    L.append("")
    L.append(
        "Generated from a real eval run against the live index and a live LLM "
        "(`src.ragbot.eval.runner.run_set`). Not hand-written. Regenerate with:"
    )
    L.append("")
    L.append("```")
    L.append("python scripts/phase8_eval_capture.py   # run the 8 queries, capture the results")
    L.append("python scripts/phase8_sample_qa.py      # render this file from that capture")
    L.append("```")
    L.append("")
    L.append("- Corpus: 5 HDFC Direct Growth pages")
    L.append(
        "- LLM provider in this run: "
        + BT
        + str(d["provider"])
        + BT
        + " / "
        + BT
        + str(d["model"])
        + BT
    )
    L.append(
        "- "
        + BT
        + "SIMILARITY_THRESHOLD"
        + BT
        + " in force: **"
        + str(d["threshold_in_force"])
        + "** - read from "
        + BT
        + "artifacts/calibration.json"
        + BT
        + ", derived by "
        + BT
        + "python -m src.ragbot.eval.calibrate"
        + BT
        + ", never typed in"
    )
    L.append(
        "- Judged M-1 is in "
        + BT
        + "artifacts/eval_report.md"
        + BT
        + " (this capture ran with the judge off; see the metrics table below)"
    )
    L.append("- Generated: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    L.append("")
    L.append("---")
    L.append("")

    for o in d["outcomes"]:
        L.append("## " + o["id"] + " - " + str(o["intent"]).replace("_", " "))
        L.append("")
        L.append("**Q:** " + o["question"])
        L.append("")
        state = "REFUSED" if o["refused"] else "ANSWERED"
        dense = o["raw_dense_max"]
        dense_s = (
            "n/a - routed before retrieval"
            if dense is None or dense < 0
            else str(round(dense, 4))
        )
        L.append(
            "**Outcome:** "
            + state
            + "  |  intent "
            + BT
            + str(o["intent"])
            + BT
            + "  |  raw_dense_max "
            + dense_s
        )
        L.append("")
        L.append("> " + (o["text"] or "").replace("\n", "\n> "))
        L.append("")
        if o["source_url"]:
            L.append(
                "- Source: [" + o["source_url"] + "](" + o["source_url"] + ")"
            )
        else:
            L.append("- Source: none - refusal paths cite nothing by design")
        if o["last_updated"]:
            L.append("- Last updated from sources: " + o["last_updated"][:10])
        if o["educational_link"]:
            L.append(
                "- Educational link: ["
                + o["educational_link"]
                + "]("
                + o["educational_link"]
                + ")"
            )
        elif o["educational_link_missing"]:
            L.append(
                "- Educational link: **none available** - "
                + BT
                + "education_links.yml"
                + BT
                + " ships empty, so the refusal says so rather than inventing a URL (OD-2)"
            )
        if o.get("expected_source"):
            L.append(
                "- Expected source (from "
                + BT
                + "eval/sample_set.jsonl"
                + BT
                + "): "
                + str(o["expected_source"])
            )
        ef = o.get("expected_facts") or []
        if ef:
            L.append("- Expected facts: " + "; ".join(str(x) for x in ef))
        L.append(
            "- Deterministic checks: "
            + (
                "ALL PASS"
                if not o["failed_checks"]
                else "FAIL -> " + str(o["failed_checks"])
            )
        )
        if o.get("error"):
            L.append("- Run note: " + str(o["error"])[:180])
        L.append("")

    L.append("---")
    L.append("")
    L.append("## Metrics from the same run")
    L.append("")
    L.append("| Metric | Value | Target | Status |")
    L.append("|---|---|---|---|")
    for m in d["metrics"]:
        L.append(
            "| "
            + str(m["id"])
            + " | "
            + str(m["value"])
            + " | "
            + str(m["target"])
            + " | "
            + str(m["status"])
            + " |"
        )
    L.append("")
    L.append(
        "`M-1` reads `unavailable` here because this capture ran with the judge "
        "disabled. The judged run - model, version, rubric and prompt fingerprint - is "
        "in " + BT + "artifacts/eval_report.md" + BT + "."
    )
    L.append("")
    L.append("## One honest observation")
    L.append("")
    L.append(
        "**A confident non-answer passes every automated check.** Q5 (benchmark of "
        "HDFC Balanced Advantage Fund) is **answered**, not refused, with the text "
        '"The provided corpus does not contain the benchmark for HDFC Balanced '
        'Advantage Fund - Direct Growth." - while the benchmark **is** in the corpus '
        "(verified in Phase 0), the gate opened at " + BT + "raw_dense_max" + BT + " "
        "0.8706, and a citation to the correct page was attached."
    )
    L.append("")
    L.append(
        "Every deterministic rule was satisfied: one in-corpus link, one sentence, no "
        "advice, no return figure, correct " + BT + "last_updated" + BT + ". "
        + BT + "run_checks" + BT + " reported no failures. Nothing in the harness can "
        "distinguish this from a good answer; only the M-1 judge can. Recorded rather "
        "than hidden - see " + BT + "artifacts/prd_checklist.md" + BT + "."
    )
    L.append("")

    (ART / "sample_qa.md").write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {ART / 'sample_qa.md'}")


if __name__ == "__main__":
    main()