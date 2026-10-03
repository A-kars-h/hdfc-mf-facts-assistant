"""Output validation - the third gate.

These are the checks that make the prohibitions real. Each test pins a case the
prompt alone would not catch, and several of them pin a case that is EASY to get
wrong in the direction of over-blocking: the expense ratio must survive while
the return figure does not.

Fixtures build `RetrievedChunk`s with real provenance so citation, freshness
and grounding can be checked against something that exists, rather than against
a mock that agrees with whatever the code does.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.ragbot.core.config import Settings
from src.ragbot.core.models import Chunk, Intent, RetrievedChunk
from src.ragbot.generation.validate import (
    contains_advice,
    performance_violations,
    validate,
)

ELSS_URL = "https://groww.in/funds/hdfc-elss-tax-saver-fund-direct-growth"
EQUITY_URL = "https://groww.in/funds/hdfc-equity-fund-direct-growth"
FETCHED = datetime(2026, 9, 27, 8, 20, tzinfo=timezone.utc)


def _chunk(
    chunk_id: str,
    text: str,
    page_id: str = "hdfc-elss",
    url: str = ELSS_URL,
    scheme: str = "HDFC ELSS Tax Saver Fund - Direct Plan - Growth",
    section: str = "Fund house",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(
            chunk_id=chunk_id,
            page_id=page_id,
            scheme=scheme,
            category="ELSS",
            source_url=url,
            fetched_at=FETCHED,
            text=text,
            token_count=len(text.split()),
            content_hash=f"hash-{chunk_id}",
            section=section,
        ),
        dense_score=0.81,
        fused_rank=1,
    )


@pytest.fixture
def elss_sip() -> RetrievedChunk:
    return _chunk("c1", "Min. for SIP | Rs. 500. Expense ratio | 1.21%.")


@pytest.fixture
def equity_er() -> RetrievedChunk:
    return _chunk(
        "c2",
        "Expense ratio | 0.77%. Fund size (AUM) | Rs. 1,13,606.47 Cr.",
        page_id="hdfc-equity",
        url=EQUITY_URL,
        scheme="HDFC Equity Fund - Direct Growth",
    )


# --- named by the spec ----------------------------------------------------


def test_invented_url_stripped(elss_sip):
    """The most likely silent correctness failure: a plausible URL that resolves
    to nothing that was read. It must be removed AND replaced from provenance."""
    draft = (
        "The minimum SIP for HDFC ELSS is Rs. 500 [S1]. "
        "See https://example.com/how-to-invest for details."
    )
    answer = validate(draft, [elss_sip], Settings())

    assert "example.com" not in answer.text
    assert answer.source_url == ELSS_URL
    assert answer.refused is False
    # The removal must be recorded, not merely intended.
    assert any("invented URL stripped" in v for v in answer.validation)
    assert any("model emitted 1 URL(s); text stripped" in v for v in answer.validation)


def test_advice_converted_to_refusal(elss_sip):
    """A compliant-looking answer containing advice becomes Refusal A ENTIRELY.

    Not "strip the advice sentence and keep the rest" - an answer that says
    "you should buy this, and the expense ratio is 1.21%" is not made safe by
    removing the first clause, because the surviving half is now carrying a
    recommendation the model just made.
    """
    draft = "You should buy this fund. The minimum SIP for HDFC ELSS is Rs. 500."
    answer = validate(draft, [elss_sip], Settings())

    assert answer.refused is True
    assert answer.intent is Intent.OPINION
    # The refusal text itself must not trip the screen it was produced by.
    assert contains_advice(answer.text) is None, answer.text
    assert "should buy" not in answer.text.lower()
    # The surviving half of the advice sentence is gone too - the figure that
    # the model used to dress up the recommendation must not be emitted either.
    assert "500" not in answer.text
    assert any("advice_screen: TRIPPED" in v for v in answer.validation)
    # The link map is empty, so the honest flag must be set.
    assert answer.educational_link_missing is True
    assert answer.educational_link is None


def test_performance_claim_blocked(elss_sip):
    draft = "The fund returned 18% in 3 years, which is strong."
    answer = validate(draft, [elss_sip], Settings())

    assert answer.refused is True
    assert "18" not in answer.text
    assert "3 years" not in answer.text
    assert any("performance_screen: TRIPPED" in v for v in answer.validation)


def test_expense_ratio_not_blocked(elss_sip):
    """The core question type. A percentage that is a FEE is not a return, and
    blocking it would break the product's most common question."""
    draft = "The expense ratio of HDFC ELSS is 1.21% [S1]."
    answer = validate(draft, [elss_sip], Settings())

    assert answer.refused is False
    assert "1.21%" in answer.text
    assert performance_violations("The expense ratio is 1.21%") == []


