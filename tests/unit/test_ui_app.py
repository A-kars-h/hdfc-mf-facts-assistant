"""The Streamlit UI is a presentation layer, and this file is what holds it to that.

Every other module in this project has tests, and the UI had none - 291 lines
that render financial answers, and the one module in the codebase whose bugs
would be seen by a grader rather than asserted by CI. Worse, `main()` ran at
import, so the module could not even be imported without rendering the whole
app, which is why there were no tests. The `__main__` guard that fixed that is
covered by `test_importing_the_module_does_not_render_the_app`.

The tests are in two groups.

**Rendering**, driven through Streamlit's own `AppTest`, which executes the
real script the way `streamlit run` does. These assert what a person would see:
the welcome line, the three starters, the persistent disclaimer, one source
link, the date, the chunk inspector.

**The presentation-only invariant**, asserted statically against the module's
AST, because it is the property that cannot be observed from the outside: that
no product rule lives in this file. A rule that lives only in the UI does not
exist for the CLI, the eval harness or the tests, and it silently diverges the
moment the demo and the report are compared - the exact Phase 7 pitfall.

The orchestrator is replaced with a hand-written double rather than mocked, and
it is injected at `generation.pipeline.Ragbot` rather than at
`ui.app.Ragbot`. `AppTest` re-executes the script on every run, which rebinds
`ui.app.Ragbot` from the import statement; patching the name in the module
under test would be undone by the next rerun. Patching the class in the module
the script imports it from survives, because `from X import Y` re-reads the
current attribute. That also means no 90 MB embedding model is loaded here.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src.ragbot.core.models import Answer, Chunk, Intent, RetrievedChunk
from src.ragbot.ui import app as ui

APP_PATH = Path(ui.__file__).resolve()
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_TOML = REPO_ROOT / ".streamlit" / "config.toml"
SAMPLE_SET = REPO_ROOT / "src" / "ragbot" / "eval" / "sample_set.jsonl"

ELSS_URL = "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"
LARGE_CAP_URL = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
FETCHED_AT = dt.datetime(2026, 9, 27, 8, 20, tzinfo=dt.timezone.utc)

LINK_RE = re.compile(r"\]\(\s*(https?://[^\s)]+)\s*\)")


# --- doubles --------------------------------------------------------------


def _chunk(rank: int, text: str = "CHUNK BODY") -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(
            chunk_id=f"chunk-{rank}",
            page_id="hdfc-elss",
            scheme="HDFC ELSS Tax Saver Fund - Direct Plan - Growth",
            category="ELSS",
            source_url=ELSS_URL,
            fetched_at=FETCHED_AT,
            text=f"{text} {rank}",
            token_count=12,
            content_hash=f"hash-{rank}",
            section="Exit load",
        ),
        dense_score=0.9 - rank / 100,
        fused_rank=rank,
        sparse_score=18.0 - rank,
    )


def _answered(*, chunks: int = 2) -> Answer:
    return Answer(
        intent=Intent.FACTUAL,
        text="The minimum SIP amount is Rs. 500.",
        source_url=ELSS_URL,
        source_title="HDFC ELSS Tax Saver Fund - Direct Plan - Growth",
        last_updated=FETCHED_AT,
        retrieved_chunk_ids=[f"chunk-{i}" for i in range(1, chunks + 1)],
    )


def _opinion_refusal(*, link: str | None, missing: bool) -> Answer:
    return Answer(
        intent=Intent.OPINION,
        text="I answer with verified facts rather than with a view.",
        educational_link=link,
        educational_link_missing=missing,
        refused=True,
    )


def _out_of_scope_refusal() -> Answer:
    return Answer(
        intent=Intent.OUT_OF_SCOPE,
        text="That is outside what I can answer.",
        refused=True,
    )


def _corpus_sources_answer() -> Answer:
    return Answer(
        intent=Intent.CORPUS_SOURCES,
        text="I cover five HDFC mutual fund pages.",
    )


class _FakeRagbot:
    """Stands in for the orchestrator. Records what the UI asked it.

    Deliberately exposes only `ask_with_evidence`. The UI cannot reach anything
    else because there is nothing else to reach - which is the property the
    static tests below pin independently, in case someone widens this class.
    """

    def __init__(self, settings: Any = None) -> None:
        self.questions: list[str] = []
        self.answer: Answer | None = None
        self.chunks: list[RetrievedChunk] = []
        self.error: Exception | None = None

    def ask_with_evidence(
        self, question: str
    ) -> tuple[Answer, list[RetrievedChunk]]:
        self.questions.append(question)
        if self.error is not None:
            raise self.error
        assert self.answer is not None
        return self.answer, list(self.chunks)


@pytest.fixture
def bot(monkeypatch: pytest.MonkeyPatch) -> _FakeRagbot:
    """Install a fake orchestrator and reset Streamlit's resource cache.

    `cache_resource` is process-wide, so without the clear a cached real
    `Ragbot` from an earlier test would be served here and load the embedding
    model - or, worse, quietly answer from the real index.
    """
    import src.ragbot.generation.pipeline as pipeline

    fake = _FakeRagbot()
    monkeypatch.setattr(pipeline, "Ragbot", lambda settings=None: fake)
    st.cache_resource.clear()
    yield fake
    st.cache_resource.clear()


def _app() -> AppTest:
    return AppTest.from_file(str(APP_PATH), default_timeout=30)


def _markdown(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown]


def _captions(at: AppTest) -> list[str]:
    return [c.value for c in at.caption]


def _all_text(at: AppTest) -> str:
    parts: list[str] = list(_markdown(at))
    parts += _captions(at)
    parts += [i.value for i in at.info]
    parts += [e.value for e in at.error]
    parts += [l.label for l in at.button]
    parts += [e.label for e in at.expander]
    # `st.text` is its own element type, and it is where the inspector shows the
    # chunk body - the one thing worth showing.
    parts += [t.value for t in at.text]
    return "\n".join(parts)


def _links(at: AppTest) -> list[str]:
    return [url for text in _markdown(at) for url in LINK_RE.findall(text)]


# --- the module is importable without rendering ---------------------------


def test_importing_the_module_does_not_render_the_app() -> None:
    """`main()` used to run at import, so no test could import this module.

    The property is checked in a subprocess with Streamlit's display functions
    replaced by recorders: if any of them fires during the import, the module
    still renders on import and this test fails.
    """
    probe = """
