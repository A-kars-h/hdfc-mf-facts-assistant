"""The third gate: checks on the OUTPUT, after generation.

The prompt asks for a compliant answer. The prompt is not the control. This
module is the control, because the failure mode that matters here is silent: an
answer that is well-formed, fluent, carries a plausible citation, and is wrong or
prohibited. Nothing crashes when that happens. So every prohibition is re-checked
on the finished text and the answer is rebuilt from what survived.

What each check does, and why it fails the way it does:

- **Sentence limit.** Trimmed to `max_answer_sentences`, keeping whole sentences
  and never cutting mid-number. Optionally regenerate once first, because a
  model that ignored the limit will usually ignore a re-ask too; the trim is
  what actually guarantees the contract.

- **Citation.** Any URL the model emitted is stripped unless it is both in the
  corpus AND among the retrieved candidates. The surviving URL is then taken
  from PROVENANCE, not from the model's text, so the citation is derived from
  what was actually retrieved. This is the single most likely silent
  correctness failure in the whole system (FR-17): `https://groww.in/funds`
  would look perfect and cite nothing that was read.

- **Freshness.** `last_updated` comes from the cited chunk's own `fetched_at`,
  never from the manifest's `generated_at` and never from the model's text.

- **Advice screen.** A single trigger word converts the WHOLE answer into
  Refusal A. Not a deletion of the offending sentence: an answer that says
  "you should buy this, and the expense ratio is 1.21%" is not made acceptable
  by removing the first clause.

- **Performance screen.** Targets return-SHAPED figures, not all percentages.
  `1.21%` expense ratio is the answer to the most common question in this
  corpus and must pass; `18% in 3 years` must not. The discriminator is
  contextual: a figure is a performance claim if a return word governs it in
  the same clause, or if it is attached to an investment period.

- **Grounding.** Every numeric token in the answer must appear in the cited
  candidate set. This is a proxy for full claim verification - it cannot tell
  whether a sentence is *supported*, only whether its figures are - so it is
  documented as a proxy rather than dressed up as proof.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from ..core.config import Settings
from ..core.errors import ProviderError
from ..core.models import Answer, Intent, RetrievedChunk, count_sentences
from .prompts import cited_markers

log = logging.getLogger(__name__)

#: Words that make an answer advice. Word-bounded, so "buying" matches "buy" but
#: "seller" does not, and a URL fragment like "/buy" is not a false positive.
ADVICE_TERMS = (
    r"buy", r"sell", r"should", r"recommend\w*", r"suggest\w*", r"allocate",
    r"portfolio", r"invest\s+in", r"worth\s+investing", r"good\s+time",
    r"best\s+time", r"ideal\s+time", r"hold\s+on\s+to", r"switch\s+to",
    r"go\s+for", r"opt\s+for", r"must\s+own", r"must\s+buy", r"we\s+rate",
)
ADVICE_RE = re.compile(r"\b(?:" + "|".join(ADVICE_TERMS) + r")\b", re.I)

#: Words that turn a figure into a return claim.
#: `NAV` is here because the source names a NAV value as return-shaped: NAV is
#: the unit performance is reported in, so quoting one is quoting a performance
#: figure. It is deliberately NOT in FEE_TERMS - a NAV value is not a fee.
RETURN_TERMS = (
    r"returns?", r"CAGR", r"yield\w*", r"XIRR", r"IRR", r"annualis?ed",
    r"absolute\s+return", r"gains?", r"growth", r"performance", r"upside",
    r"earned", r"delivered", r"p\.\s?a\.", r"profit",
)
RETURN_RE = re.compile(r"\b(?:" + "|".join(RETURN_TERMS) + r")\b", re.I)

#: A NAV quoted as a per-unit value is a performance figure, but the corpus also
#: states a NAV *date* ("NAV: 25 Sep '26"), which is provenance, not
#: performance. Reporting when a page was read is exactly what freshness is for.
NAV_RE = re.compile(r"\bNAV\b", re.I)
DATEISH_RE = re.compile(
    r"(\d{1,2}\s+[A-Za-z]{3,9}\s*'?\d{0,2}|\d{4}-\d{2}-\d{2}|'[0-9]{2}\b|"
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{4}\b(?!\s*%))"
)

#: Words that make a percentage a FEE. Checked before RETURN_TERMS so
#: "expense ratio 1.21%" is never mistaken for a return.
FEE_TERMS = (
    r"expense\s+ratio", r"TER", r"exit\s+load", r"loads?", r"charges?",
    r"fee", r"AUM", r"fund\s+size", r"minimum", r"min\.\s*for\s+SIP",
    r"stamp\s+duty", r"lock-?in", r"minimum\s+investment",
)
FEE_RE = re.compile(r"\b(?:" + "|".join(FEE_TERMS) + r")\b", re.I)

#: A period a return could be attached to: "1-year", "3Y", "in 3 years".
PERIOD_RE = re.compile(
    r"\b(?:\d+\s*[- ]?\s*(?:year|month|yr|yr\b|day|week)s?|"
    r"\d+\s*[YMD]\b|since\s+inception|since\s+launch)\b",
    re.I,
)

#: Any number with optional decimals, commas, ₹/%/x suffix.
FIGURE_RE = re.compile(r"[₹$]?\s?\d[\d,]*\.?\d*\s?(?:%|x|X\b)?")

#: A URL, for the strip pass. Deliberately greedy about trailing punctuation.
URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+", re.I)

#: Splits an answer into the units the screens reason over.
#:
#: The lookbehind/lookahead are load-bearing: a naive `[.;:!?]` split breaks
#: "1.21%" into "21", which detaches the figure from the "expense ratio" that
#: made it a fee, and the core question type gets blocked as a return claim.
#: Splitting on a period only when it is NOT between digits fixes that, and the
#: `\band\b|\bbut\b|\bwhile\b` alternatives matter because one sentence can hold
#: both a fee and a return: "the expense ratio is 1.21% and it returned 18% in 3
#: years" must be blocked for the return half, not excused by the fee half.
CLAUSE_SPLIT = re.compile(
    # Abbreviation guards come first and are all fixed-width, because Python
    # requires a fixed-width lookbehind. They exist because the naive pattern
    # splits "Rs. 64.12" at the period in "Rs.", which separates a NAV from its
    # own value - so the NAV rule never sees the figure it is supposed to catch
    # and "The NAV is Rs. 64.12." passed as clean.
    r"(?<!Rs)(?<!rs)(?<!INR)(?<!USD)(?<!Dr)(?<!No)(?<!approx)(?<![0-9])[.;:!?]+(?![0-9])"
    r"|\band\b|\bbut\b|\bwhile\b",
    re.IGNORECASE,
)


def _norm_number(token: str) -> str:
    """Normalise a figure for comparison: strip currency/space/suffix noise."""
    t = token.strip()
    for ch in ("₹", "$", "%", " ", "x", "X"):
        t = t.replace(ch, "")
    if not t or t in (".", ","):
        return ""
    # 1,13,606.47 -> 113606.47
    t = t.replace(",", "")
    try:
        value = float(t)
    except ValueError:
        return ""
    # Compare on a rounded string so 0.77 vs .77 vs 0.770 all match.
    return f"{value:.6f}".rstrip("0").rstrip(".")


#: `[S1]`, `[S12]` - our own citation markers, not model-authored numbers.
CITATION_MARKER_RE = re.compile(r"\[S\d+\]", re.IGNORECASE)

#: A named index or benchmark. See `performance_violations` for why "Total Return
#: Index" must not read as a return claim.
BENCHMARK_RE = re.compile(
    r"\b(?:benchmark|index|indices|nifty|sensex|bse\s*sensex|nsei)\b",
    re.IGNORECASE,
)

#: Plan names containing the word "Growth". This is the highest-impact exemption
#: in this module, and it exists because of a real false positive.
#:
#: All five funds in this corpus are "Direct Plan - Growth" / "Direct Growth", and
#: "growth" is a return word. So the most natural factual answer about any of
#: them - "The HDFC Small Cap Fund Direct Growth option is managed by..." - was
#: refused for return language, as was "The ... Direct Growth scheme was launched
#: in 2013". The screen was refusing the scheme's own name.
#:
#: Masked only in plan-name position. "The fund's growth was 12%" and "growth has
#: been strong" are not plan names and still trip the screen.
PLAN_NAME_RE = re.compile(
    r"\b(?:"
    r"direct(?:\s+plan)?\s*[-\u2013]?\s*growth"  # Direct Growth, Direct Plan - Growth
    r"|growth\s+(?:option|plan|variant)"  # Growth Option
    r"|[-\u2013]\s*growth"  # trailing "- Growth"
    r")\b",
    re.IGNORECASE,
)


def _figures(text: str) -> list[str]:
    """Numbers in `text`, ignoring our own citation markers.

    `[S1]` is the important case, and it is a bug this project shipped into its
    tests before it shipped into a user: the marker is a block index we invented,
    so treating its digits as a financial figure makes every correctly-cited
    answer fail grounding with `figures not in retrieved context: ['1']`. Strip
    markers before the numeric pass, not after.
    """
    stripped = CITATION_MARKER_RE.sub(" ", text)
    return [
        f for f in (m.group(0) for m in FIGURE_RE.finditer(stripped)) if _norm_number(f)
    ]


def contains_advice(text: str) -> str | None:
    """Return the offending term, or None."""
    m = ADVICE_RE.search(text)
    return m.group(0).lower() if m else None


def performance_violations(text: str) -> list[str]:
    """Return reasons the text states a performance claim, or [] if clean.

    Clause-scoped on purpose. "The expense ratio is 1.21%" has a figure and a
    fee word; "The fund returned 18% in 3 years" has a figure, a return word and
    a period. Matching at whole-answer level would make the first one fail,
    which is the bug the source warns about.
    """
    reasons: list[str] = []
    for clause in CLAUSE_SPLIT.split(text):
        clause = clause.strip()
        if not clause:
            continue
        # A named index is not a return. "NIFTY 50 Total Return Index" contains
        # the word "Return" and a figure, so a naive return-word screen flags it
        # - but every one of the five pages states its benchmark, so this screen
        # would refuse a legitimate, answerable factual question. The clause is
        # naming something to be measured against, not reporting a result.
        if BENCHMARK_RE.search(clause):
            continue
        # "Growth" in a plan name is part of the fund's identity, not a claim
        # about its performance. Screen the clause with those masked out, but
        # keep the original text for the reason message so the note is readable.
        screened = PLAN_NAME_RE.sub(" ", clause)
        figures = _figures(clause)
        # A bare return word with no figure ("the returns have been strong",
        # "performance has been good") is still a claim.
        if not figures:
            if RETURN_RE.search(screened) and not FEE_RE.search(screened):
                reasons.append(f"return language without a fee: {clause[:60]!r}")
            continue
        # A NAV per-unit value is a performance figure; a NAV date is not.
        if NAV_RE.search(screened) and not DATEISH_RE.search(screened):
            reasons.append(f"NAV value: {clause[:60]!r}")
            continue
        # Fee words govern the clause: this is a cost or a term, not a return.
        if FEE_RE.search(screened):
            continue
        if RETURN_RE.search(screened):
            reasons.append(f"return figure: {clause[:60]!r}")
            continue
        if PERIOD_RE.search(screened):
            reasons.append(f"period-attached figure: {clause[:60]!r}")
            continue
        # A bare percentage with no qualifier at all is unattributable, so it
        # is treated as unsafe. Refusing is cheap; emitting a wrong fee is not.
        if re.search(r"\d\s*%", clause) and not FEE_RE.search(screened):
            reasons.append(f"unattributed percentage: {clause[:60]!r}")
    return reasons


def _strip_urls(text: str) -> tuple[str, list[str]]:
    """Remove every URL from the draft. Returns (cleaned, removed)."""
    removed = URL_RE.findall(text)
    cleaned = URL_RE.sub("", text)
    # Tidy the whitespace the removal left behind.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([.,;:])", r"\1", cleaned)
    return cleaned.strip(), removed


def _trim_sentences(text: str, limit: int) -> str:
    """Keep the first `limit` sentences. Never splits mid-number.

    `count_sentences` is the same counter the Answer validator uses, so the two
    cannot disagree about whether a trimmed string is acceptable.
    """
    if count_sentences(text) <= limit:
        return text
    # Split on the same conservative boundary the counter uses.
    parts = re.split(r"(?<=[.!?])[\"')\]]*\s+", text.strip())
    kept: list[str] = []
    for part in parts:
        candidate = part.strip()
        if not candidate:
            continue
        if kept and count_sentences(" ".join(kept)) + count_sentences(candidate) > limit:
            break
        kept.append(candidate)
        if len(kept) == limit:
            break
    out = " ".join(kept).strip()
    if out and out[-1] not in ".!?":
        out += "."
    return out or text.strip()


def _resolve_citation(
    emitted: list[str],
    markers: list[str],
    candidates: list[RetrievedChunk],
) -> tuple[RetrievedChunk | None, list[str]]:
    """Choose the candidate this answer should cite.

    Markers first, and strictly POSITIONAL. `render_context()` numbers blocks
    `[S1]`, `[S2]`, ... in the order of the list it is given, so `S3` means
    `candidates[2]` and nothing else. Looking the marker up by `fused_rank`
    instead looks equivalent and is not: ranks can tie or be sparse, so it
    silently resolves a marker to the wrong chunk - found by
    test_citation_prefers_the_candidate_the_model_named.

    Whatever the model emitted, the URL that ends up in the answer is read off
    the chosen candidate's provenance, so a wrong citation is not possible even
    if the model invents one.
    """
    notes: list[str] = []
    allowed = {c.chunk.source_url: c for c in candidates}
    for url in emitted:
        if url in allowed:
            notes.append(f"model URL {url} resolves to a retrieved chunk")
        elif any(url.rstrip("/") == a.rstrip("/") for a in allowed):
            notes.append(f"model URL {url} matches after normalising the trailing slash")
        else:
            notes.append(f"invented URL stripped: {url}")
    if not candidates:
        return None, notes

    for index, marker in enumerate(markers):
        position = int(marker[1:]) - 1
        if 0 <= position < len(candidates):
            notes.append(
                f"citation from marker [{marker}] -> candidate {position + 1} "
                f"({candidates[position].chunk.scheme})"
            )
            return candidates[position], notes
    if markers:
        notes.append(
            f"markers {markers} out of range for {len(candidates)} blocks; "
            f"falling back"
        )
    for url in emitted:
        if url in allowed:
            return allowed[url], notes
    top = min(candidates, key=lambda c: c.fused_rank)
    notes.append(f"citation resolved from provenance: {top.chunk.source_url}")
    return top, notes


def _grounded(text: str, cited: RetrievedChunk | None, candidates: list[RetrievedChunk]) -> list[str]:
    """Every figure in the answer must exist in the retrieved context."""
    if cited is None:
        return []
    haystack = " ".join(
        _norm_number(f) for c in candidates for f in _figures(c.chunk.text)
    )
    haystack += " " + " ".join(
        _norm_number(f) for f in _figures(cited.chunk.text)
    )
    missing = []
    for figure in _figures(text):
        if _norm_number(figure) not in haystack:
            missing.append(figure.strip())
    return missing


def validate(
    draft: str,
    candidates: list[RetrievedChunk],
    settings: Settings | None = None,
    *,
    regenerate: Callable[[str], str] | None = None,
    intent: Intent = Intent.FACTUAL,
) -> Answer:
    """Turn a raw draft into a validated `Answer`, or into a refusal.

    `regenerate` is called at most once, and only when the first draft breaks
    the sentence limit. A refusal decision short-circuits: once advice or a
    performance claim is detected the draft is discarded, because rebuilding it
    piece by piece would leave fragments of a prohibited answer on screen.
    """
    from .educational import refuse_opinion, refuse_performance

    s = settings or Settings()
    checks: list[str] = [f"intent={intent.value}"]
    raw = (draft or "").strip()

    # --- strip model-emitted URLs FIRST -----------------------------------
    # The prompt asks for [S1] markers, not URLs, so any URL is noise. It is
    # removed before the screens run because screening a URL is meaningless and
    # actively harmful: a corpus slug like ".../hdfc-equity-fund-direct-growth"
    # contains the word "growth", which the performance screen reads as a return
    # claim. Found by test_url_only_from_a_candidate_is_kept.
    # The URLs are still captured, because they are evidence for the citation.
    text, emitted = _strip_urls(raw)
    if emitted:
        checks.append(f"citation: model emitted {len(emitted)} URL(s); text stripped")

    # --- sentence limit: regenerate once, then trim -----------------------
    limit = s.max_answer_sentences
    if count_sentences(text) > limit:
        if regenerate is not None:
            checks.append(
                f"sentence_limit: draft had {count_sentences(text)}, regenerating once"
            )
            try:
                second = regenerate(text)
            except ProviderError as exc:
                log.warning("regeneration failed, trimming instead: %s", exc)
                second = ""
            if second:
                # A regeneration can re-introduce a URL. Strip it again and only
                # accept the retry if it both complies and stays clean.
                second, second_urls = _strip_urls(second.strip())
                emitted = emitted + second_urls
                if count_sentences(second) <= limit and not second_urls:
                    text = second
                    checks.append("sentence_limit: regeneration complied")
                else:
                    trimmed = _trim_sentences(text, limit)
                    checks.append(
                        f"sentence_limit: trimmed {count_sentences(text)} -> "
                        f"{count_sentences(trimmed)}"
                    )
                    text = trimmed
            else:
                trimmed = _trim_sentences(text, limit)
                checks.append(
                    f"sentence_limit: trimmed {count_sentences(text)} -> "
                    f"{count_sentences(trimmed)}"
                )
                text = trimmed
        else:
            trimmed = _trim_sentences(text, limit)
            checks.append(
                f"sentence_limit: trimmed {count_sentences(text)} -> "
                f"{count_sentences(trimmed)}"
            )
            text = trimmed
    else:
        checks.append(f"sentence_limit: {count_sentences(text)} <= {limit} ok")

    # --- advice screen: whole answer becomes Refusal A --------------------
    term = contains_advice(text)
    if term:
        checks.append(f"advice_screen: TRIPPED on {term!r} -> Refusal A")
        return refuse_opinion(
            intent=Intent.OPINION,
            text="",
            checks=checks,
            settings=s,
            cause=f"generated answer contained advice language ({term!r})",
        )

    # --- performance screen: refuse + factsheet link -----------------------
    violations = performance_violations(text)
    if violations:
        checks.append(
            "performance_screen: TRIPPED -> "
            + "; ".join(violations)
        )
        return refuse_performance(checks=checks, settings=s, cause=violations[0])

    # --- citation ----------------------------------------------------------
    cited, notes = _resolve_citation(emitted, cited_markers(text), candidates)
    checks.extend(f"citation: {n}" for n in notes)
    if cited is None:
        checks.append("citation: no candidates; answer cannot cite a source")
        return Answer(
            intent=Intent.FACTUAL,
            text=_trim_sentences(text, limit) or "Not available in the corpus.",
            source_url=None,
            last_updated=None,
            refused=True,
            validation=checks,
        )

    # --- grounding ---------------------------------------------------------
    missing = _grounded(text, cited, candidates)
    if missing:
        checks.append(
            f"grounding: FAILED - figures not in retrieved context: {missing}"
        )
        return Answer(
            intent=Intent.FACTUAL,
            text="The corpus does not contain a figure for this question.",
            source_url=cited.chunk.source_url,
            source_title=cited.chunk.source_title,
            last_updated=cited.chunk.fetched_at,
            refused=True,
            retrieved_chunk_ids=[c.chunk_id for c in candidates],
            validation=checks,
        )
    checks.append("grounding: all figures present in retrieved context")

    # URLs were removed before the screens ran; the answer carries the resolved
    # one from provenance and nothing else. So are the `[S1]` markers: they are
    # scaffolding between us and the model, the citation the user actually gets
    # is `source_url`, and leaving a bracket-and-digit token in the prose is noise
    # that a future numeric screen could misread as a figure.
    final = _trim_sentences(CITATION_MARKER_RE.sub("", text), limit)

    return Answer(
        intent=Intent.FACTUAL,
        text=final,
        source_url=cited.chunk.source_url,
        source_title=cited.chunk.source_title,
        last_updated=cited.chunk.fetched_at,  # per-page, never global
        retrieved_chunk_ids=[c.chunk_id for c in candidates],
        validation=checks + [
            f"freshness: last_updated from cited page fetched_at "
            f"{cited.chunk.fetched_at.isoformat()}",
            "advice_screen: clear",
            "performance_screen: clear",
        ],
    )
