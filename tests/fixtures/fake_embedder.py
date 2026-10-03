"""A fake embedder and tokenizer for fast, deterministic pipeline tests.

Real `sentence-transformers` is exercised separately in
`test_embedder_gate.py`. Using it here would make every pipeline test pay a
model load and embed 1,200 chunks, so the idempotency and provenance tests
would be too slow to run often - and tests that are too slow get skipped.

Vectors are a deterministic hash of the text, so the same text always produces
the same vector. That is what makes the idempotency assertions meaningful.
"""

from __future__ import annotations

import hashlib
import re

from src.ragbot.core.errors import ChunkTooLongError


class FakeTokenizer:
    """Whitespace/punctuation tokenizer, ~1 token per 4 characters."""

    def encode(self, text: str) -> list[int]:
        return [1] * max(1, len(re.findall(r"\w+|[^\w\s]", text)))


class FakeEmbedder:
    """Mimics the Embedder surface the pipeline and writer rely on."""

    def __init__(self, dim: int = 384, max_seq_length: int = 256) -> None:
        self.dim = dim
        self.max_seq_length = max_seq_length
        self.model_name = "fake/mini-test-model"
        self.tokenizer = FakeTokenizer()
        self.embed_calls = 0

    def count_tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text))

    def check_fits(self, texts, labels=None) -> None:
        for i, text in enumerate(texts):
            n = self.count_tokens(text)
            if n > self.max_seq_length:
                label = labels[i] if labels and i < len(labels) else f"item {i}"
                raise ChunkTooLongError(label, n, self.max_seq_length)

    def embed(self, texts, labels=None) -> list[list[float]]:
        if not texts:
            return []
        self.check_fits(texts, labels=labels)
        self.embed_calls += 1
        out: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vec = [(digest[i % len(digest)] / 255.0) for i in range(self.dim)]
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out

    def embed_one(self, text: str, label: str | None = None) -> list[float]:
        return self.embed([text], labels=[label] if label else None)[0]
