"""The orchestrator's ordering guarantees.

These tests exist because the interesting failure modes in a pipeline like this
are not crashes - they are silent "it worked" states that a user cannot tell
apart from a correct one:

    - the model was called for a question that should have been refused
    - a refusal leaked the threshold, so the gate can be probed
    - a prohibited draft was returned because validation ran after display
    - PII pending was reported on generated answers but hidden on refusals

The client is a counting fake and the searcher is a stub with the real
signature, so "zero LLM calls" is an assertion on a number rather than an
absence of output.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.ragbot.core.config import Settings
from src.ragbot.core.errors import NotCalibratedError
from src.ragbot.core.models import Chunk, Intent, RetrievedChunk
from src.ragbot.generation import pipeline as pipeline_module
from src.ragbot.generation.pipeline import Ragbot
from src.ragbot.retrieval.gate import GateDecision
from src.ragbot.retrieval.intent import IntentMatch
from src.ragbot.retrieval.search import SearchResult
from src.ragbot.safety import pii

URL = "https://groww.in/funds/hdfc-elss-tax-saver-fund-direct-growth"


class CountingClient:
    """Records every call. `script` lets a test control what comes back."""

    def __init__(self, script: list[str] | None = None):
        self.calls: list[list[dict]] = []
        self.stream_calls = 0
        self._script = list(script or ["The minimum SIP for HDFC ELSS is Rs. 500. [S1]"])

    def complete(self, messages: list[dict]) -> str:
        self.calls.append(messages)
        return self._script[min(len(self.calls) - 1, len(self._script) - 1)]

    def stream(self, messages: list[dict]):
        self.stream_calls += 1
        self.calls.append(messages)
        for piece in ("The ", "minimum SIP ", "is Rs. 500."):
            yield piece

    @property
    def call_count(self) -> int:
        return len(self.calls)


def _cand(rank: int = 1, text: str = "Minimum for SIP | Rs. 500.") -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(
            chunk_id=f"c{rank}",
            page_id="hdfc-elss",
            scheme="HDFC ELSS Tax Saver - Direct Growth",
            category="ELSS",
            source_url=URL,
            fetched_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
            text=text,
            token_count=len(text.split()),
            content_hash=f"h{rank}",
            section="Fund house",
        ),
        dense_score=0.81,
        fused_rank=rank,
    )


class StubSearcher:
    """Stands in for HybridSearcher without loading the embedding model.

    It records whether it was *constructed*, which is how the "refuse before
    retrieval" claim is tested: building the real searcher loads a 90 MB model,
    and the point of routing first is that an opinion refusal never pays that.
    """

    def __init__(self, result: SearchResult | None = None, raise_uncalibrated: bool = False):
        self._result = result
        self._raise_uncalibrated = raise_uncalibrated
        self.queries: list[str] = []
        self.retrieve_calls = 0

    def retrieve(self, question: str) -> SearchResult:
        self.queries.append(question)
        self.retrieve_calls += 1
        return self._result if self._result is not None else _open_result()

    def search(self, question: str) -> SearchResult:
        self.queries.append(question)
        if self._raise_uncalibrated:
            raise NotCalibratedError()
        return self._result if self._result is not None else _open_result()


def _match(intent: Intent = Intent.FACTUAL) -> IntentMatch:
    return IntentMatch(intent=intent, rule="test-fixture", needs_fallback=False)


def _open_result(*candidates: RetrievedChunk) -> SearchResult:
    cands = list(candidates) or [_cand()]
    return SearchResult(
        question="q",
        intent=Intent.FACTUAL,
        intent_match=_match(),
        candidates=cands,
        raw_dense_max=0.81,
        decision=GateDecision(
            found_answer=True,
            reason="raw_dense_max above calibrated threshold",
            raw_dense_max=0.81,
            candidates_considered=len(cands),
        ),
        dense_hits=[],
        sparse_hits=[],
        sparse_available=True,
        performance_claim=False,
        threshold=0.55,
    )


def _closed_result(reason: str = "below_threshold") -> SearchResult:
    return SearchResult(
        question="q",
        intent=Intent.FACTUAL,
        intent_match=_match(),
        candidates=[_cand()],
        raw_dense_max=0.19,
        decision=GateDecision(
            found_answer=False,
            reason=reason,
            raw_dense_max=0.19,
            candidates_considered=1,
        ),
        dense_hits=[],
        sparse_hits=[],
        sparse_available=True,
        performance_claim=False,
        threshold=0.55,
    )


# `settings` is a shared fixture and lives in tests/conftest.py, so the Phase 5
# integration tests get the same one.


# --- the two named done-when tests ----------------------------------------


def test_low_similarity_makes_zero_llm_calls(settings: Settings):
    """Closed gate. The model is not consulted, because there is nothing
    trustworthy to ground it in."""
    client = CountingClient()
    bot = Ragbot(
        settings=settings,
        client=client,
        searcher=StubSearcher(_closed_result()),
    )

    answer = bot.ask("What is the exit load on the small cap fund?")

    assert answer.refused is True
    assert client.call_count == 0, "the model was called despite a closed gate"


def test_opinion_never_generates(settings: Settings):
    """Advice-seeking questions match this corpus strongly - that is what makes
    them dangerous. Retrieval is the wrong control for them, so they are refused
    on routing, and this asserts the absence of all three costs: no LLM call, no
    search, and no searcher construction."""
    client = CountingClient()
    searcher = StubSearcher(_open_result())
    bot = Ragbot(settings=settings, client=client, searcher=searcher)

    answer = bot.ask("Should I buy HDFC Equity Fund for my portfolio?")

    assert answer.refused is True
    assert answer.intent is Intent.OPINION
    assert client.call_count == 0, "the model was called for an advice question"
    assert searcher.queries == [], "retrieval ran for a routed refusal"


def test_out_of_corpus_never_generates(settings: Settings):
    """Out-of-corpus questions reach the gate rather than the router, and the gate
    is what stops them.

    Worth stating because it is not the shape one would guess: `explain()` only
    routes advice-seeking questions. "What is the weather in Mumbai?" is
    classified `factual`, because refusing on wording alone is brittle - and
    because this corpus is HDFC funds, so a weather question is genuinely
    answerable *in principle* and only out of scope *in this corpus*. The
    similarity gate is the correct control for that, and the requirement is
    therefore about call counts, not about the routing label.
    """
    client = CountingClient()
    bot = Ragbot(
        settings=settings,
        client=client,
        searcher=StubSearcher(_closed_result(reason="no_dense_match")),
    )

    answer = bot.ask("What is the weather in Mumbai tomorrow?")

    assert answer.refused is True
    assert client.call_count == 0, "the model was called for an out-of-corpus question"


def test_a_generic_scheme_detail_ask_reaches_retrieval(settings: Settings):
    """A vague but in-corpus scheme ask is a retrieval, not a refusal.

    "List the scheme details of HDFC ELSS" was reported as an out-of-scope
    refusal. The refusal was the CONFIDENCE GATE, not the router: the real
    embedder scores it `raw_dense_max=0.6802` against a calibrated 0.7562, while
    retrieving the correct page (`hdfc-elss`) at rank 1. Generic wording has low
    cosine overlap with any single chunk, and no rule in this file can change
    that - only retrieval quality or the calibrated threshold can, and both are
    measured elsewhere.

    So this test asserts the half that IS this project's decision, with a gate
    stubbed open: the question must reach retrieval and generate. Without it, a
    future rule that matched "scheme details" too eagerly - or a scope check that
    started reading the word "scheme" as a scheme NAME - would reintroduce the
    reported refusal as a routing failure, which is the part that would be
    invisible in the gate's log line.
    """
    client = CountingClient()
    searcher = StubSearcher(_open_result())
    bot = Ragbot(settings=settings, client=client, searcher=searcher)

    answer = bot.ask("List the scheme details of HDFC ELSS")

    assert answer.intent is Intent.FACTUAL
    assert answer.refused is False
    assert searcher.queries == ["List the scheme details of HDFC ELSS"]
    assert client.call_count == 1


def test_scheme_detail_wording_still_refuses_before_retrieval(settings: Settings):
    """The counterpart: the new rule must not have widened routing.

    Same wording, three different intents, three different controls. Opinion and
    out-of-scope are refused on routing; the corpus-extent phrasing is ANSWERED
    from `corpus.yaml` (it is a question the corpus answers exactly, so it is not
    a refusal and `refused` is False - only its retrieval count is zero). What
    all three share, and what this asserts, is that none of them reaches the
    searcher or the model. Only the in-corpus scheme ask does.
    """
    for question, expected in (
        ("Should I buy HDFC ELSS? Show me the scheme details", Intent.OPINION),
        ("List the scheme details of HDFC Mid Cap Fund", Intent.OUT_OF_SCOPE),
        ("List the scheme details of the funds you cover", Intent.CORPUS_SOURCES),
    ):
        client = CountingClient()
        searcher = StubSearcher(_open_result())
        bot = Ragbot(settings=settings, client=client, searcher=searcher)

        answer = bot.ask(question)

        assert answer.intent is expected, f"{question!r}"
        assert searcher.queries == [], f"retrieval ran for {question!r}"
        assert client.call_count == 0, f"the model was called for {question!r}"

    # And the two that are genuinely refusals say so.
    opinion = Ragbot(
        settings=settings, client=CountingClient(), searcher=StubSearcher(_open_result())
    ).ask("Should I buy HDFC ELSS? Show me the scheme details")
    assert opinion.refused is True


def test_etf_questions_are_refused_before_retrieval(settings: Settings):
    """The ETF scope fix, asserted at the orchestrator, not just at the router.

    "List the scheme details of the HDFC Nifty 50 ETF" used to reach the
    confidence gate and was refused at `raw_dense_max=0.7563` against the
    calibrated 0.7562 - one ten-thousandth of a cosine. It is now a routing
    refusal, and this asserts the half that matters operationally: retrieval
    never runs and the model is never called, so the answer does not depend on a
    number that was never going to stay put.

    The `refused` flag is True rather than a refusal-by-accident, and the
    searcher is stubbed with an OPEN gate - if the question ever reached it, this
    test would fail by generating an answer, which is the failure mode.
    """
    for question in (
        "List the scheme details of the HDFC Nifty 50 ETF",
        "What is the AUM of the HDFC Nifty Next 50 ETF?",
        "What is the expense ratio of the HDFC Nifty 50 ETF?",
    ):
        client = CountingClient()
        searcher = StubSearcher(_open_result())
        bot = Ragbot(settings=settings, client=client, searcher=searcher)

        answer = bot.ask(question)

        assert answer.intent is Intent.OUT_OF_SCOPE, f"{question!r}"
        assert answer.refused is True, f"{question!r}"
        assert searcher.queries == [], f"retrieval ran for {question!r}"
        assert client.call_count == 0, f"the model was called for {question!r}"


def test_a_corpus_scheme_is_still_answered_after_the_etf_fix(settings: Settings):
    """The other half of the same boundary, and the one with more users.

    The ETF fix widens a REFUSAL rule, so the risk is not losing refusals - it is
    acquiring one that should not have been. All five corpus schemes must still
    reach retrieval and the model. The gate is stubbed OPEN so a routing change
    is what the test observes.
    """
    for question in (
        "List the scheme details of HDFC Large Cap Fund",
        "Tell me about HDFC Equity Fund scheme details",
        "List the scheme details of HDFC ELSS",
        "summary of the HDFC Small Cap Fund",
        "Give me details about HDFC Balanced Advantage Fund",
        # The golden set's own five, verbatim.
        "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
        "What is the exit load on HDFC Small Cap Fund Direct Growth?",
        "What is the minimum SIP amount for HDFC ELSS Tax Saver Fund Direct Plan Growth?",
        "What is the lock-in period for HDFC ELSS Tax Saver Fund?",
        "What is the benchmark of HDFC Balanced Advantage Fund Direct Growth?",
    ):
        client = CountingClient()
        searcher = StubSearcher(_open_result())
        bot = Ragbot(settings=settings, client=client, searcher=searcher)

        answer = bot.ask(question)

        assert answer.intent is Intent.FACTUAL, f"{question!r}"
        assert answer.refused is False, f"{question!r}"
        assert searcher.queries == [question], f"retrieval did not run for {question!r}"
        assert client.call_count == 1, f"the model was not called for {question!r}"


def test_uncalibrated_gate_never_generates(settings: Settings):
    """The pre-Phase-6 state. An unset threshold must refuse, not default to
    permissive and answer everything."""
    client = CountingClient()
    bot = Ragbot(
        settings=settings,
        client=client,
        searcher=StubSearcher(raise_uncalibrated=True),
    )

    answer = bot.ask("What is the expense ratio of the ELSS fund?")

    assert answer.refused is True
    assert client.call_count == 0


# --- routing happens before the embedding model is loaded -----------------


def test_opinion_refusal_does_not_construct_a_searcher(settings: Settings):
    """`Ragbot.searcher` stays None, which is the observable form of 'the 90 MB
    model was never loaded'."""

    class ExplodingSearcher:
        def __init__(self, *a, **k):
            raise AssertionError("retrieval was constructed for an opinion refusal")

        def search(self, question):
            raise AssertionError("retrieval ran for an opinion refusal")

    bot = Ragbot(settings=settings, client=CountingClient(), searcher=None)
    # Route through _search being unreachable: patch the class it would use.
    bot._search = lambda: ExplodingSearcher()  # type: ignore[method-assign]

    answer = bot.ask("Should I invest in the ELSS fund for tax savings?")

    assert answer.refused is True
    assert answer.intent is Intent.OPINION


