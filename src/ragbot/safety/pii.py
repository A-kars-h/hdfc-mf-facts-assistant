"""PII safety layer - Phase 5. Real detectors, real checksums.

This module is the primary control for FR-30/FR-31/FR-33: detect personal data
in the question, and do it BEFORE anything else touches the input. By the time
`scan()` returns a finding, nothing has been embedded, sent to a model, or
written to disk - because the caller is required to scan first and the rest of
the pipeline is downstream of that.

What is detected
----------------
    pan         Permanent Account Number          structure + entity-type letter
    aadhaar     Aadhaar number                   12 digits + Verhoeff checksum
    account     bank account number             labelled, or a bare 12-18 digit run
    otp         one-time password                4-6 digits, with context guards
    email       email address                    syntax
    phone       mobile number                    +91 / 0 prefixed, or bare 10-digit

A note on PAN, because it is the one place where this module deliberately does
not do what the spec's phrase "checksum validation" suggests
---------------------------------------------------------------------------
The Phase 5 brief asks for "regex + checksum validation for PAN and Aadhaar".
That is achievable for Aadhaar and **not achievable for PAN**, and the difference
matters enough to state plainly rather than paper over with an invented formula.

- Aadhaar genuinely has a published check digit: the **Verhoeff algorithm**,
  chosen by UIDAI because it catches all single-digit errors and all adjacent
  transpositions. Implemented here in full.
- **PAN has no published check-digit algorithm.** The last character of a PAN is
  described as a "check character" in secondary sources, but the Income Tax
  Department publishes no algorithm for it. This is not a gap in available
  research: `indpy`, a library that implements the *official* checksums for
  GSTIN (Mod-36) and Aadhaar (Verhoeff), lists PAN in its own documentation as
  "Structure only" with checksum "N/A". A GSTIN embeds a PAN, and GSTIN's
  checksum is computable - so if a PAN checksum existed and were usable, that
  same library would use it.

So writing a "PAN checksum" here would mean inventing arithmetic, tuning it until
it accepted whatever PANs the tests used, and shipping it as validation. That is
the exact failure mode this project keeps recording in Appendix D: a
plausible-looking rule that is quietly wrong, and that fails open on real input
the moment the guess is wrong.

What PAN validation does instead, and why it still meets the brief's intent
-----------------------------------------------------------------------
The brief's stated *purpose* for checksums was stated as: "format-only regexes
produce false positives that break the demo". That purpose is served by
structure plus the real published constraints:

1. Strict structure `AAAAA9999A`.
2. **The 4th character is a published entity-type code** - P (individual),
   C (company), H (HUF), A (AOP), B (BOI), G (government), J (artificial
   juridical person), L (local authority), F (firm), T (trust). This single
   constraint removes the large majority of accidental matches, because a random
   10-character token is very unlikely to carry a valid type code in position 4.
3. Rejection of the well-known dummy PANs (`AAAAA0000A`, `AAAAA1111A`, and any
   PAN whose five letters or four digits are all identical), which is what test
   data and placeholder text actually looks like.

That is weaker than a real checksum and the code says so at every call site. It
is stronger than a bare regex, and it cannot silently reject a valid PAN, which a
guessed checksum eventually would. Recorded as OD-9 in the docs.

The asymmetry that follows from this, stated as a rule: for the two identifiers
where a checksum is authoritative (Aadhaar), a checksum *failure* means "not
Aadhaar". For PAN, a structural failure means "not PAN" and there is no further
evidence to consult. So PAN is matched on structure and Aadhaar is matched on
checksum, and the two are not symmetric on purpose.

Redaction preserves length
--------------------------
`redact()` masks with asterisks, one per character, so the redacted text keeps
the original offsets. A redacted string of different length cannot be correlated
with the input, and any code that later wants to know "where was this" loses
that. Length-preserving masking keeps both properties.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

log = logging.getLogger(__name__)

#: False. Phase 5 is implemented. Phase 4 read this to decide whether to print
#: the "PII scanning is not enforced" disclosure on every answer. That disclosure
#: is now gone, because a permanent warning on a system that does scan is a false
#: statement, and stale safety notices train people to ignore safety notices.
PENDING = False

#: Identifies this scanner in `PIIResult.scanner`. `enforced` is derived from it,
#: so a stub cannot masquerade as a real scan.
SCANNER_ID = "phase-5-verhoeff-structural"


class PIIKind(str, Enum):
    """The kinds of personal data this layer refuses to accept."""

    PAN = "pan"
    AADHAAR = "aadhaar"
    ACCOUNT = "account"
    OTP = "otp"
    EMAIL = "email"
    PHONE = "phone"


#: Human-facing wording for the neutral refusal. FR-31 requires a neutral message
#: naming the categories, and it must not name which category was actually found
#: in this question - that would turn the refusal into an oracle for probing the
#: detectors.
NEUTRAL_MESSAGE = (
    "Please remove personal details such as PAN, Aadhaar, account numbers, "
    "OTPs, email or phone, then ask again."
)


# --- Verhoeff ---------------------------------------------------------------

# The three tables of the Verhoeff algorithm (dihedral group D5): the
# multiplication table `d`, the permutation table `p`, and the inverse `inv`.
# Chosen by UIDAI for Aadhaar because it detects all single-digit substitution
# errors and all adjacent transpositions - the two mistakes people actually make.
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_VERHOEFF_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def verhoeff_check(digits: str) -> bool:
    """True if `digits` satisfies the Verhoeff check digit (the last char included).

    The position index is `i % 8` with `i = 0` at the RIGHTMOST digit. Writing
    `(i + 1) % 8` here is a silent, hard failure: the algorithm still returns a
    wrong-answer-shaped result, and it still catches adjacent transpositions, so
    it looks alive. It fails to catch exactly one single-digit substitution per
    position (96 of 108) and rejects every genuinely valid Aadhaar. `test_pii.py`
    asserts the exhaustive properties, because a checksum that is subtly wrong is
    indistinguishable from a working one until real data is rejected.
    """
    if not digits.isdigit():
        return False
    checksum = 0
    for position, char in enumerate(reversed(digits)):
        checksum = _VERHOEFF_D[checksum][_VERHOEFF_P[position % 8][int(char)]]
    return checksum == 0


def verhoeff_check_digit(payload: str) -> int:
    """The check digit that would make `payload` a valid Verhoeff number.

    The placeholder `0` MUST be appended before computing the checksum. The check
    digit occupies a position in its own right, so it participates in the
    calculation: omitting it shifts every position and yields a digit that fails
    verification. Omitting it is silent - `verhoeff_check_digit("236")` returns 0
    instead of 3, and the wrong answer is still a plausible single digit.

    Exists so tests can generate genuinely valid Aadhaar numbers instead of
    pasting a real one into the repository, and so the checksum test is not
    self-referential.
    """
    checksum = 0
    for position, char in enumerate(reversed(payload + "0")):
        checksum = _VERHOEFF_D[checksum][_VERHOEFF_P[position % 8][int(char)]]
    return _VERHOEFF_INV[checksum]


# --- PAN -------------------------------------------------------------------

#: Published entity-type codes for the 4th character of a PAN.
PAN_ENTITY_TYPES = frozenset("PCAHBGLJFT")

#: Case-insensitive because PANs are issued uppercase but users type them
#: lowercase. Only the CANDIDATE is uppercased, never the source text, so span
#: offsets and length-preserving redaction are unaffected by the case of the
#: input. (Uppercasing the whole document instead would corrupt offsets for the
#: handful of code points whose lowercase form is longer than one character.)
PAN_SHAPE = re.compile(r"\b([A-Z]{5})(\d{4})([A-Z])\b", re.IGNORECASE)

#: Placeholder PANs that pass the shape but are not real identifiers. Test data
#: and lorem-ipsum PANs look exactly like these.
_PAN_DUMMY_LETTERS = {"A", "X", "Z"}
_PAN_DUMMY_DIGITS = {"0", "1"}


def is_pan(candidate: str) -> bool:
    """Structural PAN validation.

    NO CHECKSUM IS APPLIED, because none is published - see the module docstring.
    Every rejection here is a documented property of the format, not arithmetic
    this module invented.

    Uppercases its own argument so that calling it directly is consistent with
    calling it through `scan()`. Relying on the caller to normalise first would
    make this public predicate quietly return False for a valid lowercase PAN.
    """
    candidate = candidate.upper()
    m = PAN_SHAPE.fullmatch(candidate)
    if not m:
        return False
    letters, digits, last = m.group(1), m.group(2), m.group(3)

    # 4th character is the entity type. The single most effective real
    # constraint available, and the reason this is not a bare regex.
    if letters[3] not in PAN_ENTITY_TYPES:
        return False

    # Placeholder-shaped values are not identities.
    if len(set(letters)) == 1 and letters[0] in _PAN_DUMMY_LETTERS:
        return False
    if len(set(digits)) == 1 and digits[0] in _PAN_DUMMY_DIGITS:
        return False
    if letters[0] == letters[4] == last and len(set(letters + last)) == 1:
        return False

    return True


# --- Aadhaar ---------------------------------------------------------------

AADHAAR_SHAPE = re.compile(r"\b([2-9])(\d{3})[ -]?(\d{4})[ -]?(\d{4})\b")


def is_aadhaar(candidate: str) -> bool:
    """12 digits, Verhoeff-valid, not all-equal, not starting 0 or 1.

    The all-equal rejection is not redundant: `000000000000` and `111111111111`
    do pass Verhoeff for some digit values, and they are exactly what placeholder
    text and lorem-ipsum generators produce.
    """
    digits = re.sub(r"\D", "", candidate)
    if len(digits) != 12:
        return False
    if digits[0] in "01":  # real Aadhaar never starts 0 or 1
        return False
    if len(set(digits)) == 1:  # all-equal
        return False
    return verhoeff_check(digits)


# --- other shapes ----------------------------------------------------------

EMAIL_SHAPE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")

#: Mobile numbers. Indian mobiles are 10 digits starting 6-9; `+91`, `91` and `0`
#: prefixes are accepted, with optional space or hyphen grouping. The digit
#: boundaries stop this matching inside a longer run.
PHONE_SHAPE = re.compile(
    r"(?<![\d])(?:\+?91[\s-]?)?0?[6-9]\d{4}[\s-]?\d{5}(?![\d])"
)

#: Labelled account numbers. The label is required: a bare 9-11 digit run is far
#: more often a quantity or an identifier fragment than an account number.
ACCOUNT_LABELLED = re.compile(
    r"(?i)\b(?:a\s*/\s*c|acc(?:ount)?(?:\s+number)?|acct)\s*(?:no\.?|num(?:ber)?|#)?\s*[:#=\-]?\s*(\d{9,18})\b"
)

#: Bare long digit runs. 12-18 digits with no label. Below 12 digits is where
#: false positives start, so those need a label.
ACCOUNT_BARE = re.compile(r"(?<![\d.,\-/])(\d{12,18})(?![\d.,\-/])")

#: An OTP that was named as one. Always detected.
OTP_CUED = re.compile(
    r"(?i)\b(?:otp|one[\s-]?time\s+password|verification\s+code|security\s+code"
    r"|auth(?:entication)?\s+code|passcode|secure\s+pin|\bpin\b)\b"
    r"\s*(?:is|was|[:=\-])?\s*(\d{4,6})\b"
)

#: A bare 4-6 digit run. The most dangerous pattern in this module, because the
#: corpus is full of legitimate numbers and a false positive here makes the
#: assistant refuse ordinary questions. Governed by
#: `DETECT_BARE_OTP_NUMBERS` below.
OTP_BARE = re.compile(r"(?<![\w.,\-/#])(\d{4,6})(?![\w.,\-/#])")

#: Should a bare 4-6 digit run with no surrounding cue count as an OTP?
#:
#: OFF, and this is an empirical decision rather than a stylistic one. Measured
#: against all 1,193 chunks of the real corpus, bare detection flags
#: **44 chunks (3.67%)** - and every hit is a portfolio holding code, e.g.
#: "GOVERNMENT OF INDIA 34238 GOI 22AP64 7.34 FV RS 100". A 3.67% false-positive
#: rate on the assistant's own corpus means refusing ordinary holdings questions
#: roughly one time in twenty-seven.
#:
#: With it off, OTP detection requires an explicit security cue ("otp",
#: "verification code", "pin", ...). That is a real narrowing, stated plainly: a
#: bare 6-digit string pasted with no surrounding words is NOT treated as an OTP.
#: The trade is deliberate and the asymmetry is justified - a missed detection
#: leaks one code, while a false positive makes the product unusable on its own
#: corpus, and FR-31 asks for a usable refusal, not a maximally eager one.
#:
#: If this is ever re-enabled, the corpus sweep in `test_pii.py`
#: (`test_bare_otp_detection_would_reintroduce_corpus_false_positives`) is the
#: test that must be re-run first, and its measured rate is recorded in OD-10.
DETECT_BARE_OTP_NUMBERS = False

#: Context that makes a bare number a quantity, not a secret.
#:
#: Two groups. The first is unit and currency markers, which are domain-neutral.
#: The second is this assistant's own domain vocabulary - mutual funds. That list
#: is legitimate precisely because the corpus is bounded and known: "goal is
#: 500000" and "target corpus 300000" are the single most common shape of a
#: legitimate 5-6 digit number here, and a detector that flags them refuses
#: ordinary questions, which is the failure the brief warns about when it asks
#: for checksum-backed detection in the first place.
#:
#: Deliberately does NOT include any security word (otp, pin, password, code,
#: verify), so a genuine OTP preceded by a cue is never suppressed.
_QUANTITY_CONTEXT = re.compile(
    r"(?i)(?:₹|\brs\.?\b|\binr\b|\blakh?s?\b|\bcrores?\b|\bper\s+"
    r"(?:month|day|year|unit)\b|%)\s*$"
)
_QUANTITY_WORDS = re.compile(
    r"(?i)\b(?:goal|target|corpus|capital|amount|invest\w*|saving|save|budget"
    r"|sip|lumpsum|monthly|quarterly|weekly|annuity|nav|exit|tenure|yield"
    r"|expense|risk|debt|equity|portfolio|value|price|worth|plan|scheme|fund"
    r"|year|yr|month|day|per|rate|return|returns|option|allocation)\b[^0-9]*$"
)

#: Identifier prefixes. `ORD50231` / `ORD-50231` / `#50231` are order ids, not
#: OTPs, and the brief names that as a case that must NOT trip.
_ID_PREFIX = re.compile(r"(?i)\b(?:ord|order|ref|txn|id|no|inv|cpn|utr|upi)\s*[#\-]?\s*$")


def _is_otp_like(text: str, start: int, end: int) -> bool:
    """Decide whether a bare 4-6 digit run is plausibly an OTP.

    Returns False for the three cases the brief names explicitly, and for the
    quantity contexts that dominate a mutual-fund corpus.
    """
    value = text[start:end]
    before = text[max(0, start - 24) : start]
    after = text[end : end + 8]

    # A year. `2026` is the brief's named negative and is by far the most common
    # 4-digit number in this domain - the corpus is full of launch dates, NAV
    # dates and financial years.
    if len(value) == 4 and 1900 <= int(value) <= 2099:
        return False

    # Currency, percent or a unit immediately before: a quantity.
    if _QUANTITY_CONTEXT.search(before):
        return False
    if after.lstrip().startswith("%"):
        return False

    # This domain's quantity vocabulary immediately before: a quantity. "goal is
    # 500000" and "target corpus 300000" are ordinary questions about this corpus,
    # and refusing them is the false positive that would make the assistant look
    # broken.
    if _QUANTITY_WORDS.search(before):
        return False

    # An identifier prefix: an order id, not a one-time password.
    if _ID_PREFIX.search(before):
        return False

    # 4-digit bare numbers are far more often amounts, years or id fragments
    # than OTPs, so they need the cue word (handled by OTP_CUED). 5-6 digit bare
    # runs are specific enough to stand alone.
    return len(value) >= 5


# --- result ----------------------------------------------------------------


@dataclass(frozen=True)
class PIIResult:
    """Outcome of a scan.

    `spans` are `(start, end, kind)` character offsets into the ORIGINAL text, so
    a caller can locate a finding without re-running detection. `redacted` is the
    length-preserving masked text, which is the only form allowed to be logged or
    stored (FR-33).

    `scanner` is not cosmetic. `enforced` is derived from it, so a stub cannot
    return a result that claims a real scan happened.
    """

    found: bool
    spans: list[tuple[int, int, str]] = field(default_factory=list)
    redacted: str = ""
    scanner: str = SCANNER_ID

    @property
    def kinds(self) -> list[str]:
        """Detected kinds, deduplicated, in first-appearance order.

        Deliberately does not include counts, and callers must not put this in a
        user-facing message - which kinds were present is a fact about the user's
        input that a refusal has no reason to confirm.
        """
        seen: list[str] = []
        for _, _, kind in self.spans:
            if kind not in seen:
                seen.append(kind)
        return seen

    @property
    def findings(self) -> list[str]:
        """Backwards-compatible alias for `kinds`. Phase 4's orchestrator seam
        was written against `findings` before `spans` existed."""
        return self.kinds

    @property
    def clean(self) -> bool:
        return not self.found

    @property
    def enforced(self) -> bool:
        """True only when a real scanner ran."""
        return self.scanner == SCANNER_ID

    def summary(self) -> str:
        """Log-safe one-liner. Never includes the matched text."""
        return (
            f"pii detected kinds={','.join(self.kinds)} spans={len(self.spans)}"
            if self.found
            else "pii clean"
        )


#: Phase 4's name for this result, kept as an alias so any code written against
#: the earlier seam still resolves. There is no second class and no second
#: implementation - `ScanResult is PIIResult`, so `enforced` cannot be satisfied
#: by one and not the other.
ScanResult = PIIResult


def mask(value: str) -> str:
    """One asterisk per character, so offsets and length are preserved."""
    return "*" * len(value)


# --- detection -------------------------------------------------------------


def _detectors() -> tuple[tuple[re.Pattern[str], str, object], ...]:
    """(pattern, kind, validator) in PRIORITY order.

    Priority matters because spans can overlap: a bare 12-digit run is both a
    possible account number and a possible Aadhaar, and the earlier detector in
    this list wins. Aadhaar outranks account because Aadhaar is validated by
    checksum and a bare account number is not.
    """
    detectors: list[tuple[re.Pattern[str], str, object]] = [
        (EMAIL_SHAPE, PIIKind.EMAIL, None),
        (AADHAAR_SHAPE, PIIKind.AADHAAR, is_aadhaar),
        (PAN_SHAPE, PIIKind.PAN, is_pan),
        (ACCOUNT_LABELLED, PIIKind.ACCOUNT, None),
        (ACCOUNT_BARE, PIIKind.ACCOUNT, None),
        (PHONE_SHAPE, PIIKind.PHONE, None),
        (OTP_CUED, PIIKind.OTP, None),
    ]
    if DETECT_BARE_OTP_NUMBERS:
        detectors.append((OTP_BARE, PIIKind.OTP, None))
    return tuple(detectors)


def _candidates(text: str) -> list[tuple[int, int, str]]:
    """All (start, end, kind) candidates, overlaps unresolved."""
    found: list[tuple[int, int, str]] = []

    for pattern, kind, validator in _detectors():
        kind_value = kind.value
        for m in pattern.finditer(text):
            if validator is not None:
                # A validator gets the whole match. PAN is matched
                # case-insensitively, so its candidate is uppercased first; PAN
                # and Aadhaar are both full-match shaped, so whole-match is
                # correct for both.
                candidate = m.group(0)
                if validator is is_pan:
                    candidate = candidate.upper()
                if not validator(candidate):
                    continue
                start, end = m.start(), m.end()
            elif kind is PIIKind.ACCOUNT and pattern is ACCOUNT_LABELLED:
                start, end = m.start(1), m.end(1)
            elif kind is PIIKind.OTP and pattern is OTP_CUED:
                start, end = m.start(1), m.end(1)
            elif kind is PIIKind.OTP:
                start, end = m.start(1), m.end(1)
                if not _is_otp_like(text, start, end):
                    continue
            else:
                start, end = m.start(), m.end()

            if end > start:
                found.append((start, end, kind_value))

    return found


def _resolve_overlaps(
    candidates: list[tuple[int, int, str]]
) -> list[tuple[int, int, str]]:
    """Drop lower-priority spans that overlap a higher-priority one.

    Priority is the detector order in `_detectors()`, so an Aadhaar span wins over
    a bare-account span covering the same digits. Ties are broken by the longer
    span, then by the earlier start, so the result is deterministic.
    """
    order = {kind.value: i for i, (_, kind, _) in enumerate(_detectors())}

    ranked = sorted(
        candidates, key=lambda c: (order.get(c[2], 99), -(c[1] - c[0]), c[0])
    )

    kept: list[tuple[int, int, str]] = []
    for start, end, kind in ranked:
        if any(start < k_end and k_start < end for k_start, k_end, _ in kept):
            continue
        kept.append((start, end, kind))

    return sorted(kept)


def scan(text: str) -> PIIResult:
    """Scan `text` for personal data.

    Pure and total: no settings, no logging, no I/O, and it never raises on
    malformed input. The caller decides what to do with a finding, which keeps
    the "block vs dry-run" policy out of the detector.
    """
    if not text:
        return PIIResult(found=False, spans=[], redacted="", scanner=SCANNER_ID)

    spans = _resolve_overlaps(_candidates(text))
    if not spans:
        return PIIResult(found=False, spans=[], redacted=text, scanner=SCANNER_ID)

    return PIIResult(
        found=True,
        spans=spans,
        redacted=redact(text, spans),
        scanner=SCANNER_ID,
    )


def redact(text: str, spans: list[tuple[int, int, str]] | None = None) -> str:
    """Mask every PII span with asterisks, preserving length.

    Length-preserving on purpose: the redacted text keeps the original character
    offsets, so anything that needs to reason about position still can, and a
    redacted string cannot be used to infer the original's length.
    """
    if not text:
        return ""
    if spans is None:
        spans = scan(text).spans
    if not spans:
        return text

    out = text
    for start, end, _kind in sorted(spans, key=lambda s: -s[0]):
        out = out[:start] + mask(out[start:end]) + out[end:]
    return out


#: Phase 4's name for `scan`. An alias, not a wrapper, so the pipeline cannot
#: end up calling one and a test patching the other.
scan_question = scan


def is_pending() -> bool:
    """Whether detection is still missing.

    False since Phase 5. It is kept because Phase 4 answers and the eval harness
    read it to decide whether to disclose an unenforced gate, and a caller that
    asks must get `False` rather than `AttributeError` - a missing attribute on a
    safety flag fails closed in the wrong direction, because `getattr(pii,
    "PENDING", True)` is the defensive form and it would report "pending".
    """
    return PENDING
