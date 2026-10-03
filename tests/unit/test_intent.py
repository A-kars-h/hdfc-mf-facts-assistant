"""Intent classification.

The corpus's own vocabulary is the test corpus for this file. Every opinion rule
is a word that ALSO names something factual on these pages, which is where the
misroutes came from: `exit load`, `asset allocation`, `top 10 holdings`,
`redeemed after 3 years`. A classifier that is right about "Should I buy" and
wrong about "What is the exit load" is worse than no classifier, because the
wrong answer is a confident refusal.
"""

from __future__ import annotations

import pytest

from src.ragbot.core.models import Intent
from src.ragbot.retrieval.intent import (
    NO_RULE_MATCHED,
    classify,
    explain,
    is_performance_claim,
    names_corpus_scheme,
    non_corpus_scheme,
)


# --- the two cases the spec names explicitly ---------------------------


def test_intent_opinion():
    assert classify("Should I buy HDFC Large Cap for 5 years?") is Intent.OPINION


def test_intent_factual():
    assert classify("What is the minimum SIP?") is Intent.FACTUAL


# --- corpus vocabulary must not be misrouted to a refusal ---------------


@pytest.mark.parametrize(
    "question",
    [
        "What is the exit load on HDFC Equity Fund?",
        "What are the exit load charges?",
        "What is the exit load after the lock-in period?",
        "What is the asset allocation of HDFC Balanced Advantage Fund?",
        "What are the top 10 holdings?",
        "Can I redeem after 3 years?",
        "What is the minimum SIP for HDFC ELSS?",
        "What is the benchmark of HDFC Small Cap Fund?",
        "What is the riskometer rating?",
        "What is the AUM?",
        "Who is the fund manager?",
        "What is the lock-in period for ELSS?",
    ],
)
def test_core_factual_fields_are_not_opinions(question: str):
    """Regression guard for the six misroutes found during Phase 3.

    Each of these used to classify as `opinion` and would have been refused with
    an educational link instead of answered.
    """
    match = explain(question)
    assert match.intent is Intent.FACTUAL, f"{question!r} -> {match.rule}"


# --- the statement/NAV distinction the spec calls out -------------------


def test_capital_gains_statement_download_is_factual():
    """Source-required case: a process question about a statement is FACTUAL
    even though it names capital gains, which the tax rules would otherwise
    claim."""
    match = explain("How do I download my capital-gains statement?")
    assert match.intent is Intent.FACTUAL
    assert match.rule == "statement_request"


def test_statement_request_beats_the_tax_rule():
    assert classify("How do I generate my capital gains statement?") is Intent.FACTUAL
    assert classify("How do I generate my tax statement?") is Intent.FACTUAL


def test_genuine_tax_planning_is_out_of_scope():
    assert classify("How do I file my ITR?") is Intent.OUT_OF_SCOPE
    assert classify("Can I set off capital gains tax?") is Intent.OUT_OF_SCOPE
    assert classify("What are the tax planning options?") is Intent.OUT_OF_SCOPE


# --- opinion routing ----------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "Should I buy HDFC Large Cap for 5 years?",
        "Should we invest in HDFC ELSS?",
        "Which is better, HDFC Equity or HDFC Large Cap?",
        "Is HDFC ELSS worth it?",
        "What is the best fund to invest in?",
        "Should I rebalance my portfolio?",
        "Suggest a fund for me",
        "Can you recommend a scheme?",
    ],
)
def test_advice_questions_are_opinion(question: str):
    assert classify(question) is Intent.OPINION


def test_opinion_wins_over_other_amc():
    """Documented precedence: advice about a NON-CORPUS MUTUAL FUND is still
    advice.

    Refusal A carries an educational link, and mutual-fund education is on-topic
    for "should I buy Kotak Flexi Cap". The advice context is also the one the
    source cares most about never being answered, so it is not demoted behind a
    scope check.
    """
    assert classify("Should I buy Kotak Flexi Cap?") is Intent.OPINION


def test_out_of_scope_domain_beats_opinion():
    """The counterpart, and the reason domain rules are checked first.

    "Which bank offers the best FD rate?" contains "best", so an opinion rule
    would claim it. But Refusal A would attach mutual-fund education to a
    question about bank deposits - a non-sequitur. The accurate answer is "we
    cover HDFC mutual fund pages only".
    """
    assert classify("Which bank offers the best FD rate?") is Intent.OUT_OF_SCOPE
    assert classify("Should I switch to a bank FD?") is Intent.OUT_OF_SCOPE