# --- the generated path ----------------------------------------------------


def test_open_gate_generates_once_and_returns_grounded_answer(settings: Settings):
    client = CountingClient()
    bot = Ragbot(settings=settings, client=client, searcher=StubSearcher(_open_result()))

    answer = bot.ask("What is the minimum SIP for HDFC ELSS?")

    assert client.call_count == 1
    assert answer.refused is False
    assert answer.source_url == URL  # from provenance, not the draft
    assert "groww.in" not in answer.text  # never model-authored
    # Provenance, not the model. A datetime here would be the model asserting a
    # fetch date it cannot know.
    assert answer.last_updated is not None
    assert answer.last_updated.date().isoformat() == "2026-09-27"


def test_citation_marker_is_not_left_in_user_facing_text(settings: Settings):
    """`[S1]` is scaffolding between us and the model. The citation the user gets
    is `source_url`; a raw marker in the prose is noise, and it is also a
    number-shaped token that a future numeric screen could misread."""
    client = CountingClient()
    bot = Ragbot(settings=settings, client=client, searcher=StubSearcher(_open_result()))

    answer = bot.ask("What is the minimum SIP for HDFC ELSS?")

    assert "[S1]" not in answer.text
    assert answer.source_url == URL  # the citation is still there, as a field


def test_a_prohibited_draft_is_refused_not_returned(settings: Settings):
    """Validation runs before the Answer exists. The advice draft must become a
    refusal, because the alternative is a user reading it."""
    client = CountingClient(script=["You should invest in HDFC ELSS for tax benefits."])
    bot = Ragbot(settings=settings, client=client, searcher=StubSearcher(_open_result()))

    answer = bot.ask("What is the minimum SIP for HDFC ELSS?")

    assert answer.refused is True
    assert "should invest" not in answer.text.lower()


