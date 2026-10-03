"""Run the FR-34 sample set and report M-1 through M-7.

Every metric here carries an explicit denominator, because PRD §8 opens with "every
metric has an explicit denominator, taken from the FR-34 sample set". A bare
"M-3: 3/3" invites the reader to assume a denominator of 3 that happens to be the
whole set, and hides the case where it is not.

Which layer scores which metric, and why that split is not negotiable:

- **M-1 is judged.** "Is this answer factually right" is the one question a regex
  cannot settle. `judge.py` grades it against the PRD §9.1 rubric and records the
  model, the rubric version and a hash of the prompt.
- **M-2 and M-4 through M-7 are deterministic.** PRD §8.1 forbids routing them
  through a judge, and `checks.py` re-derives those rules independently of the
  product's own output screens so the metric is capable of failing.

**A metric that could not be measured is reported as `unavailable`, never as a
number.** With `LLM_PROVIDER=none` the five factual questions retrieve and pass the
gate but cannot be generated, so M-1, M-2, M-6 and M-7 have no answer to inspect.
Printing a plausible-looking figure for them, or quietly shrinking the
denominator to the 3 refusals and reporting "M-6: 3/3", would be the exact failure
this harness exists to detect. M-3 and the leakage counts are measured in full
without a provider, because refusals never call a model.

Latency is reported per PRD §9.4 as median and max with n, and deliberately not as
a p95: with n=8 a p95 is the maximum wearing a hat.
"""

from __future__ import annotations

import logging
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ..core.config import PROJECT_ROOT, Settings
from ..core.models import Answer, Intent
from ..generation.llm import LLMClient, LLMUnavailable, build_client
from ..generation.pipeline import Ragbot
from ..retrieval.search import HybridSearcher, SearchResult
from . import checks as checks_mod
from . import judge as judge_mod
from .calibrate import Observation, observe
from .dataset import SampleQuery, load_sample_set

log = logging.getLogger(__name__)

#: The report path. `artifacts/`, beside the manifest and the calibration.
REPORT_PATH = Path("artifacts/eval_report.md")

STATUS_MEASURED = "measured"
STATUS_UNAVAILABLE = "unavailable"


@dataclass
class Metric:
    """One metric, with the denominator stated rather than implied."""

    id: str
    name: str
    target: str
    numerator: int | None = None
    denominator: int | None = None
    status: str = STATUS_MEASURED
    detail: str = ""
    #: Set for metrics whose unit is not a fraction, e.g. M-1's mean rubric score.
    display: str | None = None

    @property
    def value(self) -> str:
        if self.status != STATUS_MEASURED:
            return "n/a"
        if self.display is not None:
            return self.display
        if self.denominator is None:
            return "n/a"
        return f"{self.numerator}/{self.denominator}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "target": self.target,
            "value": self.value,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class QueryOutcome:
    """What happened to one query, end to end."""

    sample: SampleQuery
    answer: Answer | None
    observation: Observation | None
    search: SearchResult | None
    results: list[checks_mod.CheckResult] = field(default_factory=list)
    verdict: judge_mod.JudgeVerdict | None = None
    latency_ms: float = 0.0
    error: str | None = None

    @property
    def id(self) -> str:
        return self.sample.id

    @property
    def refused(self) -> bool:
        return bool(self.answer and self.answer.refused)

    @property
    def answered(self) -> bool:
        return self.answer is not None and not self.answer.refused

    def failed_checks(self) -> list[checks_mod.CheckResult]:
        return [r for r in self.results if not r.passed]

    def evidence(self, max_chars: int) -> str:
        if not self.search:
            return ""
        return "\n".join(c.chunk.text for c in self.search.candidates)[:max_chars]


# --- running the set ----------------------------------------------------

#: Suffixes of artifacts the pipeline GENERATES, and which a question can
#: therefore reach. The corpus dumps (`chunks.txt`, `embeddings.txt`) are
#: deliberately not here - see `_storage_paths`.
_GENERATED_ARTIFACT_SUFFIXES = frozenset({".json", ".md"})


