"""The FR-34 sample set: loader, schema, and a composition guard.

The eight queries are fixed by PRD §9.2 and are committed as JSONL, one object per
line, so the set is diffable and a change to it is visible in review. The
composition - 5 factual, 2 opinion, 1 unanswerable - is not a convention here, it
is enforced: `load_sample_set` raises if the counts drift.

That guard exists because a silent edit to the sample set is the easiest way to
make an evaluation meaningless. Deleting the one unanswerable query, or the two
opinion queries, turns M-3 into a metric over nothing while the report still
prints "M-3: 3/3". The file being in the repo is not protection on its own, because
a reviewer reads the summary table and not the fixture.

`expected_facts` is a conjunction: every string must be present. It serves two
callers with different strictness, deliberately:

- `calibrate.py` requires all of them in the RETRIEVED CONTEXT, which is the
  question "would the right evidence have been available to answer this at all".
- `judge.py` hands them to the judge as the checklist for the §9.1 rubric, which
  is the question "did the ANSWER state them correctly".

Keeping one list for both means the judge and the calibration cannot disagree
about what the right answer to Q1 is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.config import PROJECT_ROOT, Settings
from ..core.errors import CorpusConfigError
from ..core.models import Intent

#: Committed next to the code, not in `data/`. It is a test fixture with a fixed
#: mandated composition, and it travels with the harness that consumes it.
DEFAULT_SAMPLE_SET = Path(__file__).resolve().parent / "sample_set.jsonl"

REQUIRED_FIELDS = ("id", "question", "answerable", "intent", "expected_facts")

#: PRD §9.2. Kept as data so the guard and the doc cannot disagree.
EXPECTED_COMPOSITION = {"factual": 5, "opinion": 2, "unanswerable": 1}
EXPECTED_TOTAL = 8


@dataclass(frozen=True)
class SampleQuery:
    """One row of the sample set."""

    id: str
    question: str
    answerable: bool
    intent: Intent
    expected_source: str | None
    expected_facts: tuple[str, ...]
    note: str = ""

    @property
    def is_factual(self) -> bool:
        return self.intent is Intent.FACTUAL

    @property
    def must_refuse(self) -> bool:
        return not self.answerable

    def facts_present(self, haystack: str) -> tuple[bool, list[str]]:
        """Are ALL expected facts present in `haystack`? Returns (ok, missing)."""
        missing = [f for f in self.expected_facts if f not in haystack]
        return (not missing, missing)


def _coerce(row: dict[str, Any], path: Path, n: int) -> SampleQuery:
    where = f"{path.name} line {n}"
    for field in REQUIRED_FIELDS:
        if field not in row:
            raise CorpusConfigError(f"{where}: missing required field {field!r}")
    try:
        intent = Intent(str(row["intent"]))
    except ValueError as exc:
        raise CorpusConfigError(
            f"{where}: intent must be one of {[i.value for i in Intent]}, "
            f"got {row['intent']!r}"
        ) from exc
    facts = row["expected_facts"]
    if not isinstance(facts, list) or not all(isinstance(f, str) for f in facts):
        raise CorpusConfigError(f"{where}: expected_facts must be a list of strings")
    if intent is Intent.FACTUAL and not facts:
        raise CorpusConfigError(
            f"{where}: a factual row with no expected_facts is unscoreable - the "
            f"judge has no checklist and calibration has no correctness signal"
        )
    if not row["answerable"] and intent is Intent.FACTUAL and row.get("expected_source"):
        # A row that expects a source but declares itself unanswerable is
        # self-contradictory and would quietly inflate M-2.
        raise CorpusConfigError(
            f"{where}: expected_source is set but answerable is false"
        )
    return SampleQuery(
        id=str(row["id"]),
        question=str(row["question"]),
        answerable=bool(row["answerable"]),
        intent=intent,
        expected_source=row.get("expected_source"),
        expected_facts=tuple(facts),
        note=str(row.get("note", "")),
    )


def load_sample_set(
    path: Path | str | None = None, settings: Settings | None = None
) -> list[SampleQuery]:
    """Load the sample set and enforce the PRD §9.2 composition."""
    s = settings or Settings()
    p = Path(path) if path is not None else DEFAULT_SAMPLE_SET
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    if not p.exists():
        raise CorpusConfigError(
            f"{p} not found. It is committed; restore it from version control."
        )

    rows: list[SampleQuery] = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CorpusConfigError(f"{p.name} line {n}: invalid JSON: {exc}") from exc
        rows.append(_coerce(row, p, n))

    _guard_composition(rows, p)
    return rows


def _guard_composition(rows: list[SampleQuery], path: Path) -> None:
    if len(rows) != EXPECTED_TOTAL:
        raise CorpusConfigError(
            f"{path.name} has {len(rows)} queries; PRD §9.2 fixes it at "
            f"{EXPECTED_TOTAL} (5 factual, 2 opinion, 1 unanswerable)"
        )
    seen: set[str] = set()
    for row in rows:
        if row.id in seen:
            raise CorpusConfigError(f"{path.name}: duplicate id {row.id!r}")
        seen.add(row.id)

    counts: dict[str, int] = {"factual": 0, "opinion": 0, "unanswerable": 0}
    for row in rows:
        if row.answerable:
            counts["factual"] += 1
        else:
            counts[row.intent.value if row.intent is not Intent.OUT_OF_SCOPE else "unanswerable"] += 1
    if counts != EXPECTED_COMPOSITION:
        raise CorpusConfigError(
            f"{path.name} composition is {counts}; PRD §9.2 mandates "
            f"{EXPECTED_COMPOSITION}. Editing the sample set is legitimate, but "
            f"silently changing what M-3 measures is not."
        )


def sample_set_path(settings: Settings | None = None) -> Path:
    return DEFAULT_SAMPLE_SET


def factual(rows: list[SampleQuery]) -> list[SampleQuery]:
    return [r for r in rows if r.answerable]


def refusals(rows: list[SampleQuery]) -> list[SampleQuery]:
    return [r for r in rows if r.must_refuse]