import sys
import streamlit as st

calls = []
for name in ("title", "caption", "info", "markdown", "button", "chat_input",
             "chat_message", "container", "expander", "divider", "set_page_config"):
    setattr(st, name, (lambda n: lambda *a, **k: calls.append(n))(name))

sys.path.insert(0, r"{root}")
import src.ragbot.ui.app  # noqa: F401

print("RENDER_CALLS=" + ",".join(calls))
""".format(root=REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    assert "RENDER_CALLS=\n" in result.stdout, result.stdout


def test_the_entrypoint_is_guarded_so_streamlit_run_still_renders() -> None:
    """The guard must not disable the app under a real launch.

    Streamlit builds the main script as a module named `__main__` in both real
    launches and `AppTest` (`ScriptRunner._run_script`), so a `__main__` guard
    holds in both. If a future Streamlit ever changed that, the app would render
    nothing and still look healthy, so it is asserted rather than assumed.
    """
    source = APP_PATH.read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in source
    at = _app()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title, "the app rendered no title"


# --- welcome, starters, disclaimer ----------------------------------------


def test_welcome_line_is_visible_before_any_question_is_asked() -> None:
    at = _app()
    at.run()
    assert not at.exception
    assert ui.WELCOME in _captions(at)


def test_there_are_exactly_three_clickable_example_questions() -> None:
    at = _app()
    at.run()
    assert len(ui.EXAMPLE_QUESTIONS) == 3
    assert [b.label for b in at.button] == list(ui.EXAMPLE_QUESTIONS)


def test_the_starters_are_the_questions_the_eval_actually_scored() -> None:
    """The starters are Q3, Q6 and Q8 of the golden set, not invented strings.

    This is what stops the demo and the eval report from describing different
    systems: the same three questions are asked by the screen, by the harness
    and by the calibration sweep, so a divergence shows up as a failing number
    rather than as a flattering screenshot.
    """
    rows = [
        json.loads(line)
        for line in SAMPLE_SET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_id = {row["id"]: row["question"] for row in rows}
    assert set(ui.EXAMPLE_QUESTIONS) == {by_id["Q3"], by_id["Q6"], by_id["Q8"]}


def test_the_starters_cover_all_three_answer_shapes() -> None:
    """One click each must reach an answer, an advice refusal and an
    out-of-corpus refusal - the three states the app has to be able to show."""
    golden = {
        row["id"]: row
        for row in (
            json.loads(line)
            for line in SAMPLE_SET.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    starters = set(ui.EXAMPLE_QUESTIONS)
    assert golden["Q3"]["question"] in starters
    assert golden["Q6"]["question"] in starters
    assert golden["Q8"]["question"] in starters
    assert golden["Q3"]["answerable"] is True
    assert golden["Q6"]["intent"] == "opinion"
    assert golden["Q8"]["answerable"] is False


def test_the_disclaimer_is_the_exact_string_the_source_requires() -> None:
    assert ui.DISCLAIMER == "Facts-only. No investment advice."


def test_the_disclaimer_is_persistent_and_not_scrolled_away() -> None:
    """Present before any question, and still present after a conversation.

    A disclaimer shown once at the top is not a persistent note. The product
    claim is that no advice is given, and the reader has to be able to see that
    at a glance next to the answers.
    """
    at = _app()
    at.run()
    assert ui.DISCLAIMER in [i.value for i in at.info]
    assert ui.DISCLAIMER not in _markdown(at), "the disclaimer must be its own element"


def test_the_disclaimer_survives_a_conversation(bot: _FakeRagbot) -> None:
    bot.answer = _answered()
    bot.chunks = [_chunk(1)]
    at = _app()
    at.run()
    at.button[0].click().run()
    assert ui.DISCLAIMER in [i.value for i in at.info]
    assert "The minimum SIP amount is Rs. 500." in _markdown(at)


# --- the answer card ------------------------------------------------------


def test_the_answer_card_shows_the_answer_text(bot: _FakeRagbot) -> None:
    bot.answer = _answered()
    bot.chunks = [_chunk(1)]
    at = _app()
    at.run()
    at.button[0].click().run()
    assert "The minimum SIP amount is Rs. 500." in _markdown(at)
    assert not at.exception


def test_an_answer_has_exactly_one_clickable_source_link(bot: _FakeRagbot) -> None:
    bot.answer = _answered()
    bot.chunks = [_chunk(1)]
    at = _app()
    at.run()
    at.button[0].click().run()
    assert _links(at) == [ELSS_URL]


def test_each_answered_turn_carries_exactly_one_link(bot: _FakeRagbot) -> None:
    """One per answer, not one per conversation and not one per rendered line."""
    bot.answer = _answered()
    bot.chunks = [_chunk(1)]
    at = _app()
    at.run()
    at.button[0].click().run()
    at.button[0].click().run()
    at.button[0].click().run()
    assert _links(at) == [ELSS_URL] * 3


def test_the_source_link_is_the_url_from_provenance_not_one_in_the_text(
    bot: _FakeRagbot,
) -> None:
    """A URL inside the answer prose is not the citation.

    Invariant 8: model-emitted URLs are stripped, and the citation is resolved
    from chunk provenance. If the UI linked whatever URL appeared in the text,
    a hallucinated link would be one click away. The answer here deliberately
    contains a plausible-looking URL that differs from the real provenance URL.
    """
    bot.answer = Answer(
        intent=Intent.FACTUAL,
        text="The minimum SIP is Rs. 500, see https://example.com/fake for detail.",
        source_url=ELSS_URL,
        source_title="HDFC ELSS",
        last_updated=FETCHED_AT,
    )
    bot.chunks = [_chunk(1)]
    at = _app()
    at.run()
    at.button[0].click().run()
    assert _links(at) == [ELSS_URL]


def test_the_last_updated_line_names_the_date_from_provenance(
    bot: _FakeRagbot,
) -> None:
    bot.answer = _answered()
    bot.chunks = [_chunk(1)]
    at = _app()
    at.run()
    at.button[0].click().run()
    assert "Last updated from sources: 2026-09-27" in _captions(at)


def test_an_answer_without_a_freshness_date_says_nothing_rather_than_guessing(
    bot: _FakeRagbot,
) -> None:
    """No date means no date line. Inventing one is the same failure as
    inventing a URL, and 'last updated' is a factual claim about a snapshot."""
    bot.answer = Answer(
        intent=Intent.FACTUAL,
        text="The minimum SIP amount is Rs. 500.",
        source_url=ELSS_URL,
    )
    bot.chunks = [_chunk(1)]
    at = _app()
    at.run()
    at.button[0].click().run()
    assert not any("Last updated" in c for c in _captions(at))
    assert not any("Last updated" in t for t in _markdown(at))


# --- refusals -------------------------------------------------------------


def test_an_opinion_refusal_renders_its_educational_link(
    bot: _FakeRagbot,
) -> None:
    """The link is rendered because the orchestrator supplied one."""
    verified = "https://www.hdfcassetmanagement.com/funds"
    bot.answer = _opinion_refusal(link=verified, missing=False)
    bot.chunks = []
    at = _app()
    at.run()
    at.button[1].click().run()
    assert verified in _links(at)


def test_an_opinion_refusal_with_no_verified_link_says_so_and_invents_nothing(
    bot: _FakeRagbot,
) -> None:
    """The map ships empty, so this is the state a real opinion refusal is in.

    The requirement is that the refusal carries the link. What matters is that
    the UI renders the link when there is one, and that when there is not it
    says so rather than substituting a plausible URL - invariant 10, and the
    reason `educational_link_missing` exists at all.
    """
    bot.answer = _opinion_refusal(link=None, missing=True)
    bot.chunks = []
    at = _app()
    at.run()
    at.button[1].click().run()
    assert any("No verified" in c for c in _captions(at))
    assert "http" not in _all_text(at)
    assert _links(at) == []


def test_a_refusal_carries_no_source_link_and_says_why(bot: _FakeRagbot) -> None:
    bot.answer = _out_of_scope_refusal()
    bot.chunks = []
    at = _app()
    at.run()
    at.button[2].click().run()
    assert _links(at) == []
    assert any("No source cited" in c for c in _captions(at))


def test_a_refusal_does_not_expose_the_chunk_inspector(bot: _FakeRagbot) -> None:
    """A user who sees the score learns the bar and can aim at it.

    `educational.py` is explicit that a refusal must not reveal a score, a
    rank, a threshold or chunk text. The inspector is the only place this UI
    shows those, so it is withheld from refusals - even when the orchestrator
    hands back candidates.
    """
    bot.answer = _out_of_scope_refusal()
    bot.chunks = [_chunk(1), _chunk(2)]
    at = _app()
    at.run()
    at.button[2].click().run()
    assert at.expander == []
    text = _all_text(at).lower()
    for leak in ("raw dense", "fused rank", "bm25", "chunk body", "0.8900"):
        assert leak not in text, f"refusal leaked {leak!r}"


def test_a_refusal_does_not_claim_to_have_retrieved_anything(
    bot: _FakeRagbot,
) -> None:
    bot.answer = _out_of_scope_refusal()
    bot.chunks = []
    at = _app()
    at.run()
    at.button[2].click().run()
    text = _all_text(at)
    assert "sent to the model" not in text


def test_the_threshold_value_is_never_shown(bot: _FakeRagbot) -> None:
    """0.7562 on screen is the retrieval boundary, stated exactly."""
    bot.answer = _answered()
    bot.chunks = [_chunk(1)]
    at = _app()
    at.run()
    at.button[0].click().run()
    assert "0.7562" not in _all_text(at)


# --- chunk inspector ------------------------------------------------------


def test_the_chunk_inspector_reveals_the_chunks_sent_to_the_model(
    bot: _FakeRagbot,
) -> None:
    bot.answer = _answered(chunks=2)
    bot.chunks = [_chunk(1), _chunk(2)]
    at = _app()
    at.run()
    at.button[0].click().run()
    assert [e.label for e in at.expander] == [
        "Show retrieved chunks (2 sent to the model)"
    ]
    text = _all_text(at)
    assert "chunk-1" in text and "chunk-2" in text
    assert "CHUNK BODY" in text


def test_the_inspector_shows_the_raw_dense_score_the_gate_actually_reads(
    bot: _FakeRagbot,
) -> None:
    """`dense_score` is the raw pre-fusion cosine; `fused_rank` is ordering only.

    Both are on screen because a demo that cannot show which number the gate
    read is asking to be trusted. The distinction is the reason the two are
    separate fields, so the UI is not allowed to blur them either.
    """
    bot.answer = _answered(chunks=1)
    bot.chunks = [_chunk(1)]
    at = _app()
    at.run()
    at.button[0].click().run()
    text = _all_text(at)
    assert "raw dense 0.8900" in text
    assert "fused rank 1" in text


def test_the_inspector_does_not_add_a_second_source_link(bot: _FakeRagbot) -> None:
    """Chunk provenance carries a URL too, and the inspector shows ids and
    page names - not links. A second link would break the one-link contract."""
    bot.answer = _answered(chunks=2)
    bot.chunks = [_chunk(1), _chunk(2)]
    at = _app()
    at.run()
    at.button[0].click().run()
    assert _links(at) == [ELSS_URL]


def test_an_answer_with_no_chunks_says_so_rather_than_showing_an_empty_box(
    bot: _FakeRagbot,
) -> None:
    bot.answer = _corpus_sources_answer()
    bot.chunks = []
    at = _app()
    at.run()
    at.button[0].click().run()
    assert at.expander == []
    assert any("no model was called" in c.lower() for c in _captions(at))


# --- input and session ----------------------------------------------------


def test_typed_questions_reach_the_orchestrator(bot: _FakeRagbot) -> None:
    bot.answer = _answered()
    bot.chunks = [_chunk(1)]
    at = _app()
    at.run()
    at.chat_input[0].set_value("What is the exit load on HDFC Small Cap Fund?").run()
    assert bot.questions == ["What is the exit load on HDFC Small Cap Fund?"]
    assert "The minimum SIP amount is Rs. 500." in _markdown(at)


def test_a_whitespace_only_question_is_not_asked(bot: _FakeRagbot) -> None:
    at = _app()
    at.run()
    at.chat_input[0].set_value("   ").run()
    assert bot.questions == []


def test_a_clicked_starter_asks_exactly_the_question_on_the_button(
    bot: _FakeRagbot,
) -> None:
    bot.answer = _answered()
    bot.chunks = [_chunk(1)]
    at = _app()
    at.run()
    at.button[1].click().run()
    assert bot.questions == [ui.EXAMPLE_QUESTIONS[1]]


def test_the_clear_button_empties_the_transcript(bot: _FakeRagbot) -> None:
    bot.answer = _answered()
    bot.chunks = [_chunk(1)]
    at = _app()
    at.run()
    at.button[0].click().run()
    assert at.button[-1].label == "Clear conversation"
    at.button[-1].click().run()
    assert "The minimum SIP amount is Rs. 500." not in _markdown(at)
    assert at.button[-1].label != "Clear conversation"


def test_nothing_persists_across_a_restart(bot: _FakeRagbot) -> None:
    """A fresh app is a fresh process, and the transcript starts empty.

    Streamlit has no server-side session here: state lives in
    `st.session_state`, which dies with the session. A conversation surviving a
    restart would mean it had been written somewhere.
    """
    bot.answer = _answered()
    bot.chunks = [_chunk(1)]
    first = _app()
    first.run()
    first.button[0].click().run()
    assert "The minimum SIP amount is Rs. 500." in _markdown(first)

    second = _app()
    second.run()
    assert "The minimum SIP amount is Rs. 500." not in _markdown(second)
    assert second.button[-1].label != "Clear conversation"


def test_a_product_error_is_shown_as_a_readable_message_not_a_stack_trace(
    bot: _FakeRagbot,
) -> None:
    """FR-15: a missing key is a sentence, not a traceback.

    Showing the message is presentation. Interpreting it, or retrying, would be
    this module deciding a product rule.
    """
    from src.ragbot.core.errors import MissingAPIKeyError

    bot.error = MissingAPIKeyError()
    at = _app()
    at.run()
    at.button[0].click().run()
    assert not at.exception
    assert len(at.error) == 1
    assert "Traceback" not in at.error[0].value
    assert "could not answer" in at.error[0].value


# --- the presentation-only invariant --------------------------------------


def _parsed_app() -> ast.Module:
    return ast.parse(APP_PATH.read_text(encoding="utf-8"))


def _imported_modules() -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_parsed_app()):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_the_ui_imports_no_retrieval_module() -> None:
    """Retrieval is the product's, not the screen's.

    If the UI imported a searcher it could rank differently from the
    orchestrator, and the demo would show evidence the answer was not written
    from.
    """
    assert not [m for m in _imported_modules() if ".retrieval" in m or m.endswith("retrieval")]


def test_the_ui_calls_only_the_orchestrator() -> None:
    """One product seam, and it is the orchestrator.

    Not the LLM client, not the validator, not the PII scanner, not the
    threshold. Each of those is a rule this module must not hold a copy of.
    """
    modules = _imported_modules()
    for forbidden in (
        "src.ragbot.generation.llm",
        "src.ragbot.generation.validate",
        "src.ragbot.generation.educational",
        "src.ragbot.generation.prompts",
        "src.ragbot.safety.pii",
        "src.ragbot.ingest",
    ):
        assert forbidden not in modules, f"the UI imported {forbidden}"


def test_the_ui_never_streams_an_unvalidated_draft() -> None:
    """The Phase 4 pitfall, checked structurally.

    `stream_draft()` yields text that is unvalidated by construction: it can
    contain advice, a return figure or an invented URL. Rendering it would
    display a prohibited answer for as long as it takes to read it. So the
    method must not be reachable from this file at all.
    """
    for node in ast.walk(_parsed_app()):
        if isinstance(node, ast.Attribute):
            assert node.attr != "stream_draft"
        elif isinstance(node, ast.Name):
            assert node.id != "stream_draft"


def test_the_ui_does_not_read_the_gate_threshold() -> None:
    """The calibrated threshold is the gate's, and it is not a display value."""
    for node in ast.walk(_parsed_app()):
        if isinstance(node, ast.Attribute):
            assert node.attr not in (
                "similarity_threshold",
                "require_similarity_threshold",
            )
        elif isinstance(node, ast.Name):
            assert node.id not in (
                "similarity_threshold",
                "require_similarity_threshold",
            )