# --- out of scope -------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "What is the expense ratio of Kotak Flexi Cap?",
        "What is the exit load of SBI Bluechip?",
        "How do I file my ITR?",
        "What is the premium for a term insurance?",
        "Which bank offers the best FD rate?",
        "I received a legal notice from HDFC Mutual Fund",
    ],
)
def test_out_of_scope_domains(question: str):
    assert classify(question) is Intent.OUT_OF_SCOPE


def test_out_of_scope_beats_opinion_when_no_advice_is_requested():
    """A pure out-of-scope LOOKUP stays out of scope."""
    assert classify("What is the interest rate on a bank FD?") is Intent.OUT_OF_SCOPE


def test_out_of_scope_names_a_rule_for_audit():
    """Phase 6 reports which rules fire; the rule must be recoverable."""
    assert explain("What is the expense ratio of Kotak Flexi Cap?").rule == "other_amc"
    assert explain("How do I file my ITR?").rule == "tax"


# --- the unmatched default ---------------------------------------------


def test_unmatched_defaults_to_factual_and_admits_it():
    """An unrecognised phrasing must not be silently treated as answered.

    It defaults to FACTUAL so the gate and the Phase 4 output screens decide,
    but `needs_fallback` marks the seam, and the rule is explicit rather than a
    blank. Defaulting to OUT_OF_SCOPE here would refuse every phrasing this file
    failed to enumerate.
    """
    match = explain("Tell me something interesting about this fund")
    assert match.intent is Intent.FACTUAL
    assert match.rule == NO_RULE_MATCHED
    assert match.needs_fallback is True


def test_matched_rules_do_not_ask_for_fallback():
    assert explain("What is the minimum SIP?").needs_fallback is False


def test_empty_question_is_out_of_scope():
    assert classify("") is Intent.OUT_OF_SCOPE


def test_rules_are_deterministic():
    q = "What is the exit load on HDFC Equity Fund?"
    assert [classify(q) for _ in range(5)] == [Intent.FACTUAL] * 5


# --- the corpus source list -----------------------------------------------
#
# "name the hdfc fund pages that you are using" was refused as out-of-scope.
# It is a question about the corpus itself, and it is answerable: the corpus is
# `config/corpus.yaml`. These tests pin the routing in both directions, because
# the failure this fixes is a REFUSAL - a rule that is too loose here does not
# produce a wrong extra answer, it silently takes questions away from retrieval.


def test_which_pages_do_you_use_is_a_corpus_question():
    """The exact reported query, verbatim.

    It used to classify `factual`, retrieve, and be refused by the gate at
    `raw_dense_max=0.7540` against a calibrated threshold of 0.7562 - a
    two-thousandth of a cosine deciding which pages the corpus holds.
    """
    match = explain("name the hdfc fund pages that you are using")

    assert match.intent is Intent.CORPUS_SOURCES
    assert match.rule == "corpus_source_list"
    assert match.needs_fallback is False


def test_how_many_funds_are_you_referring_to_is_a_corpus_question():
    """The second reported query, verbatim, and the harder half of the bug.

    "How many mutual funds of HDFC are you referring?" was refused, and unlike
    the first report it is not a phrasing the rule merely missed: it has no
    corpus noun next to a self-reference AND a bare-verb shape. It matched
    `_SOURCE_NOUN` on "funds" and `_SOURCE_SELF` on "you", and then failed on
    "referring" - a participle, not a stem in the verb list. It classified
    `factual` on `corpus_scheme` (bare `hdfc`), retrieved, and was refused by
    the gate like every other factual question it could not beat.

    It is a question about how many pages the corpus holds, which is the one
    number the corpus definition states exactly.
    """
    match = explain("How many mutual funds of HDFC are you referring?")

    assert match.intent is Intent.CORPUS_SOURCES
    assert match.rule == "corpus_source_list"
    assert match.needs_fallback is False


def test_what_schemes_are_covered_is_a_corpus_question():
    """The third reported query, and the one with no pronoun in it at all.

    "What schemes are covered?" contains neither `you` nor any other token in
    `_SOURCE_SELF`, so the two original branches could not reach it however the
    verb list was extended. It has to be recognised by its interrogative and its
    coverage verb, which is what branch (D) does - and why that branch is gated
    on `_FACTUAL_FIELD` below.
    """
    match = explain("What schemes are covered?")

    assert match.intent is Intent.CORPUS_SOURCES
    assert match.rule == "corpus_source_list"
    assert match.needs_fallback is False


