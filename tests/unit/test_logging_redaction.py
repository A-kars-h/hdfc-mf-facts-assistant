"""Tests for log redaction.

FR-31 forbids personal data reaching disk or a log sink. These tests are the
proof, and they double as a detector specification: if a later regex change
stops catching a pattern, this fails rather than the leak shipping.
"""

from __future__ import annotations

import logging

import pytest

from src.ragbot.core.logging import redact, redact_mapping, setup_logging


@pytest.mark.parametrize(
    "raw",
    [
        "my aadhaar is 1234 5678 9012",
        "Aadhaar: 123456789012",
        "PAN ABCDE1234F",
        "call me on +91 98765 43210",
        "9876543210",
        "email me at priya.sharma@example.com",
        "card 4111 1111 1111 1111",
        "IFSC HDFC0001234",
        "account number: 30123456789",
    ],
)
def test_pii_patterns_are_redacted(raw: str):
    out = redact(raw)
    assert "[REDACTED" in out, f"expected redaction in {out!r}"
    for leaked in ("9876543210", "123456789012", "ABCDE1234F", "priya.sharma"):
        assert leaked not in out


def test_normal_corpus_text_survives_redaction():
    """Redaction must not eat the content the assistant is built on."""
    text = "Expense ratio 1.21%. Minimum SIP Rs. 500. Exit load Nil. NIFTY 500 TRI."
    assert redact(text) == text


def test_scheme_names_survive_redaction():
    """An 8-16 digit run must not be fabricated from a fund name or NAV."""
    for name in ("HDFC ELSS Tax Saver Direct Growth", "HDFC Balanced Advantage Fund"):
        assert redact(name) == name


def test_secrets_are_redacted():
    out = redact("api_key=sk-live-abcdef123456")
    assert "sk-live-abcdef123456" not in out
    assert "[REDACTED" in out


def test_mapping_redaction_hides_secret_keys():
    out = redact_mapping({"LLM_API_KEY": "sk-123", "question": "expense ratio?"})
    assert out["LLM_API_KEY"] == "[REDACTED]"
    assert out["question"] == "expense ratio?"


def test_logging_filter_redacts_record_and_args(capsys):
    """Exercise the real handler path, not redact() in isolation.

    Uses capsys rather than caplog because setup_logging() replaces the root
    handlers, which detaches caplog's handler. The assertion that matters is on
    what actually reaches stdout.
    """
    setup_logging()
    logger = logging.getLogger("test.redaction")
    logger.info("user email %s and aadhaar 123456789012", "a@b.com")
    text = capsys.readouterr().out
    assert "a@b.com" not in text
    assert "123456789012" not in text
    assert "[REDACTED_EMAIL]" in text
    assert "[REDACTED_AADHAAR]" in text


def test_logging_filter_redacts_dict_args():
    """Test the filter directly on a LogRecord.

    Deterministic, and it covers the shape without depending on pytest's own log
    capture, which chokes on a dict passed as a positional logging argument.
    """
    from src.ragbot.core.logging import RedactingFilter

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="incoming %s",
        args=({"email": "leak@example.com", "intent": "factual"},),
        exc_info=None,
    )
    assert RedactingFilter().filter(record) is True
    rendered = record.getMessage()
    assert "leak@example.com" not in rendered
    assert "[REDACTED_EMAIL]" in rendered
    assert "factual" in rendered, "redaction must not destroy the non-secret args"


def test_logging_filter_hides_secret_keyed_values_in_dict_args():
    """Secret-keyed values must be dropped by KEY, not by content pattern.

    `sk-live-abc123` matches no PII pattern - it is not a PAN, an Aadhaar or a
    phone number - so a content-only filter passes it through untouched. A bare
    API key is recognisable only from the key it is stored under.

    This regressed once: the filter was refactored to use the pattern layer
    directly and lost the secret-key branch along the way, while
    `redact_mapping` kept it. The two had quietly diverged.
    """
    from src.ragbot.core.logging import RedactingFilter

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="config loaded",
        args={
            "api_key": "sk-live-SECRETVALUE123",
            "question": "my pan is ABCPA1234B",
            "nested": {"password": "hunter2"},
        },
        exc_info=None,
    )
    assert RedactingFilter().filter(record) is True
    args = record.args
    assert isinstance(args, dict)

    assert args["api_key"] == "[REDACTED]"
    assert args["nested"]["password"] == "[REDACTED]"
    assert "ABCPA1234B" not in args["question"]
    assert "[REDACTED_PAN]" in args["question"]

    blob = str(args)
    for secret in ("sk-live-SECRETVALUE123", "hunter2", "ABCPA1234B"):
        assert secret not in blob, f"leaked {secret} through a dict logging arg"


def test_logging_filter_redacts_tuple_args():
    from src.ragbot.core.logging import RedactingFilter

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="pan=%s ratio=%s",
        args=("ABCDE1234F", "1.21%"),
        exc_info=None,
    )
    RedactingFilter().filter(record)
    rendered = record.getMessage()
    assert "ABCDE1234F" not in rendered
    assert "[REDACTED_PAN]" in rendered
    assert "1.21%" in rendered


def test_setup_logging_is_idempotent():
    setup_logging()
    first = len(logging.getLogger().handlers)
    setup_logging()
    assert len(logging.getLogger().handlers) == first


def test_noisy_http_loggers_are_quieted():
    """httpx at DEBUG logs full request bodies - a common PII leak."""
    setup_logging()
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("openai").level >= logging.WARNING
