"""Shared test fixtures.

`settings` lives here rather than in `test_pipeline.py` because Phase 5's
integration tests need the same fixture, and importing a fixture out of a test
module works only by accident of collection order. A fixture defined in a test
file is not available to any other file; a conftest is.
"""

from __future__ import annotations

import pytest

from src.ragbot.core.config import Settings


@pytest.fixture
def settings() -> Settings:
    """A minimal valid Settings.

    `max_answer_sentences=3` keeps generated answers inside the sentence limit
    so validation does not reject drafts for an unrelated reason. Everything else
    is the real default - in particular `block_pii=True`, so a test that does not
    think about PII gets the safe behaviour rather than a permissive default.
    """
    return Settings(max_answer_sentences=3)
