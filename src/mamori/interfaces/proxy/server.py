"""An OpenAI-compatible endpoint that protects what passes through it.

Nobody rewrites a working application to adopt a library. An application that
already talks to an OpenAI-compatible API moves behind this by changing one
string -- its ``base_url`` -- and gets detection, replacement and restoration
without a line of its own code changing.

Built on :mod:`http.server` from the standard library, because the runtime
dependencies of this package are zero and a privacy tool that pulls in a web
framework to be audited is a privacy tool that will not be audited. That choice
sets the ceiling honestly: this is sized for one team's traffic on one machine,
not for a datacentre. If it ever needs streaming concurrency at scale, the
right answer is a separate package with a real server in it, not a rewrite of
this one.

**It binds to 127.0.0.1.** Reaching it from another machine is a deliberate act
(``--host 0.0.0.0``) and never a default, because anything that can reach this
port can send documents through it and read the restored answers.

**It fails closed.** Detection raising, the policy refusing, a payload it
cannot parse: all of them are errors returned to the caller, and none of them
forward anything. The one thing that must never happen is text going upstream
because a check could not be completed.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ...config import MamoriConfig
from ...errors import DetectionError, MamoriError, PolicyViolationError
from .exchange import protect_request, restore_reply, restore_stream_chunk, summarise
from .upstream import Upstream, UpstreamError

__all__ = ["ProxySettings", "build_server", "serve"]

#: The one endpoint that matters, as callers address it. Everything else is
#: refused rather than forwarded blind: a path this does not understand is a
#: path whose payload it cannot promise to have protected.
CHAT_PATH = "/v1/chat/completions"

#: The same endpoint as the upstream addresses it -- relative to a base URL
#: that already ends at the version segment, the way every client appends it.
UPSTREAM_CHAT_PATH = "chat/completions"

#: The largest request body accepted, in bytes. A proxy that reads whatever it
#: is given can be made to hold a gigabyte in memory by one caller.
MAX_BODY_BYTES = 32 * 1024 * 1024

_SSE_DATA = b"data: "
_SSE_DONE = b"[DONE]"


@dataclass(frozen=True, slots=True)
class ProxySettings:
    """How the proxy is wired up."""

    #: Where protected requests go: the service the application used to call.
    upstream: str
    host: str = "127.0.0.1"
    port: int = 8100
    #: Settings for detection itself: locales, stance, policy, model.
    config: MamoriConfig = field(default_factory=MamoriConfig)
    #: Prepend a briefing telling the model to leave placeholders alone.
    guidance: bool = True
    timeout: float = 300.0
    #: Called with a one-line summary per request. Counts and types only.
    log: Callable[[str], None] | None = None

    @property
    def is_public(self) -> bool:
        """Whether this binding accepts connections from other machines."""
        return self.host not in ("127.0.0.1", "localhost", "::1")

    def url(self) -> str:
        host = "127.0.0.1" if self.host in ("0.0.0.0", "") else self.host  # noqa: S104
        return f"http://{host}:{self.port}/v1/"


class _Handler(BaseHTTPRequestHandler):
    """One request. Everything interesting happens in :mod:`.exchange`."""

    settings: ProxySettings
    upstream: Upstream
    server_version = "mamori"
    sys_version = ""

    def do_POST(self) -> None:  # http.server's naming, not ours
        if self.path.rstrip("/") != CHAT_PATH.rstrip("/"):
            # The one path that answers without reading the body, so it is the
            # one that has to read it anyway before replying.
            self._drain()
            self._fail(
                HTTPStatus.NOT_FOUND,
                f"mamori proxies {CHAT_PATH} only. A path it does not understand "
                "is a payload it cannot promise to have protected.",
            )
            return
        try:
            payload = self._read_payload()
        except _BadRequestError as exc:
            self._fail(HTTPStatus.BAD_REQUEST, str(exc))
            return

        streaming = bool(isinstance(payload, dict) and payload.get("stream"))
        try:
            self._exchange(payload, streaming=streaming)
        except PolicyViolationError as exc:
            # Fail closed, loudly. Nothing was forwarded.
            self._fail(HTTPStatus.UNPROCESSABLE_ENTITY, f"blocked by policy: {exc}")
        except DetectionError as exc:
            self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, f"detection failed: {exc}")
        except UpstreamError as exc:
            self._fail(HTTPStatus.BAD_GATEWAY, str(exc))
        except MamoriError as exc:
            self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_GET(self) -> None:
        """A liveness check, so a client can tell the proxy is up."""
        if self.path.rstrip("/") in ("/health", "/healthz"):
            self._json(HTTPStatus.OK, {"status": "ok", "proxies": CHAT_PATH})
            return
        self._fail(HTTPStatus.NOT_FOUND, "nothing here")

    # -- the exchange ------------------------------------------------------

    def _exchange(self, payload: object, *, streaming: bool) -> None:
        with self.settings.config.session() as session:
            protected, report = protect_request(
                session, payload, add_guidance=self.settings.guidance
            )
            self._log(summarise(report))
            headers = self._forwardable_headers()

            if streaming:
                self._stream(session, protected, headers)
            else:
                reply = self.upstream.send(UPSTREAM_CHAT_PATH, protected, headers)
                restored = restore_reply(session, reply.json())
                self._json(HTTPStatus(reply.status), restored)

    def _stream(self, session: Any, protected: object, headers: Mapping[str, str]) -> None:
        """Relay server-sent events, restoring as they pass.

        A placeholder arrives split across chunks, so one restorer spans the
        whole stream and holds back the shortest suffix that could still become
        one. Its held text is flushed when the stream ends.
        """
        restorer = session.stream_restore()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        for line in self.upstream.stream(UPSTREAM_CHAT_PATH, protected, headers):
            for out in _restored_event(line, restorer.feed):
                self.wfile.write(out)
                self.wfile.flush()

        tail = restorer.finish()
        if tail:
            self.wfile.write(_event({"choices": [{"delta": {"content": tail}}]}))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    # -- plumbing ----------------------------------------------------------

    def _read_payload(self) -> object:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise _BadRequestError("Content-Length was not a number") from exc
        if length <= 0:
            raise _BadRequestError("empty request body")
        if length > MAX_BODY_BYTES:
            raise _BadRequestError(f"request body over {MAX_BODY_BYTES} bytes")
        try:
            return json.loads(self.rfile.read(length))
        except ValueError as exc:
            raise _BadRequestError("request body was not JSON") from exc

    def _forwardable_headers(self) -> dict[str, str]:
        """The caller's own credential travels; nothing about this hop does."""
        keep = ("authorization", "openai-organization", "openai-project", "api-key")
        return {k: v for k, v in self.headers.items() if k.lower() in keep}

    def _json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _drain(self) -> None:
        """Read and discard the request body.

        A server that answers without reading what it was sent leaves bytes in
        the socket, and the client sees a reset connection instead of the
        refusal it was given. The body is discarded rather than parsed: this is
        for requests mamori will not forward, and reading it is about closing
        the exchange politely rather than about looking at it.

        Called only where the body has *not* already been read. Calling it
        after :meth:`_read_payload` would block waiting for bytes that have
        already arrived and been consumed.
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return
        remaining = min(max(length, 0), MAX_BODY_BYTES)
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            remaining -= len(chunk)

    def _fail(self, status: HTTPStatus, message: str) -> None:
        """An error in the shape OpenAI clients already know how to read."""
        self._log(f"refused: {message}")
        self._json(
            status,
            {"error": {"message": message, "type": "mamori_error", "code": status.value}},
        )

    def _log(self, message: str) -> None:
        if self.settings.log is not None:
            self.settings.log(message)

    def log_message(self, format: str, *args: Any) -> None:
        """Silence the default access log.

        It prints the request line, and a request line is a URL. Logging is
        opt-in through ``ProxySettings.log``, which is handed a summary that
        has never seen a protected value.
        """


class _BadRequestError(Exception):
    """The caller's payload could not be read."""


