"""The provider adapter: error messages and retry policy.

No network. `httpx.post` is patched, so these assert the ADAPTER's behaviour -
what it retries, what it fails fast on, and what a human ends up reading - rather
than that a vendor is reachable today.

The missing-key path is a Phase 4 done-when item, so it is tested for what it
actually promises: a readable message and no traceback.
"""

from __future__ import annotations

import httpx
import pytest

from src.ragbot.core.config import Settings
from src.ragbot.core.errors import MissingAPIKeyError, ProviderError
from src.ragbot.generation import llm
from src.ragbot.generation.llm import (
    LLMUnavailable,
    OllamaClient,
    OpenAIClient,
    build_client,
)

MESSAGES = [{"role": "user", "content": "hello"}]


def _response(status: int, payload: dict | None = None, text: str = "") -> httpx.Response:
    return httpx.Response(
        status,
        json=payload if payload is not None else {"error": {"message": text or "boom"}},
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )


def _ok(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch):
    """Retries are asserted by call COUNT, so the backoff must not actually wait."""
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)


# --- missing key: a done-when item ---------------------------------------


def test_missing_key_raises_actionable_error_not_a_stack_trace():
    with pytest.raises(MissingAPIKeyError) as excinfo:
        build_client(Settings(llm_provider="openai", llm_api_key=None))
    message = str(excinfo.value)
    assert "LLM_API_KEY" in message
    assert ".env" in message or "set LLM_API_KEY" in message
    # Readable on one line, and never a Python-level error string.
    assert "\n" not in message
    assert "Traceback" not in message


def test_provider_none_is_distinct_from_a_missing_key():
    """Generation switched off is not the same problem as generation
    misconfigured, and conflating them produces 'set an API key' for someone who
    deliberately chose local."""
    with pytest.raises(LLMUnavailable) as excinfo:
        build_client(Settings(llm_provider="none"))
    message = str(excinfo.value)
    assert "LLM_PROVIDER=none" in message
    # It may name the two ways to turn generation ON. What it must not do is
    # claim a credential is missing, which is a different fault with a
    # different fix.
    assert "is not set" not in message
    assert "missing" not in message.lower()


def test_anthropic_says_so_rather_than_404ing():
    with pytest.raises(ProviderError) as excinfo:
        build_client(Settings(llm_provider="anthropic"))
    assert "no adapter" in str(excinfo.value)


def test_direct_construction_without_auth_is_rejected():
    with pytest.raises(MissingAPIKeyError):
        OpenAIClient(base_url="https://x", headers={}, model="m")


# --- happy paths ----------------------------------------------------------


def test_openai_complete_returns_message_content(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict] = []

    def fake_post(url, json, headers, timeout):
        calls.append({"url": url, "json": json})
        return _response(200, _ok("Rs. 500 is the minimum SIP."))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    client = OpenAIClient(
        base_url="https://api.openai.com/v1",
        headers={"Authorization": "Bearer sk-test"},
        model="gpt-4o-mini",
    )
    assert client.complete(MESSAGES) == "Rs. 500 is the minimum SIP."
    assert calls[0]["url"].endswith("/chat/completions")
    assert calls[0]["json"]["temperature"] == 0  # deterministic


def test_openai_sends_the_bearer_token(monkeypatch: pytest.MonkeyPatch):
    seen: dict = {}

    def fake_post(url, json, headers, timeout):
        seen.update(headers)
        return _response(200, _ok("ok"))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    OpenAIClient(
        base_url="https://x", headers={"Authorization": "Bearer sk-test"}, model="m"
    ).complete(MESSAGES)
    assert seen["Authorization"] == "Bearer sk-test"


def test_ollama_needs_no_key():
    client = OllamaClient(base_url="http://localhost:11434", headers={}, model="llama3")
    assert client.headers == {}
    assert client.provider == "ollama"


def test_ollama_complete_returns_message_content(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        llm.httpx,
        "post",
        lambda url, json, headers, timeout: _response(
            200, {"message": {"content": "local answer"}}
        ),
    )
    client = OllamaClient(base_url="http://localhost:11434", headers={}, model="llama3")
    assert client.complete(MESSAGES) == "local answer"