def test_a_draft_with_an_invented_url_is_refused_not_stripped_quietly(settings: Settings):
    """Silent stripping would hide a real defect: the model reaching for a URL is
    evidence it is blending outside knowledge, not a typo."""
    client = CountingClient(
        script=["The minimum SIP is Rs. 500. See https://example.com/invest for details."]
    )
    bot = Ragbot(settings=settings, client=client, searcher=StubSearcher(_open_result()))

    answer = bot.ask("What is the minimum SIP for HDFC ELSS?")

    assert "example.com" not in answer.text


# --- refusals carry their own audit trail ---------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "Should I buy HDFC Equity Fund?",
        "What is the weather in Mumbai?",
        "What is the minimum SIP for HDFC ELSS?",
    ],
)
def test_no_answer_disclaims_that_pii_scanning_is_unenforced(
    settings: Settings, question: str
):
    """Including refusals.

    The disclosure was attached to every answer while the Phase 5 gate was inert.
    Now that detection is real, the disclaimer must be GONE - a permanent
    "PII scanning is not enforced" note on a system that does scan is a false
    statement, and a stale safety notice trains people to ignore safety notices.
    """
    bot = Ragbot(
        settings=settings,
        client=CountingClient(),
        searcher=StubSearcher(_closed_result()),
    )
    answer = bot.ask(question)

    joined = " ".join(answer.validation)
    assert "NOT ENFORCED" not in joined, answer.validation
    assert "Phase 5 pending" not in joined, answer.validation