@pytest.mark.parametrize(
    "question",
    [
        "name the hdfc fund pages that you are using",
        "which pages are you using?",
        "what sources do you use?",
        "list the funds you cover",
        "which funds can you answer about?",
        "what is your corpus?",
        "name the source pages you use",
        "what are your source pages",
        "which documents does this assistant use?",
        "what pages does this app read?",
        "name the HDFC schemes you cover",
        "which HDFC mutual fund pages are in your corpus?",
        "what schemes does this assistant know?",
        # The three later reports, verbatim.
        "How many mutual funds of HDFC are you referring?",
        "Which HDFC fund pages are you using?",
        "What schemes are covered?",
        # The rest of the families those three opened up.
        "Which mutual funds of HDFC are you referring to?",
        "How many HDFC funds do you cover?",
        "How many pages are in your corpus?",
        # ...including the quantifier with no pronoun at all, which only branch
        # (C) can reach: "how many" plus "schemes" plus a coverage verb.
        "How many schemes are covered?",
        "What funds are included?",
        "Which schemes are supported?",
        "What sources are available?",
        # A quantifier and the plan suffix are both corpus extent, not fields.
        "How many HDFC Direct Growth funds do you cover?",
        "How many tax-saving funds do you cover?",
    ],
)
def test_corpus_source_list_phrasings(question: str):
    assert classify(question) is Intent.CORPUS_SOURCES


@pytest.mark.parametrize(
    "question",
    [
        # The whole sample set, verbatim. A new intent must not move any of it.
        "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
        "What is the exit load on HDFC Small Cap Fund Direct Growth?",
        "What is the minimum SIP amount for HDFC ELSS Tax Saver Fund Direct Plan Growth?",
        "What is the lock-in period for HDFC ELSS Tax Saver Fund?",
        "What is the benchmark of HDFC Balanced Advantage Fund Direct Growth?",
        "Should I buy HDFC Large Cap for a 5-year goal?",
        "Which of these five is the best performing fund?",
        "What is the expense ratio of the HDFC Mid Cap Fund?",
        # The six calibration hard-negative probes.
        "What is the expense ratio of the HDFC Nifty 50 ETF?",
        "What is the exit load of the HDFC Gold ETF?",
        "What is the AUM of the HDFC Nifty Next 50 ETF?",
        "What is the fund manager of the HDFC Banking and Financial Services ETF?",
        "What is the minimum SIP for the HDFC Nifty 100 ETF?",
        "What is the benchmark of the HDFC Nifty 50 ETF?",
        # A named scheme means the question is ABOUT that scheme.
        "What do you know about HDFC Large Cap Fund?",
        "Do you have the expense ratio for HDFC Equity Fund?",
        # "your" plus a singular "fund" is the reader's own fund, not ours.
        "What is the NAV of your fund today?",
        "What are your fund holdings?",
        # Nothing to do with the corpus at all.
        "What is the weather in Mumbai tomorrow?",
        "Which bank offers the best FD rate?",
        # A field over a plural noun is a question ABOUT the funds, however the
        # phrasing is built. These are what `_FACTUAL_FIELD` exists to veto, and
        # they are the price of branches (C) and (D) having no `you` to lean on.
        "What are the expense ratios of the funds you cover?",
        "What is the exit load of the funds you use?",
        "How many funds have a lock-in period?",
        "What are the fund managers of the schemes you cover?",
        "Which funds have the highest returns?",
        "What is the NAV of the funds in your corpus?",
        "What is the benchmark of the schemes you cover?",
        "How many funds have an expense ratio above 1.2%?",
        # Advice about the corpus is still advice, and opinion outranks this.
        "How many funds can I invest in?",
    ],
)
def test_corpus_source_list_does_not_swallow_real_questions(question: str):
    assert classify(question) is not Intent.CORPUS_SOURCES, (
        f"{question!r} was claimed as a corpus-list question"
    )


@pytest.mark.parametrize(
    ("field_question", "same_shape_without_the_field"),
    [
        # Pairs, because a negative assertion only means something next to the
        # positive it is protecting: each right-hand side is the reported query's
        # own shape, so the field word is the single difference.
        ("How many funds have a lock-in period?", "How many funds are you referring to?"),
        ("Which funds have the highest returns?", "Which funds are you covering?"),
        (
            "What are the expense ratios of the funds you cover?",
            "What are the names of the funds you cover?",
        ),
        (
            "What is the NAV of the funds in your corpus?",
            "What is in the funds of your corpus?",
        ),
    ],
)
def test_naming_a_corpus_field_is_what_keeps_a_question_out_of_the_source_list(
    field_question: str, same_shape_without_the_field: str
):
    """The veto, isolated.

    `_FACTUAL_FIELD` is a blunt instrument by design - it is a list of every
    field these five pages disclose - so it is worth pinning that it is doing the
    work these tests assume. Each pair differs only in whether a fund field is
    named, and the answer to each must differ: the left one is a question about
    a fund and must reach retrieval, the right one is a question about the
    corpus and must not.
    """
    assert classify(field_question) is not Intent.CORPUS_SOURCES
    assert classify(same_shape_without_the_field) is Intent.CORPUS_SOURCES


