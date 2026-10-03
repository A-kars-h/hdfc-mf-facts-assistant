"""Refusal A and Refusal B.

The properties under test are the ones a refusal can quietly lose: it must not
apologise, must not leak internals, must not invent a URL, and must be a fixed
policy string rather than generated text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ragbot.core.config import Settings
from src.ragbot.core.models import Intent
from src.ragbot.generation.educational import (
    refuse_not_in_corpus,
    refuse_opinion,
    refuse_performance,
)
from src.ragbot.generation.validate import contains_advice, performance_violations

APOLOGY = ("sorry", "apolog", "i'm afraid", "unfortunately", "i apologize")
LEAKS = (
    "threshold", "similarity", "cosine", "raw_dense", "dense_max", "score",
    "rank", "chunk", "embedding", "rrf", "bm25", "0.4", "0.5", "0.6", "0.7",
)


# --- Refusal A ------------------------------------------------------------


def test_refusal_a_sets_link_missing_when_map_is_empty():
    """The map ships empty, so the honest output is the flag, not a URL.

    This is what keeps M-3 meaningful: without the flag, 'refused correctly' and
    'refused with nothing to offer' are indistinguishable.
    """
    answer = refuse_opinion(settings=Settings())
    assert answer.refused is True
    assert answer.intent is Intent.OPINION
    assert answer.educational_link is None
    assert answer.educational_link_missing is True
    assert any("NOT generated" in v or "NO verified" in v for v in answer.validation)


def test_refusal_a_never_contains_a_url_when_unverified():
    answer = refuse_opinion(settings=Settings())
    assert "http" not in answer.text
    assert "www." not in answer.text


def test_refusal_a_text_is_advice_screen_clean():
    """The refusal states a prohibition. It must not trip the screen enforcing
    that prohibition, or the two disagree about what advice means."""
    answer = refuse_opinion(settings=Settings())
    assert contains_advice(answer.text) is None, answer.text


def test_refusal_a_does_not_apologise():
    answer = refuse_opinion(settings=Settings())
    lowered = answer.text.lower()
    assert not any(word in lowered for word in APOLOGY), answer.text


def test_refusal_a_with_a_verified_link_attaches_it(tmp_path: Path):
    """With a human-verified entry present, the refusal attaches THAT url."""
    links = tmp_path / "links.yml"
    links.write_text(
        "links:\n"
        "  opinion:\n"
        "    url: https://www.hdfcassetmanagement.com/funds\n"
        "    title: 'HDFC AMC mutual fund education'\n"
        "    verified_by: tester\n"
        "    verified_on: '2026-01-15'\n",
        encoding="utf-8",
    )
    settings = Settings(education_links_path=links)
    answer = refuse_opinion(settings=settings)

    assert answer.educational_link == "https://www.hdfcassetmanagement.com/funds"
    assert answer.educational_link_missing is False
    # The URL goes in the FIELD so a UI can render it as a link; the sentence
    # carries the human-readable title, not a raw URL pasted into prose.
    assert "HDFC AMC mutual fund education" in answer.text
    assert "http" not in answer.text


def test_refusal_a_refuses_a_link_off_the_allowlist(tmp_path: Path):
    """A verified-but-unapproved domain is treated as no link at all. The
    allowlist is the second gate on a human's click."""
    links = tmp_path / "links.yml"
    links.write_text(
        "links:\n"
        "  opinion:\n"
        "    url: https://totally-made-up.example.com/mutual-funds\n"
        "    title: 'fake'\n"
        "    verified_by: tester\n"
        "    verified_on: '2026-01-15'\n",
        encoding="utf-8",
    )
    answer = refuse_opinion(settings=Settings(education_links_path=links))

    assert answer.educational_link is None
    assert answer.educational_link_missing is True
    assert "totally-made-up" not in answer.text


# --- Refusal B ------------------------------------------------------------


def test_refusal_b_is_fixed_and_short():
    answer = refuse_not_in_corpus(settings=Settings())
    assert answer.refused is True
    assert answer.sentence_count <= 3
    assert answer.educational_link is None


def test_refusal_b_does_not_apologise():
    answer = refuse_not_in_corpus(settings=Settings())
    lowered = answer.text.lower()
    assert not any(word in lowered for word in APOLOGY), answer.text


def test_refusal_b_leaks_no_internals():
    """A user who learns "0.42" is below the bar learns the bar, and can aim at
    it. The refusal must not name the threshold, the scores, or the chunks."""
    answer = refuse_not_in_corpus(settings=Settings())
    lowered = answer.text.lower()
    for leak in LEAKS:
        assert leak not in lowered, f"refusal leaked {leak!r}: {answer.text}"


def test_refusal_b_wording_is_identical_for_out_of_scope_and_gate_refusal():
    """If the two causes worded differently, the wording would reveal WHICH
    happened, and the gate's boundary could be probed by asking repeatedly."""
    out_of_scope = refuse_not_in_corpus(
        intent=Intent.OUT_OF_SCOPE, cause="outside corpus"
    )
    gate_closed = refuse_not_in_corpus(
        intent=Intent.FACTUAL, cause="gate closed: below_threshold"
    )
    assert out_of_scope.text == gate_closed.text


def test_refusal_b_cause_is_recorded_but_not_in_the_text():
    answer = refuse_not_in_corpus(cause="gate closed: below_threshold")
    assert any("below_threshold" in v for v in answer.validation)
    assert "below_threshold" not in answer.text


# --- performance refusal --------------------------------------------------


def test_performance_refusal_does_not_echo_the_figure():
    """Repeating '18% in 3 years' in the refusal would repeat the claim the
    screen exists to stop."""
    answer = refuse_performance(cause="return figure: returned 18% in 3 years")
    assert answer.refused is True
    assert "18" not in answer.text
    assert "3 years" not in answer.text


def test_performance_refusal_is_factual_intent_not_opinion():
    """The question WAS answerable, so calling it an advice refusal would be a
    lie about what went wrong."""
    answer = refuse_performance(cause="return figure")
    assert answer.intent is Intent.FACTUAL
    assert answer.educational_link_required is False
