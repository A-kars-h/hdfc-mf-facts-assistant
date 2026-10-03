"""Configuration. One object, validated once, imported everywhere.

Design rule: **no guessed defaults for anything that affects correctness.**
Concretely, `SIMILARITY_THRESHOLD` has no default value and is read through
`require_similarity_threshold()`, which raises `NotCalibratedError` until
calibration has produced one. A default written before seeing the corpus would
be an invented number, and a wrong refusal threshold is the single most
invisible failure in this project: it does not crash, it just starts answering
"not in the data" to questions the corpus answers perfectly.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import CorpusConfigError, NotCalibratedError

# src/ragbot/core/config.py -> parents[3] is the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

VALID_PROVIDERS = ("openai", "anthropic", "ollama", "none")


def _p(value: str | Path) -> Path:
    """Resolve a config path against the project root."""
    p = Path(value)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


class Settings(BaseSettings):
    """Runtime configuration, read from the environment and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- paths ---
    corpus_path: Path = Path("config/corpus.yaml")
    raw_dir: Path = Path("data/raw")
    chroma_path: Path = Path("data/chroma")
    bm25_path: Path = Path("data/bm25.pkl")
    manifest_path: Path = Path("artifacts/manifest.json")
    education_links_path: Path = Path("config/education_links.yml")
    calibration_path: Path = Path("artifacts/calibration.json")

    # --- model (source line 20: all-MiniLM-L6-v2 is mandated) ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    llm_provider: Literal["openai", "anthropic", "ollama", "none"] = "none"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str | None = None
    llm_base_url: str | None = None

    # --- chunking (architecture §3.2) ---
    # These are architecturally fixed, not tunable-by-feel. Changing them
    # invalidates the index and the manifest.
    chunk_size: int = 200
    chunk_overlap: int = 40
    chunk_scheme: Literal["block", "label", "sentence", "auto"] = "auto"

    # --- retrieval (architecture §5) ---
    top_k: int = 5
    rrf_k: int = 60
    bm25_top_n: int = 20
    use_hybrid: bool = True

    # The calibrated gate threshold. NO DEFAULT, on purpose - see module docstring.
    similarity_threshold: float | None = Field(
        default=None,
        description="Raw cosine-similarity floor for `found_answer`. Must be "
        "produced by eval.calibrate; never hand-set.",
    )

    # --- generation / validation ---
    max_answer_sentences: int = 3
    max_evidence_chars: int = 6000

    # --- retrieval hygiene ---
    min_chunk_tokens: int = 12
    # Return/NAV figures are ~17% of the corpus and the assistant must not
    # report them (source line 41). Chunks are TAGGED `return_heavy` at ingest
    # so Phase 3 can deprioritise them at retrieval. This flag additionally
    # DROPS them from the index, and defaults to False on purpose: dropping
    # deletes real page content irreversibly, and it is not needed for
    # correctness because the output screen is the actual control. Enable it
    # only to A/B the retrieval effect.
    drop_return_only_chunks: bool = False

    # Multiplier applied to a return-heavy chunk's RRF score, so return/NAV
    # tables rank below fee and minimum facts. Ordering ONLY - it cannot affect
    # whether an answer is given, because the gate reads raw dense cosine and
    # never a fused score. 1.0 disables the nudge.
    return_heavy_penalty: float = 0.85

    # --- ingestion ---
    min_extract_chars: int = 1500
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    max_retries: int = 2

    # --- safety ---
    block_pii: bool = True
    dry_run_pii: bool = False

    @field_validator("chunk_size")
    @classmethod
    def _chunk_size_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("CHUNK_SIZE must be positive")
        return v

    @field_validator("chunk_overlap")
    @classmethod
    def _overlap_sane(cls, v: int) -> int:
        if v < 0:
            raise ValueError("CHUNK_OVERLAP must be >= 0")
        return v

    @field_validator("chunk_scheme")
    @classmethod
    def _scheme_known(cls, v: str) -> str:
        return v

    @field_validator("llm_provider", mode="before")
    @classmethod
    def _provider_normalised(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip().lower()
            if v not in VALID_PROVIDERS:
                raise ValueError(
                    f"LLM_PROVIDER must be one of {VALID_PROVIDERS}, got {v!r}. "
                    f"Use 'none' to run retrieval-only with no generation."
                )
        return v

    # --- resolved paths ---

    @property
    def corpus_file(self) -> Path:
        return _p(self.corpus_path)

    @property
    def raw_dir_abs(self) -> Path:
        return _p(self.raw_dir)

    @property
    def chroma_dir(self) -> Path:
        return _p(self.chroma_path)

    @property
    def bm25_file(self) -> Path:
        return _p(self.bm25_path)

    @property
    def manifest_file(self) -> Path:
        return _p(self.manifest_path)

    @property
    def education_links_file(self) -> Path:
        return _p(self.education_links_path)

    @property
    def calibration_file(self) -> Path:
        return _p(self.calibration_path)

    @property
    def has_llm(self) -> bool:
        return self.llm_provider != "none"

    # --- the calibration guard ---

    def require_similarity_threshold(self) -> float:
        """Return the calibrated threshold, or refuse to guess one.

        This is the only sanctioned way to read the gate threshold. Retrieval
        code must call this rather than touching `similarity_threshold` directly,
        so an uncalibrated run fails loudly at the gate instead of silently
        never answering or silently always answering.
        """
        if self.similarity_threshold is None:
            if self.calibration_file.exists():
                data = _read_yaml(self.calibration_file)
                value = data.get("similarity_threshold")
                if value is not None:
                    return float(value)
            raise NotCalibratedError()
        return float(self.similarity_threshold)

    def require_api_key(self) -> str:
        """Return the LLM key, or raise an actionable error (FR-15)."""
        from .errors import MissingAPIKeyError

        if not self.llm_api_key:
            raise MissingAPIKeyError()
        return self.llm_api_key

    def ensure_dirs(self) -> None:
        for d in (self.raw_dir_abs, self.chroma_dir, self.manifest_file.parent):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the cache. Tests mutate env vars between cases."""
    get_settings.cache_clear()


# --- corpus.yaml ---------------------------------------------------------


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise CorpusConfigError(
            f"{path} not found. It is committed to the repo; if you deleted it, "
            f"restore it with `git checkout config/corpus.yaml`."
        )
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CorpusConfigError(f"{path} is not valid YAML: {exc}") from exc


def load_corpus(settings: Settings | None = None) -> dict[str, Any]:
    """Load and validate config/corpus.yaml.

    Validation is strict on the fields Phase 2 needs to build provenance:
    without a unique `page_id` and an `http(s)` `url` per page, chunks cannot
    be cited compliantly and the run should stop before fetching anything.
    """
    settings = settings or get_settings()
    data = _read_yaml(settings.corpus_file)

    pages = data.get("pages")
    if not isinstance(pages, list) or not pages:
        raise CorpusConfigError(
            f"{settings.corpus_file} defines no 'pages'. Phase 0 established "
            f"that all 5 pages are required - a partial corpus silently drops an "
            f"entire scheme."
        )

    seen: set[str] = set()
    for i, page in enumerate(pages):
        where = f"pages[{i}]"
        if not isinstance(page, dict):
            raise CorpusConfigError(f"{where} is not a mapping")
        # `source_url` matches the key on Chunk and the name the answer cites.
        for key in ("page_id", "scheme", "category", "source_url"):
            if not page.get(key):
                raise CorpusConfigError(f"{where} is missing '{key}'")
        pid = str(page["page_id"])
        if pid in seen:
            raise CorpusConfigError(
                f"duplicate page_id '{pid}'. page_id is the primary key of the "
                f"index and the manifest."
            )
        seen.add(pid)
        url = str(page["source_url"])
        if not url.startswith(("http://", "https://")):
            raise CorpusConfigError(
                f"{where}.source_url must be http(s) so the answer can cite it, "
                f"got {url!r}"
            )

    # corpus.yaml and Settings both carry min_extract_chars. If they drift, the
    # fetcher and the ingester disagree about what counts as a usable page, and
    # a page rejected at ingest is only discovered after it was already indexed.
    declared = data.get("min_extract_chars")
    if declared is not None and int(declared) != int(settings.min_extract_chars):
        raise CorpusConfigError(
            f"min_extract_chars disagrees: {settings.corpus_file} says "
            f"{declared}, Settings.MIN_EXTRACT_CHARS says {settings.min_extract_chars}. "
            f"Set it in one place, not both."
        )
    return data


def corpus_page_ids(settings: Settings | None = None) -> list[str]:
    return [str(p["page_id"]) for p in load_corpus(settings)["pages"]]


def corpus_source_url(page_id: str, settings: Settings | None = None) -> str:
    """Look up a page's source URL. Phase 2 uses this to build chunk provenance."""
    for page in load_corpus(settings)["pages"]:
        if str(page["page_id"]) == page_id:
            return str(page["source_url"])
    raise CorpusConfigError(
        f"unknown page_id {page_id!r}. Known: {', '.join(corpus_page_ids(settings))}"
    )


# --- education_links.yml ------------------------------------------------

# Opinion refusals must offer a real article (source line 36). These are the
# domains acceptable to point at. A link outside this list is a red flag - the
# map is meant to contain only links a human opened and checked.
EDUCATION_LINK_DOMAINS = (
    "hdfcassetmanagement.com",
    "amc.hdfc.com",
    "sebi.gov.in",
    "investor.gov.in",
    "rbi.org.in",
)


def load_education_links(settings: Settings | None = None) -> dict[str, dict[str, Any]]:
    """Load the human-verified education link map.

    Ships EMPTY by design (FR-21). It must never be populated by an LLM. Until
    a human fills it in, every opinion refusal reports
    `educational_link_missing=True`, which is an honest, testable state - and
    which is what makes the M-3 test meaningful rather than vacuously passing.
    """
    settings = settings or get_settings()
    path = settings.education_links_file
    if not path.exists():
        return {}
    data = _read_yaml(path)
    links = data.get("links") or {}
    if not isinstance(links, dict):
        raise CorpusConfigError(f"{path}: 'links' must be a mapping")

    for key, entry in links.items():
        if not isinstance(entry, dict) or not entry.get("url"):
            raise CorpusConfigError(
                f"{path}: links.{key} needs a 'url'. Refusals must never generate "
                f"a URL - the map is the only source (FR-21)."
            )
        if not entry.get("verified_by") or not entry.get("verified_on"):
            raise CorpusConfigError(
                f"{path}: links.{key} is missing 'verified_by'/'verified_on'. An "
                f"unverified link is not a valid citation for a refusal."
            )
    return links


def education_link_for(intent: str, settings: Settings | None = None) -> str | None:
    """Look up a verified link. Returns None when the map has no entry."""
    links = load_education_links(settings)
    entry = links.get(intent) or links.get("default")
    if not entry:
        return None
    url = str(entry.get("url", ""))
    from urllib.parse import urlparse

    host = urlparse(url).hostname or ""
    allowed = EDUCATION_LINK_DOMAINS
    if not any(host == d or host.endswith("." + d) for d in allowed):
        return None
    return url


def env_summary() -> dict[str, str]:
    """Safe view of configuration for startup logging. Never log secrets."""
    s = get_settings()
    return {
        "embedding_model": s.embedding_model,
        "llm_provider": s.llm_provider,
        "llm_model": s.llm_model if s.has_llm else "<disabled>",
        "llm_api_key": "<set>" if s.llm_api_key else "<unset>",
        "chunk_size": str(s.chunk_size),
        "chunk_overlap": str(s.chunk_overlap),
        "chunk_scheme": s.chunk_scheme,
        "top_k": str(s.top_k),
        "rrf_k": str(s.rrf_k),
        "use_hybrid": str(s.use_hybrid),
        "similarity_threshold": (
            f"{s.similarity_threshold}" if s.similarity_threshold is not None
            else "<UNCALIBRATED - gate will raise>"
        ),
        "min_extract_chars": str(s.min_extract_chars),
        "block_pii": str(s.block_pii),
        "raw_dir": str(s.raw_dir_abs),
        "chroma_path": str(s.chroma_dir),
        "python": f"{os.sys.version_info.major}.{os.sys.version_info.minor}",
    }
