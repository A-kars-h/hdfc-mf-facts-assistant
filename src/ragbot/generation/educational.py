"""The two refusals. Neither one calls a model.

Refusal A (opinion, FR-21) and Refusal B (not in the corpus, FR-22) are fixed
policy decisions. There is no text to generate, so nothing is generated - a
refusal produced by an LLM is a refusal that can be talked out of, hedged, or
preceded by "however, many investors believe that...".

Both refusals share four properties the source cares about:

- **No apologising.** "I'm sorry, I can't help with that" reads as a policy
  about the assistant rather than a fact about the data. The boundary is a
  feature of the product.
- **No leaking internals.** No threshold, no similarity score, no rank, no chunk
  text, no page count. A user who learns "0.42" is below the bar learns the
  bar, and can then aim at it.
- **No invented links.** Refusal A reads `config/education_links.yml` and
  nothing else. That file ships empty, so the honest output is a refusal with
  `educational_link_missing=True` rather than a confident-looking URL that 404s.
  A broken link is worse than no link: it makes the refusal look complete.
- **Non-apologetic and brief.** Under three sentences, so the `Answer`
  contract's sentence limit holds without trimming.

Refusal B is triggered by two distinct conditions - an out-of-scope question,
and a factual question the gate declined - and both produce the *same* string.
That is deliberate: if the corpus gap and the threshold refusal worded
differently, the wording itself would leak which one happened, and a user could
tell the gate's boundary by asking repeatedly.
"""

from __future__ import annotations

from ..core.config import Settings
from ..core.models import Answer, Intent

#: Refusal A: opinion declined, educational material offered. Under 3 sentences.
#:
#: These are written to be ADVICE-SCREEN CLEAN. The refusal has to say what it
#: declines to do, and the obvious phrasing ("I will not tell you whether to
#: buy, sell or hold") is itself a hit for the advice screen - so the text that
#: implements the prohibition trips the prohibition. Rewritten to say the same
#: thing without the trigger vocabulary. `test_advice_converted_to_refusal`
#: asserts this, so a future edit cannot quietly reintroduce the self-trip.
_OPINION_WITH_LINK = (
    "I answer with verified facts about these funds rather than with a view on "
    "whether an investment in any of them suits you. For background on what to "
    "weigh before deciding, see: {title}"
)
_OPINION_NO_LINK = (
    "I answer with verified facts about these funds rather than with a view on "
    "whether an investment in any of them suits you. No verified "
    "investor-education page is available in this deployment yet, so there is no "
    "link I can point you to without risking a wrong one."
)

#: Refusal B: the question is outside the closed corpus. One boundary statement,
#: no mention of thresholds, scores, ranks, or what the chunks contained.
_NOT_IN_CORPUS = (
    "That is outside what I can answer. I cover verified facts from a fixed set "
    "of HDFC mutual fund pages - scheme details, fees and expense ratios, minimum "
    "investment amounts, exit loads, tax treatment, benchmark, riskometer level, "
    "holdings, and fund manager and company information. I do not give investment "
    "advice, and I do not answer from outside that material."
)

#: Used when a generated answer tripped the performance screen. Names the
#: boundary without echoing the number back, because repeating "18% in 3 years"
#: in the refusal would repeat the claim the screen exists to stop.
_PERFORMANCE_REFUSED = (
    "I cannot state or compare returns, so I will not repeat those figures. The "
    "official factsheet and the fund's published page carry the full performance "
    "history with the dates and periods attached."
)


def _link_for(intent: Intent, settings: Settings | None) -> str | None:
    from ..core.config import education_link_for

    return education_link_for(intent.value, settings)


def _link_title(settings: Settings | None) -> str:
    from ..core.config import load_education_links

    links = load_education_links(settings)
    for entry in links.values():
        if entry.get("title"):
            return str(entry["title"])
    return "the investor-education page linked below"


