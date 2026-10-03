"""Logging with redaction.

This module is DEFENCE IN DEPTH, not the primary control. The primary control is
that `safety.pii` scans the question before anything is embedded, sent, or logged
(FR-31), so a redacted question should never reach here at all. These patterns
exist for the paths that bypass that gate: exception text, provider HTTP error
bodies, and debug logging added during development - which is exactly how PII
leaks into otherwise PII-free systems.

Two layers, and the reason for both:

1. The broad regexes below, run first. They over-redact on purpose. A log line
   full of `[REDACTED_NUMBER]` is an annoyance; a PAN on disk is a breach. They
   also cover things the detector deliberately does not, such as bare 9-18 digit
   runs and card numbers, which are worth redacting even though they are not
   detectable PII for refusal purposes. Because they run first, the common cases
   come out as labelled markers an operator can grep for.

2. A delegation to `safety.pii.redact()`, run last as a safety net. Before Phase 5
   these regexes were the only patterns, which made this module an independent
   reimplementation of the detector - free to drift from it, and free to
   disagree. Now that a checksum-validated detector exists, anything it finds is
   masked here too, so the two cannot disagree about a PAN or an Aadhaar.

Layer 2 alone would be wrong for logs: the detector declines to treat a bare
5-digit number as an OTP precisely because it is usually a holdings code, but in
a log line that ambiguity does not matter. Layer 1 alone is what let a lowercase
PAN through. Keeping both is deliberate.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
from typing import Any

# Patterns are deliberately broad. Over-redacting a log line is a minor
# annoyance; under-redacting writes someone's PAN to disk (FR-31).
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Aadhaar: 12 digits, optionally space/separated in 4-4-4. Not checksum-
    # checked, unlike safety.pii: in a log line, over-redaction is the safe error.
    (re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), "[REDACTED_AADHAAR]"),
    # PAN: 5 letters, 4 digits, 1 letter. Case-insensitive because people type
    # their PAN in lowercase, and this pattern was uppercase-only until Phase 5 -
    # a lowercase PAN passed straight through the redaction that existed to
    # stop exactly that.
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.IGNORECASE), "[REDACTED_PAN]"),
    # Indian mobile numbers, with optional +91 / separators.
    (re.compile(r"\b(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b"), "[REDACTED_PHONE]"),
    # Email.
    (
        re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
        "[REDACTED_EMAIL]",
    ),
    # One-time passwords, but only in an explicitly labelled context. A bare 4-6
    # digit run is NOT matched here either: in a log full of chunk ids, ranks and
    # scores, masking every short number would destroy the log's usefulness. The
    # detector applies the same rule, for the same measured reason.
    (
        re.compile(
            r"(?i)\b(?:otp|one[\s-]?time\s+password|verification\s+code"
            r"|security\s+code|auth(?:entication)?\s+code|passcode|pin)\b"
            r"(\s*(?:is|was|[:=\-])?\s*)\d{4,6}\b"
        ),
        r"[REDACTED_OTP]\1[REDACTED_OTP]",
    ),
    # 16-digit card numbers, optionally spaced.
    (re.compile(r"\b(?:\d[ -]?){15,16}\b"), "[REDACTED_CARD]"),
    # IFSC codes.
    (re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", re.IGNORECASE), "[REDACTED_IFSC]"),
    # Bank account numbers, in labelled context.
    (
        re.compile(r"(?i)\b(a/c|account)\s*(?:no\.?|number)?\s*[:=]?\s*\d{9,18}\b"),
        r"\1 [REDACTED_ACCOUNT]",
    ),
    # Bare 9-18 digit runs are the classic missed case; keep last.
    (re.compile(r"(?<![\w.])\d{9,18}(?![\w.])"), "[REDACTED_NUMBER]"),
)

# Never log these, whatever they contain.
_SECRET_KEYS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "passwd",
    "authorization",
)


def _redact_patterns(text: str) -> str:
    """Layer 1 only: the broad, fast, over-eager patterns."""
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return re.sub(
        r"(?i)\b(" + "|".join(_SECRET_KEYS) + r")\b(\s*[:=]\s*)\S+",
        r"\1\2[REDACTED]",
        out,
    )


def _detector_redact(text: str) -> str:
    """Mask anything the real detector finds.

    Imported lazily and defensively: `redact()` is called from exception
    handlers, and a logging call that can itself raise turns a recoverable error
    into a crash. If the detector is unavailable for any reason, the broad
    patterns above have already run and the line is still protected.
    """
    try:
        from ..safety.pii import redact as detector_redact

        return detector_redact(text)
    except Exception:  # pragma: no cover - defensive only
        return text


def redact(text: str) -> str:
    """Remove PII and secrets from a string destined for a log or file.

    Both layers: the broad patterns first, so the common cases come out as
    greppable labelled markers, then the real detector as a safety net for
    anything the patterns missed.

    Never raises, and never returns the input unchanged merely because the
    detector could not be imported.
    """
    if not text:
        return ""
    return _detector_redact(_redact_patterns(text))


def question_ref(text: str) -> str:
    """A stable, non-reversible handle for a question, for use in logs.

    Sometimes a log genuinely needs to show that two requests carried the same
    question - for debugging a retry, or for counting distinct questions. The
    question text cannot be used for that, and neither can the redacted text:
    redaction is lossy, so every question that redacts to the same asterisks
    becomes indistinguishable, which destroys exactly the correlation the log
    was wanted for.

    A truncated SHA-256 gives a short, stable id that reveals nothing about the
    content. Truncated to 12 hex digits, which keeps accidental collisions
    negligible for log-correlation purposes while staying readable.
    """
    if not text:
        return "q_empty"
    return "q_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _redact_mapping_patterns(data: dict[str, Any]) -> dict[str, Any]:
    """Layer 1 for mappings: hide secret-keyed values, pattern-redact the rest.

    Values under a secret-looking key are dropped whole rather than pattern-
    matched, because a bare API key matches no PII pattern: `sk-abc123` is not a
    PAN, an Aadhaar or a phone number. It has to be recognised by the KEY, and
    that is a job no content pattern can do.
    """
    safe: dict[str, Any] = {}
    for key, value in data.items():
        if any(k in key.lower() for k in _SECRET_KEYS):
            safe[key] = "[REDACTED]"
        elif isinstance(value, str):
            safe[key] = _redact_patterns(value)
        elif isinstance(value, dict):
            safe[key] = _redact_mapping_patterns(value)
        else:
            safe[key] = value
    return safe


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Redact a dict, hiding values under secret-looking keys entirely.

    Both layers: the same ordering as `redact()` - patterns first so common
    cases stay greppable, detector last for whatever the patterns missed.
    """
    safe = _redact_mapping_patterns(data)
    for key, value in safe.items():
        if isinstance(value, str) and value != "[REDACTED]":
            safe[key] = _detector_redact(value)
    return safe


