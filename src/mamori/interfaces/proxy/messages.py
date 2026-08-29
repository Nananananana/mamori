"""Finding the text inside an OpenAI-shaped chat payload, and putting it back.

The proxy has to protect everything the caller wrote and nothing else. In a
chat completion request the text is scattered: several messages, each with a
role, and a ``content`` that is either a string or a list of parts of which
only some are text. Miss one and it goes upstream in the clear.

So the walk is written once, here, with no HTTP anywhere near it. Everything in
this module is a pure function over already-parsed JSON, which means the rule
"every string a caller could put words into is protected" is a property that
can be tested directly rather than inferred from a server's behaviour.

Two rules the walk follows, both deliberate:

**Every role is protected, including ``system``.** A system prompt is where an
organisation puts its own context, and that context is exactly the sort of
thing this library exists to keep local. Treating it as trusted because it came
from the developer rather than the user would protect the message and leak the
briefing.

**Anything unrecognised is left alone and reported.** A payload shape this
module does not know is not silently forwarded as safe: the caller decides
whether an unknown field is a reason to refuse. Guessing in either direction is
worse than saying so.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "TextSlot",
    "assistant_texts",
    "delta_texts",
    "map_choice_strings",
    "request_texts",
    "with_texts",
]

#: Content-part kinds whose ``text`` field carries words. Anything else -- an
#: image, an audio clip, a tool call -- is passed through untouched, because
#: this library reads text and has nothing to say about the rest.
_TEXTUAL_PART_KINDS = frozenset({"text", "input_text", "output_text"})


@dataclass(frozen=True, slots=True)
class TextSlot:
    """One place a caller's words sit, and how to describe where that was."""

    #: Human-readable location, for diagnostics. Never contains the text.
    where: str
    text: str


def request_texts(payload: object) -> tuple[TextSlot, ...]:
    """Every string in a chat request that a caller could have written into.

    Order is stable and matches :func:`with_texts`, so the two compose.
    """
    return tuple(_walk_request(payload))


def with_texts(payload: object, texts: Sequence[str]) -> dict[str, Any]:
    """Return a copy of ``payload`` with each slot replaced, in order.

    Raises:
        ValueError: ``texts`` does not have one entry per slot. A mismatch
            would put the wrong protected text into the wrong message, so it
            is refused rather than zipped to the shorter of the two.
    """
    slots = request_texts(payload)
    if len(texts) != len(slots):
        raise ValueError(f"expected {len(slots)} replacements, got {len(texts)}")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    supply = iter(texts)
    result = dict(payload)
    result["messages"] = [_replace_in_message(m, supply) for m in payload.get("messages", [])]
    return result


def assistant_texts(payload: object) -> tuple[str, ...]:
    """The assistant's words in a non-streamed response.

    These are what restoration is applied to. A response is untrusted input --
    it may contain placeholder-shaped text the model invented -- so this only
    locates the strings; it decides nothing about them.
    """
    return tuple(_choice_strings(payload, "message"))


def delta_texts(payload: object) -> tuple[str, ...]:
    """The assistant's words in one streamed chunk."""
    return tuple(_choice_strings(payload, "delta"))


def _walk_request(payload: object) -> Iterator[TextSlot]:
    if not isinstance(payload, dict):
        return
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "?"))
        content = message.get("content")
        if isinstance(content, str):
            yield TextSlot(f"messages[{index}].content ({role})", content)
        elif isinstance(content, list):
            for part_index, part in enumerate(content):
                text = _part_text(part)
                if text is not None:
                    yield TextSlot(f"messages[{index}].content[{part_index}].text ({role})", text)


def _part_text(part: object) -> str | None:
    if not isinstance(part, dict):
        return None
    if str(part.get("type", "")) not in _TEXTUAL_PART_KINDS:
        return None
    text = part.get("text")
    return text if isinstance(text, str) else None


def _replace_in_message(message: object, supply: Iterator[str]) -> object:
    if not isinstance(message, dict):
        return message
    content = message.get("content")
    if isinstance(content, str):
        return {**message, "content": next(supply)}
    if isinstance(content, list):
        parts = [_replace_in_part(part, supply) for part in content]
        return {**message, "content": parts}
    return message


def _replace_in_part(part: object, supply: Iterator[str]) -> object:
    if _part_text(part) is None:
        return part
    assert isinstance(part, dict)  # guaranteed by _part_text
    return {**part, "text": next(supply)}


def _choice_strings(payload: object, key: str) -> Iterator[str]:
    if not isinstance(payload, dict):
        return
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        holder = choice.get(key)
        if isinstance(holder, dict):
            content = holder.get("content")
            if isinstance(content, str):
                yield content


def map_choice_strings(
    payload: object, key: str, transform: Callable[[str], str]
) -> dict[str, Any]:
    """Return a copy with every assistant string passed through ``transform``."""
    if not isinstance(payload, dict):
        return {}
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return dict(payload)

    rebuilt = []
    for choice in choices:
        if not isinstance(choice, dict):
            rebuilt.append(choice)
            continue
        holder = choice.get(key)
        if isinstance(holder, dict) and isinstance(holder.get("content"), str):
            rebuilt.append({**choice, key: {**holder, "content": transform(holder["content"])}})
        else:
            rebuilt.append(choice)
    return {**payload, "choices": rebuilt}