def test_every_answer_records_the_scan_that_actually_ran(settings: Settings):
    """The audit trail must name the scanner, so a stubbed scan is visible."""
    bot = Ragbot(
        settings=settings, client=CountingClient(), searcher=StubSearcher(_closed_result())
    )
    answer = bot.ask("What is the minimum SIP for HDFC ELSS?")
    joined = " ".join(answer.validation)
    assert "pii_scan" in joined
    assert pii.SCANNER_ID in joined, "notes must name the real scanner"


# --- a refusal is not a place to leak the gate ----------------------------


def test_refusal_does_not_reveal_the_threshold(settings: Settings):
    """Repeated probing plus a leaked number turns a gate into a tunable
    parameter."""
    bot = Ragbot(
        settings=settings, client=CountingClient(), searcher=StubSearcher(_closed_result())
    )
    answer = bot.ask("What is the minimum SIP for HDFC ELSS?")

    lowered = answer.text.lower()
    for word in ("threshold", "similarity", "0.81", "0.19", "dense", "cosine"):
        assert word not in lowered, f"refusal leaked {word!r}: {answer.text}"


def test_refusal_text_is_identical_whether_out_of_scope_or_gated(settings: Settings):
    """Otherwise the wording reveals WHICH check failed, and the user learns the
    gate is a real boundary they can push against."""
    gated = Ragbot(
        settings=settings, client=CountingClient(), searcher=StubSearcher(_closed_result())
    ).ask("What is the exit load on the small cap fund?")

    unscoped = Ragbot(
        settings=settings, client=CountingClient(), searcher=StubSearcher(_closed_result())
    ).ask("What is the weather in Mumbai?")

    assert gated.text == unscoped.text