class RedactingFilter(logging.Filter):
    """Applies redaction to every record and its args.

    Attached by `setup_logging`, so it protects every logger in the app
    including ones created later in other modules. This matters because a
    `logging.getLogger(__name__)` in a phase module is a normal thing to write,
    and it should not silently be the one path that leaks.

    Uses the broad patterns only, NOT the full detector. Two reasons:

    - The filter runs on every log record in the process, including third-party
      debug spam. Running a checksum-validating detector per record is real
      work for no extra protection: for log text the broad patterns are already
      a superset (they mask every 12-digit run, every PAN-shaped token, and
      cued OTPs whether or not the checksum validates).
    - It kept the pipeline's scan count unmeasurable. A detector call here
      re-scanned the log line, so a single `ask()` ran the PII scanner three
      times, and "the scan runs first" became an assertion about a count rather
      than about order.

    The thorough two-layer path is the explicit `redact()`, which is what call
    sites and exception handling use.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact_patterns(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = _redact_mapping_patterns(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _redact_patterns(a) if isinstance(a, str) else a for a in record.args
                )
        return True


_CONFIGURED = False


class _CurrentStdoutHandler(logging.StreamHandler):
    """Writes to whatever `sys.stdout` is at emit time.

    `logging.StreamHandler(sys.stdout)` binds the stream once, at construction.
    That silently ignores any later redirection - which is exactly what pytest's
    capture and Streamlit both do, producing an empty log where output was
    demonstrably produced. Resolving lazily avoids that class of bug.
    """

    def __init__(self) -> None:
        super().__init__()

    @property  # type: ignore[override]
    def stream(self):  # noqa: D102
        return sys.stdout

    @stream.setter
    def stream(self, value) -> None:  # noqa: D102
        # StreamHandler.__init__ assigns to .stream; ignore it so that a later
        # close() cannot detach the real stdout.
        pass


def setup_logging(level: int | str = "INFO") -> None:
    """Configure root logging once, with redaction and no secrets."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = _CurrentStdoutHandler()
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(name)-28s %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    handler.addFilter(RedactingFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper() if isinstance(level, str) else level)

    # These libraries log full request payloads at DEBUG. That is the single
    # easiest way to leak a question into a log file.
    for noisy in ("httpx", "httpcore", "urllib3", "openai", "anthropic",
                  "chromadb", "sentence_transformers", "urllib3.connectionpool"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
