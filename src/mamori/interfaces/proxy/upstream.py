"""Forwarding a protected request to the service it was always going to.

The trust direction here is the opposite of everywhere else in this library,
and the inversion is worth stating plainly because it looks like a mistake.

:mod:`mamori.domain.trust` refuses to send text to a model outside your
network, because a *detector* is handed the document before it is protected: an
external detector is the leak. This upstream is the other case entirely. It is
the external service the caller already chose, and what reaches it has been
through detection and replacement. Sending to it is the point of the exercise,
so no boundary is applied and none should be.

What this module does care about is that nothing extra travels. It forwards the
caller's own credential rather than holding one, keeps no copy of any body, and
puts nothing from a request into an error message.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from http.client import HTTPResponse
from typing import Any
from urllib.parse import urlsplit

from ...errors import MamoriError

__all__ = ["Upstream", "UpstreamError", "UpstreamReply"]

#: Headers that describe the hop rather than the request. Re-sending them makes
#: the upstream answer a question about a connection that no longer exists.
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "content-length",
        "host",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "accept-encoding",
    }
)


class UpstreamError(MamoriError):
    """The upstream service could not be reached, or refused the request.

    Carries a status where there was one. Never carries a response body: the
    body of a failed completion can quote the prompt back, and the prompt is
    the protected text whose handling is the entire subject of this library.
    """

    def __init__(self, reason: str, status: int | None = None) -> None:
        super().__init__(f"upstream failed: {reason}")
        self.reason = reason
        self.status = status


@dataclass(frozen=True, slots=True)
class UpstreamReply:
    """A reply that has been read in full."""

    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except ValueError as exc:
            raise UpstreamError("reply was not JSON", self.status) from exc


@dataclass(frozen=True, slots=True)
class Upstream:
    """Where protected requests go.

    Args:
        base_url: The service the caller would have used directly.
        timeout: Seconds. Generous by default: a long completion behind a
            proxy is still a long completion, and a timeout here looks to the
            caller like the model failing.
        extra_headers: Sent with every request. For a deployment that reaches
            its provider through a gateway wanting its own header.
    """

    base_url: str
    timeout: float = 300.0
    extra_headers: Mapping[str, str] = field(default_factory=dict)

    def url_for(self, path: str) -> str:
        """Join the base URL with a path relative to it.

        ``base_url`` is the string the application already puts in its client,
        which by convention ends at the version segment --
        ``https://api.openai.com/v1/``. So the path appended here is relative
        (``chat/completions``), exactly as every OpenAI client appends it. A
        base URL with no path at all is the one common mistake worth absorbing:
        ``https://api.openai.com`` gets ``/v1`` added rather than producing a
        404 the caller has to work out for themselves.
        """
        base = self.base_url.rstrip("/")
        parsed = urlsplit(base)
        if not parsed.path:
            base = f"{base}/v1"
        return base + "/" + path.lstrip("/")

    def send(self, path: str, payload: object, headers: Mapping[str, str]) -> UpstreamReply:
        """Send and read the whole reply."""
        with self._open(path, payload, headers) as response:
            return UpstreamReply(
                status=response.status,
                headers=tuple(response.getheaders()),
                body=response.read(),
            )

    def stream(self, path: str, payload: object, headers: Mapping[str, str]) -> Iterator[bytes]:
        """Send, and yield the reply one line at a time as it arrives.

        Server-sent events are line-oriented, and a caller waiting on a
        streamed answer is waiting because the latency is the feature. Reading
        the whole body first would restore correctly and defeat the purpose.
        """
        with self._open(path, payload, headers) as response:
            yield from response

    def _open(self, path: str, payload: object, headers: Mapping[str, str]) -> HTTPResponse:
        body = json.dumps(payload).encode("utf-8")
        # The suppressions are safe because base_url is operator-supplied
        # configuration, not caller-supplied: a request cannot redirect its own
        # destination, and the scheme is whatever the operator configured.
        request = urllib.request.Request(  # noqa: S310
            self.url_for(path),
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                **{k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP},
                **dict(self.extra_headers),
            },
        )
        try:
            opened: HTTPResponse = urllib.request.urlopen(  # noqa: S310
                request, timeout=self.timeout
            )
            return opened
        except urllib.error.HTTPError as exc:
            # The status is useful and safe. The body is not: a provider that
            # echoes the prompt in its error would print the document here.
            raise UpstreamError(f"HTTP {exc.code}", exc.code) from exc
        except urllib.error.URLError as exc:
            raise UpstreamError(f"could not reach {self.base_url}") from exc
        except TimeoutError as exc:
            raise UpstreamError("timed out") from exc