def refuse_opinion(
    *,
    intent: Intent = Intent.OPINION,
    text: str = "",
    checks: list[str] | None = None,
    settings: Settings | None = None,
    cause: str = "advice-seeking question",
) -> Answer:
    """Refusal A: decline advice, attach a verified educational link if one exists.

    If the link map is empty the refusal still goes out, with
    `educational_link_missing=True`. That flag is what lets the eval harness tell
    "refused correctly" apart from "refused with nothing to offer" - without it
    M-3 passes vacuously on an empty map.
    """
    notes = list(checks or [])
    notes.append(f"refusal_a: {cause}")
    url = _link_for(intent, settings)
    if url:
        notes.append(f"refusal_a: educational link from verified map ({url})")
        body = _OPINION_WITH_LINK.format(title=_link_title(settings))
        return Answer(
            intent=intent,
            text=body,
            educational_link=url,
            educational_link_missing=False,
            refused=True,
            validation=notes,
        )
    notes.append(
        "refusal_a: NO verified educational link available "
        "(config/education_links.yml is empty). A URL was NOT generated."
    )
    return Answer(
        intent=intent,
        text=_OPINION_NO_LINK,
        educational_link=None,
        educational_link_missing=True,
        refused=True,
        validation=notes,
    )


def refuse_performance(
    *,
    checks: list[str] | None = None,
    settings: Settings | None = None,
    cause: str = "",
) -> Answer:
    """Refuse a performance claim, and point at the official factsheet.

    This is deliberately NOT Refusal A: the question was factual and the
    assistant did retrieve real context, so the honest message is about the
    specific figure, not about advice. It also reuses the verified-link map so
    it can attach a real factsheet URL - and reports honestly when there is
    none to attach.
    """
    notes = list(checks or [])
    notes.append(f"performance_refused: {cause}")
    url = _link_for(Intent.FACTUAL, settings)
    if url:
        return Answer(
            intent=Intent.FACTUAL,
            text=_PERFORMANCE_REFUSED,
            educational_link=url,
            educational_link_missing=False,
            refused=True,
            validation=notes,
        )
    return Answer(
        intent=Intent.FACTUAL,
        text=_PERFORMANCE_REFUSED,
        educational_link=None,
        educational_link_missing=True,
        refused=True,
        validation=notes,
    )


def refuse_not_in_corpus(
    *,
    intent: Intent = Intent.OUT_OF_SCOPE,
    checks: list[str] | None = None,
    settings: Settings | None = None,
    cause: str = "question outside the closed corpus",
) -> Answer:
    """Refusal B: the fixed out-of-corpus boundary. No LLM call, ever.

    Wording is identical whether the cause was an out-of-scope intent or a gate
    refusal, so the message cannot be used to probe the gate's threshold.
    """
    notes = list(checks or [])
    notes.append(f"refusal_b: {cause}")
    return Answer(
        intent=intent,
        text=_NOT_IN_CORPUS,
        refused=True,
        validation=notes,
    )


def refuse_pii(
    *,
    kinds: list[str] | None = None,
    checks: list[str] | None = None,
    settings: Settings | None = None,
    cause: str = "personal data detected in the question",
) -> Answer:
    """Refusal C: personal data present, so the question is declined (FR-31).

    The user-facing text is `safety.pii.NEUTRAL_MESSAGE` and nothing else. It is
    a single constant for every category, which is the point: a per-category
    message would confirm *which* pattern matched, turning the refusal into an
    oracle for discovering where the detectors' edges are. The categories are
    named in full so the user knows what to remove.

    `kinds` goes into the internal `validation` notes and must never reach the
    user. The notes are developer-facing; the UI renders `text`.
    """
    from ..safety.pii import NEUTRAL_MESSAGE

    notes = list(checks or [])
    notes.append(f"refusal_c: {cause}")
    if kinds:
        notes.append(f"refusal_c: categories={','.join(kinds)} (internal only)")
    notes.append("refusal_c: nothing embedded, sent, or stored")
    return Answer(
        intent=Intent.OUT_OF_SCOPE,
        text=NEUTRAL_MESSAGE,
        refused=True,
        validation=notes,
    )
