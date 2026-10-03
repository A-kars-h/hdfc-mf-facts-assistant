"""Cleaner tests. Each one pins a Phase 0/2 finding that cost real debugging."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.ragbot.core.errors import EmptyPageError
from src.ragbot.ingest.clean import check_not_empty, parse_page
from tests.fixtures import PAGE_HTML, SCHEME, THIN_HTML

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _parse(html: str = PAGE_HTML, page_id: str = "hdfc-equity"):
    return parse_page(
        html,
        page_id=page_id,
        scheme=SCHEME,
        category="Flexi Cap",
        source_url="https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
        fetched_at=NOW,
    )


def _texts(page) -> list[str]:
    return [b.text for b in page.blocks]


# --- the two findings that silently destroyed data ----------------------


def test_header_content_survives_cleaning():
    """Groww puts scheme name, riskometer and lock-in inside <header>.

    An earlier version of this module dropped `header` by tag name, which
    deleted the riskometer for all 5 schemes and the ELSS 3-year lock-in. The
    riskometer question then had no attributable answer at all.
    """
    text = _parse().flat_text
    assert "Very High Risk" in text
    assert SCHEME in text


def test_exit_load_modal_survives_cleaning():
    """Exit load lives in a `div.rodal` modal and is a source-named question."""
    text = _parse().flat_text
    assert "Exit load of 1% if redeemed within 1 year" in text
    assert "Stamp duty on investment" in text


def test_site_navigation_is_excluded():
    """Finding 1: no <main> on these pages, so an implicit root eats the nav."""
    text = _parse().flat_text
    for leak in ("ETF Screener", "Demat Account", "IPO"):
        assert leak not in text, f"navigation leaked into the corpus: {leak}"


def test_scripts_are_removed():
    assert "__DATA__" not in _parse().flat_text


# --- self-contained facts ----------------------------------------------


def test_fund_facts_are_label_value_pairs():
    """A chunk reading '0.77%' with no label is unusable and uncitable."""
    text = _parse().flat_text
    assert "Expense ratio | 0.77%" in text
    assert "Min. for SIP | ₹100" in text
    assert "Fund benchmark | NIFTY 500 Total Return Index" in text
    assert "Fund size (AUM) | ₹1,13,606.47 Cr" in text


def test_table_rows_are_serialised_row_wise_with_caption():
    rows = [t for t in _texts(_parse()) if t.startswith("Fund returns")]
    assert rows, "table rows must carry their caption"
    assert any("1 year | + 0.01 %" in r for r in rows)
    assert any("3 years | + 14.2%" in r for r in rows)


def test_rupee_sign_is_preserved():
    assert "₹" in _parse().flat_text


# --- structure ----------------------------------------------------------


def test_headings_become_section_labels():
    page = _parse()
    assert any(b.kind == "heading" for b in page.blocks)
    assert any(b.section for b in page.blocks)


def test_blocks_are_deduplicated():
    texts = _texts(_parse())
    assert len(texts) == len(set(texts)), "duplicate blocks skew BM25"


def test_content_hash_is_stable_and_text_sensitive():
    a, b = _parse(), _parse()
    assert a.content_hash == b.content_hash
    changed = _parse(html=PAGE_HTML.replace("0.77%", "0.99%"))
    assert changed.content_hash != a.content_hash


def test_fetched_at_is_preserved_per_page():
    page = _parse()
    assert page.fetched_at == NOW


# --- FR-2 gate ----------------------------------------------------------


def test_thin_page_raises_empty_page_error():
    page = _parse(THIN_HTML, "hdfc-thin")
    assert page.chars < 1500
    with pytest.raises(EmptyPageError) as exc:
        check_not_empty(page, 1500)
    assert "hdfc-thin" in str(exc.value)


def test_structurally_complete_fixture_passes_a_low_gate():
    """The fixture is a ~700-char structural sample, not a real page.

    Real pages clean to 11k-41k chars, which `test_real_pages_clear_the_real_gate`
    in the integration suite verifies at the production threshold of 1500. Here
    the point is only that a page WITH content is not rejected.
    """
    page = _parse()
    assert page.chars > 500
    check_not_empty(page, 500)
