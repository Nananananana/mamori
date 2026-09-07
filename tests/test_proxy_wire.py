"""What a real client puts on the wire, and whether the proxy reads it.

Everything else in this repository speaks to the proxy through `urllib`, which
always sends a `Content-Length`. An OpenAI SDK does not: it is built on
`httpx`, and `httpx` frames the body as `Transfer-Encoding: chunked` whenever
it is given an iterator. That request used to fail, and it failed in the shape
this proxy has now been caught in twice -- **the connection died with no
response**, so a caller saw a reset socket rather than the refusal it had
actually been given.

The mechanism: `_read_payload` looked only at `Content-Length`, found none,
called the body empty, and refused a request that was perfectly well formed.
Chunked bodies are read now, and every refusal below has to arrive as a
refusal rather than as a closed socket.

The drain has a deadline, and the reason is not the one to guess. Whether an
undrained body costs a client its refusal was measured -- 2 MB left unread,
and the `400` arrived either way. What an *unbounded* drain costs is the
thread: a partial chunked body never sends its terminator, and the handler
waits for it forever. `TestAPartialBodyDoesNotHoldAThread` is that.

These use a raw socket rather than a client library, so they run wherever the
suite runs and so that the bytes under test are the ones written here.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any

import pytest

from .test_proxy import FakeUpstream, RunningProxy, chat, completion

EMAIL = "tanaka@example.com"


def address(proxy: RunningProxy) -> tuple[str, int]:
    host, port = proxy.url.split("//")[1].split("/")[0].split(":")
    return host, int(port)


def send_raw(proxy: RunningProxy, request: bytes, *, timeout: float = 10) -> bytes:
    """Write exactly these bytes and read the whole reply."""
    host, port = address(proxy)
    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.sendall(request)
        received = b""
        while True:
            piece = connection.recv(65536)
            if not piece:
                break
            received += piece
    return received


def chunked_request(
    body: bytes, *, sizes: tuple[int, ...] = (17,), path: str = "/v1/chat/completions"
) -> bytes:
    """A POST whose body is framed in chunks of the given sizes, cycling."""
    parts = []
    index = 0
    step = 0
    while index < len(body):
        size = sizes[step % len(sizes)]
        piece = body[index : index + size]
        parts.append(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
        index += size
        step += 1
    parts.append(b"0\r\n\r\n")
    head = (
        f"POST {path} HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        "Content-Type: application/json\r\n"
        "Transfer-Encoding: chunked\r\n"
        "Connection: close\r\n\r\n"
    ).encode()
    return head + b"".join(parts)


def status_of(reply: bytes) -> int:
    return int(reply.split(b" ", 2)[1])


def body_of(reply: bytes) -> Any:
    head, _, body = reply.partition(b"\r\n\r\n")
    assert b"Transfer-Encoding" not in head or b"chunked" not in head, "reply was chunked"
    return json.loads(body)


class TestAChunkedRequestBodyIsRead:
    """`Transfer-Encoding: chunked` is what an SDK sends for a streamed upload."""

    @pytest.mark.parametrize("sizes", [(1,), (17,), (4096,), (3, 1, 200)], ids=str)
    def test_the_body_is_reassembled_whatever_the_chunking(self, sizes: tuple[int, ...]) -> None:
        payload = json.dumps(chat(f"Mail {EMAIL}")).encode()
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            service.reply = completion("Mailed <EMAIL_001>.")
            reply = send_raw(proxy, chunked_request(payload, sizes=sizes))

        assert status_of(reply) == 200, reply[:200]
        answer = body_of(reply)
        assert answer["choices"][0]["message"]["content"] == f"Mailed {EMAIL}."
        assert EMAIL not in json.dumps(service.received), "the address went upstream"

    def test_the_value_is_still_protected(self) -> None:
        payload = json.dumps(chat(f"Mail {EMAIL} and call Jane Doe")).encode()
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            service.reply = completion("ok")
            send_raw(proxy, chunked_request(payload))
        sent = json.dumps(service.received, ensure_ascii=False)
        assert EMAIL not in sent
        assert "Jane Doe" not in sent
        assert "<EMAIL_001>" in sent

    def test_chunk_extensions_are_tolerated(self) -> None:
        """`1a;name=value` is a legal chunk header."""
        payload = json.dumps(chat("hello")).encode()
        head = (
            b"POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n"
            b"Connection: close\r\n\r\n"
        )
        framed = f"{len(payload):x};note=first\r\n".encode() + payload + b"\r\n0\r\n\r\n"
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            service.reply = completion("ok")
            reply = send_raw(proxy, head + framed)
        assert status_of(reply) == 200, reply[:200]


class TestARefusalReachesTheClient:
    """The other half of the same bug: a `400` written while the caller is
    still sending makes the caller's write fail, and it sees a reset socket
    rather than the reason. Every refusal below has to arrive as a refusal."""

    @pytest.mark.parametrize(
        ("name", "body"),
        [
            ("not JSON", b"not json at all"),
            ("empty", b""),
        ],
        ids=lambda value: value if isinstance(value, str) else "",
    )
    def test_a_bad_chunked_body_is_answered_not_dropped(self, name: str, body: bytes) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            reply = send_raw(proxy, chunked_request(body))
        assert reply, f"{name}: the connection closed with no response at all"
        assert status_of(reply) == 400, reply[:200]
        assert body_of(reply)["error"]["type"] == "mamori_error"
        assert not service.received

    def test_a_body_that_ends_early_is_answered(self) -> None:
        """The chunk header promises more than the client sends."""
        head = (
            b"POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n"
            b"Connection: close\r\n\r\n"
        )
        with FakeUpstream() as _, RunningProxy("http://127.0.0.1:1/v1/") as proxy:
            host, port = address(proxy)
            with socket.create_connection((host, port), timeout=10) as connection:
                connection.sendall(head + b"ff\r\nshort")
                connection.shutdown(socket.SHUT_WR)
                received = b""
                while True:
                    piece = connection.recv(65536)
                    if not piece:
                        break
                    received += piece
        assert received, "the connection closed with no response at all"
        assert status_of(received) == 400, received[:200]

    def test_a_chunk_size_that_is_not_hexadecimal_is_answered(self) -> None:
        head = (
            b"POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n"
            b"Connection: close\r\n\r\n"
        )
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            reply = send_raw(proxy, head + b"zz\r\nhello\r\n0\r\n\r\n")
        assert reply, "the connection closed with no response at all"
        assert status_of(reply) == 400, reply[:200]
        assert not service.received

    def test_a_chunked_body_over_the_ceiling_is_refused(self) -> None:
        """A chunked body announces no total, so the cap is counted as the
        chunks arrive. Sent as a header that claims more than the ceiling, so
        the test does not have to write eight megabytes to prove it."""
        head = (
            b"POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n"
            b"Connection: close\r\n\r\n"
        )
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            reply = send_raw(proxy, head + b"1000000\r\n" + b"x" * 64)
        assert reply, "the connection closed with no response at all"
        assert status_of(reply) == 400, reply[:200]
        assert b"over" in reply
        assert not service.received


class TestTheSdkClientItself:
    """The same ground through `httpx`, which is what the OpenAI SDK uses.

    Skipped where `httpx` is not installed -- it is not a dependency of this
    library and must not become one. The raw-socket tests above are the ones
    that run everywhere; this is the check that the bytes assumed there are
    the bytes a real client writes.
    """

    def test_an_iterator_body_works(self) -> None:
        httpx = pytest.importorskip("httpx")
        payload = json.dumps(chat(f"Mail {EMAIL}")).encode()

        def pieces() -> Any:
            yield payload[:20]
            yield payload[20:]

        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            service.reply = completion("Mailed <EMAIL_001>.")
            with httpx.Client(timeout=10) as client:
                response = client.post(
                    proxy.url, content=pieces(), headers={"Content-Type": "application/json"}
                )
        assert response.status_code == 200
        assert response.json()["choices"][0]["message"]["content"] == f"Mailed {EMAIL}."

    def test_streaming_reads_back_restored(self) -> None:
        httpx = pytest.importorskip("httpx")
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            service.stream_chunks = ["Mailed <EMA", "IL_001>.", " Done."]
            with httpx.Client(timeout=10) as client:
                with client.stream(
                    "POST", proxy.url, json=chat(f"Mail {EMAIL}", stream=True)
                ) as response:
                    events = [line for line in response.iter_lines() if line.startswith("data: ")]
        text = "".join(
            json.loads(event[6:])["choices"][0]["delta"].get("content", "")
            for event in events
            if event[6:] != "[DONE]"
        )
        assert text == f"Mailed {EMAIL}. Done."


class TestAPartialBodyDoesNotHoldAThread:
    """The drain has a deadline, and this is what the deadline is for.

    A chunked body ends with a zero-length chunk. Draining one means reading
    until that arrives -- and a client that sends a partial chunk and stops
    never sends it. Measured without the deadline: a `POST` to an unproxied
    path carrying `ff\r\nshort` and then silence got **no reply in eight
    seconds**, the handler thread parked in `readline`. Enough of those and
    there are no threads left to serve anybody.

    Nothing here is about being polite to that client. It is about the next
    caller still having a thread.
    """

    def test_an_unproxied_path_with_a_truncated_body_still_answers(self) -> None:
        head = (
            b"POST /v1/embeddings HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n"
            b"Connection: close\r\n\r\n"
        )
        with FakeUpstream() as _unused, RunningProxy("http://127.0.0.1:1/v1/") as proxy:
            host, port = address(proxy)
            with socket.create_connection((host, port), timeout=5) as connection:
                connection.sendall(head + b"ff\r\nshort")
                received = connection.recv(65536)
        assert received, "no reply within five seconds: the thread is parked in the drain"
        assert status_of(received) == 404

    def test_the_thread_is_free_again_afterwards(self) -> None:
        """The failure this guards is exhaustion, so the check is that the
        server still serves -- not that one caller was answered."""
        head = (
            b"POST /v1/embeddings HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n"
            b"Connection: close\r\n\r\n"
        )
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            service.reply = completion("ok")
            host, port = address(proxy)
            for _ in range(4):
                with socket.create_connection((host, port), timeout=5) as connection:
                    connection.sendall(head + b"ff\r\nshort")
                    connection.recv(65536)
            reply = send_raw(proxy, chunked_request(json.dumps(chat("hello")).encode()))
        assert status_of(reply) == 200, reply[:200]


class TestAnIdleConnectionDoesNotKeepAThread:
    """`ThreadingHTTPServer` gives every connection a thread and holds it
    until the client is done, so a client that opens a socket, writes half a
    request line and stops holds that thread indefinitely.

    Measured before the deadline existed: 500 such connections, 503 threads,
    and the count only stopping where the operating system does. Ordinary
    callers were served instantly throughout, so this is exhaustion rather
    than denial -- but it costs one socket per thread to cause, and it is the
    same shape as the drain hang above: a thread parked on a client that will
    never speak again.
    """

    def test_a_half_written_request_is_dropped(self) -> None:
        started = threading.active_count()
        with FakeUpstream() as service, RunningProxy(service.url, idle_timeout=1.0) as proxy:
            service.reply = completion("ok")
            host, port = address(proxy)
            held = [socket.create_connection((host, port), timeout=5) for _ in range(20)]
            try:
                for connection in held:
                    connection.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\n")
                deadline = time.monotonic() + 1.0
                peak = started
                while time.monotonic() < deadline:
                    peak = max(peak, threading.active_count())
                    time.sleep(0.05)
                assert peak >= started + 10, f"only {peak - started} threads: nothing was held"

                settled = time.monotonic() + 8.0
                while time.monotonic() < settled and threading.active_count() > started + 2:
                    time.sleep(0.1)
                assert threading.active_count() <= started + 2, (
                    f"{threading.active_count() - started} threads still held a minute after "
                    "the deadline; an idle connection keeps its thread"
                )
            finally:
                for connection in held:
                    connection.close()

    def test_an_upstream_slower_than_the_deadline_still_streams(self) -> None:
        """The deadline is on a read that blocks, and a proxy waiting for an
        upstream is not reading from its caller. Measured: 2.5 seconds of
        upstream silence against a 1 second deadline."""
        with FakeUpstream() as service, RunningProxy(service.url, idle_timeout=1.0) as proxy:
            service.stream_chunks = ["Mailed <EMA", "IL_001>.", " Done."]
            service.first_delay = 2.5
            text = self._stream(proxy)
        assert text == f"Mailed {EMAIL}. Done."

    def test_a_reader_slower_than_the_deadline_still_gets_the_whole_stream(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url, idle_timeout=1.0) as proxy:
            service.stream_chunks = ["Mailed <EMA", "IL_001>.", " Done."]
            text = self._stream(proxy, pause=1.5)
        assert text == f"Mailed {EMAIL}. Done."

    @staticmethod
    def _stream(proxy: RunningProxy, *, pause: float = 0.0) -> str:
        import urllib.request

        request = urllib.request.Request(
            proxy.url,
            data=json.dumps(chat(f"Mail {EMAIL}", stream=True)).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        text = ""
        with urllib.request.urlopen(request, timeout=30) as response:
            for raw in response:
                if pause:
                    time.sleep(pause)
                line = raw.decode()
                if line.startswith("data: ") and "[DONE]" not in line:
                    text += json.loads(line[6:])["choices"][0]["delta"].get("content", "")
        return text
