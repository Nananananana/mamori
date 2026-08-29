"""Any server that speaks the OpenAI chat API, here or on the network.

Ollama, llama.cpp's server, vLLM, LM Studio and text-generation-webui all
expose ``/v1/chat/completions``. One adapter covers all of them, which is why
this shape was chosen over any single vendor's SDK.

It does not care whether the server is on this machine or a GPU box in the
server room. That is a hostname, and treating the two as different code paths
was a mistake worth not making: a model on this machine can be busy too --
Ollama loading weights, vLLM working through a queue -- so a retryable failure
is retryable wherever it came from. What distance changes is how long to wait,
which is a number, not a branch.

Written against ``urllib``, so the library still installs with no runtime
dependencies. A team that would rather use ``httpx``, a vendor SDK, or anything
that goes through their corporate proxy registers their own factory under the
same name; nothing else changes.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin

from ...errors import ConfigurationError, ProviderError
from ...ports.llm import LLMRequest, LLMResponse
from ...ports.llm_endpoint import LLMEndpoint

__all__ = ["OpenAICompatibleProvider", "open_ai_compatible_factory"]

#: Statuses worth trying again: the server is busy, restarting, or a gateway in
#: between hiccuped. A 4xx means the request was wrong and will be wrong again.
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

_TRANSIENT = (
    TimeoutError,
    ConnectionError,
    http.client.RemoteDisconnected,
    http.client.IncompleteRead,
)


class OpenAICompatibleProvider:
    """Talks to an OpenAI-compatible chat endpoint.

    Args:
        endpoint: Where the model is and how long to wait for it.
        name: Recorded on every entity produced from this provider's answers.

    Raises:
        ConfigurationError: no model name, or an endpoint outside its own
            trust boundary.
    """

    def __init__(self, endpoint: LLMEndpoint, *, name: str = "local-llm") -> None:
        if not endpoint.model:
            raise ConfigurationError("a model name is required")
        if not endpoint.policy.admits(endpoint.base_url):
            raise ConfigurationError(endpoint.policy.explain(endpoint.base_url))
        self._endpoint = endpoint
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._endpoint.model

    @property
    def endpoint(self) -> LLMEndpoint:
        return self._endpoint

    @property
    def supports_structured_output(self) -> bool:
        """Advertised as unsupported.

        Servers disagree about whether ``response_format`` means a JSON schema,
        JSON-ish, or nothing at all, and a schema silently ignored is worse
        than one never sent. The parser validates the answer either way.
        """
        return False

    def health_check(self) -> bool:
        """Whether the server answers at all.

        Worth calling at startup when the model is on another machine: finding
        out that the GPU box is unreachable is better done then than on the
        first document.
        """
        url = urljoin(self._endpoint.normalised_base_url(), "models")
        # The suppressions below are safe because __init__ checked this URL
        # against the endpoint's trust boundary, which settles the scheme too.
        request = urllib.request.Request(  # noqa: S310
            url, headers=self._headers(), method="GET"
        )
        try:
            with urllib.request.urlopen(request, timeout=5.0):  # noqa: S310
                return True
        except Exception:
            return False

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Ask the model, retrying transient failures.

        Only transient ones. A rejected key or a malformed request will be
        rejected again, and retrying a rate limit that is not backed off makes
        it worse.


        Raises:
            ProviderError: unreachable, refused, or something that was not a
                chat completion. The message carries a reason and never the
                prompt, the answer or the server's body.
        """
        attempts = 1 + self._endpoint.retries
        delay = self._endpoint.backoff

        for attempt in range(attempts):
            try:
                return self._attempt(request)
            except ProviderError as exc:
                if not exc.retryable or attempt == attempts - 1:
                    raise
                time.sleep(delay)
                delay *= 2

        raise ProviderError(self._name, "no attempt was made")  # pragma: no cover

    # -- internals ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self._endpoint.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _attempt(self, request: LLMRequest) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self._endpoint.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        body = json.dumps(payload).encode("utf-8")
        url = urljoin(self._endpoint.normalised_base_url(), "chat/completions")
        timeout = min(self._endpoint.timeout, request.timeout or self._endpoint.timeout)
        # The suppressions below are safe because __init__ checked this URL
        # against the endpoint's trust boundary, which settles the scheme too.
        http_request = urllib.request.Request(  # noqa: S310
            url, data=body, headers=self._headers(), method="POST"
        )

        try:
            with urllib.request.urlopen(http_request, timeout=timeout) as response:  # noqa: S310
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            # The body may quote the prompt the server rejected, so only the
            # status crosses this line.
            raise ProviderError(
                self._name, f"HTTP {exc.code}", retryable=exc.code in _RETRYABLE_STATUS
            ) from None
        except urllib.error.URLError as exc:
            raise ProviderError(
                self._name,
                f"unreachable ({type(exc.reason).__name__})",
                retryable=True,
            ) from None
        except _TRANSIENT as exc:
            raise ProviderError(self._name, type(exc).__name__, retryable=True) from None
        except OSError as exc:
            raise ProviderError(self._name, type(exc).__name__, retryable=True) from None

        return self._parse(raw)

    def _parse(self, raw: str) -> LLMResponse:
        try:
            payload = json.loads(raw)
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(self._name, "response was not a chat completion") from None

        usage = payload.get("usage") or {}
        return LLMResponse(
            text=str(content),
            model=str(payload.get("model", self._endpoint.model)),
            usage={k: int(v) for k, v in usage.items() if isinstance(v, int)},
        )


def open_ai_compatible_factory(endpoint: LLMEndpoint) -> OpenAICompatibleProvider:
    """Factory for the registry."""
    return OpenAICompatibleProvider(endpoint)
