"""Model providers, and where a model is allowed to live.

The deployment this has to serve comes in two shapes: a model on the user's own
machine, and a model on a GPU box somewhere on the company network. Both are
inside the trust boundary; a public API endpoint is not. Most of this file is
about telling those apart, and about what changes when the model is a network
hop away rather than a socket.

The HTTP tests run against `http.server` in a thread. A stub would prove
nothing: what needs checking is the wire behaviour, the retry decisions, and
above all that nothing from the server's answer or the user's document reaches
an error message.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest

from mamori.domain.trust import EndpointPolicy, HostKind, TrustBoundary, classify_host
from mamori.errors import ConfigurationError, ProviderError
from mamori.infrastructure.llm import (
    CallableProvider,
    OpenAICompatibleProvider,
    available_providers,
    create_provider,
    register_llm_provider,
)
from mamori.ports.llm import LLMProvider, LLMRequest, LLMResponse
from mamori.ports.llm_endpoint import LLMEndpoint

CANARY = "leaky-canary@example.com"


class _Handler(BaseHTTPRequestHandler):
    status: int = 200
    body: str = ""
    received: ClassVar[dict[str, Any]] = {}
    calls: ClassVar[list[str]] = []

    def _respond(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        _Handler.received = {"path": self.path, "headers": dict(self.headers), "body": raw}
        _Handler.calls.append(self.path)
        payload = _Handler.body.encode("utf-8")
        self.send_response(_Handler.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        self._respond()

    def do_GET(self) -> None:
        self._respond()

    def log_message(self, *args: object) -> None:
        """Silence the default stderr logging."""


@pytest.fixture
def base_url() -> Iterator[str]:
    _Handler.calls = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/v1/"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def endpoint(url: str, **kwargs: Any) -> LLMEndpoint:
    return LLMEndpoint(model=kwargs.pop("model", "test-model"), base_url=url, **kwargs)


def completion(content: str) -> str:
    return json.dumps(
        {
            "model": "test-model",
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        }
    )


class TestClassifyHost:
    @pytest.mark.parametrize(
        "host", ["localhost", "127.0.0.1", "::1", "host.docker.internal", "LOCALHOST"]
    )
    def test_this_machine(self, host: str) -> None:
        assert classify_host(host) is HostKind.LOOPBACK

    @pytest.mark.parametrize(
        "host",
        [
            "10.0.4.17",
            "192.168.1.9",
            "172.16.5.2",
            "169.254.1.1",
            "llm.internal",
            "gpu.corp",
            "nas.local",
            "box.lan",
            "wiki.intranet",
        ],
    )
    def test_the_company_network(self, host: str) -> None:
        assert classify_host(host) is HostKind.PRIVATE

    def test_a_single_label_name_is_internal(self) -> None:
        """The common in-house case: the box is just called llm01."""
        assert classify_host("llm01") is HostKind.PRIVATE

    @pytest.mark.parametrize("host", ["api.openai.com", "llm.example.com", "8.8.8.8"])
    def test_the_public_internet(self, host: str) -> None:
        assert classify_host(host) is HostKind.EXTERNAL

    def test_a_declared_host_wins(self) -> None:
        """For an internal machine whose name happens to look public."""
        assert classify_host("llm.example.com", frozenset({"llm.example.com"})) is (
            HostKind.DECLARED
        )

    def test_declaration_is_case_insensitive(self) -> None:
        assert classify_host("LLM.Example.COM", frozenset({"llm.example.com"})) is (
            HostKind.DECLARED
        )

    def test_a_declaration_is_exact_not_a_wildcard(self) -> None:
        """A wildcard in a trust list is how somebody else's host gets in."""
        assert classify_host("evil.example.com", frozenset({"example.com"})) is (HostKind.EXTERNAL)

    def test_an_empty_host(self) -> None:
        assert classify_host("") is HostKind.EXTERNAL


class TestTrustBoundary:
    def test_the_default_admits_this_machine(self) -> None:
        assert EndpointPolicy().admits("http://localhost:11434/v1/")

    def test_the_default_admits_the_company_server(self) -> None:
        """The deployment this exists for."""
        assert EndpointPolicy().admits("http://llm01.corp:8000/v1/")
        assert EndpointPolicy().admits("http://10.0.4.17:8000/v1/")

    def test_the_default_refuses_a_public_endpoint(self) -> None:
        assert not EndpointPolicy().admits("https://api.openai.com/v1/")

    def test_same_host_refuses_the_company_server(self) -> None:
        policy = EndpointPolicy(TrustBoundary.SAME_HOST)
        assert policy.admits("http://localhost:11434/v1/")
        assert not policy.admits("http://llm01.corp:8000/v1/")

    def test_anywhere_admits_everything(self) -> None:
        assert EndpointPolicy(TrustBoundary.ANYWHERE).admits("https://api.openai.com/v1/")

    def test_a_declared_host_is_admitted_under_any_boundary(self) -> None:
        policy = EndpointPolicy(TrustBoundary.SAME_HOST, frozenset({"llm.example.com"}))
        assert policy.admits("https://llm.example.com/v1/")

    def test_the_explanation_says_what_to_do(self) -> None:
        message = EndpointPolicy().explain("https://api.openai.com/v1/")
        assert "before* it is protected" in message
        assert "trusted_hosts" in message
        assert "anywhere" in message


