"""Typed error taxonomy.

Every failure mode in the pipeline has a named error so call sites can react
specifically instead of catching bare Exception. The rule this module enforces:
errors are never swallowed. An unhandled error surfaces to the user as an
actionable message (FR-15), never as a blank screen or a raw traceback.
"""

from __future__ import annotations


class RagbotError(Exception):
    """Base class for every error this project raises deliberately."""


# --- Corpus / ingestion -------------------------------------------------


class PageFetchError(RagbotError):
    """A page could not be fetched at all (network, DNS, HTTP error)."""


class EmptyPageError(RagbotError):
    """A page yielded less text than min_extract_chars.

    Raised rather than warned about (FR-2). With only 5 pages, silently skipping
    one means the assistant lacks an entire scheme and does not know it.
    """

    def __init__(self, page_id: str, chars: int, minimum: int) -> None:
        self.page_id, self.chars, self.minimum = page_id, chars, minimum
        super().__init__(
            f"page '{page_id}' yielded {chars} chars, below min_extract_chars="
            f"{minimum}. Probable client-rendered shell - the corpus cannot be "
            f"built on a partial fetch."
        )


class ChunkTooLongError(RagbotError):
    """A chunk exceeds the embedder's max_seq_length.

    This exists because sentence-transformers SILENTLY TRUNCATES past
    max_seq_length. A chunk truncated before embedding loses its tail, retrieval
    still returns it as a strong match, and the model then answers from a fact
    that was never in the vector - a hallucination wearing a real citation.
    Failing the build is the only acceptable response (FR-4, NFR-10).
    """

    def __init__(self, chunk_id: str, tokens: int, ceiling: int) -> None:
        self.chunk_id, self.tokens, self.ceiling = chunk_id, tokens, ceiling
        super().__init__(
            f"chunk '{chunk_id}' is {tokens} tokens, above the embedder ceiling "
            f"of {ceiling}. The embedder would truncate it silently and the fact "
            f"would be lost while still being cited. Reduce CHUNK_SIZE or split "
            f"on a tighter boundary."
        )


class EmbeddingDimMismatchError(RagbotError):
    """Stored vectors do not match the active embedding model's dimension.

    Caused by changing EMBEDDING_MODEL without re-indexing. Silent otherwise:
    retrieval degrades to near-noise and looks like 'RAG just does not work'.
    """

    def __init__(self, stored: int, active: int) -> None:
        self.stored, self.active = stored, active
        super().__init__(
            f"index was built with embedding_dim={stored} but the active model "
            f"produces {active}. Run `python -m src.ragbot.ingest --reindex`."
        )


# --- Configuration / calibration ---------------------------------------


class NotCalibratedError(RagbotError):
    """SIMILARITY_THRESHOLD was read before it was calibrated.

    There is deliberately no default value. Cosine-similarity ranges differ per
    embedding model AND per corpus, so any threshold written down in advance
    would be invented. Run `python -m src.ragbot.eval.calibrate` to derive one
    from the sample set (FR-13).
    """

    def __init__(self) -> None:
        super().__init__(
            "SIMILARITY_THRESHOLD is not set. It has no default on purpose - a "
            "guessed threshold silently breaks refusal correctness. Calibrate it "
            "with `python -m src.ragbot.eval.calibrate`."
        )


# --- Safety -------------------------------------------------------------


class PIIDetected(RagbotError):
    """Personal data found in a user question.

    NO LONGER the enforcement mechanism as of Phase 5. `Ragbot.ask()` returns a
    neutral Refusal C instead of raising this, because FR-31 asks for a neutral
    user-facing message and an exception renders as a traceback. It is kept for
    callers that prefer an exception (batch jobs, non-UI entry points) and is
    what `Ragbot.stream_draft()` avoided in favour of yielding the neutral text.

    It was always a weaker control than it looked: a `except PIIDetected` clause
    converts the block into a no-op. The real guarantee now lives in
    `generation.pipeline._require_clean`, which every model-reaching path must
    pass a clean, enforced `PIIResult` to satisfy - and a missing argument is a
    TypeError, not a caught exception.
    """

    def __init__(self, kinds: list[str], redacted: str) -> None:
        self.kinds, self.redacted = kinds, redacted
        super().__init__(
            f"question contained disallowed personal data ({', '.join(kinds)}). "
            f"Nothing was embedded, sent, or stored."
        )


class UnscannedInputError(RagbotError):
    """A model-reaching path was reached without a clean, enforced PII scan.

    This is the Phase 5 structural guarantee. `_route()` and `_generate()` both
    require a `PIIResult`; this error fires if that result is absent, came from a
    stub, or reports a finding. It is a programming error, not a user error, and
    the message says so - a user who typed a PAN should get a refusal, never this.
    """

    def __init__(self, detail: str = "no scan result supplied") -> None:
        self.detail = detail
        super().__init__(
            f"refusing to continue without a clean PII scan: {detail}. This is a "
            f"bug in the calling code, not something the user can fix by rewording."
        )


# --- Provider -----------------------------------------------------------


class MissingAPIKeyError(RagbotError):
    """An LLM key is required but absent. Message must be actionable (FR-15)."""

    def __init__(self, env_var: str = "LLM_API_KEY") -> None:
        self.env_var = env_var
        super().__init__(
            f"{env_var} is not set. Copy .env.example to .env and add your key, "
            f"or set LLM_PROVIDER=ollama to run fully locally."
        )


class ProviderError(RagbotError):
    """The LLM provider failed after retries. Surfaced as a plain message."""


# --- Corpus configuration ----------------------------------------------


class CorpusConfigError(RagbotError):
    """corpus.yaml is missing, malformed, or empty."""
