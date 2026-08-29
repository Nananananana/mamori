"""The proxy: what reaches the upstream, and what comes back to the caller.

The test that matters most is the simplest one to state. A fake upstream stands
in for the external service and keeps every byte it was sent; the tests then
assert that the sensitive values are **not in it**. Everything else here is in
service of that: the walk that finds text in a payload, the fail-closed paths
that must forward nothing, and the streaming restorer holding a placeholder
split across chunks.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from mamori import MamoriConfig
from mamori.interfaces.proxy.exchange import protect_request, restore_reply
from mamori.interfaces.proxy.messages import (
    map_choice_strings,
    request_texts,
    with_texts,
)
from mamori.interfaces.proxy.server import ProxySettings, build_server
from mamori.interfaces.proxy.upstream import Upstream, UpstreamError

from .credentials import FAKE_AWS_KEY

NAME = "田中太郎"
EMAIL = "tanaka@example.com"
PHONE = "090-1234-5678"


def chat(*contents: str, stream: bool = False) -> dict[str, Any]:
    return {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": c} for c in contents],
        "stream": stream,
    }


def completion(text: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
    }


# -- the fake service on the other side ------------------------------------


class FakeUpstream:
    """Records everything it is sent, and answers with whatever it was told to.

    Deliberately dumb. Its only job is to be the place sensitive values would
    end up if the proxy failed, so that a test can look inside it.
    """

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []
        self.reply: dict[str, Any] = completion("nothing to say")
        self.stream_chunks: list[str] = []
        self.status = 200
        self._server: ThreadingHTTPServer | None = None

    @property
    def raw(self) -> str:
        """Every request body, as one string to search for leaks."""
        return json.dumps(self.received, ensure_ascii=False)

    def __enter__(self) -> FakeUpstream:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                outer.received.append(json.loads(self.rfile.read(length)))
                outer.headers.append(dict(self.headers))
                if outer.stream_chunks:
                    self._stream()
                else:
                    self._json()

            def _json(self) -> None:
                body = json.dumps(outer.reply, ensure_ascii=False).encode()
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _stream(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for piece in outer.stream_chunks:
                    event = {"choices": [{"delta": {"content": piece}}]}
                    self.wfile.write(
                        b"data: " + json.dumps(event, ensure_ascii=False).encode() + b"\n\n"
                    )
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

            def log_message(self, *args: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_port}/v1/"


class RunningProxy:
    """The real proxy, on a real socket, in front of a fake upstream."""

    def __init__(self, upstream: str, config: MamoriConfig | None = None, **kwargs: Any) -> None:
        self.settings = ProxySettings(
            upstream=upstream, port=0, config=config or MamoriConfig(), **kwargs
        )
        self._server: ThreadingHTTPServer | None = None

    def __enter__(self) -> RunningProxy:
        self._server = build_server(self.settings)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_port}/v1/chat/completions"

    def post(self, payload: dict[str, Any]) -> tuple[int, Any]:
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer sk-caller"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def post_stream(self, payload: dict[str, Any]) -> Iterator[str]:
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            for line in response:
                yield line.decode("utf-8")


# -- the payload walk ------------------------------------------------------


class TestFindingTheText:
    """Miss one string and it goes upstream in the clear."""

    def test_it_finds_every_message(self) -> None:
        slots = request_texts(chat("one", "two", "three"))
        assert [s.text for s in slots] == ["one", "two", "three"]

    def test_the_system_prompt_is_not_trusted(self) -> None:
        """An organisation's briefing is exactly what should stay local."""
        payload = {
            "messages": [
                {"role": "system", "content": f"You work for {NAME}."},
                {"role": "user", "content": "hello"},
            ]
        }
        assert len(request_texts(payload)) == 2
        assert any("system" in s.where for s in request_texts(payload))

    def test_it_finds_text_inside_multipart_content(self) -> None:
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "look at this"},
                        {"type": "image_url", "image_url": {"url": "http://x/y.png"}},
                        {"type": "text", "text": "and this"},
                    ],
                }
            ]
        }
        assert [s.text for s in request_texts(payload)] == ["look at this", "and this"]

    def test_a_non_text_part_is_left_alone(self) -> None:
        payload = {
            "messages": [
                {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "u"}}]}
            ]
        }
        rebuilt = with_texts(payload, [])
        assert rebuilt["messages"][0]["content"][0]["image_url"] == {"url": "u"}

    def test_replacement_preserves_everything_else(self) -> None:
        payload = chat("secret")
        rebuilt = with_texts(payload, ["masked"])
        assert rebuilt["model"] == "gpt-4o"
        assert rebuilt["messages"][0]["role"] == "user"
        assert rebuilt["messages"][0]["content"] == "masked"

    def test_a_miscount_is_refused_rather_than_zipped(self) -> None:
        """Too few replacements would put message two's text into message one."""
        with pytest.raises(ValueError):
            with_texts(chat("a", "b"), ["only one"])

    def test_a_payload_with_no_messages_yields_nothing(self) -> None:
        assert request_texts({"model": "gpt-4o"}) == ()

    def test_garbage_does_not_raise_on_the_way_in(self) -> None:
        assert request_texts("not a payload") == ()
        assert request_texts(None) == ()

    def test_the_slot_description_never_contains_the_text(self) -> None:
        """Slots end up in logs and diagnostics."""
        for slot in request_texts(chat(f"{NAME} at {EMAIL}")):
            assert NAME not in slot.where
            assert EMAIL not in slot.where


