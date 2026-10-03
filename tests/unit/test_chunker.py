"""Chunker tests: budget, provenance, and the label-carrying rule."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.ragbot.ingest.chunker import (
    chunk_page,
    is_return_heavy,
    split_sentences,
    summarise,
)
from src.ragbot.ingest.clean import parse_page
from tests.fixtures import PAGE_HTML, SCHEME
from tests.fixtures.fake_embedder import FakeTokenizer

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
TOKENIZER = FakeTokenizer()


def _page(html: str = PAGE_HTML):
    return parse_page(
        html,
        page_id="hdfc-equity",
        scheme=SCHEME,
        category="Flexi Cap",
        source_url="https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
        fetched_at=NOW,
    )


def _chunks(**kwargs):
    return chunk_page(_page(), tokenizer=TOKENIZER, **kwargs)


# --- sentence splitting -------------------------------------------------


def test_sentences_are_not_split_on_decimals():
    assert split_sentences("The expense ratio is 0.77%. The minimum SIP is 100.") == [
        "The expense ratio is 0.77%.",
        "The minimum SIP is 100.",
    ]


def test_abbreviations_do_not_create_boundaries():
    out = split_sentences("Exit load is Nil. Min. for SIP is Rs. 100.")
    assert len(out) == 2


# --- budget -------------------------------------------------------------


def test_no_chunk_exceeds_the_size_budget():
    chunks = _chunks(size=200, overlap=40)
    assert chunks
    assert max(c.token_count for c in chunks) <= 200


def test_oversized_paragraph_is_split_not_truncated():
    """A long block must be divided at sentence boundaries, never cut off.

    Silent truncation is the failure this project cannot tolerate: the tail is
    lost but the chunk is still embedded, retrieved and cited.
    """
    long_text = " ".join(f"Sentence number {i} states a fact." for i in range(60))
    page = parse_page(
        f'<html><body><div class="pw14MainWrapper"><div class="pw14ContentWrapper">'
        f"<p>{long_text}</p></div></div></body></html>",
        page_id="p",
        scheme=SCHEME,
        category="c",
        source_url="https://groww.in/x",
        fetched_at=NOW,
    )
    chunks = chunk_page(page, size=100, overlap=20, tokenizer=TOKENIZER)
    assert len(chunks) > 1
    assert all(c.token_count <= 100 for c in chunks)
    # Every sentence survives somewhere.
    joined = " ".join(c.text for c in chunks)
    assert "Sentence number 59" in joined
    assert "Sentence number 0" in joined


def test_single_sentence_over_budget_is_still_handled():
    monster = " ".join(f"token{i}" for i in range(500))
    page = parse_page(
        f'<html><body><div class="pw14MainWrapper"><div class="pw14ContentWrapper">'
        f"<p>{monster}</p></div></div></body></html>",
        page_id="p",
        scheme=SCHEME,
        category="c",
        source_url="https://groww.in/x",
        fetched_at=NOW,
    )
    chunks = chunk_page(page, size=50, overlap=10, tokenizer=TOKENIZER)
    assert chunks
    assert all(c.token_count <= 50 for c in chunks)


def test_overlap_is_applied_between_split_pieces():
    long_text = " ".join(f"Fact {i} about the scheme." for i in range(40))
    page = parse_page(
        f'<html><body><div class="pw14MainWrapper"><div class="pw14ContentWrapper">'
        f"<p>{long_text}</p></div></div></body></html>",
        page_id="p",
        scheme=SCHEME,
        category="c",
        source_url="https://groww.in/x",
        fetched_at=NOW,
    )
    chunks = chunk_page(page, size=60, overlap=15, tokenizer=TOKENIZER)
    assert len(chunks) >= 2
    # Some trailing text of chunk N appears at the head of chunk N+1.
    assert any(
        chunks[i].text.split()[-1] in chunks[i + 1].text for i in range(len(chunks) - 1)
    )


@pytest.mark.parametrize("size,overlap", [(0, 0), (100, 100), (100, -1), (100, 150)])
def test_invalid_size_overlap_is_rejected(size, overlap):
    with pytest.raises(ValueError):
        _chunks(size=size, overlap=overlap)


# --- the label-carrying rule (Phase 0 finding 3) ------------------------


def test_every_chunk_repeats_the_scheme_name():
    """A bare 'Very High Risk' matches a question about ANY scheme."""
    for chunk in _chunks():
        assert SCHEME in chunk.text, f"chunk lacks scheme identity: {chunk.text[:80]!r}"


def test_fact_chunks_keep_their_label():
    texts = [c.text for c in _chunks()]
    assert any("Expense ratio" in t and "0.77%" in t for t in texts)
    assert any("Fund benchmark" in t and "NIFTY 500" in t for t in texts)


def test_risk_level_is_attributable():
    risk = [c for c in _chunks() if "Very High Risk" in c.text]
    assert risk, "riskometer text must be indexed"
    assert all(SCHEME in c.text for c in risk)


# --- provenance ---------------------------------------------------------


def test_every_chunk_carries_full_provenance():
    for chunk in _chunks():
        assert chunk.page_id == "hdfc-equity"
        assert chunk.source_url == (
            "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth"
        )
        assert chunk.fetched_at == NOW, "per-page fetched_at, never a global stamp"
        assert chunk.scheme == SCHEME
        assert chunk.category == "Flexi Cap"
        assert chunk.content_hash
        assert chunk.char_end >= chunk.char_start


def test_chunk_ids_are_deterministic_and_unique():
    first = [c.chunk_id for c in _chunks()]
    second = [c.chunk_id for c in _chunks()]
    assert first == second, "chunk_id must be stable across runs for idempotency"
    assert len(first) == len(set(first))


# --- return tagging (Phase 0 finding 5) --------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Return calculator | 3 years | Rs. 1,80,000 | Rs. 1,95,187 | + 8.44 %",
        "Returns and rankings | Fund returns | +11.1% | +14.6% | +17.4%",
        "NAV: 25 Sep '26 | Rs.159.82",
        "3Y annualised",
    ],
)
def test_return_heavy_is_detected(text):
    assert is_return_heavy(text)


@pytest.mark.parametrize(
    "text",
    [
        "Expense ratio 0.77%",
        "Min. for SIP | Rs. 100",
        "Very High Risk",
        "Fund benchmark | NIFTY 500 Total Return Index",
        "Exit load Nil",
    ],
)
def test_ordinary_facts_are_not_return_heavy(text):
    assert not is_return_heavy(text)


def test_return_heavy_chunks_are_tagged_in_the_index():
    tagged = [c for c in _chunks() if c.return_heavy]
    assert tagged, "return data is present and must be tagged for Phase 3"
    # At least one tagged chunk must carry an actual figure, not just a heading
    # such as "Annualised returns" (which is also correctly tagged).
    assert any(("%" in c.text) or ("NAV" in c.text) for c in tagged)


def test_drop_return_heavy_removes_them():
    kept = _chunks()
    dropped = _chunks(drop_return_heavy=True)
    assert len(dropped) < len(kept)
    assert not any(c.return_heavy for c in dropped)


# --- reporting ----------------------------------------------------------


def test_summarise_reports_useful_stats():
    stats = summarise(_chunks())
    assert stats["chunks"] > 0
    assert stats["min_tokens"] <= stats["mean_tokens"] <= stats["max_tokens"]
    assert stats["max_tokens"] <= 200
