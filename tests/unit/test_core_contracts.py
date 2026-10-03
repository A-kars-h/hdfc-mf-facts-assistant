"""Contract tests for the Phase 1 core.

These are not filler. Each one pins a decision that would be easy to undo by
accident in a later phase - the uncalibrated threshold, the dense/fused score
split, the 3-sentence cap, the empty education-link map. If a later phase breaks
one of these, that is the test earning its keep.
"""

from __future__ import annotations

import pytest

from src.ragbot.core import config as cfg
from src.ragbot.core.errors import CorpusConfigError, NotCalibratedError
from src.ragbot.core.models import (
    Answer,
    Chunk,
    GateDecision,
    Intent,
    PageManifest,
    RetrievedChunk,
    count_sentences,
)


@pytest.fixture(autouse=True)
def _clean_settings_cache():
    cfg.reset_settings_cache()
    yield
    cfg.reset_settings_cache()


# --- config -------------------------------------------------------------


def test_settings_load_with_committed_env_example(monkeypatch):
    """The committed .env.example must be parseable - it is the peer's template.

    This reads `.env.example` EXPLICITLY, and must keep doing so. It previously
    called `Settings()` with no arguments, which resolves `env_file=".env"` - the
    developer's local, gitignored file. So the test never checked the committed
    template it names, and instead asserted on whatever the local machine
    happened to be configured for: correctly setting `LLM_PROVIDER=openai` in a
    real `.env` failed a test whose entire claim is that the DEFAULT is no-LLM.

    Two details make it deterministic rather than merely pointed at the right
    file. `env_file` is resolved against `PROJECT_ROOT` so the test does not
    depend on pytest's rootdir. And pydantic-settings ranks real environment
    variables ABOVE the dotenv file, so a peer who exports `LLM_PROVIDER` in
    their shell would shadow the template and fail here again. Clearing the
    fields by name defeats that without asserting anything about their values.
    """
    for field in cfg.Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)

    template = cfg.PROJECT_ROOT / ".env.example"
    assert template.is_file(), f"{template} is the peer's template; it must be committed"

    cfg.reset_settings_cache()
    s = cfg.Settings(_env_file=template)
    assert s.chunk_size == 200
    assert s.chunk_overlap == 40
    assert s.top_k == 5
    assert s.rrf_k == 60
    assert s.max_answer_sentences == 3
    assert s.embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
    assert s.llm_provider == "none", "default must be no-LLM, not a guessed provider"


def test_similarity_threshold_has_no_default():
    """Invariant 13: a guessed threshold silently breaks refusal correctness."""
    s = cfg.Settings(
        _env_file=None,
        similarity_threshold=None,
        # Phase 6 committed artifacts/calibration.json; this test pins the
        # PRE-calibration contract, so the file fallback must not satisfy it.
        calibration_path="artifacts/__no_calibration__.json",
    )
    assert s.similarity_threshold is None
    with pytest.raises(NotCalibratedError):
        s.require_similarity_threshold()


def test_require_threshold_returns_calibrated_value():
    s = cfg.Settings(_env_file=None, similarity_threshold=0.42)
    assert s.require_similarity_threshold() == pytest.approx(0.42)


def test_manifest_and_education_paths_are_absolute():
    s = cfg.Settings(_env_file=None)
    for p in (s.corpus_file, s.manifest_file, s.education_links_file, s.chroma_dir):
        assert p.is_absolute(), f"{p} must resolve against the project root"


def test_corpus_yaml_is_valid_and_has_five_pages():
    data = cfg.load_corpus()
    assert data["amc"] == "HDFC Asset Management"
    assert len(data["pages"]) == 5, "Phase 0: a partial corpus is not a corpus"
    assert cfg.corpus_page_ids() == [
        "hdfc-large-cap",
        "hdfc-equity",
        "hdfc-elss",
        "hdfc-small-cap",
        "hdfc-balanced",
    ]


