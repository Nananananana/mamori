"""The OpenAI-compatible provider, against a real local server.

A stub would prove nothing here. What needs checking is the wire behaviour --
that the request is shaped the way every local server expects, that an error
response becomes a `ProviderError` and not a traceback, and above all that
nothing from the server's answer or the user's document ends up in an error
message.

The server is `http.server` in a thread on an ephemeral port, so the test needs
no fixture, no container and no network.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest

from mamori.errors import ConfigurationError, ProviderError
from mamori.infrastructure.llm import OpenAICompatibleProvider
from mamori.ports.llm import LLMProvider, LLMRequest

CANARY = "leaky-canary@example.com"


class _Handler(BaseHTTPRequestHandler):
    status: int = 200
    body: str = ""
    received: ClassVar[dict[str, Any]] = {}

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        _Handler.received = {"path": self.path, "headers": dict(self.headers), "body": raw}
        payload = _Handler.body.encode("utf-8")
        self.send_response(_Handler.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        """Silence the default stderr logging."""


@pytest.fixture
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/v1/"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def completion(content: str) -> str:
    return json.dumps(
        {
            "model": "test-model",
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        }
    )


class TestLocalOnly:
    def test_a_remote_url_is_refused(self) -> None:
        """The text reaches a detector before it is protected."""
        with pytest.raises(ConfigurationError, match="not local"):
            OpenAICompatibleProvider("m", base_url="https://api.example.com/v1/")

    def test_the_refusal_says_why(self) -> None:
        with pytest.raises(ConfigurationError, match=re.escape("*before* it is protected")):
            OpenAICompatibleProvider("m", base_url="https://api.example.com/v1/")

    def test_it_can_be_overridden_deliberately(self) -> None:
        provider = OpenAICompatibleProvider(
            "m", base_url="https://gpu.internal/v1/", allow_remote=True
        )
        assert provider.name

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:11434/v1/",
            "http://127.0.0.1:8000/v1/",
            "http://host.docker.internal:11434/v1/",
        ],
    )
    def test_local_urls_are_accepted(self, url: str) -> None:
        assert OpenAICompatibleProvider("m", base_url=url).model == "m"

    def test_a_model_name_is_required(self) -> None:
        with pytest.raises(ConfigurationError):
            OpenAICompatibleProvider("")


class TestProtocol:
    def test_it_satisfies_the_port(self, server: str) -> None:
        assert isinstance(OpenAICompatibleProvider("m", base_url=server), LLMProvider)

    def test_structured_output_is_not_claimed(self, server: str) -> None:
        """Servers disagree about what response_format means; the parser
        validates either way."""
        assert not OpenAICompatibleProvider("m", base_url=server).supports_structured_output


class TestRequestShape:
    def test_it_posts_to_chat_completions(self, server: str) -> None:
        _Handler.status, _Handler.body = 200, completion("{}")
        OpenAICompatibleProvider("test-model", base_url=server).generate(LLMRequest(user="hi"))
        assert _Handler.received["path"] == "/v1/chat/completions"

    def test_it_sends_the_system_and_user_messages(self, server: str) -> None:
        _Handler.status, _Handler.body = 200, completion("{}")
        OpenAICompatibleProvider("test-model", base_url=server).generate(
            LLMRequest(system="be careful", user="the text")
        )
        sent = json.loads(_Handler.received["body"])
        assert [m["role"] for m in sent["messages"]] == ["system", "user"]
        assert sent["messages"][1]["content"] == "the text"

    def test_it_asks_for_a_deterministic_answer(self, server: str) -> None:
        _Handler.status, _Handler.body = 200, completion("{}")
        OpenAICompatibleProvider("test-model", base_url=server).generate(LLMRequest(user="x"))
        assert json.loads(_Handler.received["body"])["temperature"] == 0.0

    def test_it_does_not_stream(self, server: str) -> None:
        _Handler.status, _Handler.body = 200, completion("{}")
        OpenAICompatibleProvider("test-model", base_url=server).generate(LLMRequest(user="x"))
        assert json.loads(_Handler.received["body"])["stream"] is False

    def test_no_authorization_header_without_a_key(self, server: str) -> None:
        _Handler.status, _Handler.body = 200, completion("{}")
        OpenAICompatibleProvider("test-model", base_url=server).generate(LLMRequest(user="x"))
        assert "Authorization" not in _Handler.received["headers"]

    def test_an_api_key_is_sent_as_a_bearer_token(self, server: str) -> None:
        _Handler.status, _Handler.body = 200, completion("{}")
        provider = OpenAICompatibleProvider("test-model", base_url=server, api_key="secret")
        provider.generate(LLMRequest(user="x"))
        assert _Handler.received["headers"]["Authorization"] == "Bearer secret"


class TestResponses:
    def test_a_normal_answer(self, server: str) -> None:
        _Handler.status, _Handler.body = 200, completion('{"entities": []}')
        response = OpenAICompatibleProvider("test-model", base_url=server).generate(
            LLMRequest(user="x")
        )
        assert response.text == '{"entities": []}'
        assert response.model == "test-model"

    def test_usage_is_carried_through(self, server: str) -> None:
        _Handler.status, _Handler.body = 200, completion("{}")
        response = OpenAICompatibleProvider("test-model", base_url=server).generate(
            LLMRequest(user="x")
        )
        assert response.usage["prompt_tokens"] == 10

    def test_an_empty_answer_is_falsey(self, server: str) -> None:
        _Handler.status, _Handler.body = 200, completion("   ")
        response = OpenAICompatibleProvider("test-model", base_url=server).generate(
            LLMRequest(user="x")
        )
        assert not response

    def test_an_error_status_becomes_a_provider_error(self, server: str) -> None:
        _Handler.status, _Handler.body = 500, '{"error": "boom"}'
        with pytest.raises(ProviderError):
            OpenAICompatibleProvider("test-model", base_url=server).generate(LLMRequest(user="x"))

    def test_a_non_completion_body_becomes_a_provider_error(self, server: str) -> None:
        _Handler.status, _Handler.body = 200, '{"unexpected": true}'
        with pytest.raises(ProviderError, match="not a chat completion"):
            OpenAICompatibleProvider("test-model", base_url=server).generate(LLMRequest(user="x"))

    def test_malformed_json_becomes_a_provider_error(self, server: str) -> None:
        _Handler.status, _Handler.body = 200, "{not json"
        with pytest.raises(ProviderError):
            OpenAICompatibleProvider("test-model", base_url=server).generate(LLMRequest(user="x"))

    def test_an_unreachable_server_becomes_a_provider_error(self) -> None:
        provider = OpenAICompatibleProvider("m", base_url="http://127.0.0.1:9/v1/", timeout=1.0)
        with pytest.raises(ProviderError):
            provider.generate(LLMRequest(user="x"))


class TestErrorsDoNotLeak:
    """The one place the unprotected text is in scope."""

    def test_an_error_body_is_not_repeated(self, server: str) -> None:
        _Handler.status, _Handler.body = 400, json.dumps({"error": f"bad input: {CANARY}"})
        with pytest.raises(ProviderError) as caught:
            OpenAICompatibleProvider("test-model", base_url=server).generate(LLMRequest(user="x"))
        assert CANARY not in str(caught.value)

    def test_the_request_text_is_not_repeated(self, server: str) -> None:
        _Handler.status, _Handler.body = 500, "{}"
        with pytest.raises(ProviderError) as caught:
            OpenAICompatibleProvider("test-model", base_url=server).generate(
                LLMRequest(system="s", user=CANARY)
            )
        assert CANARY not in str(caught.value)

    def test_the_request_repr_holds_no_text(self) -> None:
        request = LLMRequest(system="a system prompt", user=CANARY)
        assert CANARY not in repr(request)
        assert "a system prompt" not in repr(request)

    def test_the_response_repr_holds_no_text(self, server: str) -> None:
        _Handler.status, _Handler.body = 200, completion(CANARY)
        response = OpenAICompatibleProvider("test-model", base_url=server).generate(
            LLMRequest(user="x")
        )
        assert CANARY not in repr(response)