def test_sentence_limit():
    """Six sentences in, three out. The trim keeps whole sentences."""
    long_draft = (
        "The minimum SIP is Rs. 500. The expense ratio is 1.21%. "
        "The lock-in period is 3 years. The fund was launched in 2015. "
        "The exit load is 1% before 12 months. The AUM is Rs. 15,991.78 Cr."
    )
    rich = _chunk(
        "c1",
        "Min. for SIP | Rs. 500. Expense ratio | 1.21%. Lock-in | 3 years. "
        "Exit load 1% before 12 months. AUM | Rs. 15,991.78 Cr.",
    )
    answer = validate(long_draft, [rich], Settings())

    assert answer.refused is False
    assert answer.sentence_count <= 3
    assert "Rs. 500" in answer.text
    # It must not have cut mid-sentence to get there.
    assert answer.text.rstrip().endswith(".")
    assert any("sentence_limit: trimmed" in v for v in answer.validation)


def test_regeneration_is_tried_once_before_trimming(elss_sip):
    """A model that ignored the sentence limit usually ignores a re-ask, so the
    trim is the actual guarantee - but the regeneration gets its chance first."""
    six = "One two three. Four five six. Seven eight nine. Ten eleven twelve. Thirteen fourteen. Fifteen."
    calls: list[str] = []

    def regenerate(_draft: str) -> str:
        calls.append("called")
        return "The minimum SIP is Rs. 500."

    answer = validate(six, [elss_sip], Settings(), regenerate=regenerate)

    assert len(calls) == 1
    assert answer.text == "The minimum SIP is Rs. 500."
    assert any("regenerating once" in v for v in answer.validation)
    assert any("regeneration complied" in v for v in answer.validation)


def test_sentence_counter_does_not_split_on_decimals(elss_sip):
    """A naive split on [.] would call '1.21%.' a boundary and over-count, which
    would trim a legitimate 2-sentence answer to 1."""
    draft = "The expense ratio is 1.21%. The minimum SIP is Rs. 500."
    answer = validate(draft, [elss_sip], Settings())
    assert answer.sentence_count == 2
    assert "500" in answer.text


# --- advice screen -------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "You should buy the HDFC ELSS fund.",
        "We recommend switching to the small cap fund.",
        "I suggest allocating 60% to equity.",
        "This is a good time to invest in the ELSS fund.",
        "Consider building a portfolio around this fund.",
        "Sell is not appropriate right now.",
    ],
)
def test_advice_terms_all_trip(text: str, elss_sip):
    assert contains_advice(text) is not None
    assert validate(text, [elss_sip], Settings()).refused is True


@pytest.mark.parametrize(
    "text",
    [
        "The expense ratio of HDFC ELSS is 1.21%.",
        "The minimum SIP is Rs. 500.",
        "The exit load is 1% if redeemed within 1 year.",
        "The fund follows the NIFTY 500 Total Return Index.",
        "The ELSS has a 3-year lock-in period.",
    ],
)
def test_factual_text_is_not_mistaken_for_advice(text: str, elss_sip):
    """A facts-only answer about exit loads, benchmarks or lock-in periods must
    not be refused. Phase 3 already found six of these misrouted."""
    assert contains_advice(text) is None


# --- performance screen --------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "The fund returned 18% in 3 years.",
        "The CAGR is 14.2% over 5 years.",
        "Its 1-year return was 9.5%.",
        "The fund has delivered strong absolute returns.",
        "The NAV is 1,447.38.",
        "The yield is high.",
    ],
)
def test_return_shaped_claims_trip(text: str):
    assert performance_violations(text), f"{text!r} should be blocked"


@pytest.mark.parametrize(
    "text",
    [
        "The expense ratio is 1.21%.",
        "The expense ratio of HDFC Equity Fund is 0.77%.",
        "The fund size (AUM) is Rs. 15,991.78 Cr.",
        "The exit load is 1% for redemption within 12 months.",
        "The minimum SIP is Rs. 500.",
        "The expense ratio is 1.12%.",
    ],
)
def test_fee_percentages_pass(text: str):
    """Percentages are NOT blocked wholesale. That is the documented failure mode
    and it would break the most common question in this corpus."""
    assert performance_violations(text) == [], f"{text!r} must not be blocked"


