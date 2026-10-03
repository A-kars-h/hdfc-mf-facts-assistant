"""The Streamlit UI. Presentation only.

This module contains no retrieval, no ranking, no threshold, no prompting, no
generation, no output validation and no PII handling. It calls exactly one
product function, `Ragbot.ask_with_evidence()`, and renders what comes back. If
a rule ever needs deciding here, it belongs in `retrieval/`, `generation/` or
`safety/` instead, because this file is not covered by those invariants and a
rule that lives only in the UI does not exist for the CLI, the eval harness or
the tests.

The four rules that shape the code below
----------------------------------------

1. **The orchestrator is the only thing called.** Not the searcher, not the LLM
   client, not the PII scanner, not the validator. `ask_with_evidence()` returns
   the finished `Answer` plus the chunks it was actually written from, so the
   inspector can show real evidence without this file doing any retrieval.

2. **Nothing is rendered before validation has finished.** `ask_with_evidence()`
   returns a finished, already-validated `Answer` or raises; there is no token
   streaming here. The Phase 4 pitfall was rendering a draft as it arrived, which
   briefly displays a prohibited answer. `Ragbot.stream_draft()` exists and is
   deliberately NOT used - a streamed fragment is unvalidated.

3. **Refusals leak no internals.** `educational.py` is explicit that a refusal
   must not reveal a score, a rank, a threshold or chunk text, because a user who
   learns the bar can aim at it. So the chunk inspector is rendered for ANSWERED
   questions only. A refusal shows its text, its educational link (or the honest
   note that there is none) and nothing else. The threshold value itself is
   never displayed either, for the same reason.

4. **No URL is ever generated.** The educational link is read from
   `Answer.educational_link`, which the orchestrator populated from the
   human-verified map. If that map is empty - and it ships empty - the UI says
   so. It does not substitute a plausible-looking URL, because a broken link
   makes the refusal look complete when it is not.

Deployment
----------
Single process, `127.0.0.1` only, no auth, no persistence across restarts
(architecture §2.4, AD-13). The bind address is set in `.streamlit/config.toml`
so it is correct even when `streamlit run` is invoked without flags.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import streamlit as st

# `streamlit run src/ragbot/ui/app.py` executes this file the way Python executes
# a script: `__name__` is `"__main__"`, the module has no parent package, and the
# repo root is on `sys.path` only by accident of the working directory. A leading
# `..` therefore cannot resolve and the import below raises
# `ImportError: attempted relative import with no known parent package`.
#
# Two lines fix it without moving any file or renaming the package. The repo root
# goes on `sys.path` explicitly - the same thing pytest's `pythonpath = ["."]` does
# for the tests - and the imports are absolute against `src.ragbot`, which is the
# import path the Makefile, the tests and `docs/` already use. Every other module
# in the package keeps its relative imports; only this entrypoint cannot, because
# only this entrypoint is launched as a file rather than as a module.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.ragbot.core.config import Settings  # noqa: E402
from src.ragbot.core.errors import RagbotError  # noqa: E402
from src.ragbot.core.logging import setup_logging  # noqa: E402
from src.ragbot.core.models import Answer, Intent, RetrievedChunk  # noqa: E402
from src.ragbot.generation.pipeline import Ragbot  # noqa: E402

# --- constants -----------------------------------------------------------

#: The persistent banner. The exact string is a Phase 8 deliverable (D-5), so it
#: lives in one place and that report must quote this constant, not a paraphrase.
DISCLAIMER = "Facts-only. No investment advice."

WELCOME = (
    "Ask about the HDFC mutual fund facts in this deployment. Answers come from "
    "a fixed set of HDFC pages and are cited back to you."
)

#: EXACTLY THREE starters, one per intent, and they are the golden-set queries
#: from `src/ragbot/eval/sample_set.jsonl` (Q3, Q6, Q8) rather than invented
#: strings. Two reasons. The demo then shows the same questions the eval scored,
#: so the CLI, the report and the screen cannot disagree - the Phase 7 pitfall
#: was putting retrieval into the UI to make the demo work, and that is what
#: causes the divergence. And one starter per intent makes all three required
#: states (answered, opinion refusal, out-of-corpus refusal) reachable in one
#: click each, which is what makes the app demo-ready.
EXAMPLE_QUESTIONS = (
    "What is the minimum SIP amount for HDFC ELSS Tax Saver Fund Direct Plan Growth?",
    "Should I buy HDFC Large Cap for a 5-year goal?",
    "What is the expense ratio of the HDFC Mid Cap Fund?",
)


# --- the one product call ------------------------------------------------


@st.cache_resource(show_spinner="Loading the index and the embedding model...")
def _bot() -> Ragbot:
    """One orchestrator per process, so the 90 MB model loads once.

    `cache_resource` is process-level caching of an already-constructed
    collaborator, not shared per-user state. Each question re-enters
    `ask_with_evidence()`, which resets the recorded evidence before it runs, so
    nothing carries over between questions.
    """
    setup_logging()
    return Ragbot(settings=Settings())


# --- rendering (presentation only) ---------------------------------------


def _render_source(answer: Answer) -> None:
    """At most one source link, plus the date it was last updated from sources."""
    if answer.source_url:
        label = answer.source_title or "source page"
        st.markdown(f"[Source: {label}]({answer.source_url})")
    elif answer.refused:
        # A refusal carries no citation by design: naming a page, or hinting at
        # the gate, would leak. Saying so is clearer than a silently empty area.
        st.caption("No source cited - this was a refusal, not a corpus answer.")

    if answer.last_updated is not None:
        st.caption(f"Last updated from sources: {answer.last_updated.date()}")


def _render_educational_link(answer: Answer) -> None:
    """Show the verified educational link, or say honestly that there is none."""
    if answer.educational_link:
        st.markdown(f"[Background reading on this topic]({answer.educational_link})")
    elif answer.educational_link_missing:
        st.caption(
            "No verified investor-education link is available in this deployment, "
            "so none is shown. A URL is never generated."
        )


def _render_answer_card(answer: Answer) -> None:
    """One answer: text, at most one source link, the date, any educational link."""
    with st.container(border=True):
        if answer.refused:
            st.markdown("**Not answering that**")
        st.markdown(answer.text)
        _render_source(answer)
        _render_educational_link(answer)


def _render_chunk_inspector(chunks: list[RetrievedChunk], answer: Answer) -> None:
    """Show the exact chunks the answer was written from. Answered questions only.

    The numbers shown are the ones the gate actually reads: `dense_score` is the
    raw cosine similarity and `fused_rank` is ordering only. The threshold value
    is deliberately not displayed - see rule 3 in the module docstring.
    """
    if answer.refused:
        # A refusal must not reveal scores, ranks or chunk text.
        return

    if answer.intent is Intent.CORPUS_SOURCES:
        # Presentation only: saying where the text came from. The source list is
        # read from the corpus definition, so there are no chunks to show and the
        # "(0 sent to the model)" label would be a lie - nothing was sent to a
        # model either. The decision about what to answer was already made by the
        # orchestrator; this only renders which kind of answer it was.
        st.caption(
            "This answer is the corpus itself, read from the source configuration. "
            "No page text was retrieved and no model was called."
        )
        return

    with st.expander(f"Show retrieved chunks ({len(chunks)} sent to the model)"):
        if not chunks:
            st.caption("No chunks were used for this answer.")
            return
        st.caption(
            "These are the exact chunks this answer was written from. "
            "`raw dense` is the score the confidence gate reads; `fused rank` "
            "is ordering only."
        )
        for position, retrieved in enumerate(chunks, start=1):
            chunk = retrieved.chunk
            with st.container(border=True):
                st.markdown(f"**{position}. {chunk.scheme}**")
                st.caption(
                    f"`{chunk.chunk_id}` · page `{chunk.page_id}` · "
                    f"section {chunk.section or '-'}"
                )
                bm25 = (
                    f"{retrieved.sparse_score:.4f}"
                    if retrieved.sparse_score is not None
                    else "-"
                )
                st.caption(
                    f"raw dense {retrieved.dense_score:.4f} · "
                    f"fused rank {retrieved.fused_rank} · bm25 {bm25}"
                )
                if chunk.return_heavy:
                    st.caption("tagged return-heavy at ingest")
                st.text(chunk.text)


def _render_turn(turn: dict[str, Any]) -> None:
    """One question and whatever the orchestrator made of it."""
    with st.chat_message("user"):
        st.markdown(turn["question"])

    with st.chat_message("assistant"):
        error = turn.get("error")
        if error:
            # Product errors are actionable text by design (FR-15). Showing the
            # message is presentation; interpreting it or working around it is
            # not this module's job, so it is shown and nothing is retried.
            st.error(f"The assistant could not answer that: {error}")
            return
        answer: Answer = turn["answer"]
        chunks: list[RetrievedChunk] = turn["chunks"]
        _render_answer_card(answer)
        _render_chunk_inspector(chunks, answer)


# --- the whole of the UI's behaviour -------------------------------------


def _submit(question: str) -> None:
    """Record one question, ask the orchestrator, and store what it returned.

    The single place the product is called. There is no rule here: whether the
    question is answered, refused, or fails outright was decided upstream, and
    this function only carries the result into the transcript.
    """
    question = (question or "").strip()
    if not question:
        return
    turn: dict[str, Any] = {"question": question, "answer": None, "chunks": [], "error": None}
    st.session_state.messages.append(turn)
    try:
        answer, chunks = _bot().ask_with_evidence(question)
    except RagbotError as exc:
        turn["error"] = str(exc)
    else:
        turn["answer"] = answer
        turn["chunks"] = chunks


# --- the app -------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title="HDFC MF facts assistant",
        page_icon="📄",
        layout="centered",
    )
    st.session_state.setdefault("messages", [])

    st.title("HDFC mutual fund facts assistant")
    st.caption(WELCOME)

    st.markdown("**Try one of these**")
    for starter in EXAMPLE_QUESTIONS:
        if st.button(starter, key=f"starter::{starter}", use_container_width=True):
            _submit(starter)
            st.rerun()

    # Persistent: re-rendered on every rerun, so it is never shown once and then
    # scrolled away, and it sits below the starters but above the input and every
    # rendered answer - the whole product claim is that no advice is given, and
    # the reader must be able to see that at a glance next to the answers. The
    # order is the source's: welcome, then the three starters, then this note
    # (problem statement, Phase 7 wire-up order).
    st.info(DISCLAIMER, icon="⚠️")

    if st.session_state.messages:
        st.divider()
        for turn in st.session_state.messages:
            _render_turn(turn)
        if st.button("Clear conversation", key="clear", type="secondary"):
            st.session_state.messages = []
            st.rerun()

    typed = st.chat_input("Ask a question")
    if typed:
        _submit(typed)
        st.rerun()


# Streamlit executes the entrypoint as a module named `"__main__"` in both real
# launches and `streamlit.testing.v1.AppTest`, so the guard holds in both
# (`ScriptRunner._run_script` builds the main module with that name). Without it
# the module cannot be imported without rendering the entire app, which is what
# made 291 lines of presentation code untestable.
if __name__ == "__main__":
    main()
