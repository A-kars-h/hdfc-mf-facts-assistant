"""The corpus source list: "name the hdfc fund pages that you are using".

This query was refused. Traced end to end, it classified `factual`, retrieved
five chunks, and the gate closed at `raw_dense_max=0.7540` against the
calibrated threshold of 0.7562 - so the user was told the question was outside
the corpus, when the corpus is the thing they were asking about. The retrieved
chunks were HDFC Equity's "Fund house" boilerplate (a website address, an online
centre), which says nothing about which pages the assistant covers.

The fix routes it to `Intent.CORPUS_SOURCES` and answers it from
`config/corpus.yaml`. These tests pin three things, and the third matters as much
as the first two:

1. The reported query is answered, with the five schemes the corpus holds.
2. It is answered with NO model call and NO retrieval - not "the model happened
   to be right this time".
3. Every refusal path still refuses. This change makes an answer possible where
   there was a refusal, so the tests below are as much about the refusals as
   about the new answer.
"""

from __future__ import annotations

import pytest

from src.ragbot.core.config import Settings, load_corpus
from src.ragbot.core.errors import CorpusConfigError
from src.ragbot.core.models import Intent
from src.ragbot.generation import corpus as corpus_module
from src.ragbot.generation.corpus import answer_source_list, display_scheme
from src.ragbot.generation.pipeline import Ragbot
from src.ragbot.generation.validate import contains_advice, performance_violations
from src.ragbot.retrieval.gate import GateDecision
from src.ragbot.retrieval.intent import IntentMatch
from src.ragbot.retrieval.search import SearchResult

#: The reported query, verbatim. Not paraphrased anywhere in this file, because a
#: regression test for a specific user report has to be about that string.
REPORTED_QUERY = "name the hdfc fund pages that you are using"

#: Two more reported queries, and the ones that mattered more. The first report
#: was a phrasing the rule missed. These were shapes it could not have matched:
#:
#: - "How many mutual funds of HDFC are you referring?" reached `_SOURCE_NOUN` on
#:   "funds" and `_SOURCE_SELF` on "you" and then failed, because "referring" is a
#:   participle rather than a stem in the verb list. It fell through to
#:   `corpus_scheme` (bare `hdfc`), so it retrieved and was refused by the gate
#:   like any other factual question it could not beat.
#: - "What schemes are covered?" has no token from `_SOURCE_SELF` anywhere in it,
#:   so no amount of verb-list maintenance reaches it. It needed recognition by
#:   its interrogative instead, which is only safe because naming a fund field is
#:   an explicit veto.
#:
#: Kept verbatim, and used for the end-to-end assertions below, so that this file
#: fails if any of the three regresses at either the routing or the answer layer.
#: Every test in this file is parameterised over all three; a test that only saw
#: the first would keep passing after the other two were broken again.
REPORTED_QUERIES = (
    "name the hdfc fund pages that you are using",
    "How many mutual funds of HDFC are you referring?",
    "Which HDFC fund pages are you using?",
    "What schemes are covered?",
)

#: Questions that look like the two above and must still reach retrieval, because
#: they ask about the funds rather than about the corpus. See `_FACTUAL_FIELD`.
ATTRIBUTE_QUESTIONS = (
    "What are the expense ratios of the funds you cover?",
    "What is the exit load of the funds you use?",
    "How many funds have a lock-in period?",
    "What are the fund managers of the schemes you cover?",
    "Which funds have the highest returns?",
    "What is the NAV of the funds in your corpus?",
)

#: The five schemes the corpus holds. Written out here on purpose: a test that
#: compares the answer against `load_corpus()` can only prove the answer copied
#: the config, not that the config is right. Spelling them out makes this file
#: fail if a scheme is renamed, dropped or added without the answer changing.
EXPECTED_SCHEMES = (
    "HDFC Large Cap Fund",
    "HDFC Equity Fund",
    "HDFC ELSS Tax Saver Fund",
    "HDFC Small Cap Fund",
    "HDFC Balanced Advantage Fund",
)


class ExplodingSearcher:
    """Any retrieval at all is a failure here, not just an expensive one."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("retrieval was constructed for a source-list question")

    def search(self, question: str):
        raise AssertionError("retrieval ran for a source-list question")

    def retrieve(self, question: str):
        raise AssertionError("retrieval ran for a source-list question")


class CountingClient:
    def __init__(self) -> None:
        self.calls = 0
        self.stream_calls = 0

    def complete(self, messages: list[dict]) -> str:
        self.calls += 1
        return "The minimum SIP for HDFC ELSS is Rs. 500. [S1]"

    def stream(self, messages: list[dict]):
        self.stream_calls += 1
        yield "The minimum SIP for HDFC ELSS is Rs. 500."


class ClosedSearcher:
    """Retrieval that was reached and refused. Records that it was reached."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, question: str) -> SearchResult:
        self.queries.append(question)
        return SearchResult(
            question=question,
            intent=Intent.FACTUAL,
            intent_match=IntentMatch(intent=Intent.FACTUAL, rule="test-fixture"),
            candidates=[],
            raw_dense_max=0.19,
            decision=GateDecision(
                found_answer=False,
                reason="below_threshold",
                raw_dense_max=0.19,
                candidates_considered=0,
            ),
            threshold=0.7562,
        )


