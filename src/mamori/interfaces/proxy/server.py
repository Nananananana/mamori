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

**It is sized for one team on one machine, and says so in numbers.** Protection
allocates roughly a hundred times the size of the text while it works -- most of
it transient, most of it detections rather than characters -- so the body cap is
a memory bound rather than a bandwidth one, and concurrent large requests
multiply it. See ``MAX_BODY_BYTES``.

**It holds nothing between requests unless it is asked to.** The default is
one scope per exchange, purged with the reply. A deployment whose clients keep
their history server-side can turn on conversations
(:mod:`mamori.application.conversations`), which names each one with a token it
mints itself and discards them on an idle timeout. What is being traded is a
real property, so it is a choice rather than a default.

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

from ...application.conversations import ConversationRegistry
from ...application.session import PrivacySession
from ...config import MamoriConfig
from ...errors import DetectionError, MamoriError, PolicyViolationError
from ...provenance import ProtectionLedger
from .exchange import StreamRestoration, protect_request, restore_reply, summarise
from .upstream import Upstream, UpstreamError

__all__ = ["END_HEADER", "SESSION_HEADER", "ProxySettings", "build_server", "serve"]

#: The one endpoint that matters, as callers address it. Everything else is
#: refused rather than forwarded blind: a path this does not understand is a
#: path whose payload it cannot promise to have protected.
CHAT_PATH = "/v1/chat/completions"

#: The same endpoint as the upstream addresses it -- relative to a base URL
#: that already ends at the version segment, the way every client appends it.
UPSTREAM_CHAT_PATH = "chat/completions"

#: The header a client echoes to stay in the same conversation, and the header
#: this sends back naming it. The value is minted here, never accepted from
#: outside: an identifier an outsider can choose is an identifier an outsider
#: can collide with, and the thing on the other side of it is a table of real
#: values. An unrecognised token quietly starts a new conversation.
SESSION_HEADER = "X-Mamori-Session"

#: Ending a conversation early, so a client that knows it is finished does not
#: have to wait out the idle timeout.
END_HEADER = "X-Mamori-Session-End"

#: The scope this reply's placeholders were allocated in, on every reply
#: that had one -- success, stream, and refusal alike. It is the join key to
#: the `protection-scope/1` records `--audit` writes, and it is minted here:
#: an orchestrator that named scopes itself would be choosing the key its
#: own audit trail is filed under, which is the oracle `X-Mamori-Session`
#: already refuses to hand out. Without `--conversations` a scope lives for
#: one request; with it, for the conversation, so the lines in the audit
#: file that carry it are that conversation's turns in order.
SCOPE_HEADER = "X-Mamori-Scope"

#: What this request replaced, as ``KIND=count`` pairs -- ``PERSON=2,EMAIL=1``
#: -- and nothing else. Enough for an orchestrator to say *"three values were
#: protected in this turn"* on a status line, without an endpoint that would
#: aggregate across conversations, which is a place one tenant's counts could
#: be read by another.
REPLACED_HEADER = "X-Mamori-Replaced"

#: The largest request body accepted, in bytes. A proxy that reads whatever it
#: is given can be made to hold a gigabyte in memory by one caller.
#:
#: Lowered from 32 MB to 8 MB in 0.23, once somebody measured what protecting a
#: large text actually costs. Reading the body is the cheap part: a 534 KB
#: document produces nine thousand detections, and the transient allocation
#: while resolving and rebuilding them peaks near **a hundred times** the size
#: of the text. At 32 MB that is gigabytes, from one request, on a server whose
#: whole design brief is "one team's traffic on one machine".
#:
#: 8 MB is still about two million tokens of text -- far past any model's
#: context window -- so the cap that protects the process does not constrain
#: any real prompt. If your payload genuinely exceeds it, the right answer is
#: to protect the documents separately rather than to raise this.
MAX_BODY_BYTES = 8 * 1024 * 1024

#: How long to spend discarding a body nobody will read. See :meth:`_drain`.
_DRAIN_SECONDS = 0.5