class TestEndpoint:
    def test_a_local_endpoint_is_not_remote(self) -> None:
        assert not LLMEndpoint("m", base_url="http://localhost:11434/v1/").is_remote

    def test_a_company_endpoint_is_remote(self) -> None:
        """Reported for diagnostics and timeout choices, not acted on."""
        assert LLMEndpoint("m", base_url="http://llm01.corp:8000/v1/").is_remote

    def test_the_key_is_read_from_the_environment(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("MY_LLM_KEY", "secret")
        assert LLMEndpoint("m", api_key_env="MY_LLM_KEY").api_key() == "secret"

    def test_no_key_when_none_is_named(self) -> None:
        assert LLMEndpoint("m").api_key() is None

    def test_a_missing_variable_yields_none(self) -> None:
        assert LLMEndpoint("m", api_key_env="NOT_SET_ANYWHERE").api_key() is None

    def test_the_base_url_is_normalised(self) -> None:
        assert LLMEndpoint("m", base_url="http://h/v1").normalised_base_url() == "http://h/v1/"

    def test_the_boundary_can_be_widened(self) -> None:
        widened = LLMEndpoint("m").with_policy(TrustBoundary.ANYWHERE)
        assert widened.policy.admits("https://api.openai.com/v1/")


class TestConstruction:
    def test_a_public_endpoint_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="outside the private_network"):
            OpenAICompatibleProvider(endpoint("https://api.openai.com/v1/"))

    def test_the_refusal_says_why(self) -> None:
        with pytest.raises(ConfigurationError, match=re.escape("*before* it is protected")):
            OpenAICompatibleProvider(endpoint("https://api.openai.com/v1/"))

    def test_a_company_server_is_accepted(self) -> None:
        assert OpenAICompatibleProvider(endpoint("http://llm01.corp:8000/v1/")).model

    def test_a_declared_host_is_accepted(self) -> None:
        policy = EndpointPolicy(trusted_hosts=frozenset({"llm.example.com"}))
        provider = OpenAICompatibleProvider(
            LLMEndpoint("m", base_url="https://llm.example.com/v1/", policy=policy)
        )
        assert provider.model == "m"

    def test_the_boundary_can_be_widened_deliberately(self) -> None:
        provider = OpenAICompatibleProvider(
            LLMEndpoint("m", base_url="https://gpu.example.com/v1/").with_policy(
                TrustBoundary.ANYWHERE
            )
        )
        assert provider.name

    def test_a_model_name_is_required(self) -> None:
        with pytest.raises(ConfigurationError):
            OpenAICompatibleProvider(LLMEndpoint(""))


class TestProtocol:
    def test_it_satisfies_the_port(self, base_url: str) -> None:
        assert isinstance(OpenAICompatibleProvider(endpoint(base_url)), LLMProvider)

    def test_structured_output_is_not_claimed(self, base_url: str) -> None:
        assert not OpenAICompatibleProvider(endpoint(base_url)).supports_structured_output