def test_malformed_provider_response_becomes_a_provider_error(monkeypatch: pytest.MonkeyPatch):
    """A 200 with an unexpected body must not surface as a KeyError at the call
    site; the user needs to be told the provider is misbehaving."""
    monkeypatch.setattr(
        llm.httpx, "post", lambda url, json, headers, timeout: _response(200, {"weird": 1})
    )
    client = OpenAIClient(
        base_url="https://x", headers={"Authorization": "Bearer k"}, model="m"
    )
    with pytest.raises(ProviderError) as excinfo:
        client.complete(MESSAGES)
    assert "no message content" in str(excinfo.value)


# --- retry policy ---------------------------------------------------------


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_retryable_statuses_are_retried_twice(
    monkeypatch: pytest.MonkeyPatch, no_sleep, status: int
):
    attempts = {"n": 0}

    def fake_post(url, json, headers, timeout):
        attempts["n"] += 1
        return _response(status)

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    client = OpenAIClient(
        base_url="https://x",
        headers={"Authorization": "Bearer k"},
        model="m",
        max_retries=2,
    )
    with pytest.raises(ProviderError) as excinfo:
        client.complete(MESSAGES)
    assert attempts["n"] == 3  # 1 initial + 2 retries
    assert "3 attempt(s)" in str(excinfo.value)


def test_a_retry_can_succeed(monkeypatch: pytest.MonkeyPatch, no_sleep):
    attempts = {"n": 0}

    def fake_post(url, json, headers, timeout):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return _response(503)
        return _response(200, _ok("recovered"))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    client = OpenAIClient(
        base_url="https://x", headers={"Authorization": "Bearer k"}, model="m"
    )
    assert client.complete(MESSAGES) == "recovered"
    assert attempts["n"] == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_non_retryable_statuses_fail_fast(
    monkeypatch: pytest.MonkeyPatch, no_sleep, status: int
):
    """A 401 is a config bug. Retrying it three times just delays the message and
    burns quota."""
    attempts = {"n": 0}

    def fake_post(url, json, headers, timeout):
        attempts["n"] += 1
        return _response(status)

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    client = OpenAIClient(
        base_url="https://x", headers={"Authorization": "Bearer k"}, model="m"
    )
    with pytest.raises(ProviderError):
        client.complete(MESSAGES)
    assert attempts["n"] == 1


def test_bad_credentials_name_the_credential_problem(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        llm.httpx, "post", lambda url, json, headers, timeout: _response(401, text="bad key")
    )
    client = OpenAIClient(
        base_url="https://x", headers={"Authorization": "Bearer k"}, model="m"
    )
    with pytest.raises(ProviderError) as excinfo:
        client.complete(MESSAGES)
    message = str(excinfo.value)
    assert "credentials" in message
    assert "LLM_API_KEY" in message


def test_network_errors_are_retried_then_surfaced(
    monkeypatch: pytest.MonkeyPatch, no_sleep
):
    attempts = {"n": 0}

    def fake_post(url, json, headers, timeout):
        attempts["n"] += 1
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    client = OpenAIClient(
        base_url="https://x", headers={"Authorization": "Bearer k"}, model="m"
    )
    with pytest.raises(ProviderError) as excinfo:
        client.complete(MESSAGES)
    assert attempts["n"] == 3
    assert "connection refused" in str(excinfo.value)


def test_provider_error_suggests_a_local_fallback(
    monkeypatch: pytest.MonkeyPatch, no_sleep
):
    monkeypatch.setattr(
        llm.httpx, "post", lambda url, json, headers, timeout: _response(503)
    )
    client = OpenAIClient(
        base_url="https://x", headers={"Authorization": "Bearer k"}, model="m"
    )
    with pytest.raises(ProviderError) as excinfo:
        client.complete(MESSAGES)
    assert "ollama" in str(excinfo.value)


# --- the egress boundary --------------------------------------------------


def test_llm_module_imports_nothing_from_retrieval():
    """The adapter is the single egress point and must know nothing about
    chunks. A retrieval import here would be the boundary leaking."""
    import ast
    from pathlib import Path

    source = Path(llm.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
    assert not any("retrieval" in m for m in imported), imported
    assert not any("ingest" in m for m in imported), imported


def test_no_chunk_or_score_vocabulary_in_the_adapter():
    """Belt and braces on the same boundary: the module should not even use the
    words."""
    import inspect

    source = inspect.getsource(llm)
    for word in ("chunk_id", "dense_score", "fused_rank", "RetrievedChunk"):
        assert word not in source, f"{word} leaked into the egress adapter"