def test_the_ui_does_not_scan_or_rewrite_the_question() -> None:
    """PII scanning runs once, in the pipeline, before anything else.

    A second scan here would be a second place to get it wrong, and a
    redaction done for display would be a refusal decision made in the
    presentation layer.
    """
    for node in ast.walk(_parsed_app()):
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("scan", "redact", "redacted")
        elif isinstance(node, ast.Name):
            assert node.id not in ("scan", "redact", "PIIResult")


def test_the_ui_makes_exactly_one_product_call() -> None:
    """`ask_with_evidence` is the whole of the product surface used here."""
    names = [
        node.attr
        for node in ast.walk(_parsed_app())
        if isinstance(node, ast.Attribute) and node.attr.startswith("ask")
    ]
    assert names == ["ask_with_evidence"], names


def test_the_ui_holds_no_numeric_similarity_threshold() -> None:
    """No float literal in the module may act as a gate.

    Presentation legitimately formats numbers - chunk scores are read off the
    candidate and printed - so this cannot ban floats outright. It bans a float
    literal used in a comparison, which is what a copied-in threshold looks
    like.
    """
    for node in ast.walk(_parsed_app()):
        if isinstance(node, ast.Compare):
            for operand in node.comparators:
                assert not isinstance(operand, ast.Constant) or not isinstance(
                    operand.value, float
                ), "a float literal in a comparison in the UI module"


# --- deployment -----------------------------------------------------------


def test_the_app_binds_to_loopback_only() -> None:
    """No auth, no persistence, one local process (architecture AD-13).

    `tomllib` is 3.11+ and this project is pinned to 3.10 (Phase 0 finding 7),
    so the file is read as text rather than parsed. Comments are stripped first:
    this file explains at length why binding to `0.0.0.0` would be wrong, and
    that sentence is not a bind address.
    """
    raw = CONFIG_TOML.read_text(encoding="utf-8")
    text = "\n".join(
        line for line in raw.splitlines() if not line.lstrip().startswith("#")
    )
    address = re.search(r'^\s*address\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert address is not None, "no address in .streamlit/config.toml"
    assert address.group(1) == "127.0.0.1"
    for unsafe in ("0.0.0.0", "::"):
        assert unsafe not in text


def test_there_is_no_auth_material_in_the_streamlit_directory() -> None:
    directory = CONFIG_TOML.parent
    assert not (directory / "secrets.toml").exists()
    assert not (directory / "credentials.toml").exists()


def test_usage_stats_are_disabled() -> None:
    """A demo should not phone home about being opened."""
    assert "gatherUsageStats = false" in CONFIG_TOML.read_text(encoding="utf-8")