class TestRewritingTheReply:
    def test_it_transforms_the_assistant_message(self) -> None:
        out = map_choice_strings(completion("hello"), "message", str.upper)
        assert out["choices"][0]["message"]["content"] == "HELLO"

    def test_it_leaves_the_envelope_alone(self) -> None:
        out = map_choice_strings(completion("hello"), "message", str.upper)
        assert out["id"] == "chatcmpl-1"
        assert out["choices"][0]["index"] == 0

    def test_a_reply_with_no_choices_survives(self) -> None:
        assert map_choice_strings({"error": {"message": "x"}}, "message", str.upper) == {
            "error": {"message": "x"}
        }


# -- the exchange, without a socket ----------------------------------------


class TestTheExchange:
    def test_values_are_replaced_before_anything_leaves(self) -> None:
        with MamoriConfig().session() as session:
            protected, report = protect_request(session, chat(f"{NAME}さんへ {EMAIL} から"))
        body = json.dumps(protected, ensure_ascii=False)
        assert NAME not in body
        assert EMAIL not in body
        assert report.total_replaced >= 2

    def test_one_value_gets_one_placeholder_across_messages(self) -> None:
        """A model must be able to tell that two mentions are the same person."""
        with MamoriConfig().session() as session:
            protected, _ = protect_request(
                session, chat(f"{NAME}さんへ", f"{NAME}さんから返信がありました")
            )
        first, second = protected["messages"][-2:]
        assert "<PERSON_001>" in first["content"]
        assert "<PERSON_001>" in second["content"]

    def test_the_briefing_is_prepended(self) -> None:
        with MamoriConfig().session() as session:
            protected, report = protect_request(session, chat("hello"))
        assert report.guidance_added
        assert protected["messages"][0]["role"] == "system"

    def test_the_briefing_can_be_turned_off(self) -> None:
        with MamoriConfig().session() as session:
            protected, report = protect_request(session, chat("hello"), add_guidance=False)
        assert not report.guidance_added
        assert len(protected["messages"]) == 1

    def test_the_round_trip_returns_the_callers_own_words(self) -> None:
        with MamoriConfig().session() as session:
            protect_request(session, chat(f"{NAME}さんへ"))
            restored = restore_reply(session, completion("<PERSON_001>さんに返信しました"))
        assert restored["choices"][0]["message"]["content"] == f"{NAME}さんに返信しました"

    def test_a_placeholder_the_session_never_issued_is_left_alone(self) -> None:
        """A reply is untrusted input. It cannot fish for values by guessing."""
        with MamoriConfig().session() as session:
            protect_request(session, chat(f"{NAME}さんへ"))
            restored = restore_reply(session, completion("<PERSON_042> and <EMAIL_099>"))
        assert restored["choices"][0]["message"]["content"] == "<PERSON_042> and <EMAIL_099>"

    def test_the_report_never_contains_a_value(self) -> None:
        with MamoriConfig().session() as session:
            _, report = protect_request(session, chat(f"{NAME} {EMAIL} {PHONE}"))
        blob = json.dumps({"replaced": report.replaced, "where": [s.where for s in report.slots]})
        for secret in (NAME, EMAIL, PHONE):
            assert secret not in blob


# -- end to end, over a real socket ----------------------------------------