# --- the streaming seam ----------------------------------------------------


def test_stream_draft_refuses_to_stream_a_routed_refusal(settings: Settings):
    """Streaming is a generation path. If it streamed for an opinion question it
    would be an end run around the refusal."""
    client = CountingClient()
    bot = Ragbot(settings=settings, client=client, searcher=StubSearcher(_open_result()))

    assert list(bot.stream_draft("Should I buy HDFC Equity Fund?")) == []
    assert client.stream_calls == 0


def test_stream_draft_yields_unvalidated_text_when_open(settings: Settings):
    """Documenting the hazard, not endorsing it: the fragments are exactly what
    validate() would have to reject. This test exists so that if someone starts
    treating stream_draft as a display path, this fails loudly."""
    client = CountingClient()
    bot = Ragbot(settings=settings, client=client, searcher=StubSearcher(_open_result()))

    fragments = list(bot.stream_draft("What is the minimum SIP for HDFC ELSS?"))

    assert fragments  # tokens were produced
    assert client.stream_calls == 1
    # The reassembled text is NOT an Answer: no validation, no citation.
    assert "".join(fragments) == "The minimum SIP is Rs. 500."


# --- the PII gate is enforced, not merely wired -----------------------------


def test_pii_scan_runs_before_classification_retrieval_and_the_model(
    settings: Settings,
):
    """The ordering invariant, asserted on order rather than on a count.

    A count would be the wrong thing to pin: an earlier version of the logging
    filter ran the detector on every log record, which made a single `ask()`
    scan three times and turned this into a test of logging internals. What
    actually matters is that the FIRST thing that happens is a scan, and that
    nothing downstream of it runs before it.
    """
    events: list[str] = []
    real_scan = pii.scan

    def fake_scan(question: str) -> pii.PIIResult:
        events.append("scan")
        return real_scan(question)  # the ORIGINAL, or this recurses forever

    def tracking_explain(question: str):
        events.append("classify")
        return real_explain(question)

    real_explain = pipeline_module.explain
    original = pii.scan
    pii.scan = fake_scan  # type: ignore[assignment]
    pipeline_module.explain = tracking_explain  # type: ignore[assignment]
    try:
        searcher = StubSearcher(_open_result())
        client = CountingClient()
        bot = Ragbot(settings=settings, client=client, searcher=searcher)
        bot.ask("What is the minimum SIP for HDFC ELSS?")
    finally:
        pii.scan = original  # type: ignore[assignment]
        pipeline_module.explain = real_explain  # type: ignore[assignment]

    assert events[0] == "scan", f"scan was not first: {events}"
    assert "classify" in events
    assert events.index("scan") < events.index("classify")
    assert client.call_count == 0 or events.index("classify") < len(events)


