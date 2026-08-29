"""One request through the proxy: protect it, and restore what comes back.

Kept apart from the server on purpose. Everything here is a function from a
parsed payload and a session to another parsed payload, so the questions that
actually matter -- did every message get protected, does a blocked credential
stop the request, does the reply come back in the caller's own words -- are
answered by tests that never open a socket.

**One scope per exchange, and it is discarded at the end.** The mapping from
``<PERSON_001>`` back to a name exists for the length of one request and is
purged when the reply has been restored. Nothing accumulates between requests,
so a proxy left running for a month holds exactly as much as one started a
second ago.

That numbering restarts each time is not a problem in practice: a chat client
resends the whole conversation on every turn, so the same value meets the same
allocator in the same order and lands on the same placeholder. What it buys is
a claim that needs no qualification -- the proxy remembers nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ...application.session import PrivacySession
from .messages import (
    TextSlot,
    map_choice_strings,
    request_texts,
    with_texts,
)

__all__ = [
    "ExchangeReport",
    "protect_request",
    "restore_reply",
    "restore_stream_chunk",
    "summarise",
]

#: Where the placeholder briefing is inserted. First, so a model that weights
#: early instructions most heavily gets it before anything else.
_GUIDANCE_INDEX = 0


@dataclass(frozen=True, slots=True)
class ExchangeReport:
    """What happened on the way out. Never contains a protected value."""

    #: One entry per message that was scanned.
    slots: tuple[TextSlot, ...] = ()
    #: Placeholders allocated, by entity type.
    replaced: dict[str, int] = field(default_factory=dict)
    #: True when a briefing about the placeholders was prepended.
    guidance_added: bool = False

    @property
    def total_replaced(self) -> int:
        return sum(self.replaced.values())

    @property
    def scanned_messages(self) -> int:
        return len(self.slots)


def protect_request(
    session: PrivacySession, payload: object, *, add_guidance: bool = True
) -> tuple[dict[str, Any], ExchangeReport]:
    """Replace every sensitive value in a chat request.

    Every message is protected against one session, so a name in the system
    prompt and the same name in the last user turn become the same placeholder
    and the model can tell they are the same person.

    Args:
        session: Supplies the policy, the detectors and the mapping scope.
        payload: An already-parsed chat completion request.
        add_guidance: Prepend a system message telling the model to leave the
            placeholders alone. Every placeholder that survives intact is one
            restoration does not have to recover from a mangled form.

    Raises:
        PolicyViolationError: The policy refuses to send this text at all --
            an API key in a message, by default. The request does not go
            upstream. This is the fail-closed rule of ADR 0002 reaching the
            proxy: a blocked request is a visible error, and a forwarded
            credential is a silent one.
    """
    slots = request_texts(payload)
    protected: list[str] = []
    counts: dict[str, int] = {}

    for slot in slots:
        result = session.protect(slot.text)
        protected.append(result.protected_text)
        for name, count in result.counts_by_type().items():
            counts[name] = counts.get(name, 0) + count

    rebuilt = with_texts(payload, protected)
    guidance_added = False
    if add_guidance and slots:
        rebuilt = _with_guidance(rebuilt, session.external_system_prompt())
        guidance_added = True

    return rebuilt, ExchangeReport(slots=slots, replaced=counts, guidance_added=guidance_added)


def restore_reply(session: PrivacySession, payload: object) -> dict[str, Any]:
    """Put the caller's own values back into a completed reply.

    The reply is untrusted input. Restoration resolves only placeholders this
    session actually allocated, so a model that invents ``<PERSON_042>`` gets
    it back unchanged rather than being handed a value it was never given.
    """
    return map_choice_strings(payload, "message", lambda text: session.restore(text).text)


def restore_stream_chunk(payload: object, restore: Callable[[str], str]) -> dict[str, Any]:
    """Restore one streamed chunk with an already-open streaming restorer.

    A placeholder arrives split across chunks -- ``<PER``, ``SON_0``, ``01>`` --
    so the restorer holds back the shortest suffix that could still become one.
    That state belongs to the stream, which is why it is passed in rather than
    created here.
    """
    return map_choice_strings(payload, "delta", restore)


def _with_guidance(payload: dict[str, Any], guidance: str) -> dict[str, Any]:
    messages = list(payload.get("messages", []))
    messages.insert(_GUIDANCE_INDEX, {"role": "system", "content": guidance})
    return {**payload, "messages": messages}


def summarise(report: ExchangeReport) -> str:
    """A one-line log entry. Types and counts only -- never a value."""
    if not report.total_replaced:
        return f"{report.scanned_messages} message(s), nothing to replace"
    parts = ", ".join(f"{name}x{count}" for name, count in sorted(report.replaced.items()))
    return f"{report.scanned_messages} message(s), replaced {parts}"
