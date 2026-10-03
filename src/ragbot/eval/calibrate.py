"""Derive `SIMILARITY_THRESHOLD` from data. No threshold is ever written by hand.

The gate reads raw dense cosine, pre-fusion (invariant 5). That number is a
property of the *query and the index* - it does not depend on the chat model, on
the prompt, or on whether a provider is configured at all. So the sweep below runs
in full with `LLM_PROVIDER=none`, which is why the threshold can be calibrated and
committed in a phase where no answer can yet be generated.

**Retrieval happens once, and the sweep replays the gate over the cached scores.**
The alternative - re-running retrieval per threshold - is 96 loads of a 90 MB
embedding model for arithmetic, and it invites the mistake of letting the
threshold change which candidates come back. It cannot: `retrieve()` is upstream
of the gate by construction, and `SearchResult.raw_dense_max` is captured in the
dense leg before fusion. Replaying is not an optimisation, it is the reason the
sweep is trustworthy.

Selection rule: **the midpoint of the widest feasible interval.**

Feasibility is `max(hard-negative probe raw_dense_max) < threshold <=
min(factual raw_dense_max)`. Pick the midpoint rather than an edge because the
objective is to be as far as possible from both failure modes, and an edge
threshold is one rounding difference away from answering "not in the data" to a
question the corpus answers perfectly. Deriving the interval arithmetically rather
than by scanning a grid means the chosen value does not depend on the grid
resolution, and the curve is emitted for inspection rather than for selection.

**The negative class comes from `calibration_probes.jsonl`, not from the sample
set, and that is not a convenience.** The eight FR-34 queries include three
must-refuse cases, but all three are refused by *intent routing* before retrieval
ever runs: two opinions and one non-corpus scheme of our own AMC. They are
therefore invisible to the gate, and if they were used as the negative class the
upper bound would be minus infinity - the sweep would report a false-answer rate of
zero at every threshold and the chosen value would be constrained by nothing at
all. A threshold with no negative class is a one-sided rule, not a boundary. The
probes supply the missing class: genuine HDFC products that are not in the corpus
and are phrased to *pass* routing, so the gate has to reject them on similarity
alone. They are the hardest negatives obtainable without editing the corpus - same
AMC, same field vocabulary, same page structure as a real corpus question, differing
only in the product name - and they are excluded from M-1..M-7 so they can never
inflate a product metric.

Three honesty rules, all of which came from how this harness could have lied:

- **Separation and evidence are separate findings.** Whether the gate opens is a
  threshold question. Whether the *right evidence* is in the retrieved context is
  not - no threshold can fix a query that never retrieves its own answer. If a
  factual query's expected facts are missing from its context, that is reported as
  a retrieval defect and NOT quietly absorbed into a threshold choice, because
  "the threshold is fine" and "the threshold can be fine" are different claims.

- **A metric that cannot be measured is reported as such.** The sweep's M-1
  column is a retrieval-level proxy, named as one, and is never printed as "M-1".
  The judged M-1 belongs to `runner.py`, and the two are shown separately so a
  reader can never mistake the proxy for the metric.

- **A routing refusal is not a gate success.** The sweep reports the sample
  false-answer rate and the probe false-answer rate in separate columns, because
  the first is identically zero by construction while only the second measures the
  threshold. Collapsing them into one "false answers" figure would report a clean
  0.00 that says nothing about the number it appears to describe.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ..core.config import Settings
from ..core.errors import CorpusConfigError
from ..core.models import Intent
from ..retrieval.search import HybridSearcher, SearchResult
from .dataset import SampleQuery, load_sample_set

log = logging.getLogger(__name__)

#: Selection rule name, recorded in calibration.json so a reader knows HOW the
#: number was chosen and not just what it is.
SELECTION_RULE = "midpoint-of-widest-feasible-interval"

#: The emitted curve. Fine enough to read the shape of the trade-off, coarse
#: enough that the file stays diffable.
SWEEP_START = 0.0
SWEEP_STOP = 0.95
SWEEP_STEP = 0.01

#: M-1 target from PRD §8, as a fraction of the rubric maximum.
M1_TARGET = 1.6 / 2.0


@dataclass(frozen=True)
class Probe:
    """A calibration-only hard negative.

    Deliberately NOT part of the FR-34 sample set and never counted in M-1..M-7.
    The sample set measures the product; these measure the THRESHOLD. The
    distinction matters because the sample set cannot supply a gate-routed
    negative on its own: once the router recognises a non-corpus scheme of our own
    AMC, all three of its refusals are routing refusals, and the gate is left with
    no counter-example to be separated from. A threshold calibrated with no
    negative class is one-sided, and a one-sided threshold is not a boundary.
    """

    id: str
    question: str
    note: str = ""


def load_probes(path: Path | None = None) -> list[Probe]:
    p = path or (Path(__file__).resolve().parent / "calibration_probes.jsonl")
    out: list[Probe] = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CorpusConfigError(f"{p.name} line {n}: invalid JSON: {exc}") from exc
        out.append(Probe(id=str(row["id"]), question=str(row["question"]),
                         note=str(row.get("note", ""))))
    if not out:
        raise CorpusConfigError(
            f"{p.name} is empty. Calibration with no hard negatives is one-sided; "
            f"see the module docstring."
        )
    return out


@dataclass
class Observation:
    """What one query did at retrieval time, independent of any threshold."""

    id: str
    question: str
    intent: Intent
    answerable: bool
    raw_dense_max: float
    #: True when the query is decided by intent routing, so the gate never sees it
    #: and NO threshold value can change its outcome.
    gate_routed: bool
    facts_in_context: bool
    missing_facts: list[str] = field(default_factory=list)
    page_ids: list[str] = field(default_factory=list)
    rule: str = ""
    #: "sample" (counted in M-1..M-7) or "probe" (calibration only).
    origin: str = "sample"

    @property
    def gate_opens_at(self) -> float | None:
        """The inclusive lower bound on threshold for the gate to open, if it ever does."""
        if self.gate_routed:
            return None
        return self.raw_dense_max

    @property
    def is_gate_negative(self) -> bool:
        """A query the gate must CLOSE: unanswerable, and actually reaching the gate."""
        return not self.answerable and not self.gate_routed


def observe(
    rows: Sequence[SampleQuery],
    searcher: HybridSearcher | None = None,
    settings: Settings | None = None,
    *,
    probes: Sequence[Probe] | None = None,
) -> list[Observation]:
    """Run retrieval once per query and record everything threshold-independent."""
    s = settings or Settings()
    searcher = searcher or HybridSearcher(s)
    out: list[Observation] = []
    # The expected facts live on the sample row, so the lookup is by id and the
    # real row is used. Rebuilding a row with empty `expected_facts` would make
    # `facts_present` vacuously true and every query would look answered - a
    # check that cannot fail is not a check, and the vacuous version reported
    # Q5 as OK when its benchmark was genuinely absent.
    by_id = {r.id: r for r in rows}
    work: list[tuple[str, str, bool, str]] = [
        (r.id, r.question, r.answerable, "sample") for r in rows
    ]
    work += [(p.id, p.question, False, "probe") for p in (probes or [])]

    for qid, question, answerable, origin in work:
        result: SearchResult = searcher.retrieve(question)
        # A non-factual question is refused by routing before retrieval, so it
        # has no candidates and its dense score is meaningless. Recording it as
        # 0.0 would be a lie the sweep could act on; `gate_routed` marks it
        # threshold-independent instead.
        gate_routed = result.intent is not Intent.FACTUAL
        context = "\n".join(c.chunk.text for c in result.candidates)
        ok, missing = (True, [])
        if answerable:
            sample = by_id.get(qid)
            if sample is None:  # pragma: no cover - defensive
                raise CorpusConfigError(
                    f"no sample row for answerable query {qid!r}; expected facts "
                    f"cannot be checked without one"
                )
            ok, missing = sample.facts_present(context)
        out.append(
            Observation(
                id=qid,
                question=question,
                intent=result.intent,
                answerable=answerable,
                raw_dense_max=result.raw_dense_max,
                gate_routed=gate_routed,
                facts_in_context=ok,
                missing_facts=missing,
                page_ids=sorted({c.chunk.page_id for c in result.candidates}),
                rule=result.intent_match.rule,
                origin=origin,
            )
        )
        log.info(
            "observed %s (%s) intent=%s rule=%s raw_dense_max=%.4f gate_routed=%s facts=%s",
            qid, origin, result.intent.value, result.intent_match.rule,
            result.raw_dense_max, gate_routed, ok,
        )
    return out


# --- replaying the gate over cached scores ------------------------------

@dataclass(frozen=True)
class SweepPoint:
    """Metrics at one candidate threshold."""

    threshold: float
    #: Sample factual queries the gate would admit, with their facts in context.
    #: This is the RETRIEVAL-LEVEL PROXY for M-1, not M-1.
    answerable_with_evidence: int
    #: Sample factual queries the gate would admit but whose facts are absent: the
    #: dangerous case, because the model would answer from the wrong context.
    unsupported: int
    #: Sample refusal queries correctly refused.
    refusals_correct: int
    #: Sample refusal queries the system would answer. Must be 0.
    false_answers: int
    #: Calibration probes the gate would wrongly admit. The threshold's real
    #: false-answer rate, because every sample refusal is routing-refused and so
    #: contributes zero to it at any threshold.
    probe_false_answers: int
    factual_total: int
    refusal_total: int
    probe_total: int

    @property
    def m1_proxy(self) -> float | None:
        if not self.factual_total:
            return None
        return self.answerable_with_evidence / self.factual_total

    @property
    def m3(self) -> float | None:
        if not self.refusal_total:
            return None
        return self.refusals_correct / self.refusal_total

    @property
    def probe_false_answer_rate(self) -> float | None:
        if not self.probe_total:
            return None
        return self.probe_false_answers / self.probe_total


def evaluate_threshold(obs: Sequence[Observation], threshold: float) -> SweepPoint:
    """Replay the gate at `threshold`. Mirrors `gate.decide` exactly.

    `gate.decide` opens when `raw_dense_max >= threshold`; the mirror has to be
    the same comparison, not an approximation of it, or the sweep is measuring a
    gate that does not exist.
    """
    answered_with_evidence = 0
    unsupported = 0
    refusals_correct = 0
    false_answers = 0
    factual_total = 0
    refusal_total = 0
    probe_false = 0
    probe_total = 0

    for o in obs:
        if o.origin == "probe":
            probe_total += 1
            # A probe that routing already refuses is not a threshold failure.
            if not o.gate_routed and o.raw_dense_max >= threshold:
                probe_false += 1
            continue
        if o.answerable:
            factual_total += 1
            if not o.gate_routed and o.raw_dense_max >= threshold:
                if o.facts_in_context:
                    answered_with_evidence += 1
                else:
                    unsupported += 1
        else:
            refusal_total += 1
            if o.gate_routed:
                # Refused by intent routing. No threshold reaches this query.
                refusals_correct += 1
            elif o.raw_dense_max < threshold:
                refusals_correct += 1
            else:
                false_answers += 1

    return SweepPoint(
        threshold=round(threshold, 6),
        answerable_with_evidence=answered_with_evidence,
        unsupported=unsupported,
        refusals_correct=refusals_correct,
        false_answers=false_answers,
        probe_false_answers=probe_false,
        factual_total=factual_total,
        refusal_total=refusal_total,
        probe_total=probe_total,
    )


def sweep(
    obs: Sequence[Observation],
    *,
    start: float = SWEEP_START,
    stop: float = SWEEP_STOP,
    step: float = SWEEP_STEP,
) -> list[SweepPoint]:
    n = int(round((stop - start) / step)) + 1
    return [evaluate_threshold(obs, start + i * step) for i in range(max(n, 1))]


# --- selection ----------------------------------------------------------

@dataclass
class Decision:
    """The chosen threshold and the reasoning that produced it."""

    threshold: float | None
    rule: str
    feasible: bool
    lower_bound: float | None
    upper_bound: float | None
    rationale: str
    evidence_failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def choose(obs: Sequence[Observation]) -> Decision:
    """Pick the threshold. Fails loudly rather than inventing a number."""
    notes: list[str] = []

    # Evidence condition, threshold-independent.
    evidence_failures = [
        f"{o.id}: expected facts absent from retrieved context ({', '.join(o.missing_facts)})"
        for o in obs
        if o.origin == "sample" and o.answerable and not o.facts_in_context
    ]
    if evidence_failures:
        notes.append(
            "One or more factual queries do not retrieve their own answer. No "
            "threshold can fix that; it is a retrieval defect and is reported "
            "separately rather than absorbed into the threshold choice."
        )

    # Separation condition: the exact continuous feasible interval.
    #
    # The negative bound comes from the calibration probes, NOT from the sample
    # set's refusals. Every sample refusal is decided by intent routing, so
    # including them would put an upper bound of -infinity on the threshold - the
    # sweep would report a perfect false-answer rate at every value and the
    # chosen threshold would be constrained by nothing at all.
    negatives = [o for o in obs if o.is_gate_negative and o.origin == "probe"]
    routed_samples = [o.id for o in obs if o.origin == "sample" and not o.answerable and o.gate_routed]
    facts = [o.raw_dense_max for o in obs if o.answerable and not o.gate_routed]

    if routed_samples:
        notes.append(
            f"{len(routed_samples)} sample refusal quer"
            f"{'y is' if len(routed_samples) == 1 else 'ies are'} ({', '.join(routed_samples)}) "
            f"refused by intent routing before retrieval, so no threshold value can change "
            f"their outcome. They count towards M-3 but place NO bound on the threshold, "
            f"which is why the false-answer rate below is measured on the calibration "
            f"probes instead."
        )

    if not negatives or not facts:
        return Decision(
            threshold=None,
            rule=SELECTION_RULE,
            feasible=False,
            lower_bound=None,
            upper_bound=None,
            rationale=(
                "Cannot calibrate: "
                + ("no gate-routed negative probe " if not negatives else "")
                + ("no factual query." if not facts else "")
                + " Without both classes there is nothing to separate, and a "
                "one-sided threshold is not a boundary."
            ),
            evidence_failures=evidence_failures,
            notes=notes,
        )

    r = max(o.raw_dense_max for o in negatives)  # threshold must EXCEED this
    f = min(facts)                               # threshold must not EXCEED this
    lower, upper = r, f

    if r >= f:
        worst = max(negatives, key=lambda o: o.raw_dense_max)
        return Decision(
            threshold=None,
            rule=SELECTION_RULE,
            feasible=False,
            lower_bound=lower,
            upper_bound=upper,
            rationale=(
                f"NO threshold separates the classes. The hardest negative probe "
                f"{worst.id} (\"{worst.question}\") scores {r:.4f}, at or above the "
                f"easiest factual question's {f:.4f}. Every value that closes the "
                f"negative also closes a real question. This is a retrieval "
                f"separability failure, not a tuning problem, and no number is written."
            ),
            evidence_failures=evidence_failures,
            notes=notes,
        )

    threshold = round((r + f) / 2.0, 4)
    margin = (f - r) / 2.0
    notes.append(
        f"Chosen midpoint sits {margin:.4f} from both failure boundaries "
        f"(closes the gate up to {r:.4f}, opens it from {f:.4f}), so it is the "
        f"value furthest from either failure in the feasible interval."
    )
    return Decision(
        threshold=threshold,
        rule=SELECTION_RULE,
        feasible=True,
        lower_bound=lower,
        upper_bound=upper,
        rationale=(
            f"Feasible interval ({lower:.4f}, {upper:.4f}]: above {lower:.4f} the "
            f"gate closes on the hardest negative probe, at or below {upper:.4f} it "
            f"opens on the easiest factual question. Midpoint {threshold:.4f}."
        ),
        evidence_failures=evidence_failures,
        notes=notes,
    )


# --- artefacts ----------------------------------------------------------

def _fmt_curve(curve: list[SweepPoint]) -> str:
    """Markdown table plus a text bar chart, so the trade-off is inspectable."""
    lines = [
        "| threshold | factual answered w/ evidence | unsupported | sample refusals correct | "
        "sample false answers | probe false answers | M-1 proxy* | M-3 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in curve:
        m1 = "-" if p.m1_proxy is None else f"{p.m1_proxy:.2f}"
        m3 = "-" if p.m3 is None else f"{p.m3:.2f}"
        lines.append(
            f"| {p.threshold:.2f} | {p.answerable_with_evidence}/{p.factual_total} "
            f"| {p.unsupported} | {p.refusals_correct}/{p.refusal_total} "
            f"| {p.false_answers} | {p.probe_false_answers}/{p.probe_total} "
            f"| {m1} | {m3} |"
        )

    # A bar per 0.05, because 96 rows of table is the data and 20 rows of chart is
    # the shape. '#' = factual answered with evidence, 'x' = a false answer,
    # 'o' = a probe wrongly admitted.
    width = max(
        (p.factual_total + p.probe_total for p in curve), default=1
    )
    lines += [
        "",
        "Trade-off curve (every 0.05; `#` factual answered with evidence, "
        "`o` probe wrongly admitted, `x` sample false answer, `!` unsupported):",
        "",
        "```",
    ]
    for p in curve:
        if abs((p.threshold * 100) % 5.0) > 1e-6:
            continue
        bar = (
            "#" * p.answerable_with_evidence
            + "o" * p.probe_false_answers
            + "x" * p.false_answers
            + "!" * p.unsupported
        )
        lines.append(f"{p.threshold:5.2f} |{bar:<{max(width, 1)}}|")
    lines.append("```")
    lines.append("")
    lines.append(
        "*M-1 proxy is the share of factual queries the gate would admit *and* whose "
        "key facts are in the retrieved context. It is **not** M-1, which is a judged "
        "0-2 rubric score reported by `runner.py`."
    )
    lines.append("")
    lines.append(
        "The `sample false answers` column is 0 at every threshold by construction: "
        "all three sample refusals are decided by intent routing before retrieval. "
        "The `probe false answers` column is the threshold's real false-answer rate."
    )
    return "\n".join(lines)


def write_calibration(
    decision: Decision,
    obs: Sequence[Observation],
    curve: list[SweepPoint],
    settings: Settings,
    path: Path | None = None,
) -> Path:
    """Write artifacts/calibration.json, the file the gate reads at runtime.

    `Settings.require_similarity_threshold()` falls back to this file's
    `similarity_threshold` key when the env var is unset, so writing it here IS
    how the value reaches config - there is no second copy to keep in sync, and
    no `.env` edit for a value that would then silently disagree with this file.
    """
    target = path or settings.calibration_file
    target.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "embedding_model": settings.embedding_model,
        "top_k": settings.top_k,
        "similarity_threshold": decision.threshold,
        "selection_rule": decision.rule,
        "feasible": decision.feasible,
        "bounds": {
            "hard_negative_dense_max": decision.lower_bound,
            "factual_dense_min": decision.upper_bound,
        },
        "rationale": decision.rationale,
        "evidence_failures": decision.evidence_failures,
        "notes": decision.notes,
        "per_query": [
            {
                "id": o.id,
                "question": o.question,
                # "sample" queries are FR-34 and counted in M-1..M-7. "probe"
                # queries are calibration-only and are deliberately excluded from
                # every product metric, so a reader can never count them twice.
                "origin": o.origin,
                "intent": o.intent.value,
                "answerable": o.answerable,
                "rule": o.rule,
                "raw_dense_max": o.raw_dense_max,
                "gate_routed": o.gate_routed,
                "facts_in_context": o.facts_in_context,
                "missing_facts": o.missing_facts,
                "page_ids": o.page_ids,
            }
            for o in obs
        ],
        "curve": [asdict(p) for p in curve],
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def render_report(
    decision: Decision,
    obs: Sequence[Observation],
    curve: list[SweepPoint],
    settings: Settings,
    path: Path,
) -> str:
    """The calibration section of artifacts/eval_report.md."""
    lines = [
        "## Threshold calibration",
        "",
        f"- **Chosen `SIMILARITY_THRESHOLD`: "
        f"{'**' + format(decision.threshold, '.4f') + '**' if decision.threshold is not None else '**NONE - see below**'}**",
        f"- Selection rule: `{decision.rule}`",
        f"- Feasible: {'yes' if decision.feasible else 'NO'}",
        f"- Written to: `{path.as_posix()}`",
        "",
        decision.rationale,
        "",
        "### Per-query retrieval at the gate input",
        "",
        "`origin` is `sample` for the eight FR-34 queries, which are the only ones "
        "counted in M-1..M-7. `origin` is `probe` for calibration-only hard "
        "negatives: real HDFC products that are absent from the corpus, phrased to "
        "reach the gate. They exist because all three sample refusals are refused "
        "by intent routing *before* retrieval, which leaves the threshold with no "
        "counter-example and therefore no upper bound to be calibrated against.",
        "",
        "| id | origin | intent | rule | raw_dense_max | gate-routed | key facts in context |",
        "|---|---|---|---|---|---|---|",
    ]
    for o in obs:
        lines.append(
            f"| {o.id} | {o.origin} | {o.intent.value} | `{o.rule}` | {o.raw_dense_max:.4f} "
            f"| {'yes' if o.gate_routed else 'no'} "
            f"| {'-' if not o.answerable else ('yes' if o.facts_in_context else 'NO - ' + ', '.join(o.missing_facts))} |"
        )
    if decision.evidence_failures:
        lines += ["", "**Retrieval defects (no threshold can fix these):**", ""]
        lines += [f"- {f}" for f in decision.evidence_failures]
    if decision.notes:
        lines += ["", "**Notes:**", ""] + [f"- {n}" for n in decision.notes]
    lines += ["", _fmt_curve(curve), ""]
    return "\n".join(lines)


# --- CLI ----------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m src.ragbot.eval.calibrate",
        description="Derive SIMILARITY_THRESHOLD from the sample set.",
    )
    parser.add_argument("--sample-set", default=None, help="path to sample_set.jsonl")
    parser.add_argument("--probes", default=None, help="path to calibration_probes.jsonl")
    parser.add_argument("--no-write", action="store_true", help="report only, write nothing")
    parser.add_argument("--report", default=None, help="also write the calibration section here")
    args = parser.parse_args(argv)

    settings = get_settings_safe()
    rows = load_sample_set(args.sample_set, settings)
    probes = load_probes(Path(args.probes) if args.probes else None)
    print(f"sample set: {len(rows)} queries "
          f"({sum(r.answerable for r in rows)} factual, "
          f"{sum(r.must_refuse for r in rows)} must-refuse)")
    print(f"calibration probes: {len(probes)} hard negatives (excluded from M-1..M-7)")

    obs = observe(rows, settings=settings, probes=probes)
    curve = sweep(obs)
    decision = choose(obs)

    print()
    for o in obs:
        flag = "routed" if o.gate_routed else ("facts-ok" if o.facts_in_context else "FACTS-MISSING")
        kind = "" if o.origin == "sample" else f"  [{o.origin}]"
        print(f"  {o.id:>3}  {o.intent.value:<13} raw_dense_max={o.raw_dense_max:7.4f}  {flag}{kind}")

    print()
    print(decision.rationale)
    for n in decision.notes:
        print(f"  note: {n}")
    for f in decision.evidence_failures:
        print(f"  DEFECT: {f}")

    if decision.threshold is None:
        print()
        print("No threshold written. Calibration is infeasible; see the report.")
        if args.report:
            Path(args.report).write_text(
                render_report(decision, obs, curve, settings, settings.calibration_file),
                encoding="utf-8",
            )
        return 2

    if not args.no_write:
        path = write_calibration(decision, obs, curve, settings)
        print()
        print(f"wrote {path}")
        print(f"SIMILARITY_THRESHOLD={decision.threshold}")

    if args.report:
        p = Path(args.report)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            render_report(decision, obs, curve, settings, settings.calibration_file),
            encoding="utf-8",
        )
        print(f"wrote {p}")
    return 0


def get_settings_safe() -> Settings:
    from ..core.config import get_settings

    return get_settings()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