def _storage_paths(settings: Settings) -> list[str]:
    """Generated text artifacts the PII check reads.

    **The scope line: a file is in scope iff it is a SINK for text derived from a
    user's question.** That puts the run's own outputs in scope and the corpus out
    of it, and the distinction is by KIND, never by whether a file happens to pass.

    - **In:** `manifest.json`, `calibration.json`, `eval_report.md`. These are
      written by the pipeline, and `eval_report.md` embeds the questions and the
      answers verbatim - so a question carrying a PAN would be visible here. This
      is the check doing real work.
    - **Out: `data/raw/*.html`** - the fetched third-party corpus, which is the
      system's INPUT, not a sink. Groww pages carry HDFC's own published contact
      addresses and Next.js bundle hashes, and the detector correctly reports
      email/account/phone shapes in them. Those are not user PII. Including this
      directory failed `pii_absent` on all 8 queries for that reason alone, which
      made M-3 permanently red and told us nothing.
    - **Out: `chunks.txt` / `embeddings.txt`** - dumps of the corpus-derived index
      written by `tools/dump_index.py`. Their `chunk_id=` and `content_hash`
      values are 32-hex strings, which the account and phone detectors match. They
      contain no question text, so they cannot contain user PII.
    - **Out: `data/chroma/*`, `data/bm25.pkl`** - the vector store. Corpus-derived
      by construction, and binary, so grepping it for text patterns is
      meaningless. Phase 5 owns this invariant instead:
      `test_ingest_paths_are_not_reachable_from_a_question` proves a question
      cannot reach the writer, and `test_no_detector_fires_on_any_real_corpus_chunk`
      runs the detector over every real chunk.
    - **Logs: there is no log file to read.** `core.logging.setup_logging` attaches
      a stdout handler and nothing else, so nothing lands on disk. Phase 5 covers
      the stream itself with `test_no_secret_reaches_the_log`.

    Excluding a file is only sound while the exclusion is principled, so the check
    must remain capable of failing. `test_pii_absent_fails_on_a_planted_secret`
    plants a real PAN in an in-scope artifact and asserts the check rejects it.
    """
    base = settings.manifest_file.parent
    if not base.is_dir():
        return []
    return [
        str(p)
        for p in sorted(base.glob("*"))
        if p.is_file() and p.suffix.lower() in _GENERATED_ARTIFACT_SUFFIXES
    ]


def run_set(
    rows: Sequence[SampleQuery],
    settings: Settings | None = None,
    *,
    searcher: HybridSearcher | None = None,
    client: LLMClient | None = None,
    judge_enabled: bool = True,
) -> list[QueryOutcome]:
    """Ask every query through the real orchestrator and check the result.

    The searcher is built once and injected into the `Ragbot`, so the 90 MB
    embedding model is loaded a single time for the whole set. It is retrieved
    from twice per factual query - once here, to obtain the evidence and the
    retrieved page ids that M-2 and the judge need, and once inside `ask()`.
    Only the query is re-embedded, which is milliseconds; reloading the model per
    query would be minutes.
    """
    s = settings or Settings()
    searcher = searcher or HybridSearcher(s)
    bot = Ragbot(settings=s, searcher=searcher)
    storage = _storage_paths(s)
    outcomes: list[QueryOutcome] = []

    # One retrieval pass for everything threshold-independent, so the report can
    # show raw_dense_max and the evidence position without a second walk.
    observations = {o.id: o for o in observe(rows, searcher=searcher, settings=s)}

    llm_error: str | None = None
    if judge_enabled and client is None:
        try:
            client = build_client(s)
        except (LLMUnavailable, Exception) as exc:  # noqa: BLE001
            # Recorded, not raised. A missing provider makes M-1 unmeasurable; it
            # does not invalidate M-3, and it must not abort the run.
            llm_error = f"{type(exc).__name__}: {exc}"
            log.warning("no LLM client for the judge: %s", llm_error)

    for row in rows:
        search = None
        try:
            search = searcher.retrieve(row.question)
        except Exception as exc:  # noqa: BLE001
            log.error("retrieval failed for %s: %s", row.id, exc)

        started = time.perf_counter()
        answer: Answer | None = None
        error: str | None = None
        try:
            answer = bot.ask(row.question)
        except LLMUnavailable as exc:
            # Expected with LLM_PROVIDER=none on every factual query.
            error = str(exc)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            log.error("ask() failed for %s: %s", row.id, exc)
        latency = (time.perf_counter() - started) * 1000.0

        outcome = QueryOutcome(
            sample=row,
            answer=answer,
            observation=observations.get(row.id),
            search=search,
            latency_ms=latency,
            error=error,
        )

        if answer is not None:
            page_ids = [c.chunk.page_id for c in (search.candidates if search else [])]
            outcome.results = checks_mod.run_checks(
                answer,
                answerable=row.answerable,
                retrieved_page_ids=page_ids,
                settings=s,
                storage_paths=storage,
            )

        if (
            judge_enabled
            and client is not None
            and answer is not None
            and not answer.refused
            and row.answerable
        ):
            outcome.verdict = judge_mod.score(
                row, answer.text, outcome.evidence(s.max_evidence_chars),
                client=client, settings=s,
            )

        outcomes.append(outcome)

    if llm_error:
        log.info("run_set complete with judge unavailable: %s", llm_error)
    return outcomes