def test_pii_finding_stops_the_request_before_retrieval_and_the_model(
    settings: Settings,
):
    """A finding must stop the request, not merely annotate it.

    Asserts on observable counters - the searcher was never queried and the
    client was never called - rather than on the absence of output, so a stub
    that returns "" cannot make this pass.
    """
    searcher = StubSearcher(_open_result())
    client = CountingClient()
    bot = Ragbot(settings=settings, client=client, searcher=searcher)

    answer = bot.ask("My PAN is ABCPA1234B, what is the exit load?")

    assert answer.refused is True
    assert searcher.queries == [], "retrieval ran despite a PII finding"
    assert client.call_count == 0, "the model was called despite a PII finding"
    assert client.stream_calls == 0


def test_pii_finding_returns_the_neutral_refusal_not_an_exception(settings: Settings):
    """FR-31 asks for a neutral message. Raising would surface a traceback."""
    bot = Ragbot(
        settings=settings, client=CountingClient(), searcher=StubSearcher(_open_result())
    )
    answer = bot.ask("mail me at ravi.kumar@example.co.in")

    assert answer.text == pii.NEUTRAL_MESSAGE
    assert "ravi.kumar" not in answer.text


@pytest.mark.parametrize(
    "question",
    [
        "My PAN is ABCPA1234B",
        "My aadhaar is 379980670381",
        "a/c no. 30123456789 please check",
        "my otp is 492015",
        "mail me at ravi.kumar@example.co.in",
        "call me on +91 98765 43210",
    ],
)
def test_every_pii_kind_is_refused_before_use(settings: Settings, question: str):
    searcher = StubSearcher(_open_result())
    client = CountingClient()
    bot = Ragbot(settings=settings, client=client, searcher=searcher)

    answer = bot.ask(question)

    assert answer.refused and answer.text == pii.NEUTRAL_MESSAGE
    assert searcher.queries == [] and client.call_count == 0


def test_refusal_c_does_not_name_the_category_that_matched(settings: Settings):
    """Otherwise the refusal is an oracle for mapping the detectors' edges."""
    pan = Ragbot(
        settings=settings, client=CountingClient(), searcher=StubSearcher(_open_result())
    ).ask("My PAN is ABCPA1234B")
    email = Ragbot(
        settings=settings, client=CountingClient(), searcher=StubSearcher(_open_result())
    ).ask("mail me at ravi.kumar@example.co.in")

    assert pan.text == email.text == pii.NEUTRAL_MESSAGE


def test_pii_values_never_appear_in_the_answer_or_its_notes(settings: Settings):
    bot = Ragbot(
        settings=settings, client=CountingClient(), searcher=StubSearcher(_open_result())
    )
    answer = bot.ask("My PAN is ABCPA1234B and aadhaar 379980670381")

    blob = answer.text + " " + " ".join(answer.validation)
    assert "ABCPA1234B" not in blob
    assert "379980670381" not in blob


# --- the structural guarantee: no clean scan token, no model ----------------


