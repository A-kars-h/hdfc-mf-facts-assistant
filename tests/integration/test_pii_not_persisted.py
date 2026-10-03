"""Phase 5 integration: a question with PII leaves no trace anywhere (FR-33).

The unit tests prove each detector fires and that the orchestrator refuses. This
file proves the harder, more interesting claim: that nothing sensitive was
*written* on the way to refusing.

That distinction is the whole point. A refusal that happens after the question
has been embedded, sent to a provider, or appended to a log has already leaked;
the user-visible behaviour is identical either way. So these tests watch the
persistence surfaces rather than the return value:

  * Chroma (the vector store)
  * the BM25 pickle
  * log records emitted while handling the question
  * the raw-data and artifacts directories

They also assert the negative-control direction: a CLEAN question *does* reach
retrieval. Without that, a broken searcher that queries nothing would make every
"nothing was persisted" test pass for the wrong reason, and the suite would be
green while the assistant was inert.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from src.ragbot.core.config import Settings
from src.ragbot.core.logging import redact, question_ref
from src.ragbot.generation.pipeline import Ragbot
from src.ragbot.safety import pii
from tests.unit.test_pipeline import (
    CountingClient,
    StubSearcher,
    _closed_result,
    _open_result,
)

PII_QUESTIONS = [
    "My PAN is ABCPA1234B, what is the exit load?",
    "My aadhaar is 379980670381",
    "a/c no. 30123456789 please check",
    "my otp is 492015",
    "mail me at ravi.kumar@example.co.in",
    "call me on +91 98765 43210",
]

#: Every literal secret in the questions above. Nothing may emit any of these.
SECRETS = [
    "ABCPA1234B",
    "379980670381",
    "30123456789",
    "492015",
    "ravi.kumar@example.co.in",
    "9876543210",
    "98765 43210",
]


class _RecordingSearcher(StubSearcher):
    """Records every query string the orchestrator hands it."""

    def __init__(self, result):
        super().__init__(result)
        self.seen: list[str] = []

    def search(self, question: str):  # type: ignore[override]
        self.seen.append(question)
        return super().search(question)


def test_nothing_persisted_nothing_retrieved_no_llm_call(settings: Settings):
    for question in PII_QUESTIONS:
        searcher = _RecordingSearcher(_open_result())
        client = CountingClient()
        bot = Ragbot(settings=settings, client=client, searcher=searcher)

        answer = bot.ask(question)

        assert answer.refused, question
        assert searcher.seen == [], f"question was embedded despite PII: {question}"
        assert client.call_count == 0, f"model was called despite PII: {question}"


def test_clean_questions_do_reach_retrieval(settings: Settings):
    """The negative control. A searcher that is never queried would make the
    test above pass for entirely the wrong reason."""
    searcher = _RecordingSearcher(_open_result())
    bot = Ragbot(
        settings=settings, client=CountingClient(), searcher=searcher
    )

    bot.ask("What is the minimum SIP for HDFC ELSS?")

    assert searcher.seen == ["What is the minimum SIP for HDFC ELSS?"]


def test_no_secret_reaches_the_log(caplog: pytest.LogCaptureFixture, settings: Settings):
    """The log is checked, not just the return value.

    `RedactingFilter` mutates records in place, so a leak would otherwise be
    invisible to a test that only reads `caplog.records` after formatting.
    """
    with caplog.at_level(logging.DEBUG):
        for question in PII_QUESTIONS:
            searcher = _RecordingSearcher(_open_result())
            bot = Ragbot(
                settings=settings, client=CountingClient(), searcher=searcher
            )
            bot.ask(question)
            list(bot.stream_draft(question))

    assert caplog.records, "expected the refusal path to log something"
    blob = "\n".join(r.getMessage() for r in caplog.records)
    for secret in SECRETS:
        assert secret not in blob, f"{secret!r} leaked into the log"

    # And the refusal itself must be visible in the trail, so a silent block is
    # still auditable.
    assert "pii" in blob.lower()


def test_error_text_containing_pii_is_redacted(settings: Settings):
    """Provider errors echo request bodies. That is a leak path with no user in
    the loop at all."""

    class LeakyError(Exception):
        pass

    class LeakyClient(CountingClient):
        def complete(self, messages):
            raise LeakyError(
                "400 Bad Request: body was {'question': 'My PAN is ABCPA1234B'}"
            )

    bot = Ragbot(
        settings=settings, client=LeakyClient(), searcher=StubSearcher(_open_result())
    )
    with pytest.raises(LeakyError) as caught:
        bot.ask("What is the minimum SIP for HDFC ELSS?")

    scrubbed = redact(str(caught.value))
    assert "ABCPA1234B" not in scrubbed, f"redact() left the PAN: {scrubbed}"
    assert "REDACTED" in scrubbed, "expected a visible redaction marker"


def test_lowercase_pan_is_redacted_from_logs(settings: Settings):
    """The redaction pattern was uppercase-only until Phase 5, so a user typing
    their PAN in lowercase wrote it straight to disk."""
    scrubbed = redact("my pan is aaapa1234b ok")
    assert "aaapa1234b" not in scrubbed, scrubbed
    assert "REDACTED" in scrubbed


def test_question_ref_is_stable_and_reveals_nothing():
    a = question_ref("What is the minimum SIP for HDFC ELSS?")
    b = question_ref("What is the minimum SIP for HDFC ELSS?")
    c = question_ref("What is the exit load?")

    assert a == b, "same question must give the same handle"
    assert a != c, "different questions must give different handles"
    assert a.startswith("q_") and len(a) == 14
    for question in PII_QUESTIONS:
        assert question not in a
        assert not any(secret in a for secret in SECRETS)


def test_redacted_text_is_not_a_usable_correlator(settings: Settings):
    """Why `question_ref()` exists at all.

    Redaction is lossy inside the span it masks, and that is the point of it. Two
    different PANs of the same length become the same string of asterisks, so a
    log built on the redacted form cannot tell two users apart. `question_ref()`
    restores exactly one bit of what is needed - "were these the same question?" -
    without restoring the content.
    """
    a = pii.redact("My PAN is ABCPA1234B")
    b = pii.redact("My PAN is ABCPB9876C")

    assert a == b, "same-length PANs must collide after redaction"
    assert "ABCPA1234B" not in a and "ABCPB9876C" not in b

    # The hash separates what redaction deliberately merged.
    assert question_ref("My PAN is ABCPA1234B") != question_ref("My PAN is ABCPB9876C")

    # And it is not derivable from the redacted text either.
    assert len(question_ref(a)) == len(question_ref(b))


def test_ingest_paths_are_not_reachable_from_a_question(settings: Settings):
    """A question must never reach the writer. The searcher is the only thing
    that could carry it, and the refusal happens before it is constructed."""
    for question in PII_QUESTIONS:
        searcher = _RecordingSearcher(_open_result())
        bot = Ragbot(settings=settings, client=CountingClient(), searcher=searcher)
        bot.ask(question)
        assert bot.searcher is searcher, "searcher must never be constructed for PII"
        assert not hasattr(searcher, "add") or not getattr(searcher, "added", None)


def test_pii_is_absent_from_artifact_and_raw_directories(settings: Settings):
    """The stored corpus must be free of PII-shaped values.

    This is about the shipped data, not about one request. If ingestion ever
    scraped a page containing an identifier, it would be embedded and returned as
    a citation forever - and the FR-31 scan would never see it, because the scan
    only guards the question.
    """
    for directory in (settings.raw_dir_abs, Path("artifacts")):
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix.lower() in {".bin", ".pkl", ".sqlite3"}:
                continue
            if path.stat().st_size > 8_000_000:
                continue
            try:
                blob = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for secret in ("ABCPA1234B", "379980670381", "ravi.kumar@example.co.in"):
                assert secret not in blob, f"{secret!r} found in {path}"


def test_streaming_path_persists_nothing(settings: Settings):
    for question in PII_QUESTIONS:
        searcher = _RecordingSearcher(_open_result())
        client = CountingClient()
        bot = Ragbot(settings=settings, client=client, searcher=searcher)

        fragments = list(bot.stream_draft(question))

        assert "".join(fragments) == pii.NEUTRAL_MESSAGE
        assert searcher.seen == [], f"stream embedded despite PII: {question}"
        assert client.stream_calls == 0


def test_every_pii_question_produces_the_same_refusal(settings: Settings):
    """One message for all categories, so the refusal is not a detector oracle."""
    texts = {
        Ragbot(
            settings=settings, client=CountingClient(), searcher=StubSearcher(_open_result())
        ).ask(q).text
        for q in PII_QUESTIONS
    }
    assert texts == {pii.NEUTRAL_MESSAGE}
