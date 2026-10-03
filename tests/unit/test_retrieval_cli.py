"""CLI-level tests for `python -m src.ragbot.retrieval`.

The CLI shipped an `IndentationError` in Phase 3 that made every invocation
die before it ran. Nothing caught it: the retrieval modules are unit-tested, but
`__main__.py` itself was not, so an entry point that cannot be imported looked
identical to a working one until it was executed by hand. These tests import the
module and drive `main()` directly so that class of failure cannot return.

`--show-rule` is used wherever the test does not need the index, because it
routes and prints without constructing an embedder - no model download, no
Chroma, no BM25 pickle. The paths that DO need the index are covered against the
real index in tests/integration/test_hybrid_retrieval.py.
"""

from __future__ import annotations

import pytest

from src.ragbot.core.models import Intent
from src.ragbot.retrieval import __main__ as cli
from src.ragbot.retrieval.intent import classify


def test_module_imports():
    """Guards the failure that actually shipped: an unimportable entry point."""
    assert callable(cli.main)
    assert cli.RULE


def test_show_rule_reports_the_matched_rule(capsys: pytest.CaptureFixture):
    rc = cli.main(["--show-rule", "What", "is", "the", "minimum", "SIP?"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "intent   : factual" in out
    assert "rule=" in out


def test_show_rule_needs_no_index_or_model(capsys: pytest.CaptureFixture):
    """`--show-rule` must stay a pure routing probe. If it ever grows a
    HybridSearcher, a missing index would break the one diagnostic that is
    supposed to work when the index is broken."""
    assert cli.main(["--show-rule", "Should I buy HDFC Equity Fund?"]) == 0
    assert "opinion" in capsys.readouterr().out


def test_question_is_joined_from_multiple_argv_tokens(capsys: pytest.CaptureFixture):
    """The question is `nargs="+"`, so a multi-word question must survive
    argv splitting intact or intent routing sees the wrong string."""
    assert cli.main(["--show-rule", "Should", "I", "buy", "HDFC", "ELSS?"]) == 0
    out = capsys.readouterr().out
    assert "question : Should I buy HDFC ELSS?" in out
    assert "opinion" in out


@pytest.mark.parametrize(
    "question,intent",
    [
        ("What is the minimum SIP for HDFC ELSS?", Intent.FACTUAL),
        ("Should I buy HDFC Equity Fund for 5 years?", Intent.OPINION),
        ("What is the expense ratio of Parag Parikh Flexi Cap?", Intent.OUT_OF_SCOPE),
    ],
)
def test_show_rule_agrees_with_the_router(question: str, intent: Intent):
    """The CLI must not re-implement routing; if these ever diverge the printed
    intent is a lie."""
    assert classify(question) is intent
    assert cli.main(["--show-rule", question]) == 0