# --- metric aggregation -------------------------------------------------

def compute_metrics(outcomes: Sequence[QueryOutcome]) -> list[Metric]:
    """M-1 through M-7, each with its denominator and its availability."""
    settings_n = len(outcomes)
    answerable = [o for o in outcomes if o.sample.answerable]
    must_refuse = [o for o in outcomes if o.sample.must_refuse]
    answered = [o for o in outcomes if o.answered]
    opinion = [o for o in outcomes if o.sample.intent is Intent.OPINION]

    metrics: list[Metric] = []

    # --- M-1: judged accuracy over the 5 factual -------------------------
    verdicts = [o.verdict for o in answerable if o.verdict is not None]
    if len(verdicts) == len(answerable) and answerable:
        mean = judge_mod.mean_score(verdicts)  # type: ignore[arg-type]
        models = sorted({v.model for v in verdicts})  # type: ignore[union-attr]
        metrics.append(
            Metric(
                "M-1",
                "Factual accuracy (judged, PRD 9.1 rubric)",
                ">= 1.6 / 2",
                numerator=len(answerable),
                denominator=len(answerable),
                status=STATUS_MEASURED,
                display=f"{mean:.2f}/2",
                detail=(
                    f"mean {mean:.2f}/2 over {len(answerable)} factual; judge "
                    f"{', '.join(models)}; rubric {judge_mod.JUDGE_RUBRIC_VERSION}; "
                    f"prompt {judge_mod.prompt_fingerprint()}"
                ),
            )
        )
    else:
        why = (
            "no answer was generated for the factual queries, so there is nothing "
            "to grade. Set LLM_PROVIDER and re-run."
            if not answerable or not any(o.answered for o in answerable)
            else f"only {len(verdicts)}/{len(answerable)} factual answers graded"
        )
        metrics.append(
            Metric(
                "M-1", "Factual accuracy (judged, PRD 9.1 rubric)", ">= 1.6 / 2",
                status=STATUS_UNAVAILABLE, detail=why,
            )
        )

    # --- M-2: citation validity over the 5 factual -----------------------
    m2_checks = [
        r for o in answered for r in o.results if r.metric == "M-2" and r.name == "citation_in_corpus"
    ]
    m2_retrieved = [
        r for o in answered for r in o.results if r.metric == "M-2" and r.name == "citation_among_retrieved"
    ]
    if answered and len(m2_checks) == len(answered):
        metrics.append(
            Metric(
                "M-2", "Citation validity", "5/5",
                numerator=sum(1 for r in m2_checks + m2_retrieved if r.passed),
                denominator=2 * len(answered),
                status=STATUS_MEASURED,
                detail=(
                    f"{len(answered)} answered query(ies); both halves required - URL in "
                    f"corpus AND its page among the retrieved chunks"
                ),
            )
        )
    else:
        metrics.append(
            Metric(
                "M-2", "Citation validity", "5/5", status=STATUS_UNAVAILABLE,
                detail="no factual answer was produced, so no citation exists to validate",
            )
        )

    # --- M-3: refusal correctness over the 3 must-refuse -----------------
    # Measured over the must-refuse set (the PRD denominator), NOT over all 8
    # queries: an answerable query that could not be answered because no chat
    # model is configured is not a refusal failure. Over-refusal of a query the
    # assistant COULD answer counts as a failure, so the numerator is reduced
    # by `answerable_was_answered` failures among the answerable outcomes.
    m3_must = [
        r for o in must_refuse for r in o.results
        if r.metric == "M-3" and r.name == "must_refuse_did_refuse"
    ]
    m3_over = [
        r for o in answerable for r in o.results
        if r.metric == "M-3" and r.name == "answerable_was_answered" and not r.passed
    ]
    if must_refuse and len(m3_must) == len(must_refuse):
        refused_ok = sum(1 for r in m3_must if r.passed)
        missing_link = [
            o.id for o in opinion
            if o.answer is not None and o.answer.educational_link_missing
        ]
        metrics.append(
            Metric(
                "M-3", "Refusal correctness", "3/3",
                numerator=max(refused_ok - len(m3_over), 0),
                denominator=len(must_refuse),
                status=STATUS_MEASURED,
                detail=(
                    f"{refused_ok}/{len(must_refuse)} must-refuse refused (2 opinion + "
                    f"{len(must_refuse) - len(opinion)} out-of-corpus)"
                    + (
                        f", minus {len(m3_over)} ANSWERABLE query wrongly refused"
                        if m3_over else ", no over-refusal observed"
                    )
                    + (
                        f"; educational link map is EMPTY, so {', '.join(missing_link)} "
                        f"refused correctly but had no link to offer (reported, not hidden)"
                        if missing_link
                        else ""
                    )
                ),
            )
        )
    else:
        metrics.append(
            Metric("M-3", "Refusal correctness", "3/3", status=STATUS_UNAVAILABLE,
                   detail="not every must-refuse query produced an answer to check")
        )

    # --- M-4: advice leakage over every answer text produced -------------
    # The screen is applied by `run_checks` to the answer texts that exist.
    # Every answer text an LLM run produces is screened; the denominator is the
    # count actually screened, with shortfall stated, so "0 leaks" is never
    # implied for answer texts that were never produced.
    m4 = [r for o in outcomes for r in o.results if r.metric == "M-4"]
    if m4:
        metrics.append(
            Metric(
                "M-4", "Advice leakage", "0",
                numerator=sum(1 for r in m4 if not r.passed),
                denominator=len(m4),
                status=STATUS_MEASURED,
                detail=(
                    f"deterministic screen over {len(m4)} answer text(s)"
                    + (
                        f"; {settings_n - len(m4)} query(ies) produced no text "
                        f"(no LLM provider), so nothing to screen"
                        if len(m4) < settings_n
                        else ""
                    )
                ),
            )
        )
    else:
        metrics.append(
            Metric("M-4", "Advice leakage", "0", status=STATUS_UNAVAILABLE,
                   detail="no answer text was produced, so nothing to screen")
        )

    # --- M-5: performance-claim leakage --------------------------------
    m5 = [r for o in outcomes for r in o.results if r.metric == "M-5"]
    if m5:
        metrics.append(
            Metric(
                "M-5", "Performance-claim leakage", "0",
                numerator=sum(1 for r in m5 if not r.passed),
                denominator=len(m5),
                status=STATUS_MEASURED,
                detail=(
                    f"return/NAV/CAGR screen over {len(m5)} answer text(s)"
                    + (
                        f"; {settings_n - len(m5)} query(ies) produced no text "
                        f"(no LLM provider), so nothing to screen"
                        if len(m5) < settings_n
                        else ""
                    )
                ),
            )
        )
    else:
        metrics.append(
            Metric("M-5", "Performance-claim leakage", "0", status=STATUS_UNAVAILABLE,
                   detail="no answer text was produced, so nothing to screen")
        )

    # --- M-6: sentence limit over the ANSWERED queries -------------------
    # Same deviation as M-7, stated rather than buried: `run_checks` only
    # screens NON-refused answers, because a refusal is a fixed policy string
    # and its shape is not what M-6 measures. So M-6 is scored over the queries
    # that produced a generated answer, with the screened count printed.
    m6 = [r for o in answered for r in o.results if r.metric == "M-6"]
    if answered and len(m6) == len(answered):
        metrics.append(
            Metric(
                "M-6", "Sentence-limit compliance", "8/8",
                numerator=sum(1 for r in m6 if r.passed),
                denominator=len(m6),
                status=STATUS_MEASURED,
                detail=(
                    f"{len(m6)} answered query(ies) screened against the "
                    f"3-sentence limit; refusals are a fixed policy text and are "
                    f"not screened (their shape is covered by M-3)"
                ),
            )
        )
    else:
        metrics.append(
            Metric("M-6", "Sentence-limit compliance", "8/8", status=STATUS_UNAVAILABLE,
                   detail="no generated answer text to screen")
        )

    # --- M-7: answer shape ----------------------------------------------
    # DEVIATION, stated rather than buried. PRD §8 defines M-7 as "exactly one
    # source link, one last_updated date, every answer", denominator 8. Applied
    # literally that is unreachable: a Refusal B carries no source link and no
    # date BY DESIGN (educational.py - a refusal that cited a page, or hinted at
    # the gate, would leak). So M-7 is scored over the ANSWERED queries, which is
    # the only set where a citation is meaningful, and refusals are covered
    # instead by M-3 plus `refusal_leaks_nothing`. Both readings are printed.
    m7 = [r for o in answered for r in o.results if r.metric == "M-7"]
    if answered and len(m7) == 2 * len(answered):
        metrics.append(
            Metric(
                "M-7", "Answer shape (one link + one date)", "5/5",
                numerator=sum(1 for r in m7 if r.passed),
                denominator=len(m7),
                status=STATUS_MEASURED,
                detail=(
                    f"{len(answered)} answered query(ies). Scored over ANSWERED queries, "
                    f"not all 8: refusals carry no citation by design, so the literal "
                    f"reading has an unreachable ceiling. See report."
                ),
            )
        )
    else:
        metrics.append(
            Metric("M-7", "Answer shape (one link + one date)", "5/5",
                   status=STATUS_UNAVAILABLE,
                   detail="no factual answer was produced, so no answer shape exists to check")
        )

    return metrics


