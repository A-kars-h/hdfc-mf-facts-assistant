"""Evaluation harness: the numbers the submission quotes.

Four modules, split by what each one is allowed to decide:

- `dataset` - the FR-34 sample set and its composition guard.
- `checks`  - deterministic checks. No model, ever.
- `judge`   - the M-1 factual-accuracy judge, and only M-1.
- `calibrate` - derives `SIMILARITY_THRESHOLD` from data.
- `runner`  - runs the set, reports M-1..M-7, writes `artifacts/eval_report.md`.

The split is a control, not an organisation preference. If one module could both
score and decide, a metric could be made to pass by editing the thing it measures.
"""

from __future__ import annotations

__all__ = ["checks", "calibrate", "dataset", "judge", "runner"]