def test_all_corpus_plans_are_direct_growth():
    """Source lines 25-31: only Direct Growth, exactly these 5 schemes."""
    data = cfg.load_corpus()
    for page in data["pages"]:
        assert "direct" in page["scheme"].lower(), page["scheme"]
        assert "growth" in page["scheme"].lower(), page["scheme"]


def test_corpus_duplicate_page_id_is_rejected(tmp_path):
    bad = tmp_path / "corpus.yaml"
    bad.write_text(
        "amc: X\npages:\n"
        "  - {page_id: a, scheme: A Direct Growth, category: x, "
        "source_url: 'https://groww.in/a'}\n"
        "  - {page_id: a, scheme: B Direct Growth, category: x, "
        "source_url: 'https://groww.in/b'}\n",
        encoding="utf-8",
    )
    s = cfg.Settings(_env_file=None, corpus_path=bad)
    with pytest.raises(CorpusConfigError, match="duplicate page_id"):
        cfg.load_corpus(s)


def test_corpus_missing_url_is_rejected(tmp_path):
    bad = tmp_path / "corpus.yaml"
    bad.write_text(
        "amc: X\npages:\n  - {page_id: a, scheme: A, category: x}\n", encoding="utf-8"
    )
    s = cfg.Settings(_env_file=None, corpus_path=bad)
    with pytest.raises(CorpusConfigError, match="missing 'source_url'"):
        cfg.load_corpus(s)


def test_corpus_min_extract_chars_drift_is_rejected(tmp_path):
    """Fetch and ingest must agree on what counts as a usable page (FR-2)."""
    drifted = tmp_path / "corpus.yaml"
    drifted.write_text(
        "amc: X\nmin_extract_chars: 4000\npages:\n"
        "  - {page_id: a, scheme: A Direct Growth, category: x, "
        "source_url: 'https://groww.in/a'}\n",
        encoding="utf-8",
    )
    s = cfg.Settings(_env_file=None, corpus_path=drifted, min_extract_chars=1500)
    with pytest.raises(CorpusConfigError, match="min_extract_chars disagrees"):
        cfg.load_corpus(s)


def test_corpus_source_url_lookup():
    url = cfg.corpus_source_url("hdfc-elss")
    assert url == (
        "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"
    )
    with pytest.raises(CorpusConfigError, match="unknown page_id"):
        cfg.corpus_source_url("hdfc-parag-parksh")


# --- education links (OD-2) --------------------------------------------


def test_education_link_map_ships_empty():
    """FR-21: the map is human-verified only. An LLM must never populate it."""
    assert cfg.load_education_links() == {}


def test_education_link_lookup_returns_none_when_empty():
    assert cfg.education_link_for("opinion") is None


def test_education_link_entry_requires_verification(tmp_path):
    """An unverified link is not a valid citation for a refusal."""
    bad = tmp_path / "links.yml"
    bad.write_text(
        "links:\n  opinion:\n    url: https://www.hdfcassetmanagement.com/x\n",
        encoding="utf-8",
    )
    s = cfg.Settings(_env_file=None, education_links_path=bad)
    with pytest.raises(CorpusConfigError, match="verified_by"):
        cfg.load_education_links(s)


def test_education_link_off_allowlist_is_refused(tmp_path):
    """Stops a hallucinated or lookalike domain reaching a refusal."""
    good = tmp_path / "links.yml"
    good.write_text(
        "links:\n  opinion:\n    url: https://total-not-hdfc.example.com/mf\n"
        "    verified_by: tester\n    verified_on: 2026-01-15\n",
        encoding="utf-8",
    )
    s = cfg.Settings(_env_file=None, education_links_path=good)
    assert cfg.education_link_for("opinion", s) is None


# --- models -------------------------------------------------------------


def test_count_sentences_handles_decimals_and_abbreviations():
    assert count_sentences("The expense ratio is 1.21%.") == 1
    assert count_sentences("Exit load is Nil. Minimum SIP is Rs. 500.") == 2
    assert count_sentences("") == 0


def test_chunk_rejects_multiple_urls():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _chunk(source_url="https://a.example.com https://b.example.com")


def test_chunk_requires_http_url():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _chunk(source_url="see groww dot in")


