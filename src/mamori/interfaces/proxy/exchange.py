"""One request through the proxy: protect it, and restore what comes back.

Kept apart from the server on purpose. Everything here is a function from a
parsed payload and a session to another parsed payload, so the questions that
actually matter -- did every message get protected, does a blocked credential
stop the request, does the reply come back in the caller's own words -- are
answered by tests that never open a socket.

**One scope per exchange by default, and it is discarded at the end.** The
mapping from ``<PERSON_001>`` back to a name exists for the length of one
request and is purged when the reply has been restored. Nothing accumulates
between requests, so a proxy left running for a month holds exactly as much as
one started a second ago.

That numbering restarts each time is not a problem for most clients: a chat
client that resends the whole conversation on every turn meets the same
allocator in the same order and lands on the same placeholders. That argument
was made here for four releases without being checked; it is checked now, in
``tests/test_conversations.py``, and it holds.

It does not hold for a client that sends only the new turn, because the service
is keeping the history for it. That client gets a reply about ``<PERSON_001>``
and no way to turn it back, which is a token printed at a human. For those,
0.16 added :mod:`mamori.application.conversations`, off unless the deployment
asks for it -- see that module for what it holds and for how long.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ...application.session import PrivacySession
from ...application.streaming import StreamingRestorer
from ...errors import MamoriError
from .messages import (
    TextSlot,
    json_survived,
    map_choice_strings,
    map_tool_arguments,
    request_texts,
    unclaimed_texts,
    with_texts,
)

__all__ = [
    "ExchangeReport",
    "StreamRestoration",
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
        MamoriError: A field this module cannot rewrite carries something
            sensitive. See :func:`_refuse_unwalked_text`.
    """
    if not isinstance(payload, dict):
        # A top-level array or string. `with_texts` refused this with a bare
        # `ValueError`, which `do_POST` does not catch, so the client got a
        # connection reset and a traceback went to stderr -- one unauthenticated
        # line of JSON was enough. A MamoriError becomes a 400 in the shape the
        # caller's OpenAI client already understands.
        raise MamoriError("a chat completion request must be a JSON object; nothing was forwarded")
    _refuse_unwalked_text(session, payload)
    slots = request_texts(payload)
    protected: list[str] = []
    counts: dict[str, int] = {}

    for slot in slots:
        result = session.protect(slot.text)
        # A tool call's arguments are JSON that an application will parse. No
        # rule in this library matches across a structural boundary, so this
        # should never fire -- which is exactly why it is checked here rather
        # than assumed: the failure would otherwise be a caller's parse error
        # in a different process, hours later.
        if not json_survived(slot.text, result.protected_text):
            raise MamoriError(
                f"protecting {slot.where} produced text that is no longer valid JSON; "
                "nothing was forwarded"
            )
        protected.append(result.protected_text)
        for name, count in result.counts_by_type().items():
            counts[name] = counts.get(name, 0) + count

    rebuilt = with_texts(payload, protected)
    guidance_added = False
    if add_guidance and slots:
        rebuilt = _with_guidance(rebuilt, session.external_system_prompt())
        guidance_added = True

    return rebuilt, ExchangeReport(slots=slots, replaced=counts, guidance_added=guidance_added)


def _refuse_unwalked_text(session: PrivacySession, payload: object) -> None:
    """Refuse a request whose unrecognised fields carry sensitive values.

    The walk in :mod:`~mamori.interfaces.proxy.messages` is an allow-list of
    somebody else's evolving API, so it is out of date by construction. The
    server's own docstring has always said this proxy fails closed -- *"a
    payload it cannot parse... none of them forward anything"* -- and until
    0.32 an unrecognised **shape** was neither parsed nor refused: it was
    forwarded verbatim, with a 200. Six shapes did, measured. Four of them are
    walked now; this is what covers the seventh, whatever it turns out to be.

    Why refuse rather than protect in place. A field whose meaning is unknown
    cannot be rewritten safely: replacing an enum value or a stop sequence
    turns a valid request into one the upstream rejects or, worse, answers
    differently. Refusing is the only move that is right for a field nobody
    has looked at yet.

    The error names the JSON path and the kinds found. **Never the value** --
    an error message crosses process boundaries and lands in logs, which is
    the leak this whole library exists to prevent, arrived at through the
    complaint about a leak.
    """
    for slot in unclaimed_texts(payload):
        kinds = session.inspect(slot.text)
        if not kinds:
            continue
        raise MamoriError(
            f"{slot.where} carries {', '.join(kinds)} and this proxy does not know how "
            "to rewrite that field, so nothing was forwarded. Move the value into a "
            "message, or drop the field. This is the fail-closed rule: a field whose "
            "shape is unrecognised cannot be protected in place, and forwarding it "
            "unprotected is the one outcome that must not happen."
        )


