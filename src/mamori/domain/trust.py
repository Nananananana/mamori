"""Where a detector is allowed to live.

A detector sees the text **before** it is protected. That is not an
implementation detail -- it means the endpoint a detector talks to receives
every document in the clear, and a detector pointed at the wrong place is not a
detector but the leak itself.

The first version of this rule said "localhost or nothing", which was wrong. A
company running a model on a GPU box in its own server room is doing exactly
what this library is for, and the box is not localhost. The question was never
*which machine*; it is **which side of the trust boundary**.

So the boundary is declared rather than inferred:

    SAME_HOST         only this machine
    PRIVATE_NETWORK   this machine, or somewhere on the internal network
    ANYWHERE          no check; you have said you know what you are doing

``PRIVATE_NETWORK`` is the default, because both shapes of the intended
deployment -- a model on the user's laptop, a model on the company's server --
fall inside it, and a public API endpoint does not.

**This is a seatbelt, not a security boundary.** The real boundary is your
network. What this catches is the accident: a base URL copied from a vendor's
quickstart, a staging config that reached production. It classifies by hostname
and literal address without asking DNS, so a name that resolves somewhere
surprising will pass. Pair it with egress rules if the outcome matters.

What it will no longer do is classify a *different host* than the one the
request goes to. That was the 0.34 defect: the client normalises a URL before
resolving it, this module did not, and three Unicode characters that IDNA
turns into label separators were enough to make `api。openai。com` look
like a single-label internal name. See ``_normalise``.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse

__all__ = ["EndpointPolicy", "HostKind", "TrustBoundary", "classify_host"]


class HostKind(Enum):
    """What kind of place a hostname points at, as far as can be told locally."""

    #: 127.0.0.1, ::1, localhost.
    LOOPBACK = "loopback"
    #: An RFC 1918 or equivalent address, or a name that only exists on an
    #: internal network: a single-label hostname, or one under .internal,
    #: .corp, .local, .lan, .intranet, .home.arpa.
    PRIVATE = "private"
    #: Named by the operator in ``trusted_hosts``.
    DECLARED = "declared"
    #: Everything else. Which mostly means the public internet.
    EXTERNAL = "external"


class TrustBoundary(Enum):
    """How far a detector endpoint may be from this machine."""

    SAME_HOST = "same_host"
    #: The default. Covers a model on this laptop and a model on the company's
    #: GPU server, and refuses a public API endpoint.
    PRIVATE_NETWORK = "private_network"
    #: No check. For a deployment whose boundary this module cannot see -- a
    #: mesh VPN, a private link, an operator who has thought about it.
    ANYWHERE = "anywhere"

    def admits(self, kind: HostKind) -> bool:
        """Whether a host of this kind sits inside the boundary."""
        if self is TrustBoundary.ANYWHERE:
            return True
        if kind is HostKind.DECLARED:
            return True
        if self is TrustBoundary.SAME_HOST:
            return kind is HostKind.LOOPBACK
        return kind in (HostKind.LOOPBACK, HostKind.PRIVATE)


#: Suffixes that only exist inside an organisation. ``.local`` is mDNS,
#: ``.home.arpa`` is the RFC 8375 home network name, the rest are conventional.
_PRIVATE_SUFFIXES = (
    ".internal",
    ".intranet",
    ".corp",
    ".local",
    ".lan",
    ".home.arpa",
    ".localdomain",
    ".test",
)

_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain"})

#: Docker's name for the host it runs on. Loopback in every way that matters.
_HOST_ALIASES = frozenset({"host.docker.internal", "host.containers.internal"})

#: The three characters IDNA maps onto the label separator. A name written
#: with any of them has more labels than a split on ASCII "." can see, and the
#: single-label rule below then calls a public name internal.
#:
#: Measured, not guessed: ``httpx.URL("http://api\u3002openai\u3002com/").host``
#: is ``api.openai.com``, and the default boundary used to admit it.
_SEPARATORS = str.maketrans({"\u3002": ".", "\uff0e": ".", "\uff61": "."})

#: Everything a hostname may contain once it has been normalised. Anything
#: else -- a lookalike letter, a percent-escape, whitespace -- is a name this
#: module cannot vouch for, and an operator who really has one can name it in
#: ``trusted_hosts``.
_HOST_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-_")


def _normalise(host: str) -> str:
    """Read ``host`` the way the HTTP client will, before classifying it.

    The gap between the two readings is the whole defect this closes: a
    config file spells one host, the client sends to another, and the check
    ran against the spelling.
    """
    name = host.strip().strip("[]").translate(_SEPARATORS).lower()
    # A trailing dot is the root label written out. `localhost.` is localhost.
    if len(name) > 1 and name.endswith("."):
        name = name[:-1]
    return name


def _is_an_address_notation(name: str) -> bool:
    """Whether ``name``'s last label is numeric, so it is an address.

    ``inet_aton`` reads ``2130706433``, ``0177.0.0.1``, ``0x7f.1`` and
    ``127.1`` as 127.0.0.1, and glibc's resolver tries ``inet_aton`` before
    DNS -- so on Linux these forms connect. None of them parse as an address
    here, so they used to fall through to the rule that a name without dots
    cannot be public, and ``1560984610`` -- a public address -- came out
    private.

    This module does not decode them. RFC 1123 forbids an all-numeric final
    label in a hostname, so a name shaped like this is an address in some
    notation, and saying so is better than guessing which one.
    """
    last = name.rsplit(".", 1)[-1]
    if last.startswith(("0x", "0X")):
        return True
    return last.isascii() and last.isdigit()


def classify_host(host: str, trusted_hosts: frozenset[str] = frozenset()) -> HostKind:
    """Say what kind of place ``host`` is, without asking DNS.

    Args:
        host: A hostname or literal address, without scheme or port.
        trusted_hosts: Names the operator has declared trusted. Matched
            case-insensitively and exactly -- no wildcards, because a wildcard
            in a trust list is how ``*.example.com`` ends up including a
            hostname somebody else controls.
    """
    name = _normalise(host)
    if not name:
        return HostKind.EXTERNAL
    if name in {_normalise(h) for h in trusted_hosts}:
        return HostKind.DECLARED
    if name in _LOOPBACK_NAMES or name in _HOST_ALIASES:
        return HostKind.LOOPBACK

    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        pass
    else:
        if address.is_loopback:
            return HostKind.LOOPBACK
        if address.is_private or address.is_link_local:
            return HostKind.PRIVATE
        return HostKind.EXTERNAL

    # Past this point the name is not an address, so anything that still
    # looks like one is a notation this module refused to decode.
    if _is_an_address_notation(name):
        return HostKind.EXTERNAL
    if not set(name) <= _HOST_CHARACTERS:
        return HostKind.EXTERNAL

    if name.endswith(_PRIVATE_SUFFIXES):
        return HostKind.PRIVATE
    if "." not in name:
        # A single-label name resolves through the local search domain, so it
        # cannot be a public host. This is the common in-house case: the box is
        # just called `llm01`.
        return HostKind.PRIVATE
    return HostKind.EXTERNAL


@dataclass(frozen=True, slots=True)
class EndpointPolicy:
    """Which endpoints a detector may talk to.

    Args:
        boundary: How far away the endpoint may be.
        trusted_hosts: Extra names to admit whatever the boundary. For an
            internal host whose name looks public -- ``llm.example.com``
            resolving to a machine in your own rack.
    """

    boundary: TrustBoundary = TrustBoundary.PRIVATE_NETWORK
    trusted_hosts: frozenset[str] = field(default_factory=frozenset)

    def classify(self, url: str) -> HostKind:
        """Classify the host in ``url``."""
        return classify_host(urlparse(url).hostname or "", self.trusted_hosts)

    def admits(self, url: str) -> bool:
        """Whether ``url`` sits inside this boundary."""
        return self.boundary.admits(self.classify(url))

    def explain(self, url: str) -> str:
        """Why ``url`` was refused, and what to do about it.

        An error that only says "refused" gets worked around with whatever
        flag makes it stop. One that says what the rule is gets read.
        """
        host = urlparse(url).hostname or url
        kind = self.classify(url)
        return (
            f"{host!r} looks {kind.value}, which is outside the "
            f"{self.boundary.value} trust boundary.\n"
            "A detector is sent the text *before* it is protected, so this "
            "endpoint would receive every document in the clear.\n"
            "If it is inside your network, add it to trusted_hosts. If the "
            "whole deployment is somewhere this cannot see -- a VPN, a private "
            "link -- set the boundary to 'anywhere'."
        )
