"""Any local server that speaks the OpenAI chat API.

Ollama, llama.cpp's server, vLLM, LM Studio and text-generation-webui all
expose ``/v1/chat/completions``. One adapter covers all of them, which is why
this shape was chosen over any single vendor's SDK.

Written against ``urllib`` rather than ``httpx`` or ``requests``, so the
library still installs with no runtime dependencies. The request is a JSON POST
and the response is JSON; nothing here needs a client library.

**This is for a model on your machine.** The default base URL is localhost. A
detector that sends the unprotected text somewhere is not a detector, it is the
leak — pointing this at a hosted endpoint sends every document, before
protection, to that endpoint. The constructor refuses a non-local URL unless
you say ``allow_remote=True``, which nobody handling real data should.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin, urlparse

from ...errors import ConfigurationError, ProviderError
from ...ports.llm import LLMRequest, LLMResponse

__all__ = ["OpenAICompatibleProvider"]

# Matched against the host in a URL, never bound to.
_LOCAL_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0", "host.docker.internal"}  # noqa: S104
)


class OpenAICompatibleProvider:
    """Talks to a local OpenAI-compatible chat endpoint.

    Args:
        model: Model name the server knows, e.g. ``qwen2.5:7b``.
        base_url: Root of the API. Defaults to Ollama's.
        api_key: Sent as a bearer token if the server wants one. Most local
            servers do not.
        timeout: Seconds. A local model on CPU is slow; the default is
            generous, and the pass gives up rather than blocking a request
            forever.
        allow_remote: Permit a non-local ``base_url``. Off, on purpose.
        name: Recorded on every entity produced from this provider's answers.
    """

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://localhost:11434/v1/",
        api_key: str | None = None,
        timeout: float = 60.0,
        allow_remote: bool = False,
        name: str = "local-llm",
    ) -> None:
        if not model:
            raise ConfigurationError("a model name is required")
        host = (urlparse(base_url).hostname or "").lower()
        if host not in _LOCAL_HOSTS and not allow_remote:
            raise ConfigurationError(
                f"base_url {base_url!r} is not local. This provider is sent the text "
                "*before* it is protected, so pointing it at a remote endpoint sends "
                "every document there in the clear. Pass allow_remote=True only if "
                "that endpoint is inside your trust boundary."
            )
        self._model = model
        self._base_url = base_url if base_url.endswith("/") else base_url + "/"
        self._api_key = api_key
        self._timeout = timeout
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    @property
    def supports_structured_output(self) -> bool:
        """Advertised as unsupported.

        Servers disagree about whether ``response_format`` means a JSON schema,
        JSON-ish, or nothing at all, and a schema silently ignored is worse
        than one never sent. The parser validates the answer either way.
        """
        return False

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Ask the model.

        Raises:
            ProviderError: the server was unreachable, refused the request, or
                answered with something that was not a chat completion.
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }

        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        url = urljoin(self._base_url, "chat/completions")

        # __init__, which also refuses anything that is not a local host.
        http_request = urllib.request.Request(  # noqa: S310
            url, data=body, headers=headers, method="POST"
        )

        try:
            with urllib.request.urlopen(  # noqa: S310 - scheme is checked in __init__
                http_request, timeout=min(self._timeout, request.timeout or self._timeout)
            ) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            # The body may contain the prompt the server rejected, so only the
            # status is reported.
            raise ProviderError(self._name, f"HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(self._name, type(exc).__name__) from None

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
            model=str(payload.get("model", self._model)),
            usage={k: int(v) for k, v in usage.items() if isinstance(v, int)},
        )