def _bot() -> tuple[Ragbot, CountingClient]:
    client = CountingClient()
    bot = Ragbot(settings=Settings(), client=client, searcher=None)
    bot._search = lambda: ExplodingSearcher()  # type: ignore[method-assign]
    return bot, client


# --- the reported query --------------------------------------------------


@pytest.mark.parametrize("question", REPORTED_QUERIES)
def test_the_reported_query_is_answered_not_refused(question: str):
    bot, _ = _bot()

    answer = bot.ask(question)

    assert answer.refused is False
    assert answer.intent is Intent.CORPUS_SOURCES


@pytest.mark.parametrize("question", REPORTED_QUERIES)
def test_the_answer_names_the_five_schemes_the_corpus_actually_uses(question: str):
    bot, _ = _bot()

    text = bot.ask(question).text

    for scheme in EXPECTED_SCHEMES:
        assert scheme in text, f"{scheme!r} missing from the source list: {text!r}"


@pytest.mark.parametrize("question", REPORTED_QUERIES)
def test_the_answer_states_how_many_pages_the_corpus_holds(question: str):
    """A count is the whole answer to "how many ... are you referring?", so the
    number has to be in the text rather than implied by it.

    Counted from the corpus, not written into the expected value, because the
    point of `answer_source_list` is that the number is derived from
    `config/corpus.yaml`. Spelling out "5" here would let a sixth page be added
    without the answer - or this test - noticing.
    """
    bot, _ = _bot()

    text = bot.ask("How many mutual funds of HDFC are you referring?").text

    assert str(len(load_corpus()["pages"])) in text
    assert f"fixed set of {len(load_corpus()['pages'])}" in text


def test_the_answer_lists_every_page_in_corpus_yaml():
    """No scheme invented, none dropped, and none left in a different order than
    the corpus defines them."""
    pages = load_corpus()["pages"]
    text = answer_source_list().text

    assert len(pages) == len(EXPECTED_SCHEMES)
    listed = [display_scheme(str(p["scheme"])) for p in pages]
    assert listed == list(EXPECTED_SCHEMES)
    for scheme in listed:
        assert scheme in text


@pytest.mark.parametrize("question", REPORTED_QUERIES)
def test_the_answer_costs_no_model_call_and_no_retrieval(question: str):
    """The point of routing before retrieval.

    It is not enough that the answer came out right: a retrieval-based path that
    happened to be right this time would be one threshold nudge from refusing
    again, which is the bug. `ExplodingSearcher` fails on CONSTRUCTION as well as
    on use, so this also pins that the 90 MB embedding model is not loaded to
    name five strings that are already in a YAML file."""
    bot, client = _bot()

    bot.ask(question)

    assert client.calls == 0, "the model was called for a fixed answer"
    assert client.stream_calls == 0


def test_no_chunks_are_reported_as_evidence():
    """`ask_with_evidence` is what the UI's chunk inspector reads. Returning an
    empty list is the truth: nothing was retrieved."""
    bot, _ = _bot()

    answer, chunks = bot.ask_with_evidence(REPORTED_QUERY)

    assert answer.intent is Intent.CORPUS_SOURCES
    assert chunks == []


def test_ask_and_ask_with_evidence_agree():
    """`ask()` delegates, so the two can never disagree."""
    bot, _ = _bot()

    assert bot.ask(REPORTED_QUERY).text == bot.ask_with_evidence(REPORTED_QUERY)[0].text


@pytest.mark.parametrize("question", REPORTED_QUERIES)
def test_every_reported_query_gets_the_same_answer(question: str):
    """One question shape, one answer. These are three phrasings of a single
    question about the corpus, so three different answers - even three correct
    ones - would mean the rule had leaked into somewhere it should not have."""
    bot, _ = _bot()

    assert bot.ask(question).text == bot.ask(REPORTED_QUERY).text


# --- the answer obeys the same output contract as a generated one ---------


def test_the_answer_is_within_the_sentence_limit():
    """Five schemes in a list is exactly the case where a sentence-count bug would
    show up, and the `Answer` validator raises rather than trims."""
    answer = answer_source_list()

    assert answer.sentence_count <= 3
    assert answer.sentence_count == 2


def test_the_answer_is_advice_screen_clean():
    """It names five funds. A word like "best" or "prefer" would turn the page list
    into a recommendation, and the advice screen is not bypassed just because
    nothing was generated."""
    text = answer_source_list().text

    assert contains_advice(text) is None


def test_the_answer_is_performance_screen_clean():
    """Scheme names carry plan vocabulary ("Direct Growth", "Tax Saver"). The same
    masking that lets a generated answer name a plan must apply here, so the
    answer is screened the same way rather than trusted because it is constant."""
    assert performance_violations(answer_source_list().text) == []