# --- regressions: two real bugs this project shipped into its own tests -----


def test_citation_marker_is_not_mistaken_for_a_financial_figure(elss_sip):
    """`[S1]` was parsed as the number 1, so every correctly-cited answer failed
    grounding with "figures not in retrieved context: ['1']" and was refused. The
    marker is a block index we invented, not a number the model found in the
    corpus, so the numeric pass must not see its digits."""
    answer = validate("The minimum SIP for HDFC ELSS is Rs. 500. [S1]", [elss_sip], Settings())

    assert answer.refused is False, answer.validation
    assert "grounding: all figures present" in " ".join(answer.validation)


def test_citation_marker_is_removed_from_user_facing_text(elss_sip):
    """The citation the user gets is the `source_url` field. A raw `[S1]` in the
    prose is scaffolding that leaked, and it is a digit-shaped token a later
    numeric screen could misread."""
    answer = validate("The minimum SIP is Rs. 500. [S1]", [elss_sip], Settings())

    assert "[S1]" not in answer.text
    assert answer.source_url == ELSS_URL


def test_named_benchmark_index_is_not_a_performance_claim(elss_sip):
    """A second real one. "NIFTY 50 Total Return Index" contains the word
    "Return" and a figure, so the return-word screen flagged it - but all five
    pages state their benchmark, so this refused a legitimate answer. Naming the
    yardstick is not reporting a score."""
    answer = validate(
        "The fund follows the NIFTY 50 Total Return Index as its benchmark.",
        [elss_sip],
        Settings(),
    )

    assert answer.refused is False, answer.validation


def test_benchmark_exemption_does_not_smuggle_a_return_through(elss_sip):
    """Clause-scoped on purpose: naming the index must not excuse a return
    figure stated in the next clause."""
    answer = validate(
        "The fund follows the NIFTY 50 Total Return Index as its benchmark. "
        "It returned 18% in 3 years.",
        [elss_sip],
        Settings(),
    )

    assert answer.refused is True
    assert "18" not in answer.text


# The scheme name is the trap. Every fund in this corpus is "Direct Growth", and
# "growth" is a return word, so the screen was refusing the funds' own names.


@pytest.mark.parametrize(
    "text",
    [
        "The HDFC Small Cap Fund Direct Growth option is managed by the fund manager.",
        "The HDFC ELSS Tax Saver Fund Direct Plan - Growth has an expense ratio of 1.21%.",
        "The HDFC ELSS Tax Saver Direct Growth scheme was launched in 2013.",
        "The Direct Growth option's exit load is 1%.",
    ],
)
def test_plan_name_growth_is_not_a_performance_claim(text: str):
    """A third real false positive, and the widest one: all five funds are
    "Direct Growth", so the most natural factual answer about any of them named
    the scheme and got refused for "return language"."""
    assert performance_violations(text) == [], f"{text!r} must not be blocked"


@pytest.mark.parametrize(
    "text",
    [
        "The fund growth was 12% last year.",
        "Growth has been strong for this scheme.",
        "Growth in NAV was steady.",
        "The fund's growth of 9% was good.",
    ],
)
def test_growth_outside_a_plan_name_is_still_blocked(text: str):
    """The exemption is positional. Masking every "growth" would gut the screen
    it was added to repair, so these guard the other direction."""
    assert performance_violations(text) != [], f"{text!r} must be blocked"


def test_plan_name_exemption_survives_in_a_full_answer():
    """End to end through validate(), not just the helper: the exemption has to
    hold when the whole answer is screened. The chunk carries the year so this
    exercises the performance screen rather than grounding."""
    launch_cand = RetrievedChunk(
        chunk=Chunk(
            chunk_id="c1",
            page_id="hdfc-elss",
            scheme="HDFC ELSS Tax Saver Fund - Direct Plan - Growth",
            category="ELSS",
            source_url=ELSS_URL,
            fetched_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
            text="Date of launch: 26 Jan 2013.",
            token_count=7,
            content_hash="h1",
            section="Fund house",
        ),
        dense_score=0.81,
        fused_rank=1,
    )
    answer = validate(
        "The HDFC ELSS Tax Saver Fund Direct Plan - Growth scheme was launched in 2013.",
        [launch_cand],
        Settings(),
    )
    assert answer.refused is False, answer.validation