def test_generate_refuses_to_run_without_a_scan_result(settings: Settings):
    """The guard the whole design rests on."""
    client = CountingClient()
    bot = Ragbot(settings=settings, client=client, searcher=StubSearcher(_open_result()))

    from src.ragbot.core.errors import UnscannedInputError

    with pytest.raises(UnscannedInputError):
        bot._generate("What is the minimum SIP?", [], None)  # type: ignore[arg-type]
    assert client.call_count == 0


def test_route_requires_a_real_scan_not_merely_an_object(settings: Settings):
    """A scan that did not really scan must not unlock the model.

    This is what `enforced` is for: without it, any object shaped like a result
    would satisfy the guard. The guard checks that the input was SCANNED, not
    that it was clean - blocking on a finding is policy, and policy is applied in
    `_ask()` (see `test_pii_finding_stops_the_request_before_retrieval...`).
    """
    from src.ragbot.core.errors import UnscannedInputError

    stub = pii.PIIResult(found=False, spans=[], redacted="", scanner="not-a-real-scanner")
    bot = Ragbot(
        settings=settings, client=CountingClient(), searcher=StubSearcher(_open_result())
    )

    with pytest.raises(UnscannedInputError):
        bot._route("What is the minimum SIP?", stub, allow_generation=True)


def test_route_rejects_a_forged_result_object(settings: Settings):
    """Duck-typing is not enough: a hand-rolled stand-in must not pass either."""
    from src.ragbot.core.errors import UnscannedInputError

    class Forged:
        found = False
        clean = True
        enforced = True
        scanner = pii.SCANNER_ID
        kinds: list[str] = []
        spans: list = []

    bot = Ragbot(
        settings=settings, client=CountingClient(), searcher=StubSearcher(_open_result())
    )
    with pytest.raises(UnscannedInputError):
        bot._route("What is the minimum SIP?", Forged(), allow_generation=True)  # type: ignore[arg-type]


def test_the_guard_is_not_an_assert(settings: Settings):
    """`python -O` strips asserts. A safety control that vanishes when the
    deployment is optimised is not a safety control."""
    import inspect

    from src.ragbot.generation import pipeline

    source = inspect.getsource(pipeline._require_scanned)
    assert "assert " not in source, "guard must raise, not assert"


# --- streaming must scan too ----------------------------------------------


def test_stream_draft_scans_and_refuses_pii_before_the_model(settings: Settings):
    """stream_draft used to skip the scan entirely - a direct path from a
    question containing a PAN to an LLM provider."""
    client = CountingClient()
    searcher = StubSearcher(_open_result())
    bot = Ragbot(settings=settings, client=client, searcher=searcher)

    fragments = list(bot.stream_draft("My PAN is ABCPA1234B"))

    assert "".join(fragments) == pii.NEUTRAL_MESSAGE
    assert "ABCPA1234B" not in "".join(fragments)
    assert client.stream_calls == 0, "model streamed despite a PII finding"
    assert searcher.queries == []


def test_stream_draft_still_streams_clean_questions(settings: Settings):
    client = CountingClient()
    bot = Ragbot(settings=settings, client=client, searcher=StubSearcher(_open_result()))

    fragments = list(bot.stream_draft("What is the minimum SIP for HDFC ELSS?"))

    assert "".join(fragments) == "The minimum SIP is Rs. 500."
    assert client.stream_calls == 1


# --- policy switches are honoured -----------------------------------------


def test_dry_run_pii_lets_the_question_through_but_says_so(settings: Settings):
    """A documented setting must actually work.

    This is also why `_require_scanned` checks for a scan rather than for
    cleanliness: if the guard demanded a clean result, this test could not pass
    and `dry_run_pii` would be a setting with no behaviour behind it.
    """
    settings.dry_run_pii = True
    settings.block_pii = False
    client = CountingClient()
    bot = Ragbot(settings=settings, client=client, searcher=StubSearcher(_open_result()))

    answer = bot.ask("My PAN is ABCPA1234B")

    assert not answer.refused, "dry run must not block"
    assert any("DRY RUN" in note for note in answer.validation), answer.validation
    assert "ABCPA1234B" not in " ".join(answer.validation)