def test_the_amc_token_does_not_veto_the_query_that_names_it():
    """The one deliberate omission in the field list, pinned behaviorally.

    "How many mutual funds of HDFC are you referring?" names the AMC and is still
    a question about the corpus. A field list containing `hdfc` would veto the
    exact query the rule exists to answer, and asserting on the compiled pattern
    would test the implementation; asserting on the routing tests the promise.
    """
    assert classify("How many mutual funds of HDFC are you referring?") is (
        Intent.CORPUS_SOURCES
    )
    assert classify("How many HDFC funds do you cover?") is Intent.CORPUS_SOURCES
    # ...and a field still vetoes, so the AMC is not simply ignored wholesale.
    assert classify("What is the AUM of the HDFC funds you cover?") is not (
        Intent.CORPUS_SOURCES
    )


def test_scope_and_opinion_still_beat_the_corpus_source_list():
    """The new rule is the only one that can turn a refusal into an answer, so it
    is checked LAST. These three are the cases that ordering protects."""
    assert classify("Should I buy the funds you cover?") is Intent.OPINION
    assert classify("Do you cover the HDFC Mid Cap Fund?") is Intent.OUT_OF_SCOPE
    assert classify("Do you cover a bank account?") is Intent.OUT_OF_SCOPE


# --- generic scheme-detail asks -------------------------------------------
#
# "list the scheme details of HDFC ELSS" was reported as refused out-of-scope.
# It was not: `explain()` returned FACTUAL on `corpus_scheme` (the bare `\bhdfc\b`
# backstop) and retrieval then closed the gate at `raw_dense_max=0.6802` against
# the calibrated 0.7562, having correctly retrieved `hdfc-elss` at rank 1. The
# refusal was the gate, and no change to this file can move it - see
# `test_a_generic_scheme_detail_ask_reaches_retrieval` in test_pipeline.py.
#
# What WAS missing is a rule for the question. "Scheme details" is unmodelled
# vocabulary, so the query reached retrieval only by noticing the AMC token
# rather than by understanding the ask, and the same question with the AMC
# removed fell to `default:unmatched`. These tests pin the rule, and then pin
# every safeguard the new rule could plausibly have broken.


def test_scheme_detail_query_is_factual_and_names_its_rule():
    """The reported query, verbatim.

    Asserted on `rule` as well as intent on purpose. `corpus_scheme` also returns
    FACTUAL for this, so an intent-only assertion would pass on the old code and
    prove nothing; the gap being closed is that no rule understood the question.
    """
    for question in (
        "List the scheme details of HDFC ELSS",
        "What are the scheme details of HDFC ELSS?",
        "Tell me about HDFC ELSS scheme details",
        "list the scheme details of hdfc Elss",
    ):
        match = explain(question)
        assert match.intent is Intent.FACTUAL, f"{question!r} -> {match.rule}"
        assert match.rule == "scheme_details", f"{question!r} -> {match.rule}"
        assert match.needs_fallback is False


@pytest.mark.parametrize(
    "question",
    [
        # The AMC removed: these are the ones the backstop could not carry.
        "List the scheme details",
        "List the scheme details of ELSS",
        "List the scheme details of the ELSS scheme?",
        "What are the details of the ELSS scheme?",
        "Give me all the details about this fund",
        "Give me the overview of the fund",
        "key details of HDFC Equity Fund",
        # Multi-word scheme names, which is every name in corpus.yaml but one.
        "information on HDFC Large Cap Fund",
        "Give me details about HDFC Balanced Advantage Fund",
        "summary of the HDFC Small Cap Fund",
    ],
)
def test_generic_scheme_detail_asks_are_matched_by_a_rule(question: str):
    """The actual gap: these fell to `default:unmatched` before the rule.

    Intent was FACTUAL either way - the fallback defaults to FACTUAL on purpose -
    so the observable change is `needs_fallback`, which is the file's own signal
    that a phrasing went unenumerated.
    """
    match = explain(question)
    assert match.intent is Intent.FACTUAL, f"{question!r} -> {match.rule}"
    assert match.rule == "scheme_details", f"{question!r} -> {match.rule}"
    assert match.needs_fallback is False


