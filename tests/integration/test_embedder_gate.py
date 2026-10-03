"""The truncation gate, against the REAL model.

The rest of the suite uses a fake embedder so it stays fast. This file is the
exception: the gate's whole purpose is to catch what the real
sentence-transformers tokenizer would silently truncate, so testing it against a
fake tokenizer would test nothing.

Verified against all-MiniLM-L6-v2: a 1,260-character input tokenises to 422
tokens against a ceiling of 256, and transformers emits only a warning.
"""

from __future__ import annotations

import pytest

from src.ragbot.core.errors import ChunkTooLongError
from src.ragbot.ingest.embedder import DEFAULT_MODEL, Embedder


@pytest.fixture(scope="module")
def embedder() -> Embedder:
    return Embedder(DEFAULT_MODEL)


def test_limits_are_read_from_the_model_not_hardcoded(embedder: Embedder):
    """all-MiniLM-L6-v2 reports 256. The point is that it was READ."""
    assert embedder.max_seq_length == 256
    assert embedder.dim == 384
    assert embedder.model_name == DEFAULT_MODEL


def test_oversized_text_raises_instead_of_truncating(embedder: Embedder):
    long_text = "Min. for SIP Rs. 500. " * 200
    assert embedder.count_tokens(long_text) > embedder.max_seq_length
    with pytest.raises(ChunkTooLongError) as exc:
        embedder.embed([long_text], labels=["too-long"])
    err = exc.value
    assert err.ceiling == embedder.max_seq_length
    assert err.tokens > err.ceiling
    assert "too-long" in str(err)
    assert "truncat" in str(err).lower(), "the error must explain the silent risk"


def test_gate_checks_every_text_not_just_the_first(embedder: Embedder):
    ok = "Expense ratio 0.77%"
    bad = "Exit load. " * 400
    with pytest.raises(ChunkTooLongError) as exc:
        embedder.embed([ok, bad], labels=["fine", "bad"])
    assert exc.value.chunk_id == "bad"


def test_batch_within_budget_embeds_normally(embedder: Embedder):
    texts = [
        "HDFC Equity Fund Direct Growth Expense ratio 0.77%",
        "HDFC Equity Fund Direct Growth Min. for SIP Rs. 100",
        "HDFC Equity Fund Direct Growth Exit load 1% if redeemed within 1 year",
    ]
    vectors = embedder.embed(texts, labels=["a", "b", "c"])
    assert len(vectors) == 3
    assert all(len(v) == embedder.dim for v in vectors)


def test_embeddings_are_normalised(embedder: Embedder):
    """The gate's cosine threshold is only meaningful on normalised vectors."""
    vectors = embedder.embed(["Expense ratio 0.77%", "Exit load Nil"])
    for vec in vectors:
        norm = sum(v * v for v in vec) ** 0.5
        assert norm == pytest.approx(1.0, abs=1e-5)


def test_cosine_similarity_equals_dot_product_and_discriminates(
    embedder: Embedder,
):
    """Normalised embeddings turn cosine into a plain dot product, which is what
    lets Phase 3 threshold a raw score directly.

    No absolute floor is asserted: SIMILARITY_THRESHOLD deliberately has no
    default (FR-1) and is calibrated in Phase 5. What must hold is that the
    vectors discriminate - a paraphrase must outrank an unrelated fact - and
    that identical text is self-similar. A model that scored everything alike
    would pass an absolute threshold but be useless for retrieval.
    """
    identical = "Expense ratio 0.77%"
    paraphrase = "Expense ratio is 0.77% for this fund"
    unrelated = "Exit load Nil if held for 3 years"

    vec_same, vec_para, vec_unrel = embedder.embed(
        [identical, paraphrase, unrelated]
    )

    self_score = sum(x * y for x, y in zip(vec_same, vec_same))
    assert self_score == pytest.approx(1.0, abs=1e-5), "identical text scores 1.0"

    para_score = sum(x * y for x, y in zip(vec_same, vec_para))
    unrel_score = sum(x * y for x, y in zip(vec_same, vec_unrel))

    assert para_score > unrel_score, "a paraphrase must outrank an unrelated fact"
    assert para_score > 0.5, "paraphrase similarity is implausibly low for MiniLM"


def test_empty_input_is_not_an_error(embedder: Embedder):
    assert embedder.embed([]) == []