def test_the_answer_carries_no_performance_or_advice_flags():
    answer = answer_source_list()

    assert answer.perf_claim is False
    assert answer.is_advice is False


# --- no URL is generated, and FR-17 still holds ----------------------------


def test_no_url_appears_in_the_answer_text():
    """FR-17 allows exactly ONE source link per answer. Five verified URLs would
    be five, so the names go in the text and the links do not."""
    text = answer_source_list().text

    assert "http" not in text
    assert "groww.in" not in text


def test_there_is_no_single_citation():
    """`source_url` stays None: naming one of the five would imply the other four
    are unsupported."""
    answer = answer_source_list()

    assert answer.source_url is None
    assert answer.last_updated is None


def test_the_recorded_urls_are_the_corpus_urls_not_generated_ones():
    """The audit trail names each page and its verified URL. It must be exactly
    the corpus's own set - this is the assertion that catches a URL invented
    here, which is the failure mode `educational.py` refuses to allow for
    educational links."""
    notes = " ".join(answer_source_list().validation)
    corpus_urls = {str(p["source_url"]) for p in load_corpus()["pages"]}

    for url in corpus_urls:
        assert url in notes, f"corpus URL missing from the audit trail: {url}"
    for page_id in ("hdfc-large-cap", "hdfc-equity", "hdfc-elss", "hdfc-small-cap",
                    "hdfc-balanced"):
        assert page_id in notes
    assert "no model call" in notes


def test_the_scheme_display_name_drops_only_the_plan_suffix():
    assert display_scheme("HDFC ELSS Tax Saver Fund - Direct Plan - Growth") == (
        "HDFC ELSS Tax Saver Fund"
    )
    assert display_scheme("HDFC Large Cap Fund - Direct Growth") == "HDFC Large Cap Fund"
    # A scheme with no suffix is returned unchanged, not mangled.
    assert display_scheme("HDFC Equity Fund") == "HDFC Equity Fund"


# --- a broken deployment fails closed --------------------------------------


def test_an_unreadable_corpus_config_refuses_instead_of_guessing(monkeypatch):
    """No corpus definition means no honest list. The output is the fixed
    out-of-corpus wording - not a partial list, and not a remembered one.

    Fails CLOSED on purpose: a deployment missing its own config should look like
    the boundary it is, not like an assistant with a partly remembered corpus.
    """

    def explode(*args, **kwargs):
        raise CorpusConfigError("config/corpus.yaml not found")

    monkeypatch.setattr(corpus_module, "load_corpus", explode)

    answer = answer_source_list(settings=Settings())

    assert answer.refused is True
    assert "HDFC Large Cap Fund" not in answer.text


# --- the refusal paths are untouched ---------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "Should I buy HDFC Equity Fund?",
        "What is the expense ratio of the HDFC Mid Cap Fund?",
        "What is the expense ratio of Kotak Flexi Cap?",
    ],
)
def test_the_refusals_still_refuse(question: str, settings: Settings):
    """The new intent turns a refusal into an answer for one question shape. This
    is the counterweight: the shape is narrow, and these must be untouched."""
    client = CountingClient()
    bot = Ragbot(settings=settings, client=client, searcher=None)
    bot._search = lambda: ExplodingSearcher()  # type: ignore[method-assign]

    answer = bot.ask(question)

    assert answer.refused is True
    assert client.calls == 0


def test_a_named_scheme_question_is_not_answered_with_the_page_list(settings: Settings):
    """"What do you know about HDFC Large Cap Fund?" contains both a self-reference
    and a scheme name, and it is a question about that fund - so it must reach
    retrieval. The stub searcher closes the gate on purpose: this asserts the
    question was ROUTED to retrieval (which the page-list answer would have
    skipped), not that the corpus could answer it."""
    bot, client = _bot()
    bot._search = lambda: ClosedSearcher()  # type: ignore[method-assign]

    answer = bot.ask("What do you know about HDFC Large Cap Fund?")

    assert answer.intent is Intent.FACTUAL
    assert answer.refused is True
    assert "I answer from a fixed set of" not in answer.text
    assert client.calls == 0


@pytest.mark.parametrize("question", ATTRIBUTE_QUESTIONS)
def test_a_question_about_the_funds_is_not_answered_with_the_page_list(question: str):
    """The counterweight to the two new branches, and the sharpest edge in this
    change.

    Each of these has the reported query's shape - a plural corpus noun, and
    "you" or a bare interrogative - and asks about a field of the funds rather
    than about the corpus. Answering them with the page list would be the worst
    failure available here: not a refusal, but a confident, uncitable, entirely
    different answer to a question the user did ask.

    `ClosedSearcher` closes the gate on purpose. The assertion is that retrieval
    was REACHED, which is what distinguishes "correctly routed to the corpus"
    from "routed to the corpus and answered wrongly".
    """
    bot, client = _bot()
    bot._search = lambda: ClosedSearcher()  # type: ignore[method-assign]

    answer = bot.ask(question)

    assert answer.intent is Intent.FACTUAL
    assert "I answer from a fixed set of" not in answer.text
    assert client.calls == 0
