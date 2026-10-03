"""The orchestrator: one question in, one validated `Answer` out.

The order of operations is the product, so it is stated here once and enforced
by the code below:

    PII scan -> classify -> route
      pii       -> Refusal C          (no retrieval, no model, no persistence)
      opinion      -> Refusal A          (no retrieval, no model)
      out_of_scope -> Refusal B          (no retrieval, no model)
      corpus_sources -> fixed answer from config/corpus.yaml (no retrieval, no model)
      factual      -> retrieve -> gate
                       closed  -> Refusal B   (no model)
                       open    -> prompt -> model -> validate -> Answer

Four properties this sequence buys, each of which is a requirement:

- **The model is not called for anything but an answered factual question.**
  `test_low_similarity_makes_zero_llm_calls` and
  `test_opinion_never_generates` assert this, and the client is injected so the
  assertion is on a real call count rather than on an absence of output.

- **A question containing personal data is refused before it is used for
  anything.** The scan is the first statement in `_ask()`, ahead of intent
  classification, retrieval, embedding, and every log write that could carry the
  text. Refusal C is returned rather than raised, because FR-31 asks for a
  neutral user-facing message, and a traceback is not one.

- **Validation runs before anything is displayed.** `answer()` returns a
  finished `Answer` or raises. There is no streaming-to-UI path here, by
  design: a streamed fragment is unvalidated, and "briefly showing a prohibited
  answer" is still showing it. `stream_draft()` exists for callers that want
  tokens, and it is documented as unsafe to render directly.

- **Refusals are free.** A refusal path never constructs an LLM client, so a
  misconfigured provider cannot turn a refusal into an error page.

The PII guarantee is structural rather than conventional
---------------------------------------------------------
"Scan first" is easy to state and easy to erode: the scan stays first only while
nobody adds a new call path. So `_route()` and `_generate()` do not take a
question alone - they also take the `PIIResult` produced by the scan, and reject
anything that is not the result of a real, enforced scan. A future method that
forgets to scan cannot reach the model, because the model is only reachable from
a method that demands a scan token.

The guard checks that the input was *scanned*, not that it was *clean*, because
whether a finding should block is policy (`block_pii`, `dry_run_pii`) and policy
belongs in `_ask()`. This is also why `PIIDetected` is no longer the enforcement
mechanism: an exception can be caught and ignored, whereas a missing argument is
a `TypeError`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterator

from ..core.config import Settings, get_settings
from ..core.errors import NotCalibratedError, ProviderError, UnscannedInputError
from ..core.models import Answer, Intent, RetrievedChunk
from ..retrieval.intent import explain
from ..retrieval.search import HybridSearcher
from ..safety import pii
from .corpus import answer_source_list
from .educational import refuse_not_in_corpus, refuse_opinion, refuse_pii
from .llm import LLMClient, build_client
from .prompts import build_messages
from .validate import validate

log = logging.getLogger(__name__)


def _require_scanned(result: pii.PIIResult) -> None:
    """Gate every downstream stage on a real scan having actually happened.

    Checks that the input was SCANNED, not that it was clean. The distinction
    matters: `block_pii=False` and `dry_run_pii=True` both mean "we saw the PII
    and decided to proceed anyway", and a guard that also demanded cleanliness
    would silently make those two documented settings unconfigurable. Deciding
    what to do about a finding is policy, and policy lives in `_ask()`.

    Raises rather than asserts. `assert` is removed under `python -O`, so a
    safety control written as an assertion disappears exactly when a deployment
    is optimised - which is the one situation where it is still needed.
    """
    if not isinstance(result, pii.PIIResult):
        raise UnscannedInputError(
            f"expected a PIIResult from a completed scan, got {type(result).__name__}"
        )
    if not result.enforced:
        raise UnscannedInputError(
            f"scan came from {result.scanner!r}, which is not an enforced scanner"
        )


@dataclass
class Ragbot:
    """Question in, validated answer out.

    `client` and `searcher` are injectable so tests can count real LLM calls and
    so retrieval can be exercised without loading the embedding model twice.
    Neither is built until it is actually needed - constructing an OpenAI client
    at import time would make every refusal path depend on a valid key.
    """

    settings: Settings = field(default_factory=get_settings)
    client: LLMClient | None = None
    searcher: HybridSearcher | None = None
    _client_built: bool = False
    #: The candidates from the most recent `ask()`. Purely additive bookkeeping
    #: for the Phase 7 chunk inspector, and the reason that inspector does not
    #: have to run retrieval itself - see `ask_with_evidence`.
    _last_candidates: list[RetrievedChunk] = field(default_factory=list)

    def _llm(self) -> LLMClient:
        if self.client is None and not self._client_built:
            self.client = build_client(self.settings)
            self._client_built = True
        return self.client  # type: ignore[return-value]

    def _search(self) -> HybridSearcher:
        if self.searcher is None:
            self.searcher = HybridSearcher(self.settings)
        return self.searcher

    def ask(self, question: str) -> Answer:
        """Answer a question, or refuse it. Never raises for a policy refusal."""
        return self._ask(question, allow_generation=True)

    def ask_with_evidence(self, question: str) -> tuple[Answer, list[RetrievedChunk]]:
        """Answer a question AND return the exact chunks that were sent to the model.

        Added in Phase 7 for the UI's "show retrieved chunks" inspector. The
        orchestrator is the only component that knows what it actually used, so
        the honest way to expose the evidence is to have the orchestrator report
        it. The alternative - letting the UI call the searcher itself - would be
        worse in two ways, and both are reasons this method exists rather than a
        convenience: it would put retrieval in the presentation layer, and a
        second, independent retrieval could rank the chunks differently, so the
        inspector would be showing a plausible-looking list that is not what the
        answer was written from. A demo that can display evidence it did not use
        is worse than no inspector.

        Refusals return an empty list, which is the truth: a routed refusal
        retrieved nothing, and a gate refusal's candidates were never sent to a
        model. `ask()` delegates here, so the two can never disagree.
        """
        answer = self._ask(question, allow_generation=True)
        return answer, list(self._last_candidates)

    def _ask(self, question: str, *, allow_generation: bool) -> Answer:
        # Reset the evidence for this question. Without this, a routed refusal -
        # which retrieves nothing - would leave the previous question's chunks in
        # `_last_candidates`, and the UI inspector would show evidence for a
        # question it did not retrieve. An empty list is the correct state for
        # every path that never reached retrieval.
        self._last_candidates = []

        # 1. PII scan, the first thing that touches the input.
        #
        #    This runs before intent classification, before the searcher is
        #    constructed (which would load a 90 MB embedding model), before any
        #    prompt is built, and before any log line that could carry the text.
        #    Only the redacted form and the category names are ever recorded.
        result = pii.scan(question)
        notes: list[str] = [f"pii_scan: scanner={result.scanner} findings={len(result.spans)}"]

        if result.found:
            # Note the asymmetry: the log records the scanner's own summary, which
            # contains kinds and counts but never the matched characters.
            log.warning("pii refused before use: %s", result.summary())
            if not (self.settings.block_pii or self.settings.dry_run_pii):
                log.error(
                    "PII detected but both block_pii and dry_run_pii are off; "
                    "continuing with the RAW question. This transmits personal data."
                )
            elif self.settings.dry_run_pii and not self.settings.block_pii:
                log.warning("dry_run_pii is set; continuing past detected PII")
                notes.append("pii: DRY RUN - detected personal data, not blocked")
            else:
                return refuse_pii(kinds=result.kinds, checks=notes, settings=self.settings)

        # Every exit goes through _route so that `notes` lands on every answer,
        # refusals included. Attaching them only to generated answers would hide
        # the scan evidence from exactly the paths that never call a model - and
        # those are the paths most likely to be shown to a person as a
        # confident, safe-looking refusal.
        answer = self._route(question, result, allow_generation=allow_generation)
        return answer.model_copy(update={"validation": notes + answer.validation})

    def _route(self, question: str, result: pii.PIIResult, *, allow_generation: bool) -> Answer:
        # The scan token is re-checked here, not merely passed, so this method
        # cannot become a back door to the model.
        _require_scanned(result)

        # 2. Classify. Non-factual intents are refused on routing, before any
        #    retrieval: "should I buy HDFC Equity?" matches this corpus strongly,
        #    so the gate cannot catch it and must not be asked to.
        #
        #    The searcher is NOT built yet, and that ordering is load-bearing:
        #    constructing a HybridSearcher loads the embedding model, so routing
        #    first is the difference between an opinion refusal costing a dict
        #    lookup and it costing a 90 MB model load.
        match = explain(question)

        if match.intent is Intent.OPINION:
            log.info("intent=opinion (%s); refusing before retrieval", match.rule)
            return refuse_opinion(
                intent=Intent.OPINION,
                settings=self.settings,
                cause=f"advice-seeking question routed as opinion (rule={match.rule})",
            )

        if match.intent is Intent.OUT_OF_SCOPE:
            log.info("intent=out_of_scope (%s); refusing before retrieval", match.rule)
            return refuse_not_in_corpus(
                intent=Intent.OUT_OF_SCOPE,
                settings=self.settings,
                cause=f"question outside the closed corpus (rule={match.rule})",
            )

        if match.intent is Intent.CORPUS_SOURCES:
            # "Which pages are you using?" Answered here, before `self._search()`,
            # for the same reason the refusals are: the answer is a fixed
            # statement read from config/corpus.yaml, so there is nothing to
            # retrieve and nothing to score. Routing it through retrieval is what
            # produced the original bug - it retrieved fund-page boilerplate,
            # scored 0.7540 against a 0.7562 threshold, and refused.
            log.info(
                "intent=corpus_sources (%s); answering from the corpus definition",
                match.rule,
            )
            return answer_source_list(
                settings=self.settings,
                cause=f"source-list question (rule={match.rule})",
            )

        # 3. Factual: retrieve, then gate.
        searcher = self._search()
        try:
            search_result = searcher.search(question)
        except NotCalibratedError:
            return refuse_not_in_corpus(
                intent=Intent.FACTUAL,
                settings=self.settings,
                cause="gate is uncalibrated, so no factual answer can be trusted",
            )

        # The evidence actually in play for this question. Recorded before any
        # early return below, so a gate refusal still reports the candidates that
        # were considered and rejected rather than nothing at all.
        self._last_candidates = list(search_result.candidates)

        if not search_result.found_answer:
            # Closed gate -> Refusal B. No LLM call. The wording is the fixed
            # out-of-corpus string, identical to an out-of-scope refusal, so the
            # message cannot be used to probe the threshold.
            reason = search_result.decision.reason if search_result.decision else "unknown"
            log.info("gate closed (%s); refusing before generation", reason)
            return refuse_not_in_corpus(
                intent=Intent.FACTUAL,
                settings=self.settings,
                cause=f"no sufficiently similar context in the corpus ({reason})",
            )

        # 4. Generate, then validate. The draft is never returned raw.
        if not allow_generation:
            raise ProviderError("generation is disabled for this call")
        draft = self._generate(question, search_result.candidates, result)
        return validate(
            draft,
            search_result.candidates,
            self.settings,
            regenerate=lambda _: self._generate(question, search_result.candidates, result),
            intent=match.intent,
        )

    def _generate(
        self, question: str, candidates: list[RetrievedChunk], result: pii.PIIResult
    ) -> str:
        """The only place a question reaches a model. Requires a clean scan token."""
        _require_scanned(result)
        messages = build_messages(question, candidates, self.settings)
        return self._llm().complete(messages).strip()

    def stream_draft(self, question: str) -> Iterator[str]:
        """Stream raw draft tokens. UNSAFE TO DISPLAY - see module docstring.

        Provided because a caller may want progress indication, not because it
        is a supported user path. Every prohibition in this project is enforced
        on finished text, so a streamed fragment is unvalidated: it can contain
        advice, a return figure, or an invented URL. Buffer it and run it
        through `validate()` before any of it reaches a person.

        The PII scan is NOT optional here. This method used to call the model
        without scanning, which was a straight path from a question containing a
        PAN to an LLM provider. It now scans first and, on a finding, yields only
        the neutral refusal. Yielding the refusal rather than nothing is
        deliberate: a generator that returns silently leaves a UI showing a
        spinner forever, and the neutral message is a fixed constant that needs
        no validation.
        """
        result = pii.scan(question)
        if result.found:
            log.warning("pii refused before streaming: %s", result.summary())
            yield pii.NEUTRAL_MESSAGE
            return
        if explain(question).intent is not Intent.FACTUAL:
            return
        search_result = self._search().search(question)
        if not search_result.found_answer:
            return
        _require_scanned(result)
        messages = build_messages(question, search_result.candidates, self.settings)
        yield from self._llm().stream(messages)


def ask(question: str, settings: Settings | None = None) -> Answer:
    """Convenience one-shot. Builds a fresh `Ragbot` per call."""
    return Ragbot(settings=settings or get_settings()).ask(question)