def latency_summary(outcomes: Sequence[QueryOutcome]) -> dict[str, Any]:
    """Median and max with n. No p95 - PRD §9.4, n=8."""
    values = [o.latency_ms for o in outcomes if o.latency_ms > 0]
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "median_ms": round(statistics.median(values), 1),
        "max_ms": round(max(values), 1),
    }


# --- report -------------------------------------------------------------

def _outcome_row(o: QueryOutcome) -> str:
    if o.error and o.answer is None:
        outcome = "ERROR"
    elif o.answered:
        outcome = "answered"
    elif o.refused:
        outcome = f"refused ({o.answer.intent.value})"  # type: ignore[union-attr]
    else:
        outcome = "-"
    dense = f"{o.observation.raw_dense_max:.4f}" if o.observation else "-"
    failed = o.failed_checks()
    checks = "all pass" if o.answer is not None and not failed else (
        ", ".join(f"{r.metric}/{r.name}" for r in failed) or "-"
    )
    judge = (
        f"{o.verdict.score}/2" if o.verdict and o.verdict.score is not None
        else ("ERR" if o.verdict else "-")
    )
    cite = o.answer.source_url if o.answer and o.answer.source_url else "-"
    return (
        f"| {o.id} | {o.sample.intent.value} | {outcome} | {dense} | {cite} | "
        f"{o.latency_ms:.0f} | {judge} | {checks} |"
    )


