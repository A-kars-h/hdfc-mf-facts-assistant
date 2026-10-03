"""Typed data contracts shared by every phase.

Two structural decisions in this file are load-bearing and must not be
"simplified" later:

1. `RetrievedChunk.dense_score` and `.fused_rank` are SEPARATE fields.
   Reciprocal-rank fusion produces scale-free rank scores, not similarity, so a
   threshold on a fused score is not calibratable. Keeping them apart at the type
   level makes reading a rank score as a threshold a visible misuse rather than
   a silent quality regression (architecture §5.2, invariant 5).

2. `Answer` validates its own shape. Prohibitions are checked on the output
   (invariant 7), so by the time an `Answer` is constructed the answer must
   already satisfy them. A violation here is a bug, and raising is correct.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

# --- Sentence counting --------------------------------------------------

# The answer contract caps answers at 3 sentences. Counting is done once, here,
# so validate.py and the Answer validator cannot disagree.
#
# Heuristic, deliberately conservative: a decimal point or a known abbreviation
# is never treated as a sentence boundary. "Expense ratio 1.21%." is one
# sentence; a naive split on [.!?] would call it two and wrongly reject it.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "vs", "etc", "e.g", "i.e", "approx",
    "no", "fig", "rs", "inr", "min", "max", "incl", "excl", "cf", "ca",
}
_BOUNDARY = re.compile(r"(?<=[.!?])[\"')\]]*\s+")
_DECIMAL = re.compile(r"\d[.!?]\d")


def count_sentences(text: str) -> int:
    """Count sentences without splitting on decimals or abbreviations."""
    stripped = text.strip()
    if not stripped:
        return 0
    parts = [p for p in _BOUNDARY.split(stripped) if p and p.strip()]
    count = 0
    for part in parts:
        candidate = part.strip()
        if not candidate:
            continue
        # Drop a trailing fragment that is only an abbreviation or a decimal.
        tail = candidate.rsplit(" ", 1)[-1].rstrip(".!?").lower()
        if tail in _ABBREVIATIONS or _DECIMAL.search(candidate[-4:] or " "):
            if count:
                continue
        count += 1
    return max(count, 1)


# --- Enums --------------------------------------------------------------


class Intent(str, Enum):
    """Question intent, classified BEFORE retrieval scoring (invariant 6).

    `opinion` exists because advice-seeking questions retrieve *strong* context
    - these pages are full of ratios, returns and fund characteristics - so the
    confidence gate cannot detect them and must not be asked to.

    `corpus_sources` is the fourth value and is the only one that is neither
    refused nor answered from retrieved chunks: the question asks WHICH pages
    this assistant itself covers. No chunk can answer that - the corpus pages do
    not describe the corpus - so it is answered deterministically from
    `config/corpus.yaml`. Measured, not assumed: routed as `factual`, this
    question retrieved `raw_dense_max=0.7540` against a calibrated threshold of
    0.7562 and was refused as out-of-scope, which is the gate being asked a
    question it cannot answer. It is kept out of `factual` so that routing
    short-circuits retrieval instead of paying for it and then refusing.
    """

    FACTUAL = "factual"
    OPINION = "opinion"
    OUT_OF_SCOPE = "out_of_scope"
    CORPUS_SOURCES = "corpus_sources"


# --- Corpus -------------------------------------------------------------


class PageRecord(BaseModel):
    """One corpus page, as recorded in the manifest (FR-8)."""

    page_id: str
    scheme: str
    category: str
    source_url: str
    fetched_at: datetime
    chunks: int = 0
    content_hash: str


class PageManifest(BaseModel):
    """artifacts/manifest.json - the contract between ingest and the UI.

    `embedding_dim` is recorded so a model change is detected rather than
    silently degrading retrieval (see EmbeddingDimMismatchError).
    """

    generated_at: datetime
    amc: str
    plan_variant: str = "Direct Growth"
    embedding_model: str
    embedding_dim: int
    chunk_size: int
    chunk_overlap: int
    pages: list[PageRecord] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)

    @property
    def total_chunks(self) -> int:
        return int(self.totals.get("chunks", 0))


class Chunk(BaseModel):
    """An embedded unit of corpus text with full provenance (FR-5).

    Provenance is not optional: the answer's source link and its `last_updated`
    date are both derived from it, so a chunk without provenance cannot be
    cited compliantly.
    """

    chunk_id: str
    page_id: str
    scheme: str
    category: str
    source_url: str
    fetched_at: datetime
    text: str
    token_count: int
    content_hash: str
    section: str | None = None
    char_start: int = 0
    char_end: int = 0
    return_heavy: bool = Field(
        default=False,
        description="Set at ingest when the chunk is mostly return/NAV figures "
        "(Phase 0 measured 17% of the corpus). Those figures are exactly what "
        "the assistant must not state (FR-20), so Phase 3 deprioritises these "
        "at retrieval rather than filtering them only at output.",
    )

    @property
    def source_title(self) -> str:
        return self.scheme

    @field_validator("source_url")
    @classmethod
    def _must_be_single_url(cls, v: str) -> str:
        if re.search(r"\s", v.strip()):
            raise ValueError(
                "source_url must be exactly one URL; the answer contract allows "
                "only one citation per answer (FR-17)"
            )
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"source_url must be http(s), got {v!r}")
        return v.strip()


class RetrievedChunk(BaseModel):
    """A candidate returned by hybrid retrieval.

    `dense_score` is the RAW cosine similarity, pre-fusion, and is the ONLY
    value the confidence gate may threshold (FR-13). `fused_rank` is ordering
    only. Do not add a `score` field that conflates them.
    """

    chunk: Chunk
    dense_score: float = Field(
        description="Raw cosine similarity from the dense retriever, pre-fusion. "
        "The confidence gate reads this and only this."
    )
    fused_rank: int = Field(description="Rank from RRF fusion. Ordering only.")
    sparse_score: float | None = Field(
        default=None, description="Raw BM25 score, when hybrid search is enabled."
    )

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id

    @property
    def source_url(self) -> str:
        return self.chunk.source_url


class GateDecision(BaseModel):
    """Outcome of the confidence gate (FR-13).

    `raw_dense_max` is carried on the decision so the refusal path can be
    audited after the fact, without re-running retrieval.
    """

    found_answer: bool
    reason: str
    raw_dense_max: float
    candidates_considered: int = 0


# --- Answers ------------------------------------------------------------


class Answer(BaseModel):
    """The answer contract from PRD §4. Every field is validated."""

    intent: Intent
    text: str
    source_url: str | None = None
    source_title: str | None = None
    last_updated: datetime | None = None
    is_advice: bool = Field(
        default=False, description="Must be False. Advice is prohibited (FR-19)."
    )
    perf_claim: bool = Field(
        default=False,
        description="Must be False. Performance claims are prohibited (FR-20).",
    )
    educational_link: str | None = Field(
        default=None,
        description="Required for opinion refusals (FR-21). Never generated - "
        "only read from a human-verified map.",
    )
    educational_link_missing: bool = Field(
        default=False,
        description="True when an opinion refusal was produced but no verified "
        "link existed. Makes M-3 report honestly instead of passing on a "
        "broken link.",
    )
    refused: bool = False
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    validation: list[str] = Field(
        default_factory=list,
        description="Which checks ran and what was adjusted. Read by the eval "
        "harness to distinguish 'correctly refused' from 'refused because the "
        "link map is empty'.",
    )
    educational_link_required: bool = Field(
        default=False,
        description="Derived: an opinion answer must carry a link or declare the "
        "link missing.",
    )

    # --- backstop shape checks -------------------------------------------

    @field_validator("is_advice")
    @classmethod
    def _advice_forbidden(cls, v: bool) -> bool:
        if v:
            raise ValueError(
                "is_advice must be False - advice is prohibited by the source "
                "(line 22/36). Route to an opinion refusal instead (FR-19)."
            )
        return v

    @field_validator("perf_claim")
    @classmethod
    def _perf_forbidden(cls, v: bool) -> bool:
        if v:
            raise ValueError(
                "perf_claim must be False - the assistant must not state or "
                "compare returns (source line 41). Route to a factsheet link "
                "instead (FR-20)."
            )
        return v

    @field_validator("text")
    @classmethod
    def _sentence_limit(cls, v: str) -> str:
        n = count_sentences(v)
        if n > 3:
            raise ValueError(
                f"answer is {n} sentences; the contract allows at most 3 "
                f"(source line 42). Trim in validate.py before constructing the "
                f"Answer (FR-16)."
            )
        return v

    @field_validator("source_url")
    @classmethod
    def _single_url(cls, v: str | None) -> str | None:
        if v is not None and re.search(r"\s", v.strip()):
            raise ValueError("exactly one source link is allowed per answer (FR-17)")
        return v

    @model_validator(mode="after")
    def _opinion_needs_link(self) -> Answer:
        if self.intent is Intent.OPINION:
            object.__setattr__(self, "educational_link_required", True)
            if self.educational_link is None and not self.educational_link_missing:
                raise ValueError(
                    "an opinion refusal must carry a verified educational link, or "
                    "declare educational_link_missing=True. It must never silently "
                    "omit one (FR-21, source line 36)."
                )
        return self

    @property
    def sentence_count(self) -> int:
        return count_sentences(self.text)