@pytest.mark.parametrize(
    "question",
    [
        # Advice. "Scheme details" is the ask, "should I" is the intent, and
        # opinion is checked before any factual rule - Refusal A still wins.
        "Should I buy HDFC ELSS based on the scheme details?",
        "Should I switch to HDFC ELSS after seeing the scheme details?",
        "Which is better, HDFC ELSS or HDFC Large Cap - give me the scheme details?",
        "Is HDFC ELSS worth it?",
        "What is the best fund to invest in?",
        # Portfolio vocabulary. The reason `details` is never matched bare.
        "Should I rebalance my portfolio?",
        "Give me details on my portfolio",
    ],
)
def test_scheme_detail_wording_does_not_defeat_the_advice_refusal(question: str):
    assert classify(question) is Intent.OPINION, f"{question!r} -> {explain(question).rule}"


@pytest.mark.parametrize(
    "question",
    [
        # A named scheme of our own AMC that the corpus does not hold, asked for
        # in the vague way. `non_corpus_scheme` runs before `_FACTUAL_RULES`, so
        # the wording cannot launder it into retrieval - which is where the five
        # near-identical HDFC pages would match it at 0.85 and answer confidently.
        "List the scheme details of HDFC Value Fund",
        "Give me all the details about HDFC Dividend Yield Fund",
        "What are the scheme details of HDFC Mid Cap Fund?",
        "Tell me the details of HDFC Large Cap Index Fund",
        # Another AMC's scheme.
        "List the scheme details of SBI Large Cap Fund?",
        "Give me the details of Kotak Flexi Cap Fund",
    ],
)
def test_scheme_detail_wording_does_not_defeat_the_scope_refusal(question: str):
    assert classify(question) is Intent.OUT_OF_SCOPE, (
        f"{question!r} -> {explain(question).rule}"
    )


def test_etf_style_names_are_now_router_refused_not_gate_refused():
    """A boundary that has been CLOSED. Read with `test_intent.py:505` history.

    This test used to assert the opposite, and the reason it was written that way
    was sound: widening `_SCHEME_NAME` is a change to a REFUSAL rule, so it was
    deliberately not made while the scheme-details rule was in flight. What was
    not known then is how close the gate came to a false answer on the very
    questions this test names:

        "List the scheme details of the HDFC Nifty 50 ETF" -> raw_dense_max=0.7563
        calibrated SIMILARITY_THRESHOLD                        =  0.7562

    One ten-thousandth of a cosine, decided by nothing. The refusal was real but
    the margin was not, and three of the six calibration probes (P1, P3, P6) are
    ETF questions that reached the gate for the same reason. That is enough to
    close the gap, and the answer is routing: an ETF is a different product class
    from a mutual fund, so no chunk of these five pages can answer a question
    about one however well the text overlaps.

    `names_corpus_scheme` stays False for all of them, which is what keeps
    `is_source_list_question` from being affected: a corpus-extent question that
    happens to name an ETF is still about the corpus, not about the ETF.
    """
    for question in (
        "List the scheme details of the HDFC Nifty 50 ETF",
        "Give me details about HDFC Gold ETF",
    ):
        assert classify(question) is Intent.OUT_OF_SCOPE, f"{question!r}"
        assert explain(question).rule == "non_corpus_scheme", f"{question!r}"
        assert names_corpus_scheme(question) is False, f"{question!r}"


# --- ETF-shaped names, and the corpus boundary they sit on -----------------
#
# Added with the ETF fix. Two things have to hold at once, and a rule change that
# only satisfies one of them is a trade rather than a fix:
#
#   1. an HDFC product that is NOT in `config/corpus.yaml` is OUT_OF_SCOPE, and
#   2. all five schemes that ARE in it stay FACTUAL and stay corpus-named.
#
# (2) is the one with teeth. `names_corpus_scheme` is the veto inside
# `is_source_list_question` (intent.py:430), so a scope rule that grew wide
# enough to swallow a real scheme name would not show up as a broken scheme
# question - it would show up as "which pages do you cover" being answered with
# a page list. Both directions are asserted below for that reason.


