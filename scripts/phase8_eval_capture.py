"""Phase 8: capture a real eval run to JSON, the provenance for `sample_qa.md`.

`artifacts/sample_qa.md` must be generated from an eval run rather than written
by hand (Phase 8, D-4). This script produces the machine-readable capture that
`artifacts/sample_qa.md` and `scripts/phase8_screenshots.py` both read, so those
two deliverables cannot drift from the run that produced them.

Nothing here changes product behaviour: it calls the same
`src.ragbot.eval.runner.run_set` the `python -m src.ragbot.eval` CLI calls, and
writes one extra file. The judge is disabled because M-1 requires a provider call
per factual query and the judged numbers are already recorded, with model and
version, in `artifacts/eval_report.md`.

Usage:  python scripts/phase8_eval_capture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ragbot.core.config import Settings  # noqa: E402
from src.ragbot.eval.dataset import load_sample_set  # noqa: E402
from src.ragbot.eval.runner import compute_metrics, run_set  # noqa: E402

OUT = ROOT / "artifacts" / "eval_run_capture.json"


def main() -> None:
    settings = Settings()
    rows = load_sample_set(None, settings)
    outcomes = run_set(rows, settings, judge_enabled=False)
    metrics = compute_metrics(outcomes)

    payload = {
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "threshold_in_force": settings.require_similarity_threshold(),
        "judge_enabled": False,
        "outcomes": [
            {
                "id": o.id,
                "question": o.sample.question,
                "intent": o.sample.intent.value,
                "answerable": o.sample.answerable,
                "must_refuse": o.sample.must_refuse,
                "expected_source": o.sample.expected_source,
                "expected_facts": o.sample.expected_facts,
                "refused": o.answer.refused if o.answer else None,
                "text": o.answer.text if o.answer else None,
                "source_url": o.answer.source_url if o.answer else None,
                "last_updated": (
                    o.answer.last_updated.isoformat()
                    if o.answer and o.answer.last_updated
                    else None
                ),
                "educational_link": o.answer.educational_link if o.answer else None,
                "educational_link_missing": (
                    o.answer.educational_link_missing if o.answer else None
                ),
                "validation": o.answer.validation if o.answer else None,
                "raw_dense_max": o.observation.raw_dense_max if o.observation else None,
                "failed_checks": list(o.failed_checks()),
                "error": o.error,
            }
            for o in outcomes
        ],
        "metrics": [m.to_dict() for m in metrics],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT}  ({len(outcomes)} queries)")


if __name__ == "__main__":
    main()