def render_report(
    outcomes: Sequence[QueryOutcome],
    metrics: Sequence[Metric],
    settings: Settings,
    calibration_section: str | None = None,
) -> str:
    judged = [o.verdict for o in outcomes if o.verdict is not None]
    unavailable = [m for m in metrics if m.status == STATUS_UNAVAILABLE]

    lines = [
        "# Evaluation report",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Sample set: PRD §9.2 / FR-34, {len(outcomes)} queries "
        f"({sum(o.sample.answerable for o in outcomes)} factual, "
        f"{sum(o.sample.must_refuse for o in outcomes)} must-refuse)",
        f"- Embedding model: `{settings.embedding_model}`",
        f"- `SIMILARITY_THRESHOLD`: "
        f"{settings.similarity_threshold if settings.similarity_threshold is not None else 'read from artifacts/calibration.json'}",
        f"- LLM provider: `{settings.llm_provider}`"
        + (f" / `{settings.llm_model}`" if settings.has_llm else " (generation and judging disabled)"),
        "",
        "## Metrics",
        "",
        "| ID | Metric | Target | Result | Denominator | Status |",
        "|---|---|---|---|---|---|",
    ]
    for m in metrics:
        den = "-" if m.denominator is None else str(m.denominator)
        lines.append(
            f"| {m.id} | {m.name} | {m.target} | {m.value} | {den} | {m.status} |"
        )

    lines += ["", "### Per-metric detail", ""]
    for m in metrics:
        lines.append(f"- **{m.id}** - {m.detail}")

    if judged:
        lines += ["", "### Judge provenance (M-1)", ""]
        lines.append(
            f"- Model: `{judged[0].model}`  - rubric: `{judged[0].rubric_version}`  "
            f"- prompt SHA-256: `{judged[0].prompt_sha256}`"
        )
        lines.append("")
        lines.append("| id | score | reason |")
        lines.append("|---|---|---|")
        for v in judged:
            lines.append(f"| {v.sample_id} | {v.score}/2 | {v.reason} |")
    else:
        lines += [
            "",
            "### Judge provenance (M-1)",
            "",
            "No judge verdict was recorded, so M-1 is `unavailable`. This is reported "
            "rather than filled in with a placeholder: a judge score without a model, "
            "a rubric version and a prompt hash is not reproducible (PRD §9.1), and an "
            "invented score is worse than an absent one.",
        ]

    lines += [
        "",
        "## Per-query outcomes",
        "",
        "| id | intent | outcome | raw_dense_max | cited source | ms | judge | checks |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines += [_outcome_row(o) for o in outcomes]

    lines += ["", "## Full answers", ""]
    for o in outcomes:
        lines.append(f"### {o.id} - {o.sample.question}")
        lines.append("")
        if o.sample.note:
            lines.append(f"> {o.sample.note}")
            lines.append("")
        if o.answer is None:
            lines.append(f"**No answer produced.** `{o.error}`")
        else:
            lines.append(f"> {o.answer.text}")
            lines.append("")
            lines.append(f"- intent: `{o.answer.intent.value}` · refused: `{o.answer.refused}`")
            if o.answer.source_url:
                lines.append(f"- source: {o.answer.source_url}")
            if o.answer.last_updated:
                lines.append(f"- last updated: {o.answer.last_updated.date()}")
            if o.answer.educational_link:
                lines.append(f"- educational link: {o.answer.educational_link}")
            if o.answer.educational_link_missing:
                lines.append(
                    "- educational link: **MISSING** - `config/education_links.yml` is "
                    "empty, so no verified URL exists. None was generated."
                )
            for r in o.results:
                lines.append(f"- {r}")
        lines.append("")

    lat = latency_summary(outcomes)
    if lat.get("n"):
        lines += [
            "## Latency",
            "",
            f"n={lat['n']} · median {lat['median_ms']} ms · max {lat['max_ms']} ms",
            "",
            "Median and max, not a p95: with n=8 a p95 is the maximum wearing a hat "
            "(PRD §9.4). These include embedding-model load on the first query.",
            "",
        ]

    if calibration_section:
        lines += [calibration_section, ""]

    lines += ["## What this run could and could not measure", ""]
    if unavailable:
        lines.append(
            f"{len(unavailable)} of {len(metrics)} metrics are `unavailable`: "
            + ", ".join(m.id for m in unavailable)
            + "."
        )
        lines.append("")
    lines += [
        "M-3, M-4 and M-5 are measured in full without a chat model, because every "
        "refusal is a fixed policy decision that never calls one. M-1, M-2, M-6 and "
        "M-7 need a generated factual answer to inspect; with `LLM_PROVIDER=none` there "
        "is none, and the harness reports that instead of inventing a value.",
        "",
        "The screens in `checks.py` are re-derived independently of "
        "`generation/validate.py` on purpose - an eval that called the product's own "
        "screens could never fail. Their agreement with the output screen is pinned by "
        "`tests/unit/test_eval_checks.py::test_eval_screens_agree_with_the_output_screen`, "
        "which includes the three false positives Phase 4 actually shipped.",
        "",
    ]
    return "\n".join(lines)


# --- CLI ----------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m src.ragbot.eval.runner",
        description="Run the FR-34 sample set and report M-1..M-7.",
    )
    parser.add_argument("--sample-set", default=None)
    parser.add_argument("--out", default=None, help=f"report path (default {REPORT_PATH})")
    parser.add_argument("--no-judge", action="store_true", help="skip the M-1 judge")
    parser.add_argument("--json", action="store_true", help="emit metrics as JSON on stdout")
    args = parser.parse_args(argv)

    settings = Settings()
    rows = load_sample_set(args.sample_set, settings)
    outcomes = run_set(rows, settings, judge_enabled=not args.no_judge)
    metrics = compute_metrics(outcomes)

    if args.json:
        import json

        print(json.dumps([m.to_dict() for m in metrics], indent=2))
        return 0

    print(f"sample set: {len(outcomes)} queries")
    for o in outcomes:
        if o.answered:
            state = "answered"
        elif o.refused:
            state = "refused"
        elif o.error:
            state = "ERROR"
        else:
            state = "no answer"
        dense = f"{o.observation.raw_dense_max:.4f}" if o.observation else "-"
        failed = o.failed_checks()
        mark = "ok " if o.answer is not None and not failed else "FAIL"
        print(f"  [{mark}] {o.id:<3} {o.sample.intent.value:<13} {state:<10} dense={dense}")
        for r in failed:
            print(f"          {r}")
        if o.error and o.answer is None:
            print(f"          {o.error.splitlines()[0][:150]}")

    print()
    width = max(len(m.id) for m in metrics)
    for m in metrics:
        print(f"  {m.id:<{width}}  {m.value:<8} target {m.target:<10} [{m.status}]")

    out = Path(args.out) if args.out else PROJECT_ROOT / REPORT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    calibration = None
    if settings.calibration_file.exists():
        from .calibrate import render_report as render_calibration

        import json as _json

        data = _json.loads(settings.calibration_file.read_text(encoding="utf-8"))
        from .calibrate import Decision, SweepPoint

        decision = Decision(
            threshold=data.get("similarity_threshold"),
            rule=data.get("selection_rule", "unknown"),
            feasible=bool(data.get("feasible")),
            lower_bound=(data.get("bounds") or {}).get("gate_refusal_dense_max"),
            upper_bound=(data.get("bounds") or {}).get("factual_dense_min"),
            rationale=data.get("rationale", ""),
            evidence_failures=data.get("evidence_failures", []),
            notes=data.get("notes", []),
        )
        curve = [SweepPoint(**p) for p in data.get("curve", [])]
        obs = [
            Observation(
                id=p["id"], question=p["question"], intent=Intent(p["intent"]),
                answerable=p["answerable"], raw_dense_max=p["raw_dense_max"],
                gate_routed=p["gate_routed"], facts_in_context=p["facts_in_context"],
                missing_facts=p.get("missing_facts", []), page_ids=p.get("page_ids", []),
                rule=p.get("rule", ""),
            )
            for p in data.get("per_query", [])
        ]
        calibration = render_calibration(decision, obs, curve, settings, settings.calibration_file)

    out.write_text(render_report(outcomes, metrics, settings, calibration), encoding="utf-8")
    print()
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
