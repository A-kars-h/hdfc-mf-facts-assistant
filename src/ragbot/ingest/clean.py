"""HTML -> structure-preserving blocks.

Phase 0 finding 6: the spike flattens the DOM to a single line, which discards
295 `<td>`, 75 `<tr>` and 12 `<h3>` on the ELSS page alone. Chunking that flat
string wastes the 200-token budget and hands BM25 a wall of unrelated labels.
So this module re-parses `data/raw/*.html` into ordered blocks and is now the
single source of truth for the Groww selectors - `scripts/spike_fetch.py` was
the Phase 0 prototype and can delegate here.

The other Phase 0 findings encoded here:

* Finding 1 - Groww pages have no `<main>`, `<article>` or `role="main"`. Without
  an explicit class selector the whole site nav (595 anchors) is ingested.
* Finding 2 - **exit load lives inside a `div.rodal` modal.** It must NOT be
  stripped. A visibility-based cleaner drops it silently, and exit load is a
  source-named question type.
* Finding 3 - "riskometer" is not a word on the page, only the risk *level*, and
  all 5 schemes read "Very High Risk". The chunker must therefore repeat the
  scheme name on every chunk or a bare level becomes unattributable.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from ..core.errors import EmptyPageError

# --- selectors ----------------------------------------------------------

# Ordered by specificity. First match wins.
CONTENT_ROOTS = (
    "div.pw14MainWrapper",
    "div.pw14ContentWrapper",
    "div.layout-main",
    "div.layout-container",
    "main",
    "article",
    "[role='main']",
)

# Structural noise that is never content.
#
# `header` and `footer` are deliberately NOT here. Groww puts the scheme name,
# the riskometer pill and the ELSS lock-in pill inside a `<header>` element
# within the content root, so dropping headers by tag name silently deletes the
# riskometer for all 5 schemes and the 3-year lock-in for the ELSS. Site chrome
# is removed by class pattern below, and the content root already excludes the
# site navigation (Phase 0 finding 1).
#
# `div.rodal` is also not here: it holds the exit-load modal (Phase 0 finding 2).
DROP_TAGS = (
    "script", "style", "noscript", "template", "svg", "canvas", "iframe",
    "form", "button", "input", "select", "textarea", "video", "audio",
    "nav", "aside",
)

# Groww's own chrome. Matched on class/id substring.
CHROME_PATTERNS = (
    "dropdownUI", "loggedOut_", "footerTopSection", "footerSection", "letterLinks",
    "cookieBanner", "cookieConsent", "consentBanner", "gdpr",
    "shareWidget", "socialShare", "share-buttons", "shareButton",
    "breadcrumb", "breadCrumb",
    "promoBanner", "promoModule", "promotional", "offerBanner",
    "newsletterSignup", "newsletter", "subscribeForm", "popupModal",
    "headerNav", "siteHeader", "navbar", "menuIcon", "hamburger",
    "stickyBar", "floatingAction", "backToTop", "tooltip", "ratingStar",
    "appBanner", "installApp", "searchBox", "searchInput",
)

# Promotional/suggestive copy. The assistant must not quote these, and they are
# not facts about the scheme.
DROP_TEXT_PATTERNS = (
    re.compile(r"^\s*(log ?in|sign ?in|sign ?up|register)\b", re.I),
    re.compile(r"\bdownload the app\b", re.I),
    re.compile(r"^\s*share\b", re.I),
    re.compile(r"^\s*reviews?\b", re.I),
)

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_WS = re.compile(r"[ \t\u00a0]+")
_BLANKS = re.compile(r"\n{3,}")


# --- data ---------------------------------------------------------------


@dataclass(frozen=True)
class Block:
    """One ordered unit of page content, already sized for chunking."""

    kind: str  # heading | table_row | paragraph | list_item
    text: str
    section: str | None
    ordinal: int


@dataclass
class ParsedPage:
    """A cleaned page: ordered blocks plus the flat text used for hashing."""

    page_id: str
    scheme: str
    category: str
    source_url: str
    fetched_at: datetime
    blocks: list[Block] = field(default_factory=list)
    flat_text: str = ""

    @property
    def chars(self) -> int:
        return len(self.flat_text)

    @property
    def content_hash(self) -> str:
        """sha256 of the cleaned text - the idempotency key (Phase 2 spec).

        Hashed on the CLEANED text, not the raw HTML, so an irrelevant markup
        change (a class rename, an ad ID) does not trigger re-embedding, while
        a change to any real fact does.
        """
        return hashlib.sha256(self.flat_text.encode("utf-8")).hexdigest()


# --- helpers ------------------------------------------------------------


def _norm(text: str) -> str:
    text = _WS.sub(" ", text or "").strip()
    return text


def _attr_blob(node: Tag) -> str:
    """Class + id, for chrome matching."""
    parts: list[str] = []
    if node.get("id"):
        parts.append(str(node["id"]))
    cls = node.get("class") or []
    if isinstance(cls, str):
        cls = [cls]
    parts.extend(str(c) for c in cls)
    return " ".join(parts)


def _is_chrome(node: Tag) -> bool:
    blob = _attr_blob(node)
    if not blob:
        return False
    return any(pat in blob for pat in CHROME_PATTERNS)


def find_content_root(soup: BeautifulSoup) -> Tag:
    """Locate the scheme-content container (Phase 0 finding 1)."""
    for selector in CONTENT_ROOTS:
        try:
            found = soup.select_one(selector)
        except Exception:  # malformed selector on odd markup
            found = None
        if found is not None and len(found.get_text(strip=True)) > 200:
            return found
    return soup.body or soup


def _is_decomposed(node: Tag) -> bool:
    # bs4 >= 4.13 exposes `.decomposed`; guard so an older bs4 degrades to
    # "keep it" rather than raising AttributeError mid-walk.
    return bool(getattr(node, "decomposed", False))


def strip_chrome(root: Tag) -> Tag:
    """Remove noise in place, leaving the exit-load modal intact.

    Iterates over a materialised copy of the children: BeautifulSoup's
    `decompose()` clears descendant `__dict__`s, so walking a live generator
    while mutating raises `AttributeError` on the next step. That was a real
    crash in the Phase 0 prototype.
    """
    for node in list(root.find_all(True)):
        if not isinstance(node, Tag) or _is_decomposed(node):
            continue
        if node.name in DROP_TAGS or _is_chrome(node):
            node.decompose()
            continue
        # Text patterns are applied ONLY to leaf nodes. Matched against a
        # container, "Log in to see more" would delete the container and take
        # real scheme facts with it.
        if node.find(True) is None:
            text = _norm(node.get_text(" ", strip=True))
            if text and any(p.search(text) for p in DROP_TEXT_PATTERNS):
                node.decompose()
    return root


def _table_caption(table: Tag, current_section: str | None) -> str:
    """A row with no caption is an orphan fact ('1.21%' on its own).

    Prefer a real <caption>, then aria-label, then the nearest heading.
    """
    for node in (table.find("caption"), table.find(attrs={"aria-label": True})):
        if node is not None:
            label = _norm(node.get_text(" ", strip=True))
            if label:
                return label
    if current_section:
        return current_section
    return "Table"


def _table_rows(table: Tag) -> list[tuple[int, str]]:
    """Serialise a table row-wise: 'Label | Value | Value'.

    Row-wise (not cell-at-a-time) is the point. A fund page puts a scheme's
    attributes in a two-column table, and splitting cells apart yields chunks
    reading '1.21%' with no label - unusable, and worse, unciteable.

    Returns (cell_count, text) so the caller can tell a real row from a stray
    single cell.
    """
    rows: list[tuple[int, str]] = []
    for tr in table.find_all("tr"):
        cells = [
            _norm(td.get_text(" ", strip=True))
            for td in tr.find_all(["td", "th"])
        ]
        cells = [c for c in cells if c]
        if not cells:
            continue
        # Collapse a header row into a single label so it is not a lone fragment.
        rows.append((len(cells), cells[0] if len(cells) == 1 else " | ".join(cells)))
    return rows


# Containers that terminate the search for a "unit" of text. A div below one of
# these is a leaf for our purposes.
_STRUCTURAL = frozenset(
    ("div", "section", "p", "li", "ul", "ol", "table", "tr", "td", "th",
     "article", "main", "h1", "h2", "h3", "h4", "h5", "h6", "form", "a", "span")
)
# A fact row longer than this is not a fact row; it is a section.
_MAX_ROW_CHARS = 260
# Below this, a fragment is a stray label and is attached to its parent row.
_MIN_ROW_CHARS = 3
# A fact VALUE is a figure, a name or a short phrase. Real values on these pages:
# "1.21%", "Rs. 500", "Very High Risk", "NIFTY 500 Total Return Index",
# "1% - if redeemed within 1 year". A value at or above this word count is prose,
# and prose in a label/value slot means the pair is a GLOSSARY DEFINITION.
_MAX_VALUE_WORDS = 12


def _is_leaf_container(node: Tag) -> bool:
    """True when node holds text but contains no further structure to descend.

    A subtree that contributes no text of its own is decoration, not structure.
    The info icon on the expense-ratio label is `div.cur-po > svg`, and `svg` is
    already in DROP_TAGS, but the `div` around it is structural. Without
    ignoring it the label is not a leaf, the pair is left with one visible cell,
    and "Expense ratio | 1.21%" is silently dropped from the corpus - found by
    Phase 3, when the fact was missing and only the glossary definition ranked.
    """
    for child in node.find_all(True):
        if child.name in DROP_TAGS or _is_chrome(child):
            continue
        if child.name in _STRUCTURAL:
            if _norm(child.get_text(" ", strip=True)):
                return False
    return bool(_norm(node.get_text(" ", strip=True)))


def _looks_like_definition(node: Tag, pieces: list[str]) -> bool:
    """True when this container is a glossary term, not a label/value fact.

    Found by Phase 3, and it is a correctness bug rather than a tidiness one. The
    exit-load modal carries a glossary of terms, each a heading plus a prose
    definition:

        div.exitLoadStampDutyTax_termBlock
          h5  "Expense ratio"
          p   "A fee payable to a mutual fund house for managing your ..."

    Emitted as a fact row that becomes "Expense ratio | A fee payable to ...",
    which is a false fact: it reads as though the expense ratio were that
    sentence. Worse, it outranked the real "Expense ratio | 1.21%" row in
    retrieval, so the assistant would have been served a definition where a
    number was asked for.

    Two signals, because either alone is insufficient: a heading child is the
    glossary's shape, and a prose-length value is not a fact.
    """
    has_heading_child = any(
        isinstance(c, Tag) and c.name in ("h1", "h2", "h3", "h4", "h5", "h6")
        for c in node.find_all(True, recursive=False)
    )
    if has_heading_child:
        return True
    return any(len(p.split()) > _MAX_VALUE_WORDS for p in pieces)


def _own_pieces(node: Tag) -> list[str]:
    """Text pieces this node contributes directly: its own strings plus the
    text of each direct child element that is itself a leaf."""
    pieces: list[str] = []
    own = _norm(" ".join(str(s) for s in node.find_all(string=True, recursive=False)))
    if own:
        pieces.append(own)
    for child in node.find_all(True, recursive=False):
        if not isinstance(child, Tag) or child.name in DROP_TAGS:
            continue
        if _is_chrome(child):
            continue
        if _is_leaf_container(child):
            text = _norm(child.get_text(" ", strip=True))
            if text:
                pieces.append(text)
    return pieces


def _fact_row_text(node: Tag) -> str:
    """Serialise a label/value container as 'Label | Value'."""
    return " | ".join(_own_pieces(node))


def _row_leaf_children(node: Tag) -> list[Tag]:
    """Direct children that are leaf containers, i.e. the visible cells."""
    return [
        c
        for c in node.find_all(True, recursive=False)
        if isinstance(c, Tag)
        and c.name not in DROP_TAGS
        and not _is_chrome(c)
        and _is_leaf_container(c)
    ]


def _qualifies_as_row(node: Tag) -> str | None:
    """Return the row text if node is an emittable label/value row, else None."""
    if _is_decomposed(node) or _is_chrome(node):
        return None
    if any(_is_decomposed(p) for p in node.parents if isinstance(p, Tag)):
        return None
    # At least two leaf children, so the bare label div (whose only other child
    # is the info icon) is never emitted on its own.
    if len(_row_leaf_children(node)) < 2:
        return None
    pieces = _own_pieces(node)
    if not pieces or _looks_like_definition(node, pieces):
        return None
    text = " | ".join(pieces)
    if not (_MIN_ROW_CHARS <= len(text) <= _MAX_ROW_CHARS):
        return None
    if _is_droppable_text(text):
        return None
    return text


def _iter_candidate_rows(root: Tag) -> list[tuple[str | None, str]]:
    """Find label/value rows in generic div/section containers.

    Groww builds the fund-details grid from `div.flex.flex-column` wrappers
    holding a label div and a value div. Nothing about that is semantic, so a
    walk of `p`/`li`/`table` alone silently loses the expense ratio, the minimum
    SIP, the riskometer level and the benchmark - which is most of what this
    corpus exists to answer.

    Double-emission is avoided by skipping a node when an ANCESTOR would itself
    be emitted. That has to be "would be emitted", not merely "has two leaf
    children": `fundDetails_fundDetailsContainer` wraps five label/value pairs,
    so it has plenty of leaf children, but its own text is far over
    `_MAX_ROW_CHARS` and it is therefore never emitted. Under the looser rule it
    still suppressed its own children and the grid rows vanished, taking
    "Expense ratio | 1.21%" with them - the fact was simply absent from the
    corpus. Found by Phase 3, when an expense-ratio question retrieved the
    glossary definition instead of the number.
    """
    rows: list[tuple[str | None, str]] = []
    seen: set[str] = set()
    for node in root.find_all(["div", "section"]):
        text = _qualifies_as_row(node)
        if text is None:
            continue
        # An emittable ancestor would re-cover this text, so emit that one only.
        if any(
            isinstance(p, Tag) and p.name in ("div", "section") and _qualifies_as_row(p)
            for p in node.parents
        ):
            continue
        if text in seen:
            continue
        seen.add(text)
        rows.append((None, text))
    return rows


def _is_droppable_text(text: str) -> bool:
    return bool(text) and any(p.search(text) for p in DROP_TEXT_PATTERNS)


# --- main entry ---------------------------------------------------------


def parse_page(
    html: str,
    *,
    page_id: str,
    scheme: str,
    category: str,
    source_url: str,
    fetched_at: datetime,
) -> ParsedPage:
    """Clean one page's HTML into ordered blocks.

    Does NOT enforce min_extract_chars; the caller does, via `check_not_empty`,
    so that a single page's failure can be reported per page rather than
    aborting the parse of the others.
    """
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(["script", "style", "noscript"]):
        node.decompose()

    root = strip_chrome(find_content_root(soup))

    blocks: list[Block] = []
    section: str | None = None
    ordinal = 0

    def emit(kind: str, text: str, sec: str | None) -> None:
        nonlocal ordinal
        if not text:
            return
        blocks.append(Block(kind, text, sec, ordinal))
        ordinal += 1

    # Pass 1 - semantic blocks, in document order.
    for node in root.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"]
    ):
        if not isinstance(node, Tag) or _is_decomposed(node) or _is_chrome(node):
            continue
        if any(_is_decomposed(p) for p in node.parents if isinstance(p, Tag)):
            continue

        if node.name in _HEADING_TAGS:
            text = _norm(node.get_text(" ", strip=True))
            if text and not _is_droppable_text(text):
                section = text
                emit("heading", text, section)
        elif node.name == "table":
            caption = _table_caption(node, section)
            for cell_count, row in _table_rows(node):
                if not row:
                    continue
                if cell_count < 2:
                    # A lone cell is almost always a stray label; attach it to
                    # its caption so the chunk stays self-contained.
                    row = f"{caption} | {row}"
                emit("table_row", f"{caption} | {row}", caption)
        elif node.name == "li":
            text = _norm(node.get_text(" ", strip=True))
            if text and len(text) >= 2 and not _is_droppable_text(text):
                emit("list_item", text, section)
        else:  # <p>
            text = _norm(node.get_text(" ", strip=True))
            if text and not _is_droppable_text(text):
                emit("paragraph", text, section)

    # Pass 2 - label/value rows from generic containers.
    for _sec, text in _iter_candidate_rows(root):
        emit("fact_row", text, section)

    # Pass 3 - safety net. Any leaf text not already captured by pass 1 or 2.
    # Without this, an unrecognised layout silently drops facts, which is how
    # the first version of this module lost the benchmark and riskometer.
    captured = [b.text for b in blocks]
    for node in root.find_all(["div", "section", "span", "a", "b", "strong", "em"]):
        if not isinstance(node, Tag) or _is_decomposed(node) or _is_chrome(node):
            continue
        if not _is_leaf_container(node):
            continue
        text = _norm(node.get_text(" ", strip=True))
        if len(text) < _MIN_ROW_CHARS or _is_droppable_text(text):
            continue
        if any(text in existing for existing in captured):
            continue
        captured.append(text)
        emit("text", text, section)

    # Drop exact duplicates produced by the overlapping passes.
    seen: set[str] = set()
    deduped: list[Block] = []
    for b in blocks:
        if b.text in seen:
            continue
        seen.add(b.text)
        deduped.append(Block(b.kind, b.text, b.section, len(deduped)))
    blocks = deduped

    flat = _BLANKS.sub("\n\n", "\n".join(b.text for b in blocks if b.text)).strip()
    return ParsedPage(
        page_id=page_id,
        scheme=scheme,
        category=category,
        source_url=source_url,
        fetched_at=fetched_at,
        blocks=blocks,
        flat_text=flat,
    )


def check_not_empty(page: ParsedPage, minimum: int) -> None:
    """FR-2: a thin page is a hard failure, not a warning.

    With 5 pages, skipping one means the assistant lacks a whole scheme and
    does not know it - the worst failure mode in the system, because it looks
    healthy.
    """
    if page.chars < minimum:
        raise EmptyPageError(page.page_id, page.chars, minimum)


def parse_file(
    path: str | Path,
    *,
    page_id: str,
    scheme: str,
    category: str,
    source_url: str,
    fetched_at: datetime,
) -> ParsedPage:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python -m src.ragbot.ingest --fetch` to "
            f"populate data/raw first."
        )
    return parse_page(
        path.read_text(encoding="utf-8", errors="replace"),
        page_id=page_id,
        scheme=scheme,
        category=category,
        source_url=source_url,
        fetched_at=fetched_at,
    )
