"""Blocks -> token-bounded chunks.

Recursive split: heading -> table/list row -> paragraph -> sentence. A sentence
is never broken unless that sentence alone exceeds the budget.

Two Phase 0 findings are load-bearing here:

* **Finding 3 - the label must travel with the value.** Groww shows only a risk
  *level*, and all 5 schemes read "Very High Risk". A bare "Very High Risk" chunk
  matches a question about *any* scheme, so the model would answer confidently
  about the wrong fund. Every chunk therefore repeats the scheme name, and every
  table/fact row keeps its own label.

* **Finding 5 - returns are 17% of the corpus and none of it may be reported.**
  Chunks are tagged `return_heavy` at ingest so Phase 3 can deprioritise them
  at retrieval instead of relying on the output screen alone.

Sizing is in TOKENS, counted with the real model tokenizer, never characters.
Characters are the wrong unit: the corpus is dense with numbers, and 200
characters of "Expense ratio 1.21%" is nowhere near the 256-token ceiling.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

from ..core.models import Chunk
from .clean import Block, ParsedPage


class SupportsEncode(Protocol):
    """Anything with a HuggingFace-style tokenizer."""

    def encode(self, text: str) -> list[int]: ...


# Return/NAV markers. A chunk matching these is mostly numbers the assistant is
# forbidden to state (FR-20).
_RETURN_WORDS = re.compile(
    r"\b(?:annualis?ed|annualized|CAGR|absolute return|periodic return|"
    r"fund returns?|returns and rankings|return calculator)\b",
    re.I,
)
_NAV_VALUE = re.compile(r"\bNAV\b[^\n]{0,24}(?:₹|Rs\.?|\d)", re.I)
# A percentage figure, and a SIGNED one. The signed form is the tell: fund
# pages print returns as "+ 2.42 %" and ordinary facts as "1.03%".
_PCT = re.compile(r"[+\-−]?\s*\d[\d,]*\.?\d*\s*%")
_SIGNED_PCT = re.compile(r"[+\-−]\s*\d[\d,]*\.?\d*\s*%")


def is_return_heavy(text: str) -> bool:
    """True when a chunk is dominated by return/NAV figures.

    Tuned against the real corpus, where the first attempt never fired: the
    return data arrives as one small table row per period ('Return calculator |
    3 years | ... | + 8.44 %'), so a rule looking for a period label adjacent
    to a percentage missed every one of them.

    Deliberately biased towards tagging. A false positive merely deprioritises
    a chunk at retrieval, where it is still available as a fallback; a false
    negative lets a return figure compete for a factual question's top slot and
    tempt the model into the one thing the source forbids.
    """
    if _RETURN_WORDS.search(text) or _NAV_VALUE.search(text):
        return True
    if _SIGNED_PCT.search(text):
        return True
    # Three or more bare percentages, e.g. a returns table row. Two is not
    # enough: 'Expense ratio 1.03%' next to 'Dividend yield 1.10%' is a fact
    # chunk, not a returns chunk.
    return len(_PCT.findall(text)) >= 3


# Sentence split. Abbreviations and decimals must not create boundaries:
# "1.21%." is one sentence, not two.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z₹0-9\"'(])")
_ABBREV = re.compile(r"(?:Rs|Mr|Mrs|Ms|Dr|vs|etc|No|approx)\.$", re.I)


def split_sentences(text: str) -> list[str]:
    """Split into sentences, then re-join splits that followed an abbreviation."""
    parts = [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]
    merged: list[str] = []
    for part in parts:
        if merged and _ABBREV.search(merged[-1]):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TokenCounter:
    """Counts tokens with the real tokenizer, with a small cache.

    Caching matters: the same label text appears on every page, and tokenising
    is the hot loop when splitting long blocks.
    """

    def __init__(self, tokenizer: SupportsEncode) -> None:
        self._tokenizer = tokenizer
        self._cache: dict[str, list[int]] = {}

    def encode(self, text: str) -> list[int]:
        ids = self._cache.get(text)
        if ids is None:
            ids = self._tokenizer.encode(text)
            if len(self._cache) < 100_000:
                self._cache[text] = ids
        return ids

    def count(self, text: str) -> int:
        return len(self.encode(text))


# --- unit assembly ------------------------------------------------------


def _block_offsets(blocks: list[Block]) -> list[tuple[int, int]]:
    """Char offsets of each block within the page's flat_text.

    flat_text is "\n".join(block.text), so offsets are cumulative. Returning
    real offsets (rather than None) is what lets the UI jump to the exact span
    that produced an answer.
    """
    offsets: list[tuple[int, int]] = []
    pos = 0
    for b in blocks:
        offsets.append((pos, pos + len(b.text)))
        pos += len(b.text) + 1  # the joining newline
    return offsets


def _compose(scheme: str, section: str | None, body: str) -> str:
    """Prepend scheme identity so a chunk is independently answerable.

    Without this, a retrieved chunk reading "Very High Risk" or "1.21%" cannot
    be attributed, and the model either answers about the wrong scheme or
    refuses a question it can actually answer. This costs ~10 tokens per chunk
    and is the cheapest insurance in the pipeline.
    """
    parts = [scheme]
    if section and section.strip() and section.strip() != body.strip():
        parts.append(f"({section})")
    parts.append(body)
    return " ".join(parts)


def _tail_words(words: list[str], overlap: int, counter: TokenCounter) -> list[str]:
    """The trailing words of `words` that fit inside the overlap budget."""
    if overlap <= 0:
        return []
    kept: list[str] = []
    for word in reversed(words):
        if counter.count(" ".join([word, *kept])) > overlap:
            break
        kept.insert(0, word)
    return kept


def _word_split(
    text: str, counter: TokenCounter, budget: int, overlap: int
) -> list[str]:
    """Last-resort split on word boundaries, for text too big to fit.

    Only reached when a single sentence exceeds the budget on its own - which
    the corpus does contain, in the long "scheme summary" paragraphs. Emitting
    it whole would hand the embedder something it silently truncates, so it is
    divided here instead. The only case this cannot fix is one word longer than
    the budget, and the embedder gate catches that loudly.
    """
    words = text.split()
    if not words:
        return []
    out: list[str] = []
    cur: list[str] = []

    for word in words:
        if cur and counter.count(" ".join([*cur, word])) > budget:
            out.append(" ".join(cur))
            cur = _tail_words(cur, overlap, counter)
            # The overlap tail may itself push this word over; shed words until
            # it fits, so every emitted piece respects the budget.
            while cur and counter.count(" ".join([*cur, word])) > budget:
                cur.pop(0)
        cur.append(word)

    if cur:
        out.append(" ".join(cur))
    return out


def _split_to_budget(
    text: str, counter: TokenCounter, budget: int, overlap: int
) -> list[str]:
    """Split over-long text at sentence boundaries, never mid-sentence unless a
    single sentence exceeds the budget on its own."""
    if counter.count(text) <= budget:
        return [text]

    pieces: list[str] = []
    current = ""

    for sentence in split_sentences(text):
        if counter.count(sentence) > budget:
            # Too big to ever join anything: split it on its own terms.
            if current:
                pieces.append(current)
                current = ""
            parts = _word_split(sentence, counter, budget, overlap)
            pieces.extend(parts[:-1])
            current = parts[-1] if parts else ""
            continue

        candidate = f"{current} {sentence}".strip() if current else sentence
        if counter.count(candidate) <= budget:
            current = candidate
        else:
            pieces.append(current)
            # Carry the tail forward so a fact split across the boundary stays
            # retrievable from either side.
            tail = " ".join(_tail_words(current.split(), overlap, counter))
            current = f"{tail} {sentence}".strip() if tail else sentence

    if current:
        pieces.append(current)

    # Final guarantee of the invariant. Every path above tries to respect the
    # budget, but the one that matters is that nothing escapes it - an
    # over-budget chunk is silently truncated by the model and then cited.
    final: list[str] = []
    for piece in pieces:
        if not piece.strip():
            continue
        if counter.count(piece) <= budget:
            final.append(piece)
        else:
            final.extend(_word_split(piece, counter, budget, overlap))
    return final


def chunk_page(
    page: ParsedPage,
    *,
    size: int = 200,
    overlap: int = 40,
    tokenizer: SupportsEncode,
    scheme: str | None = None,
    drop_return_heavy: bool = False,
) -> list[Chunk]:
    """Turn a cleaned page into token-bounded, provenance-complete chunks.

    `size` and `overlap` are in tokens. `tokenizer` is the embedding model's
    own tokenizer - passing an approximate one would make the size budget a
    guess, and the whole point of the budget is that it is not.
    """
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must satisfy 0 <= overlap < size")

    counter = TokenCounter(tokenizer)
    scheme_name = scheme or page.scheme
    offsets = _block_offsets(page.blocks)

    # A heading is never useful alone ("Expense ratio" with no value), so it is
    # held and prepended to the block that follows.
    pending_heading: str | None = None
    chunks: list[Chunk] = []

    def add(text: str, section: str | None, start: int, end: int) -> None:
        ordinal = len(chunks)
        chunk_id = _sha(f"{page.page_id}:{ordinal}")[:32]
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                page_id=page.page_id,
                scheme=scheme_name,
                category=page.category,
                source_url=page.source_url,
                fetched_at=page.fetched_at,
                text=text,
                token_count=counter.count(text),
                content_hash=_sha(text),
                section=section,
                char_start=start,
                char_end=end,
                return_heavy=is_return_heavy(text),
            )
        )

    for block, (start, end) in zip(page.blocks, offsets):
        if not block.text.strip():
            continue

        if block.kind == "heading":
            pending_heading = block.text
            continue

        body = block.text
        section = block.section or pending_heading
        if pending_heading and pending_heading.strip() not in body:
            body = f"{pending_heading}: {body}"
        pending_heading = None

        composed = _compose(scheme_name, section, body)
        # Tag and drop on the SAME string. An earlier version tested the bare
        # block body for dropping but tagged the composed text, so a chunk
        # could be tagged return_heavy yet survive `drop_return_heavy=True`
        # whenever the section heading ("Returns and rankings") was what
        # introduced the return wording.
        for piece in _split_to_budget(composed, counter, size, overlap):
            if drop_return_heavy and is_return_heavy(piece):
                continue
            add(piece, section, start, end)

    # A trailing heading with nothing after it.
    if pending_heading:
        composed = _compose(scheme_name, pending_heading, pending_heading)
        if counter.count(composed) <= size:
            add(composed, pending_heading, 0, len(page.flat_text))

    return chunks


def summarise(chunks: list[Chunk]) -> dict[str, int]:
    """Counts for the CLI report."""
    out = {
        "chunks": len(chunks),
        "return_heavy": sum(1 for c in chunks if c.return_heavy),
        "min_tokens": min((c.token_count for c in chunks), default=0),
        "max_tokens": max((c.token_count for c in chunks), default=0),
    }
    out["mean_tokens"] = (
        round(sum(c.token_count for c in chunks) / len(chunks), 1) if chunks else 0
    )
    return out
