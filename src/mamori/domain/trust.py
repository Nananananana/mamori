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


def classify_host(host: str, trusted_hosts: frozenset[str] = frozenset()) -> HostKind:
    """Say what kind of place ``host`` is, without asking DNS.

    Args:
        host: A hostname or literal address, without scheme or port.
        trusted_hosts: Names the operator has declared trusted. Matched
            case-insensitively and exactly -- no wildcards, because a wildcard
            in a trust list is how ``*.example.com`` ends up including a
            hostname somebody else controls.
    """
    name = host.strip().lower().strip("[]")
    if not name:
        return HostKind.EXTERNAL
    if name in {h.strip().lower() for h in trusted_hosts}:
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