class TestNothingSensitiveReachesTheUpstream:
    """The claim the whole library rests on, checked against the bytes."""

    def test_names_and_addresses_do_not_arrive(self) -> None:
        with FakeUpstream() as service:
            service.reply = completion("ok")
            with RunningProxy(service.url) as proxy:
                status, _ = proxy.post(chat(f"{NAME}さんへ {EMAIL} 電話は{PHONE}"))
        assert status == 200
        assert NAME not in service.raw
        assert EMAIL not in service.raw
        assert PHONE not in service.raw

    def test_placeholders_arrive_instead(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            proxy.post(chat(f"{NAME}さんへ"))
        assert "PERSON_001" in service.raw

    def test_the_english_side_too(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            proxy.post(chat("Dear Jane Doe, reach me at jane.doe@example.com"))
        assert "jane.doe@example.com" not in service.raw
        assert "Jane Doe" not in service.raw

    def test_the_caller_gets_their_own_values_back(self) -> None:
        with FakeUpstream() as service:
            service.reply = completion("<PERSON_001>さんに折り返します")
            with RunningProxy(service.url) as proxy:
                _, body = proxy.post(chat(f"{NAME}さんへ"))
        assert body["choices"][0]["message"]["content"] == f"{NAME}さんに折り返します"

    def test_the_callers_credential_is_forwarded(self) -> None:
        """The application keeps its own key; the proxy holds none."""
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            proxy.post(chat("hello"))
        assert service.headers[0].get("Authorization") == "Bearer sk-caller"

    def test_the_briefing_reaches_the_model(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            proxy.post(chat("hello"))
        assert service.received[0]["messages"][0]["role"] == "system"

    def test_the_model_and_other_parameters_survive(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            payload = chat("hello")
            payload["temperature"] = 0.4
            proxy.post(payload)
        assert service.received[0]["model"] == "gpt-4o"
        assert service.received[0]["temperature"] == 0.4


class TestFailingClosed:
    """Nothing may be forwarded because a check could not be completed."""

    def test_a_credential_blocks_the_request_and_forwards_nothing(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            status, body = proxy.post(chat(f"the key is {FAKE_AWS_KEY}"))
        assert status == 422
        assert service.received == [], "a blocked request must not reach the upstream"
        assert "blocked by policy" in body["error"]["message"]

    def test_the_refusal_does_not_quote_the_credential_back(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            _, body = proxy.post(chat(f"the key is {FAKE_AWS_KEY}"))
        assert FAKE_AWS_KEY not in json.dumps(body)

    def test_an_unknown_path_is_refused_rather_than_forwarded(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            request = urllib.request.Request(
                proxy.url.replace("/chat/completions", "/embeddings"),
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=10)
        assert caught.value.code == 404
        assert service.received == []

    def test_a_body_that_is_not_json_is_refused(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            request = urllib.request.Request(
                proxy.url,
                data=b"not json at all",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=10)
        assert caught.value.code == 400
        assert service.received == []

    def test_an_upstream_failure_becomes_a_gateway_error(self) -> None:
        with RunningProxy("http://127.0.0.1:1/v1/") as proxy:
            status, body = proxy.post(chat("hello"))
        assert status == 502
        assert "upstream" in body["error"]["message"]

    def test_an_upstream_error_does_not_leak_its_body(self) -> None:
        upstream = Upstream("http://127.0.0.1:1/v1/", timeout=2)
        with pytest.raises(UpstreamError) as caught:
            upstream.send("/v1/chat/completions", {"secret": EMAIL}, {})
        assert EMAIL not in str(caught.value)


class TestStreaming:
    """A placeholder arrives as ``<PER``, ``SON_0``, ``01>``."""

    @staticmethod
    def _content(lines: Iterator[str]) -> str:
        out = []
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("data:"):
                continue
            body = stripped[len("data:") :].strip()
            if body == "[DONE]":
                continue
            for choice in json.loads(body).get("choices", []):
                out.append(choice.get("delta", {}).get("content", ""))
        return "".join(out)

    def test_a_placeholder_split_across_chunks_is_restored(self) -> None:
        with FakeUpstream() as service:
            service.stream_chunks = ["こんにちは、", "<PER", "SON_0", "01>", "さんです。"]
            with RunningProxy(service.url) as proxy:
                text = self._content(proxy.post_stream(chat(f"{NAME}さんへ", stream=True)))
        assert text == f"こんにちは、{NAME}さんです。"

    def test_ordinary_streamed_text_passes_through_unchanged(self) -> None:
        with FakeUpstream() as service:
            service.stream_chunks = ["Hello", " there", ", friend."]
            with RunningProxy(service.url) as proxy:
                text = self._content(proxy.post_stream(chat("hi", stream=True)))
        assert text == "Hello there, friend."

    def test_the_request_still_arrives_protected(self) -> None:
        with FakeUpstream() as service:
            service.stream_chunks = ["ok"]
            with RunningProxy(service.url) as proxy:
                list(proxy.post_stream(chat(f"{NAME}さんへ", stream=True)))
        assert NAME not in service.raw


class TestBinding:
    def test_the_default_is_this_machine_only(self) -> None:
        assert ProxySettings(upstream="x").host == "127.0.0.1"
        assert not ProxySettings(upstream="x").is_public

    def test_a_public_bind_is_recognised_so_it_can_be_warned_about(self) -> None:
        assert ProxySettings(upstream="x", host="0.0.0.0").is_public  # noqa: S104

    def test_the_health_endpoint_answers(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            url = proxy.url.replace("/chat/completions", "").replace("/v1", "") + "/health"
            with urllib.request.urlopen(url, timeout=10) as response:
                assert json.loads(response.read())["status"] == "ok"


class TestNothingIsRetained:
    """One scope per request, discarded with it."""

    def test_two_requests_do_not_share_a_mapping(self) -> None:
        """A placeholder from one caller must not resolve for the next."""
        with FakeUpstream() as service:
            service.reply = completion("<PERSON_001> said so")
            with RunningProxy(service.url) as proxy:
                proxy.post(chat(f"{NAME}さんへ"))
                _, second = proxy.post(chat("nothing sensitive here"))
        assert second["choices"][0]["message"]["content"] == "<PERSON_001> said so"