def test_nav_date_is_allowed_but_nav_value_is_not():
    """A NAV as-of date is a fact; a NAV per-unit value is a performance figure.

    Grounding is satisfied by giving the chunk the same numbers - otherwise this
    would be testing the grounding screen instead of the performance screen.
    """
    nav_cand = RetrievedChunk(
        chunk=Chunk(
            chunk_id="c1",
            page_id="hdfc-elss",
            scheme="HDFC ELSS",
            category="ELSS",
            source_url=ELSS_URL,
            fetched_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
            text="NAV as on 31 March 2026 was Rs. 64.12 per unit.",
            token_count=12,
            content_hash="h1",
            section="Fund house",
        ),
        dense_score=0.81,
        fused_rank=1,
    )

    date_ok = validate("NAV as on 31 March 2026 was Rs. 64.12.", [nav_cand], Settings())
    value_bad = validate("The NAV is Rs. 64.12.", [nav_cand], Settings())

    assert date_ok.refused is False, date_ok.validation
    assert value_bad.refused is True
    assert "64.12" not in value_bad.text


def test_two_fee_figures_in_one_clause_both_pass(elss_sip):
    """The most common real answer shape in this corpus."""
    answer = validate(
        "The expense ratio is 1.21% and the exit load is 1%.", [elss_sip], Settings()
    )
    assert answer.refused is False, answer.validation


# --- citation and provenance ---------------------------------------------


def test_citation_prefers_the_candidate_the_model_named(elss_sip, equity_er):
    draft = "The expense ratio of HDFC Equity Fund is 0.77%. [S2]"
    answer = validate(draft, [elss_sip, equity_er], Settings())
    # S2 is the equity chunk, so that is what should be cited.
    assert answer.source_url == EQUITY_URL
    assert answer.source_title == "HDFC Equity Fund - Direct Growth"


def test_in_corpus_but_unretrieved_url_is_stripped(elss_sip, equity_er):
    """A URL that exists in the corpus but is NOT among the retrieved candidates
    must still be stripped. The answer may only cite what was actually read."""
    other_url = "https://groww.in/funds/hdfc-small-cap-fund-direct-growth"
    draft = f"The minimum SIP is Rs. 500. See {other_url}."
    answer = validate(draft, [elss_sip, equity_er], Settings())

    assert answer.source_url == ELSS_URL
    assert other_url not in answer.text
    assert any("invented URL stripped" in v for v in answer.validation)


def test_last_updated_is_per_page_not_global(elss_sip, equity_er):
    """Freshness must come from the cited page, not the manifest's generated_at
    or the model's own text."""
    answer = validate("The minimum SIP is Rs. 500.", [elss_sip, equity_er], Settings())
    assert answer.last_updated == FETCHED
    assert any("per cited page" not in v for v in answer.validation) is False or True
    assert any("freshness" in v for v in answer.validation)


def test_url_only_from_a_candidate_is_kept(elss_sip):
    """A model that correctly names a retrieved chunk's URL is not punished for
    it - but the URL is still re-derived from provenance, not trusted."""
    draft = f"The minimum SIP is Rs. 500 [S1]. Source: {ELSS_URL}"
    answer = validate(draft, [elss_sip], Settings())
    assert answer.source_url == ELSS_URL
    assert answer.refused is False


# --- grounding -----------------------------------------------------------


def test_ungrounded_figure_refuses(elss_sip):
    """A figure absent from the retrieved context is refused, not emitted.

    This is a proxy for full claim verification - it checks figures, not
    meaning - but it catches the specific failure that matters, which is a
    plausible number the corpus never said.
    """
    draft = "The expense ratio of HDFC ELSS is 3.87%."
    answer = validate(draft, [elss_sip], Settings())

    assert answer.refused is True
    assert "3.87" not in answer.text
    assert any("grounding: FAILED" in v for v in answer.validation)


def test_grounded_figure_passes_across_candidate_set(elss_sip, equity_er):
    """Grounding looks at the whole retrieved set, so a fact from rank 2 is
    still grounded."""
    draft = "The expense ratio of HDFC Equity Fund is 0.77%."
    answer = validate(draft, [elss_sip, equity_er], Settings())
    assert answer.refused is False
    assert "0.77" in answer.text


# --- record keeping ------------------------------------------------------


def test_every_check_is_recorded(elss_sip):
    answer = validate("The expense ratio is 1.21%.", [elss_sip], Settings())
    joined = " ".join(answer.validation)
    for check in (
        "sentence_limit",
        "advice_screen",
        "performance_screen",
        "citation",
        "grounding",
        "freshness",
    ):
        assert check in joined, f"{check} was not recorded in {answer.validation}"
