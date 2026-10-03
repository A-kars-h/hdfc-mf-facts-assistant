"""The canonical corpus tokenizer, shared by indexing and retrieval.

This lives in `core/` rather than in `retrieval/sparse.py` for one reason: the
BM25 index is a PERSISTED PICKLE built at ingest time and read at query time.
If the tokenizer used to build it and the tokenizer used to query it ever
differ, the sparse retriever keeps working and returns quietly wrong rankings -
no exception, no warning, just worse results that look like a tuning problem.

So there is exactly one implementation, and both sides import it.

`TOKENIZER_VERSION` is recorded in the pickle. It is bumped only when the
tokenizer's OUTPUT actually changes, because bumping it invalidates every
existing index and forces a full re-ingest.
"""

from __future__ import annotations

import re

# Bump this ONLY if the tokenisation behaviour changes. Doing so invalidates
# data/bm25.pkl and requires `python -m src.ragbot.ingest --reindex`.
TOKENIZER_VERSION = "ragbot.v1"

# Alphanumerics, the rupee sign, and optional decimal/percent suffixes.
#
# Keeping numbers intact is the point. The corpus is facts, and the facts are
# numeric: "1.21%", "₹500", "3.29". A default whitespace split discards exactly
# the tokens a factual question contains, which would leave BM25 matching on
# stopword-ish prose and scoring a question about the expense ratio as though it
# had been asked about fund characteristics generally.
_TOKEN_RE = re.compile(r"[₹a-z0-9]+(?:\.[0-9]+)?%?")


def tokenize(text: str) -> list[str]:
    """Lowercase, split into numeric-preserving tokens."""
    return _TOKEN_RE.findall(text.lower())


def fingerprint(text: str) -> list[str]:
    """Alias kept for readability at the call sites that build the index."""
    return tokenize(text)