class TestRequestShape:
    def test_it_posts_to_chat_completions(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 200, completion("{}")
        OpenAICompatibleProvider(endpoint(base_url)).generate(LLMRequest(user="hi"))
        assert _Handler.received["path"] == "/v1/chat/completions"

    def test_it_sends_the_system_and_user_messages(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 200, completion("{}")
        OpenAICompatibleProvider(endpoint(base_url)).generate(
            LLMRequest(system="be careful", user="the text")
        )
        sent = json.loads(_Handler.received["body"])
        assert [m["role"] for m in sent["messages"]] == ["system", "user"]
        assert sent["messages"][1]["content"] == "the text"

    def test_it_asks_for_a_deterministic_answer(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 200, completion("{}")
        OpenAICompatibleProvider(endpoint(base_url)).generate(LLMRequest(user="x"))
        assert json.loads(_Handler.received["body"])["temperature"] == 0.0

    def test_it_does_not_stream(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 200, completion("{}")
        OpenAICompatibleProvider(endpoint(base_url)).generate(LLMRequest(user="x"))
        assert json.loads(_Handler.received["body"])["stream"] is False

    def test_no_authorization_header_without_a_key(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 200, completion("{}")
        OpenAICompatibleProvider(endpoint(base_url)).generate(LLMRequest(user="x"))
        assert "Authorization" not in _Handler.received["headers"]

    def test_a_named_key_is_sent_as_a_bearer_token(self, base_url: str, monkeypatch: Any) -> None:
        monkeypatch.setenv("MY_LLM_KEY", "secret")
        _Handler.status, _Handler.body = 200, completion("{}")
        OpenAICompatibleProvider(endpoint(base_url, api_key_env="MY_LLM_KEY")).generate(
            LLMRequest(user="x")
        )
        assert _Handler.received["headers"]["Authorization"] == "Bearer secret"


class TestResponses:
    def test_a_normal_answer(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 200, completion('{"entities": []}')
        response = OpenAICompatibleProvider(endpoint(base_url)).generate(LLMRequest(user="x"))
        assert response.text == '{"entities": []}'
        assert response.model == "test-model"

    def test_usage_is_carried_through(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 200, completion("{}")
        response = OpenAICompatibleProvider(endpoint(base_url)).generate(LLMRequest(user="x"))
        assert response.usage["prompt_tokens"] == 10

    def test_an_empty_answer_is_falsey(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 200, completion("   ")
        assert not OpenAICompatibleProvider(endpoint(base_url)).generate(LLMRequest(user="x"))

    def test_an_error_status_becomes_a_provider_error(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 400, '{"error": "boom"}'
        with pytest.raises(ProviderError):
            OpenAICompatibleProvider(endpoint(base_url)).generate(LLMRequest(user="x"))

    def test_a_non_completion_body_becomes_a_provider_error(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 200, '{"unexpected": true}'
        with pytest.raises(ProviderError, match="not a chat completion"):
            OpenAICompatibleProvider(endpoint(base_url)).generate(LLMRequest(user="x"))

    def test_malformed_json_becomes_a_provider_error(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 200, "{not json"
        with pytest.raises(ProviderError):
            OpenAICompatibleProvider(endpoint(base_url)).generate(LLMRequest(user="x"))

    def test_an_unreachable_server_becomes_a_provider_error(self) -> None:
        provider = OpenAICompatibleProvider(
            LLMEndpoint("m", base_url="http://127.0.0.1:9/v1/", timeout=1.0)
        )
        with pytest.raises(ProviderError):
            provider.generate(LLMRequest(user="x"))


class TestRetries:
    """A network between here and the model is a thing that can drop."""

    def test_a_busy_server_is_retried(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 503, "{}"
        with pytest.raises(ProviderError):
            OpenAICompatibleProvider(endpoint(base_url, retries=2, backoff=0.01)).generate(
                LLMRequest(user="x")
            )
        assert len(_Handler.calls) == 3

    def test_retries_can_be_turned_off(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 503, "{}"
        with pytest.raises(ProviderError):
            OpenAICompatibleProvider(endpoint(base_url, retries=0)).generate(LLMRequest(user="x"))
        assert len(_Handler.calls) == 1

    def test_a_retry_that_succeeds_returns_the_answer(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 503, "{}"

        def recover() -> None:
            _Handler.status, _Handler.body = 200, completion('{"entities": []}')

        # First call fails, then the handler is flipped by the test itself.
        provider = OpenAICompatibleProvider(endpoint(base_url, retries=2, backoff=0.01))
        with pytest.raises(ProviderError):
            provider.generate(LLMRequest(user="x"))
        recover()
        assert provider.generate(LLMRequest(user="x")).text == '{"entities": []}'

    def test_a_client_error_is_not_retried(self, base_url: str) -> None:
        """A malformed request will be malformed again; retrying wastes time."""
        _Handler.status, _Handler.body = 400, "{}"
        with pytest.raises(ProviderError) as caught:
            OpenAICompatibleProvider(endpoint(base_url, retries=3)).generate(LLMRequest(user="x"))
        assert not caught.value.retryable
        assert len(_Handler.calls) == 1

    def test_a_rate_limit_is_retryable(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 429, "{}"
        with pytest.raises(ProviderError) as caught:
            OpenAICompatibleProvider(endpoint(base_url)).generate(LLMRequest(user="x"))
        assert caught.value.retryable

    def test_an_unreachable_server_is_retryable(self) -> None:
        provider = OpenAICompatibleProvider(
            LLMEndpoint("m", base_url="http://127.0.0.1:9/v1/", timeout=1.0)
        )
        with pytest.raises(ProviderError) as caught:
            provider.generate(LLMRequest(user="x"))
        assert caught.value.retryable


class TestHealthCheck:
    def test_a_running_server_is_healthy(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 200, '{"data": []}'
        assert OpenAICompatibleProvider(endpoint(base_url)).health_check()

    def test_an_unreachable_server_is_not(self) -> None:
        provider = OpenAICompatibleProvider(LLMEndpoint("m", base_url="http://127.0.0.1:9/v1/"))
        assert not provider.health_check()


class TestErrorsDoNotLeak:
    """The one place the unprotected text is in scope."""

    def test_an_error_body_is_not_repeated(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 400, json.dumps({"error": f"bad input: {CANARY}"})
        with pytest.raises(ProviderError) as caught:
            OpenAICompatibleProvider(endpoint(base_url)).generate(LLMRequest(user="x"))
        assert CANARY not in str(caught.value)

    def test_the_request_text_is_not_repeated(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 400, "{}"
        with pytest.raises(ProviderError) as caught:
            OpenAICompatibleProvider(endpoint(base_url)).generate(
                LLMRequest(system="s", user=CANARY)
            )
        assert CANARY not in str(caught.value)

    def test_the_request_repr_holds_no_text(self) -> None:
        request = LLMRequest(system="a system prompt", user=CANARY)
        assert CANARY not in repr(request)
        assert "a system prompt" not in repr(request)

    def test_the_response_repr_holds_no_text(self, base_url: str) -> None:
        _Handler.status, _Handler.body = 200, completion(CANARY)
        response = OpenAICompatibleProvider(endpoint(base_url)).generate(LLMRequest(user="x"))
        assert CANARY not in repr(response)

    def test_an_endpoint_repr_holds_no_key(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("MY_LLM_KEY", "super-secret")
        assert "super-secret" not in repr(LLMEndpoint("m", api_key_env="MY_LLM_KEY"))


class TestCallableProvider:
    """Bring your own client library, or your own in-process model."""

    def test_a_function_becomes_a_provider(self) -> None:
        provider = CallableProvider(lambda r: f"saw {len(r.user)} characters")
        assert isinstance(provider, LLMProvider)
        assert provider.generate(LLMRequest(user="abc")).text == "saw 3 characters"

    def test_it_can_return_a_full_response(self) -> None:
        provider = CallableProvider(lambda r: LLMResponse(text="{}", model="mine"))
        assert provider.generate(LLMRequest()).model == "mine"

    def test_the_name_is_reported(self) -> None:
        assert CallableProvider(lambda r: "", name="llama-cpp").name == "llama-cpp"

    def test_a_raising_function_becomes_a_provider_error(self) -> None:
        """So the pass treats a broken in-process model like a broken server."""

        def boom(request: LLMRequest) -> str:
            raise RuntimeError("model not loaded")

        with pytest.raises(ProviderError):
            CallableProvider(boom).generate(LLMRequest())

    def test_a_raising_function_is_not_retryable(self) -> None:
        def boom(request: LLMRequest) -> str:
            raise RuntimeError("model not loaded")

        with pytest.raises(ProviderError) as caught:
            CallableProvider(boom).generate(LLMRequest())
        assert not caught.value.retryable

    def test_a_wrong_return_type_is_refused(self) -> None:
        with pytest.raises(ProviderError, match="expected str"):
            CallableProvider(lambda r: 42).generate(LLMRequest())  # type: ignore[arg-type,return-value]

    def test_a_non_callable_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            CallableProvider("not a function")  # type: ignore[arg-type]

    def test_it_does_not_claim_structured_output_by_default(self) -> None:
        assert not CallableProvider(lambda r: "").supports_structured_output

    def test_the_error_carries_no_text(self) -> None:
        def boom(request: LLMRequest) -> str:
            raise RuntimeError(CANARY)

        with pytest.raises(ProviderError) as caught:
            CallableProvider(boom).generate(LLMRequest(user=CANARY))
        assert CANARY not in str(caught.value)


class TestRegistry:
    def test_the_built_in_provider_is_registered(self) -> None:
        assert "openai_compatible" in available_providers()

    def test_creating_by_name(self) -> None:
        provider = create_provider("openai_compatible", LLMEndpoint("m"))
        assert isinstance(provider, OpenAICompatibleProvider)

    def test_an_unknown_name_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="unknown LLM provider"):
            create_provider("nope", LLMEndpoint("m"))

    def test_the_error_lists_what_is_available(self) -> None:
        with pytest.raises(ConfigurationError, match="openai_compatible"):
            create_provider("nope", LLMEndpoint("m"))

    def test_a_custom_provider_can_be_registered(self) -> None:
        """The point: a team's own client, usable from a config file."""
        register_llm_provider(
            "my-sdk", lambda e: CallableProvider(lambda r: "{}", name=f"sdk:{e.model}")
        )
        try:
            provider = create_provider("my-sdk", LLMEndpoint("qwen"))
            assert provider.name == "sdk:qwen"
        finally:
            from mamori.infrastructure.llm import registry

            registry._REGISTRY.pop("my-sdk", None)

    def test_a_registration_without_a_name_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            register_llm_provider("", lambda e: CallableProvider(lambda r: ""))