#: How long a connection may go without saying anything before it is dropped.
#:
#: `ThreadingHTTPServer` gives every connection a thread and keeps it until the
#: client is done, so a client that opens a socket, writes half a request line
#: and stops holds that thread indefinitely. Measured without this: 500 such
#: connections, 503 threads, and the count only stops where the operating
#: system does. Ordinary callers were still served instantly throughout, so
#: this is exhaustion rather than denial -- but it is exhaustion that costs
#: one socket per thread to cause.
#:
#: A minute, not a second. The deadline is on a *read that blocks*, and the
#: reads that block legitimately are a client writing a large body over a slow
#: link and a client that has stopped draining a stream. Sixty seconds of
#: either is a broken client already; sixty seconds of an upstream thinking
#: costs nothing here, because a proxy waiting on an upstream is not reading
#: from its caller.
DEFAULT_IDLE_TIMEOUT = 60.0

#: The longest chunk-size line this will read. A chunk header is a hexadecimal
#: number and perhaps an extension; anything approaching a kilobyte of it is a
#: caller trying to make the server hold a line it will never finish.
_MAX_CHUNK_HEADER = 1024

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
    #: How long a connection may block a read before it is dropped. Guards the
    #: thread, not the request: see :data:`DEFAULT_IDLE_TIMEOUT`.
    idle_timeout: float = DEFAULT_IDLE_TIMEOUT
    #: Called with a one-line summary per request. Counts and types only.
    log: Callable[[str], None] | None = None
    #: Hold mappings between requests when a client asks to. ``None`` -- the
    #: default -- is one scope per request and nothing kept, which is what
    #: makes "the proxy remembers nothing" a claim rather than a setting.
    conversations: ConversationRegistry | None = None
    #: Where a `protection-scope/1` record goes for every text this proxy
    #: protects, one per message slot, all carrying the scope the reply names
    #: in `X-Mamori-Scope`. ``None`` writes nothing. Strict, like the CLI's:
    #: a sink that cannot be written stops the request rather than answering
    #: with a hole in the trail the operator turned on.
    audit: ProtectionLedger | None = None

    @property
    def keeps_conversations(self) -> bool:
        return self.conversations is not None

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
    #: Applied to the connection by `socketserver` before `handle` runs, which
    #: is what makes it cover the request line and the headers -- the part of
    #: an exchange this class never gets to see. Replaced per server in
    #: :func:`build_server`.
    timeout = DEFAULT_IDLE_TIMEOUT

    #: The conversation this request belongs to, echoed on every reply it
    #: produces including the failures. A connection is reused for more than
    #: one request, so this is cleared where a request starts rather than
    #: where the handler is built.
    _token: str | None = None
    #: The scope of the session this request ran in, and what it replaced.
    #: Set as soon as a session exists, so a refusal that happens *after*
    #: allocation still names the scope its audit lines carry.
    _scope: str | None = None
    _replaced: dict[str, int] | None = None
    #: Whether the request body has been read to its end, so that a refusal
    #: does not spend the drain deadline discarding a body that is already
    #: gone. Half a second on every malformed request, for nothing.
    _body_consumed: bool = False

    def do_POST(self) -> None:  # http.server's naming, not ours
        self._token = None
        self._scope = None
        self._replaced = None
        self._body_consumed = False
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
            # Only when something is actually left. Whether an undrained body
            # costs the client its refusal was measured and does not, at least
            # here: 2 MB unread, and the `400` arrived either way. What it
            # does cost is the drain deadline, so the flag is about latency
            # rather than correctness and says so.
            if not self._body_consumed:
                self._drain()
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
        """A liveness check, so a client can tell the proxy is up.

        The per-request state is cleared here as it is in `do_POST`. Today
        `BaseHTTPRequestHandler` speaks HTTP/1.0 and closes after each reply,
        so one handler serves one request and there is nothing to clear --
        which is exactly why it is cleared: the property "a reply names its
        own scope and no other" would otherwise be true because of a default
        nobody wrote down, and a later `protocol_version = "HTTP/1.1"` for
        keep-alive would put a previous request's scope on a health check.
        """
        self._token = None
        self._scope = None
        self._replaced = None
        if self.path.rstrip("/") in ("/health", "/healthz"):
            self._json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "proxies": CHAT_PATH,
                    # Whether it keeps anything, never how much or for whom.
                    "conversations": self.settings.keeps_conversations,
                },
            )
            return
        self._fail(HTTPStatus.NOT_FOUND, "nothing here")

    # -- the exchange ------------------------------------------------------

    def _exchange(self, payload: object, *, streaming: bool) -> None:
        registry = self.settings.conversations
        if registry is None:
            # The default, and the one that needs no qualification: one scope,
            # used once, purged on the way out of this block.
            with self.settings.config.session() as session:
                self._scope = session.scope
                self._run(session, payload, streaming=streaming)
            return

        # `checkout` rather than `resume`: while this block runs, neither the
        # idle sweep nor an eviction another request triggers can purge this
        # conversation's scope. They could, and did -- 4 of 12 concurrent
        # callers got a raw placeholder back for a name they had just sent.
        with registry.checkout(self.headers.get(SESSION_HEADER)) as conversation:
            self._token = conversation.token
            self._scope = conversation.session.scope
            try:
                self._run(conversation.session, payload, streaming=streaming)
            finally:
                if _is_true(self.headers.get(END_HEADER)):
                    registry.end(conversation.token)
                    self._log("conversation ended by the client")

    def _run(self, session: PrivacySession, payload: object, *, streaming: bool) -> None:
        protected, report = protect_request(session, payload, add_guidance=self.settings.guidance)
        self._replaced = dict(report.replaced)
        self._log(summarise(report))
        if self.settings.audit is not None:
            # After protection and before anything goes upstream: a record
            # that says a protection happened, written once it has, and never
            # for a request the next line refuses to forward.
            for result in report.results:
                self.settings.audit.record(result, session=session)
        headers = self._forwardable_headers()

        if streaming:
            self._stream(session, protected, headers)
        else:
            reply = self.upstream.send(UPSTREAM_CHAT_PATH, protected, headers)
            restored = restore_reply(session, reply.json())
            # The status is relayed as the integer it is, and **not** through
            # `HTTPStatus(...)`. That call raises `ValueError` on any code the
            # enum does not know -- 299, 218, whatever a gateway or a future
            # standard invents -- and the exception escaped `do_POST`, which
            # handles `MamoriError` and nothing else. Measured: the connection
            # closed with no response at all, so a caller saw
            # `RemoteDisconnected` and could not tell a protected answer that
            # arrived from a network that failed. Only a 2xx reaches here (the
            # rest becomes `UpstreamError` upstream), so the codes this broke
            # on were successful replies being thrown away.
            self._json(reply.status, restored)

    def _stream(
        self, session: PrivacySession, protected: object, headers: Mapping[str, str]
    ) -> None:
        """Relay server-sent events, restoring as they pass.

        A placeholder arrives split across chunks, so a restorer spans the whole
        stream and holds back the shortest suffix that could still become one.
        A reply has more than one run of text in it -- the prose, and one per
        tool call -- and each needs its own held suffix, which is what
        :class:`StreamRestoration` keeps. Whatever is still held when the model
        stops is flushed as a final chunk per run.
        """
        restoration = StreamRestoration(session)

        # The generator is lazy, so nothing has been sent upstream yet. Pull
        # the first line **before** the status line goes out: the upstream
        # connection is opened by that pull, and an `UpstreamError` from it
        # used to surface after `200 OK` and `Content-Type: text/event-stream`
        # were already on the wire. `do_POST` then wrote a second, complete
        # HTTP response into the body of the first -- measured, two status
        # lines in one response. An OpenAI client sees a successful stream
        # whose first event is unparseable and never learns the upstream
        # failed.
        lines = self.upstream.stream(UPSTREAM_CHAT_PATH, protected, headers)
        first = next(lines, None)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self._send_token()
        self.end_headers()

        for line in [] if first is None else [first, *lines]:
            for out in _restored_event(line, restoration.feed):
                self.wfile.write(out)
                self.wfile.flush()

        for trailing in restoration.finish():
            self.wfile.write(_event(trailing))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    # -- plumbing ----------------------------------------------------------

    def _read_payload(self) -> object:
        """The request body, however the client chose to frame it.

        **Chunked bodies are read, not refused.** `Transfer-Encoding: chunked`
        is ordinary HTTP/1.1 -- httpx sends it whenever the body is an
        iterator, which is what the OpenAI SDK does for a streamed upload --
        and this used to look only at `Content-Length`, find none, and call
        the body empty. The refusal was then written while the client was
        still sending, so the client's write failed and it saw a reset
        connection rather than the `400` it had been given. That is the same
        shape as the `HTTPStatus` bug: a failure an orchestrator cannot tell
        from a network fault.
        """
        body = self._read_chunked() if self._is_chunked() else self._read_measured()
        self._body_consumed = True
        try:
            return json.loads(body)
        except ValueError as exc:
            raise _BadRequestError("request body was not JSON") from exc

    def _is_chunked(self) -> bool:
        return "chunked" in (self.headers.get("Transfer-Encoding") or "").lower()

    def _read_measured(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise _BadRequestError("Content-Length was not a number") from exc
        if length <= 0:
            raise _BadRequestError("empty request body")
        if length > MAX_BODY_BYTES:
            raise _BadRequestError(f"request body over {MAX_BODY_BYTES} bytes")
        return self.rfile.read(length)

    def _read_chunked(self) -> bytes:
        """Reassemble a chunked body, under the same ceiling as a measured one.

        The cap is checked as the chunks arrive rather than from a header,
        because a chunked body announces no total -- which is exactly why a
        proxy that reads one has to count.
        """
        pieces: list[bytes] = []
        total = 0
        while True:
            line = self.rfile.readline(_MAX_CHUNK_HEADER + 1)
            if not line:
                raise _BadRequestError("the chunked body ended early")
            if len(line) > _MAX_CHUNK_HEADER:
                raise _BadRequestError("a chunk header was implausibly long")
            try:
                # A chunk size may carry extensions after a semicolon.
                size = int(line.split(b";", 1)[0].strip() or b"0", 16)
            except ValueError as exc:
                raise _BadRequestError("a chunk size was not hexadecimal") from exc
            if size < 0:
                raise _BadRequestError("a chunk size was negative")
            if size == 0:
                break
            total += size
            if total > MAX_BODY_BYTES:
                raise _BadRequestError(f"request body over {MAX_BODY_BYTES} bytes")
            piece = self.rfile.read(size)
            if len(piece) != size:
                raise _BadRequestError("the chunked body ended early")
            pieces.append(piece)
            self.rfile.read(2)  # the CRLF that closes a chunk

        # Trailers, then the blank line. Read and discarded: a trailer is a
        # header, and this forwards none of the caller's own.
        while True:
            trailer = self.rfile.readline(_MAX_CHUNK_HEADER + 1)
            if not trailer or trailer in (b"\r\n", b"\n"):
                break
        if not pieces:
            raise _BadRequestError("empty request body")
        return b"".join(pieces)

    def _forwardable_headers(self) -> dict[str, str]:
        """The caller's own credential travels; nothing about this hop does."""
        keep = ("authorization", "openai-organization", "openai-project", "api-key")
        return {k: v for k, v in self.headers.items() if k.lower() in keep}

    def _json(self, status: int | HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_token()
        self.end_headers()
        self.wfile.write(body)

    def _drain(self) -> None:
        """Read and discard whatever the client is still sending, briefly.

        **Bounded, and the bound is the point.** A chunked body announces its
        end with a zero-length chunk, so draining one means reading until that
        arrives -- and a client that sent a partial chunk and stopped never
        sends it. Measured: a `POST` to an unproxied path carrying
        `ff\\r\\nshort` and then silence got **no reply at all in eight
        seconds** without this deadline, with the handler thread parked in
        `readline`. Enough such requests and there are no threads left. With
        the deadline the `404` arrives in half a second.

        A chunked body has no length to read to, so it is drained by reading
        until the terminating zero-length chunk, under the same header cap.

        A server that answers without reading what it was sent leaves bytes in
        the socket, and the client sees a reset connection instead of the
        refusal it was given. The body is discarded rather than parsed: this is
        for requests mamori will not forward, and reading it is about closing
        the exchange politely rather than about looking at it.

        Called only where the body has *not* already been read. Calling it
        after :meth:`_read_payload` would block waiting for bytes that have
        already arrived and been consumed.
        """
        original = self.connection.gettimeout()
        self.connection.settimeout(_DRAIN_SECONDS)
        try:
            self._drain_within_deadline()
        except (TimeoutError, OSError):
            # The client stopped sending, or the socket is already gone.
            # Either way the reply below is the best that can be done.
            pass
        finally:
            self.connection.settimeout(original)

    def _drain_within_deadline(self) -> None:
        if self._is_chunked():
            self._drain_chunked()
            return
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

    def _drain_chunked(self) -> None:
        """Read a chunked body to its terminator, discarding it."""
        read = 0
        while read < MAX_BODY_BYTES:
            line = self.rfile.readline(_MAX_CHUNK_HEADER + 1)
            if not line or len(line) > _MAX_CHUNK_HEADER:
                return
            try:
                size = int(line.split(b";", 1)[0].strip() or b"0", 16)
            except ValueError:
                return
            if size <= 0:
                break
            if not self.rfile.read(size):
                return
            self.rfile.read(2)
            read += size
        while True:
            trailer = self.rfile.readline(_MAX_CHUNK_HEADER + 1)
            if not trailer or trailer in (b"\r\n", b"\n"):
                return

    def _fail(self, status: HTTPStatus, message: str) -> None:
        """An error in the shape OpenAI clients already know how to read."""
        self._log(f"refused: {message}")
        self._json(
            status,
            {"error": {"message": message, "type": "mamori_error", "code": status.value}},
        )

    def _send_token(self) -> None:
        """Name the conversation, the scope, and what was replaced -- when known.

        On every reply, refusals included: a `422` for a blocked credential
        still names the scope whose audit lines say what was allocated before
        the block, and an orchestrator mapping that refusal to *"a credential
        stopped this"* wants exactly that join.
        """
        if self._token is not None:
            self.send_header(SESSION_HEADER, self._token)
        if self._scope is not None:
            self.send_header(SCOPE_HEADER, self._scope)
        if self._replaced:
            pairs = ",".join(f"{kind}={count}" for kind, count in sorted(self._replaced.items()))
            self.send_header(REPLACED_HEADER, pairs)

    def _log(self, message: str) -> None:
        if self.settings.log is not None:
            self.settings.log(message)

    def log_message(self, format: str, *args: Any) -> None:
        """Silence the default access log.

        It prints the request line, and a request line is a URL. Logging is
        opt-in through ``ProxySettings.log``, which is handed a summary that
        has never seen a protected value.
        """


def _is_true(header: str | None) -> bool:
    """Read a header a human typed. Anything but a clear yes is a no."""
    return (header or "").strip().lower() in ("1", "true", "yes", "on")


class _BadRequestError(Exception):
    """The caller's payload could not be read."""


def _restored_event(line: bytes, restore: Callable[[object], dict[str, Any]]) -> Iterator[bytes]:
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
        return  # emitted once by the caller, after the held tails are flushed
    try:
        chunk = json.loads(body)
    except ValueError:
        yield line
        return
    yield _event(restore(chunk))


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
            "timeout": settings.idle_timeout,
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