@pytest.mark.parametrize(
    "question",
    [
        # The two named in the fix. `HDFC Nifty 50 ETF` is a CALIBRATION PROBE
        # (P1/P6) and was the near-miss false answer; `HDFC Nifty Next 50 ETF` is
        # P3. Both are asserted here on `rule`, not just intent, because
        # `corpus_scheme` also returns FACTUAL for both and an intent-only
        # assertion would not notice the fix being reverted.
        "What is the expense ratio of the HDFC Nifty 50 ETF?",
        "What is the AUM of the HDFC Nifty Next 50 ETF?",
        "What is the benchmark of the HDFC Nifty 50 ETF?",
        # The other three probes, so a future probe addition is not a surprise.
        "What is the exit load of the HDFC Gold ETF?",
        "What is the minimum SIP for the HDFC Nifty 100 ETF?",
        "What is the fund manager of the HDFC Banking and Financial Services ETF?",
        # The name-shape cases. A digit-initial token ("50", "100") and a
        # lowercase conjunction mid-name ("and") are both inside real HDFC
        # product names, and both break a capitalisation-anchored pattern.
        "List the scheme details of the HDFC Nifty 50 ETF",
        "Give me details about HDFC Gold ETF",
        # All-lowercase: capitalisation carries no information, so `re.I` has to
        # carry it, as `_SCHEME_NAME_LOWER` exists to do for the Fund shape.
        "list the scheme details of hdfc nifty 50 etf",
        "give me details about hdfc gold etf",
        # Plural, and the longest real product name in the probe set - four
        # intervening tokens, which a width-3 run would stop short of.
        "Compare HDFC Nifty 50 ETFs",
        "List the scheme details of the HDFC Banking and Financial Services ETF",
    ],
)
def test_etf_products_of_our_own_amc_are_out_of_scope(question: str):
    assert classify(question) is Intent.OUT_OF_SCOPE, f"{question!r} -> {explain(question).rule}"
    assert explain(question).rule == "non_corpus_scheme", f"{question!r} -> {explain(question).rule}"
    assert non_corpus_scheme(question) is True, question


@pytest.mark.parametrize(
    "question",
    [
        # All five corpus schemes, verbatim from config/corpus.yaml, in the
        # vague scheme-detail wording the fix is about. `HDFC ELSS` is
        # deliberately absent: it is the one corpus scheme whose name never
        # carries the word "Fund", so it is a different case and has its own
        # test below rather than being quietly folded in here.
        "List the scheme details of HDFC Large Cap Fund",
        "Tell me about HDFC Equity Fund scheme details",
        "summary of the HDFC Small Cap Fund",
        "Give me details about HDFC Balanced Advantage Fund",
        # ...and in the field-specific wording the golden set actually uses. A
        # fix that only left the vague phrasing alone would pass the five lines
        # above and break Q1-Q5.
        "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
        "What is the exit load on HDFC Small Cap Fund Direct Growth?",
        "What is the minimum SIP amount for HDFC ELSS Tax Saver Fund Direct Plan Growth?",
        "What is the lock-in period for HDFC ELSS Tax Saver Fund?",
        "What is the benchmark of HDFC Balanced Advantage Fund Direct Growth?",
        # The "Direct Growth" suffix is plan vocabulary, not identity. If the ETF
        # fix had made the run unbounded these would stop being corpus names.
        "What do you know about HDFC Equity Fund?",
        "List the scheme details of HDFC Equity Fund Direct Growth",
    ],
)
def test_every_corpus_scheme_stays_factual_and_named(question: str):
    assert classify(question) is Intent.FACTUAL, f"{question!r} -> {explain(question).rule}"
    assert non_corpus_scheme(question) is False, question
    assert names_corpus_scheme(question) is True, question


def test_the_five_corpus_schemes_are_exactly_the_five_that_stay_named():
    """The corpus side, read from config rather than restated.

    Restating the five names here would let a sixth scheme be added to
    `corpus.yaml` without this file noticing, which is precisely the drift the
    `_corpus_scheme_tokens` docstring warns about. So the count and the coverage
    are both asserted against the config, and the names are checked as a set.
    """
    from src.ragbot.core.config import load_corpus

    pages = load_corpus()["pages"]
    assert len(pages) == 5, "the corpus grew; add a case to this test"

    for page in pages:
        scheme = str(page["scheme"])
        question = f"List the scheme details of {scheme}"
        assert classify(question) is Intent.FACTUAL, f"{question!r}"
        assert names_corpus_scheme(question) is True, f"{question!r}"
        assert non_corpus_scheme(question) is False, f"{question!r}"


@pytest.mark.parametrize(
    "question",
    [
        # The case the fix must not disturb: a mutual fund of our own AMC that is
        # not in the corpus. It has always been router-refused, and it is the
        # one that made the ETF gap visible - "HDFC Mid Cap Fund" ends in "Fund"
        # so `_SCHEME_NAME` saw it, and "HDFC Nifty 50 ETF" did not.
        "What are the scheme details of HDFC Value Fund?",
        "List the scheme details of HDFC Value Fund",
        "Give me all the details about HDFC Dividend Yield Fund",
        "What are the scheme details of HDFC Mid Cap Fund?",
        "Tell me the details of HDFC Large Cap Index Fund",
        "What is the expense ratio of the HDFC Mid Cap Fund?",
    ],
)
def test_the_existing_out_of_corpus_fund_case_is_unchanged(question: str):
    """The regression the ETF fix could have caused, asserted directly.

    The ETF pattern is anchored on the AMC and ends in "etf", so it cannot
    produce a match here - and that is the point: a rule that is *capable* of
    matching a corpus scheme is the failure mode, and only a test on the real
    names can catch it.
    """
    assert classify(question) is Intent.OUT_OF_SCOPE, f"{question!r} -> {explain(question).rule}"
    assert explain(question).rule == "non_corpus_scheme", f"{question!r} -> {explain(question).rule}"
    assert non_corpus_scheme(question) is True, question
    assert names_corpus_scheme(question) is False, question