def restore_reply(session: PrivacySession, payload: object) -> dict[str, Any]:
    """Put the caller's own values back into a completed reply.

    The reply is untrusted input. Restoration resolves only placeholders this
    session actually allocated, so a model that invents ``<PERSON_042>`` gets
    it back unchanged rather than being handed a value it was never given.

    Tool-call arguments are restored as well as prose. A model that answers
    with a call rather than a sentence puts the values there, and an
    application handed ``{"to": "<EMAIL_001>"}`` sends mail to nobody.
    """
    restore = lambda text: session.restore(text).text  # noqa: E731
    restored = map_choice_strings(payload, "message", restore)
    return map_tool_arguments(restored, "message", restore)


def restore_stream_chunk(payload: object, restore: Callable[[str], str]) -> dict[str, Any]:
    """Restore one streamed chunk with an already-open streaming restorer.

    A placeholder arrives split across chunks -- ``<PER``, ``SON_0``, ``01>`` --
    so the restorer holds back the shortest suffix that could still become one.
    That state belongs to the stream, which is why it is passed in rather than
    created here.

    Prose only. Tool-call arguments stream as their own runs of text and are
    handled by :class:`StreamRestoration`, which keeps one restorer each: feeding
    two interleaved runs through a single restorer would splice one's held
    suffix onto the other's next chunk.
    """
    return map_choice_strings(payload, "delta", restore)


class StreamRestoration:
    """Every run of text in one streamed reply, each reassembled on its own.

    A streamed answer is not one stream of words. It is the prose, plus one
    independent run per tool call, arriving interleaved and identified by the
    ``index`` inside each ``tool_calls`` entry. Each needs its own held suffix,
    because the whole point of holding one is that the next chunk of *the same
    run* completes it.

    What is held at the end is flushed as a final chunk per run, so a
    placeholder that was still incomplete when the model stopped is emitted as
    the value rather than as half a token.
    """

    def __init__(self, session: PrivacySession) -> None:
        self._session = session
        self._prose = session.stream_restore()
        self._arguments: dict[tuple[int, int], StreamingRestorer] = {}

    def feed(self, chunk: object) -> dict[str, Any]:
        """Restore one chunk. Returns it rebuilt, whatever shape it was."""
        restored = map_choice_strings(chunk, "delta", self._prose.feed)
        return self._feed_tool_calls(restored)

    def finish(self) -> list[dict[str, Any]]:
        """Whatever each run was still holding, as chunks ready to emit."""
        trailing: list[dict[str, Any]] = []
        tail = self._prose.finish()
        if tail:
            trailing.append({"choices": [{"index": 0, "delta": {"content": tail}}]})
        for (choice_index, call_index), restorer in self._arguments.items():
            held = restorer.finish()
            if held:
                trailing.append(
                    {
                        "choices": [
                            {
                                "index": choice_index,
                                "delta": {
                                    "tool_calls": [
                                        {"index": call_index, "function": {"arguments": held}}
                                    ]
                                },
                            }
                        ]
                    }
                )
        return trailing

    def _feed_tool_calls(self, chunk: object) -> dict[str, Any]:
        if not isinstance(chunk, dict):
            return {}
        choices = chunk.get("choices")
        if not isinstance(choices, list):
            return dict(chunk)

        rebuilt: list[Any] = []
        for position, choice in enumerate(choices):
            if not isinstance(choice, dict):
                rebuilt.append(choice)
                continue
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                rebuilt.append(choice)
                continue
            calls = delta.get("tool_calls")
            if not isinstance(calls, list):
                rebuilt.append(choice)
                continue

            choice_index = choice.get("index")
            choice_index = choice_index if isinstance(choice_index, int) else position
            rebuilt_calls = [self._feed_call(choice_index, call, n) for n, call in enumerate(calls)]
            rebuilt.append({**choice, "delta": {**delta, "tool_calls": rebuilt_calls}})
        return {**chunk, "choices": rebuilt}

    def _feed_call(self, choice_index: int, call: object, position: int) -> Any:
        if not isinstance(call, dict):
            return call
        function = call.get("function")
        if not isinstance(function, dict) or not isinstance(function.get("arguments"), str):
            return call
        # The call's own `index`, not its position in this chunk's list: a
        # chunk carries only the calls it has news about, so position moves.
        call_index = call.get("index")
        call_index = call_index if isinstance(call_index, int) else position
        key = (choice_index, call_index)
        restorer = self._arguments.get(key)
        if restorer is None:
            restorer = self._session.stream_restore()
            self._arguments[key] = restorer
        return {**call, "function": {**function, "arguments": restorer.feed(function["arguments"])}}


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
