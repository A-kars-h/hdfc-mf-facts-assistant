"""Embeddings, with the truncation gate enforced before any encoding happens.

`sentence-transformers` TRUNCATES at `max_seq_length` without complaint. That is
the most dangerous default in this stack: a chunk silently loses its tail, is
still embedded, still retrieved as a strong match, and is still cited - so the
model answers from a fact that was never in the vector. The result is a
hallucination wearing a real source link.

So every text is tokenised and checked BEFORE `encode()` is called, and an
oversized chunk fails the build loudly (FR-4, NFR-10). Verified against the
real model: a 1,260-character input tokenises to 422 tokens against a ceiling
of 256, and transformers only prints a warning.
"""

from __future__ import annotations

import logging
from typing import Sequence

from ..core.errors import ChunkTooLongError

log = logging.getLogger(__name__)

# The mandated model (source line 20). Config may override, but the default is
# not a preference - it is a requirement.
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

BATCH_SIZE = 32


class Embedder:
    """Thin wrapper over SentenceTransformer that adds the size gate.

    `max_seq_length` is READ from the loaded model. Never hardcode 256: that
    number belongs to one model, and hardcoding it is how a silent-truncation
    bug reappears after a model change.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        # READ, never hardcoded.
        self.max_seq_length = int(self._model.max_seq_length)
        self.dim = int(self._get_dim())
        log.info(
            "embedder ready model=%s max_seq_length=%d dim=%d",
            model_name, self.max_seq_length, self.dim,
        )

    def _get_dim(self) -> int:
        # `get_sentence_embedding_dimension` was renamed in sentence-transformers
        # 6.x. Try the new name FIRST so the deprecated one is never called and
        # no FutureWarning is emitted (pyproject turns warnings into errors).
        for attr in ("get_embedding_dimension", "get_sentence_embedding_dimension"):
            fn = getattr(self._model, attr, None)
            if callable(fn):
                return fn()
        raise RuntimeError(
            f"cannot determine embedding dimension from {self.model_name!r}"
        )

    @property
    def tokenizer(self):
        return self._model.tokenizer

    def count_tokens(self, text: str) -> int:
        return len(self._model.tokenizer.encode(text))

    def check_fits(self, texts: Sequence[str], *, labels: Sequence[str] | None = None) -> None:
        """Raise if ANY text exceeds the ceiling. Runs before every embed call."""
        for i, text in enumerate(texts):
            n = len(self._model.tokenizer.encode(text))
            if n > self.max_seq_length:
                label = labels[i] if labels and i < len(labels) else f"item {i}"
                raise ChunkTooLongError(label, n, self.max_seq_length)

    def embed(self, texts: Sequence[str], labels: Sequence[str] | None = None) -> list[list[float]]:
        """Embed texts, or raise. Never truncates."""
        if not texts:
            return []
        self.check_fits(texts, labels=labels)
        vectors = self._model.encode(
            list(texts),
            batch_size=BATCH_SIZE,
            normalize_embeddings=True,  # makes cosine similarity a dot product
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        # Normalised embeddings are what make the gate's raw cosine threshold
        # meaningful. If this ever changes, the calibrated threshold is invalid.
        return vectors.tolist()

    def embed_one(self, text: str, label: str | None = None) -> list[float]:
        return self.embed([text], labels=[label] if label else None)[0]