def test_etf_wording_does_not_reach_the_corpus_source_list_or_opinion_rules():
    """Ordering, pinned against the rules the ETF rule must not disturb.

    `non_corpus_scheme` runs at step 4b, after the other-AMC check and before
    `is_source_list_question`. Two of these are refused for a DIFFERENT reason
    than scope, and they must keep being refused for it: "is a good fund" is
    advice, and a question about the corpus that merely mentions an ETF is a
    question about the corpus.
    """
    assert classify("Is HDFC Nifty 50 ETF a good fund?") is Intent.OPINION
    assert classify("Should I buy the HDFC Nifty 50 ETF?") is Intent.OPINION
    assert classify("What is the expense ratio of the SBI Nifty 50 ETF?") is (
        Intent.OUT_OF_SCOPE
    )
    # A corpus-extent question naming no ETF at all is unaffected.
    assert classify("List the scheme details of the funds you cover") is (
        Intent.CORPUS_SOURCES
    )
    # ...and one that DOES name an ETF is still not a corpus-extent question,
    # because the named product is a specific non-corpus scheme.
    assert classify("Which pages you use covers the HDFC Nifty 50 ETF?") is not (
        Intent.CORPUS_SOURCES
    )


def test_the_elss_acronym_is_in_scope_but_invisible_to_the_name_extractor():
    """A pre-existing asymmetry, pinned so it stays visible.

    `HDFC ELSS` is the one corpus scheme whose name never carries the word
    "Fund", so `_SCHEME_NAME` cannot see it and `_scheme_candidates` returns
    nothing. Consequently `names_corpus_scheme` is False for it - the one corpus
    scheme the source-list rule's veto cannot recognise.

    This is NOT a regression from the ETF fix, and the direction of the change is
    the reason it is safe: `_scheme_candidates` only ever GAINED a list, and
    `names_corpus_scheme` returns True on the first match, so adding candidates
    can only make it answer True more often, never less.

    The gap is latent rather than live, because `names_corpus_scheme` is only ever
    reached from `is_source_list_question`, and "list the scheme details of HDFC
    ELSS" matches none of that rule's patterns - the assertion at the end pins
    that it stays CORPUS_SOURCES-negative. It would go live if a phrasing ever
    combined an ELSS-shaped name with a corpus-extent pattern, which is the reason
    this is pinned rather than left as a comment. Fixing it means teaching the
    extractor about acronyms, which is a change to a REFUSAL rule and belongs in
    its own decision record.
    """
    for question in (
        "List the scheme details of HDFC ELSS",
        "What are the details of the ELSS scheme?",
        "What is the lock-in period for HDFC ELSS Tax Saver Fund?",
    ):
        assert classify(question) is Intent.FACTUAL, f"{question!r} -> {explain(question).rule}"
        assert non_corpus_scheme(question) is False, question
    # The asymmetry itself, asserted rather than described.
    assert names_corpus_scheme("List the scheme details of HDFC ELSS") is False
    # The full name, which does carry "Fund", is recognised.
    assert names_corpus_scheme("HDFC ELSS Tax Saver Fund") is True
    # And the latent gap is still latent.
    assert classify("List the scheme details of HDFC ELSS") is not Intent.CORPUS_SOURCES


def test_an_etf_question_is_not_a_performance_claim_by_itself():
    """The output screen and the router stay separate controls.

    The same separation `scheme_details` relies on: routing an ETF to
    out-of-scope must not become a second, weaker output screen, and refusing it
    must not launder a return request past the screen that is mandated.
    """
    assert is_performance_claim("What is the expense ratio of the HDFC Nifty 50 ETF?") is False
    assert is_performance_claim("What is the 1 year return of the HDFC Nifty 50 ETF?") is True
    assert is_performance_claim("What is the exit load of the HDFC Gold ETF?") is False


@pytest.mark.parametrize(
    "question",
    [
        # Domains the corpus has nothing on. All four route out of scope, and the
        # second and third contain the literal words "scheme details"/"fund".
        "Tell me the scheme details of my bank account",
        "Give me details about the insurance term plan",
        "List the scheme details for a home loan",
        "I need legal advice about the HDFC ELSS scheme details",
        "How do I file my ITR?",
    ],
)
def test_scheme_detail_wording_does_not_defeat_the_domain_refusal(question: str):
    assert classify(question) is Intent.OUT_OF_SCOPE, (
        f"{question!r} -> {explain(question).rule}"
    )


