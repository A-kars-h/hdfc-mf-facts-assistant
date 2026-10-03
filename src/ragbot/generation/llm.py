"""The single egress point to the outside world.

Everything this project sends to a model leaves through this module, and this
module is the only place that knows a model exists. Two consequences, both
deliberate:

- It imports nothing from `retrieval/`. It knows nothing about chunks, pages or
  scores. It takes messages and returns text. If a retrieval bug ever needed
  "just one more field" from the provider adapter, that would be the signal that
  the boundary is wrong.
- Missing credentials, provider outages and rate limits surface as typed errors
  with actionable messages, never as a raw traceback reaching a user (FR-15).

Transport is plain `httpx` against each vendor's documented HTTP API rather than
a vendor SDK. That is not asceticism: it means the module has no import-time
dependency on an optional package, so a misconfigured or uninstalled SDK can
never turn into an ImportError at answer time, and retry/timeout behaviour is
identical across providers instead of per-SDK.

Retries cover 429 and 5xx only. A 401 or a 400 is a configuration or request
bug: retrying it just burns the user's quota and delays the error, so it fails
immediately with something readable.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Iterator, Protocol, runtime_checkable

import httpx

from ..core.config import Settings, get_settings
from ..core.errors import MissingAPIKeyError, ProviderError, RagbotError

log = logging.getLogger(__name__)

Message = dict[str, str]

#: Provider error codes worth retrying. 429 is the rate limit; 5xx is the
#: provider's fault and is usually transient. Everything else is ours.
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

DEFAULT_TIMEOUT = 60.0


class LLMUnavailable(RagbotError):
    """No usable client. Distinct from ProviderError: nothing was attempted.

    Raised instead of `MissingAPIKeyError` when the project is configured
    `LLM_PROVIDER=none`, because there is no key to be missing - generation was
    switched off on purpose, and saying "set LLM_API_KEY" would be misleading.
    """


@runtime_checkable
class LLMClient(Protocol):
    """What the rest of the project is allowed to ask of a model."""

    def complete(self, messages: list[Message], *, max_tokens: int = 400) -> str:
        """Return the full text of one assistant turn."""
        ...

    def stream(self, messages: list[Message], *, max_tokens: int = 400) -> Iterator[str]:
        """Yield the same text incrementally.

        Present so a UI can show progress, NOT so it can display tokens early.
        A streamed fragment is unvalidated: every prohibition in this project is
        checked on the finished text, so the caller must buffer and validate
        before showing anything (spec Phase 4, "Validation must run BEFORE
        anything is displayed").
        """
        ...


@dataclass(frozen=True)
class _HttpClient:
    """Shared transport plumbing: one retry policy for every provider.

    `provider` is a plain class attribute, NOT a dataclass field. As an
    annotated field it would be set on the instance by `__init__` and shadow the
    subclass's `provider = "openai"`, so every error message would say
    "unknown" - which is exactly the kind of small wrongness that makes a
    provider failure hard to diagnose.
    """

    base_url: str
    headers: dict[str, str]
    model: str
    max_retries: int = 2
    timeout: float = DEFAULT_TIMEOUT

    provider = "unknown"

    def __post_init__(self) -> None:
        """Subclass hook.

        This no-op base exists for a dataclass reason, not for tidiness.
        `dataclasses` decides once, at decoration time, whether to emit a
        `__post_init__` call into the generated `__init__` - and it can only do
        that if the class being decorated defines the method. `_HttpClient`
        originally did not, so the generated `__init__` contained no call at all
        and `OpenAIClient.__post_init__` - the missing-credential guard - was
        silently never invoked. Subclasses inherit `__init__` unchanged, so
        declaring the hook here is what makes the override reachable.
        """
        if not self.base_url:
            raise ProviderError(
                f"{self.provider}: base_url is empty. Set LLM_BASE_URL or use the "
                f"default for this provider."
            )

    def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        url = f"{self.base_url.rstrip('/')}{path}"
        last: Exception | None = None
        # max_retries is the number of RETRIES, so attempts = 1 + max_retries.
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.post(
                    url,
                    json=payload,
                    headers=self.headers,
                    timeout=self.timeout,
                )
            except httpx.HTTPError as exc:
                last = exc
                retryable = True
            else:
                if response.status_code < 400:
                    return response
                retryable = response.status_code in RETRYABLE_STATUS
                if not retryable:
                    # Fail fast, and say what is actually wrong.
                    raise self._fatal(response)
                last = ProviderError(
                    f"{self.provider} returned HTTP {response.status_code} "
                    f"({_body_excerpt(response)}). Retried {attempt} time(s)."
                )
            if attempt >= self.max_retries or not retryable:
                break
            delay = 0.5 * (2**attempt)
            log.warning(
                "%s call failed (attempt %d/%d): %s; retrying in %.1fs",
                self.provider, attempt + 1, self.max_retries + 1, last, delay,
            )
            time.sleep(delay)
        raise ProviderError(
            f"{self.provider} failed after {self.max_retries + 1} attempt(s): {last}. "
            f"Check LLM_PROVIDER/LLM_MODEL, or switch LLM_PROVIDER=ollama to run "
            f"locally."
        ) from last

    def _fatal(self, response: httpx.Response) -> ProviderError:
        detail = _body_excerpt(response)
        if response.status_code in (401, 403):
            return ProviderError(
                f"{self.provider} rejected the credentials (HTTP "
                f"{response.status_code}): {detail}. LLM_API_KEY looks wrong or "
                f"expired - reissue it in .env."
            )
        return ProviderError(
            f"{self.provider} rejected the request (HTTP {response.status_code}): "
            f"{detail}. This is not retried - the request itself is wrong."
        )


def _body_excerpt(response: httpx.Response, limit: int = 200) -> str:
    """A short, safe slice of a provider error body for a human message."""
    try:
        text = response.text
    except Exception:  # noqa: BLE001 - never let diagnostics raise
        return "<unreadable body>"
    text = " ".join(text.split())
    return text[:limit] + ("..." if len(text) > limit else "")


class OpenAIClient(_HttpClient):
    """OpenAI chat-completions. Also works for any OpenAI-compatible endpoint."""

    provider = "openai"

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.headers.get("Authorization"):
            raise MissingAPIKeyError("LLM_API_KEY")

    def _payload(self, messages: list[Message], max_tokens: int, stream: bool) -> dict:
        return {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": stream,
        }

    def complete(self, messages: list[Message], *, max_tokens: int = 400) -> str:
        response = self._post("/chat/completions", self._payload(messages, max_tokens, False))
        data = response.json()
        try:
            return str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"openai returned a response with no message content: "
                f"{_short(data)}"
            ) from exc

    def stream(self, messages: list[Message], *, max_tokens: int = 400) -> Iterator[str]:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        with httpx.stream(
            "POST", url, json=self._payload(messages, max_tokens, True),
            headers=self.headers, timeout=self.timeout,
        ) as response:
            if response.status_code >= 400:
                response.read()
                raise self._fatal(response)
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    delta = json.loads(data)["choices"][0].get("delta", {})
                except (ValueError, KeyError, IndexError):
                    continue
                piece = delta.get("content")
                if piece:
                    yield str(piece)


class OllamaClient(_HttpClient):
    """Local Ollama. No API key - that is the point of it."""

    provider = "ollama"

    def __post_init__(self) -> None:
        # No credential to require. That is the point of running locally.
        super().__post_init__()

    def _payload(self, messages: list[Message], stream: bool) -> dict:
        return {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "options": {"temperature": 0},
        }

    def complete(self, messages: list[Message], *, max_tokens: int = 400) -> str:
        response = self._post("/api/chat", self._payload(messages, False))
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(f"ollama returned non-JSON: {_short(response.text)}") from exc
        content = (data.get("message") or {}).get("content")
        if content is None:
            raise ProviderError(f"ollama returned no message content: {_short(data)}")
        return str(content)

    def stream(self, messages: list[Message], *, max_tokens: int = 400) -> Iterator[str]:
        url = f"{self.base_url.rstrip('/')}/api/chat"
        with httpx.stream(
            "POST", url, json=self._payload(messages, True),
            headers=self.headers, timeout=self.timeout,
        ) as response:
            if response.status_code >= 400:
                response.read()
                raise self._fatal(response)
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except ValueError:
                    continue
                piece = (payload.get("message") or {}).get("content")
                if piece:
                    yield str(piece)
                if payload.get("done"):
                    return


def _short(value: Any, limit: int = 200) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text[:limit] + ("..." if len(text) > limit else "")


def build_client(settings: Settings | None = None) -> LLMClient:
    """Construct the configured client.

    Raises `LLMUnavailable` when generation is switched off, and
    `MissingAPIKeyError` when it is switched on but unconfigured. The two are
    kept distinct on purpose: they need different user-facing advice, and
    conflating them produces the classic "it says set an API key but you asked
    for local" bug.
    """
    s = settings or get_settings()
    if s.llm_provider == "none":
        raise LLMUnavailable(
            "LLM_PROVIDER=none, so no answer can be generated. Retrieval and "
            "validation are unaffected - use `python -m src.ragbot.retrieval` to "
            "inspect candidates. To enable answers set LLM_PROVIDER=openai with "
            "LLM_API_KEY, or LLM_PROVIDER=ollama to run locally."
        )
    if s.llm_provider == "ollama":
        return OllamaClient(
            base_url=s.llm_base_url or "http://localhost:11434",
            headers={},
            model=s.llm_model,
            max_retries=s.max_retries,
        )
    if s.llm_provider == "anthropic":
        # Named in config but has no adapter yet. Saying so beats a confusing
        # 404 from api.openai.com if someone points it at Anthropic.
        raise ProviderError(
            "LLM_PROVIDER=anthropic is configured but no adapter is implemented. "
            "Use LLM_PROVIDER=openai (works with any OpenAI-compatible endpoint via "
            "LLM_BASE_URL) or LLM_PROVIDER=ollama."
        )
    return OpenAIClient(
        base_url=s.llm_base_url or "https://api.openai.com/v1",
        headers={
            "Authorization": f"Bearer {s.require_api_key()}",
            "Content-Type": "application/json",
        },
        model=s.llm_model,
        max_retries=s.max_retries,
    )