def test_retrieved_chunk_keeps_dense_score_and_fused_rank_separate():
    """Invariant 5: RRF rank is not a similarity, so it cannot be thresholded."""
    from datetime import datetime, timezone

    rc = RetrievedChunk(
        chunk=_chunk(),
        dense_score=0.41,
        fused_rank=1,
        sparse_score=12.7,
    )
    assert rc.dense_score == pytest.approx(0.41)
    assert rc.fused_rank == 1
    assert rc.sparse_score == pytest.approx(12.7)
    assert not hasattr(rc, "score"), "a fused `score` field invites thresholding it"
    assert rc.chunk.fetched_at <= datetime.now(timezone.utc)


def test_gate_decision_records_raw_dense_max_for_audit():
    g = GateDecision(
        found_answer=False, reason="below threshold", raw_dense_max=0.19,
        candidates_considered=5,
    )
    assert g.found_answer is False
    assert g.raw_dense_max == pytest.approx(0.19)


def test_page_manifest_round_trips():
    from datetime import datetime, timezone

    m = PageManifest(
        generated_at=datetime.now(timezone.utc),
        amc="HDFC Asset Management",
        embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        embedding_dim=384,
        chunk_size=200,
        chunk_overlap=40,
        totals={"chunks": 0, "pages": 5},
    )
    assert m.total_chunks == 0
    assert m.plan_variant == "Direct Growth"
    assert PageManifest.model_validate_json(m.model_dump_json()).amc == m.amc


# --- answer contract ----------------------------------------------------


def test_answer_rejects_four_sentences():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="at most 3"):
        Answer(
            intent=Intent.FACTUAL,
            text="One thing. Two thing. Three thing. Four thing.",
        )


def test_answer_accepts_three_sentences():
    a = Answer(
        intent=Intent.FACTUAL,
        text="The expense ratio is 0.77%. The minimum SIP is Rs. 100. "
        "The exit load is 1% if redeemed within 1 year.",
        source_url="https://www.groww.in/hdfc-equity-fund-direct-growth",
    )
    assert a.sentence_count == 3


def test_answer_refuses_advice_flag():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="advice is prohibited"):
        Answer(intent=Intent.FACTUAL, text="You should invest.", is_advice=True)


def test_answer_refuses_perf_claim_flag():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="must not state or compare returns"):
        Answer(intent=Intent.FACTUAL, text="It returns 14%.", perf_claim=True)


def test_opinion_refusal_must_carry_or_declare_a_link():
    """FR-21: no silent omission, and no invented URL."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="educational link"):
        Answer(intent=Intent.OPINION, text="I can't give investment advice.")


def test_opinion_refusal_may_declare_link_missing():
    a = Answer(
        intent=Intent.OPINION,
        text="I can't give investment advice. Read the factsheet to understand the scheme.",
        educational_link_missing=True,
        refused=True,
    )
    assert a.educational_link_required is True
    assert a.educational_link is None


def test_opinion_refusal_accepts_verified_link():
    a = Answer(
        intent=Intent.OPINION,
        text="I can't give investment advice. Here is an explainer.",
        educational_link="https://www.hdfcassetmanagement.com/faqs",
    )
    assert a.educational_link_required is True


def test_answer_rejects_two_source_urls():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="one source link"):
        Answer(
            intent=Intent.FACTUAL,
            text="The expense ratio is 0.77%.",
            source_url="https://groww.in/a https://groww.in/b",
        )


# --- helpers ------------------------------------------------------------


def _chunk(**overrides):
    from datetime import datetime, timezone

    base = dict(
        chunk_id="hdfc-equity::0001",
        page_id="hdfc-equity",
        scheme="HDFC Equity Fund Direct Growth",
        category="Equity",
        source_url="https://www.groww.in/hdfc-equity-fund-direct-growth",
        fetched_at=datetime(2026, 9, 25, tzinfo=timezone.utc),
        text="Expense ratio 0.77%",
        token_count=6,
        content_hash="deadbeef",
    )
    base.update(overrides)
    return Chunk(**base)