def test_scheme_detail_ask_does_not_defeat_the_corpus_source_list():
    """A corpus-extent question that also says "scheme details" is still about
    the corpus, and is still answered from corpus.yaml without retrieval.

    This is the one collision worth stating out loud, because the new rule's
    vocabulary ("scheme details", "funds you cover") is the source-list rule's
    vocabulary too. `is_source_list_question` is checked before `_FACTUAL_RULES`,
    and the new rule was deliberately NOT added to `_FACTUAL_FIELD`, so adding it
    could not have moved this - but the pair is easy to break later.
    """
    assert classify("List the scheme details of the funds you cover") is (
        Intent.CORPUS_SOURCES
    )
    assert classify("Give me the details of the schemes you cover") is Intent.CORPUS_SOURCES
    assert classify("List the scheme details of the HDFC ELSS") is not (
        Intent.CORPUS_SOURCES
    )


def test_a_named_field_still_outranks_the_generic_scheme_detail_rule():
    """Rule ORDER, pinned. The specific field is the more useful thing to log.

    `_SCHEME_DETAIL_ASK` is placed after every field rule and before the AMC
    backstop, so a question that names a field reports the field, and a generic
    ask reports itself rather than the word `hdfc`.
    """
    assert explain("What is the exit load and the scheme details?").rule == "exit_load"
    assert explain("List the scheme details and the expense ratio").rule == "expense_ratio"
    assert explain("Scheme details: what is the lock-in period?").rule == "lock_in"
    assert explain("List the scheme details of HDFC ELSS").rule == "scheme_details"


def test_scheme_detail_rule_does_not_turn_a_performance_ask_into_a_silent_one():
    """Performance stays a CLAIM, and intent stays FACTUAL.

    The two are separate by design: the router must not become a second, weaker
    output screen. A vague "give me the details" must not launder a return
    request past `is_performance_claim`, which is what the Phase 4 screen reads.
    """
    for question in (
        "Give me the performance details of the fund",
        "Tell me the return details of HDFC ELSS over 3 years",
        "What is the CAGR of this fund?",
    ):
        assert classify(question) is Intent.FACTUAL, question
        assert is_performance_claim(question) is True, question

    # ...and a scheme-detail ask is not itself a performance claim.
    assert is_performance_claim("List the scheme details of HDFC ELSS") is False
    assert is_performance_claim("Give me all the details about this fund") is False


def test_bare_details_is_still_the_unmatched_default():
    """The negative that justifies requiring a scheme noun.

    "Details" on its own is generic English, not corpus vocabulary. Without the
    scheme noun this phrasing stays on `default:unmatched` and keeps declaring
    its own seam, which is the correct state for a phrasing no rule claims.
    """
    match = explain("Tell me something interesting about this fund")
    assert match.rule == NO_RULE_MATCHED
    assert match.needs_fallback is True


# --- performance-claim detection ---------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "What is the 3 year return?",
        "What is the CAGR?",
        "What is the yield?",
        "18% in 3 years?",
        "What is the NAV today?",
        "Which fund performed best?",
        "How much did it return over 5 years?",
    ],
)
def test_performance_claims_are_detected(question: str):
    assert is_performance_claim(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "What is the expense ratio?",  # a percentage, but a FEE
        "What is the exit load?",
        "What is the exit load after 3 years?",  # period, but about a charge
        "What is the minimum SIP?",
        "What is the AUM?",
        "What is the riskometer rating?",
        "What is the performance risk?",  # riskometer vocabulary
        "What is the benchmark?",
        "What is the lock-in period?",
    ],
)
def test_factual_questions_are_not_performance_claims(question: str):
    assert is_performance_claim(question) is False


def test_expense_ratio_percentage_is_not_a_return():
    """The trap the spec calls out by name: expense ratio is a percentage but a
    fee. Blanket percentage-blocking would break the core question type."""
    assert "expense ratio" in "1.21% expense ratio"
    assert is_performance_claim("What is the 1.21% expense ratio?") is False


# --- routing contract ---------------------------------------------------


def test_nav_price_is_factual_intent_but_flagged_as_a_claim():
    """NAV-as-price is a performance CLAIM, but it is still a question about the
    corpus. Intent routes it to retrieval; the output screen refuses to state
    the value. Making intent itself refuse would duplicate - and weaken - the
    mandated control."""
    match = explain("What is the NAV of HDFC Large Cap?")
    assert match.intent is Intent.FACTUAL
    assert is_performance_claim("What is the NAV of HDFC Large Cap?") is True