def _restored_event(line: bytes, restore: Callable[[str], str]) -> Iterator[bytes]:
    """Restore one line of a server-sent event stream.

    Anything that is not a data line -- a comment, a blank separator, the
    terminator -- is passed through untouched. The proxy is not trying to
    understand the protocol, only to rewrite the words in it.
    """
    stripped = line.strip()
    if not stripped.startswith(_SSE_DATA.strip()):
        yield line
        return
    body = stripped[len(_SSE_DATA.strip()) :].strip()
    if body == _SSE_DONE:
        return  # emitted once by the caller, after the held tail is flushed
    try:
        chunk = json.loads(body)
    except ValueError:
        yield line
        return
    yield _event(restore_stream_chunk(chunk, restore))


def _event(payload: object) -> bytes:
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n"


def build_server(settings: ProxySettings) -> ThreadingHTTPServer:
    """Create the server without starting it. Useful in tests."""
    handler = type(
        "MamoriProxyHandler",
        (_Handler,),
        {
            "settings": settings,
            "upstream": Upstream(settings.upstream, timeout=settings.timeout),
        },
    )
    return ThreadingHTTPServer((settings.host, settings.port), handler)


def serve(settings: ProxySettings) -> None:
    """Run until interrupted."""
    server = build_server(settings)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def serve_in_background(settings: ProxySettings) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start a server on its own thread and return it, for tests and embedding."""
    server = build_server(settings)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
