"""Finding the text inside an OpenAI-shaped chat payload, and putting it back.

The proxy has to protect everything the caller wrote and nothing else. In a
chat completion request the text is scattered: several messages, each with a
role and a ``content`` that is either a string or a list of parts; the arguments
of a tool call; the descriptions of the tools themselves. Miss one and it goes
upstream in the clear.

So the walk is written once, here, with no HTTP anywhere near it. Everything in
this module is a pure function over already-parsed JSON, which means the rule
"every string a caller could put words into is protected" is a property that
can be tested directly rather than inferred from a server's behaviour.

**Slots carry a path, and replacement follows the same path.** Until 0.18 the
walk yielded strings and the rebuild put them back positionally, which works
exactly as long as the two functions are edited together. They are the two
halves of one rule and the rule is "protect everything"; pairing them by
position made adding a place to look a chance to leak the place you added.

Three rules the walk follows, all deliberate:

**Every role is protected, including ``system``.** A system prompt is where an
organisation puts its own context, and that context is exactly the sort of
thing this library exists to keep local. Treating it as trusted because it came
from the developer rather than the user would protect the message and leak the
briefing.

**A tool call is text.** ``{"to": "jane@example.com", "body": "Dear Jane"}`` is
where an agent's personal data actually lives -- more of it, and more reliably,
than in the prose around it. Until 0.18 this module said a tool call was "not
text" and passed it through untouched, which was true of the *call* and false
of its arguments.

**Anything unrecognised is left alone and reported.** A payload shape this
module does not know is not silently forwarded as safe: the caller decides
whether an unknown field is a reason to refuse. Guessing in either direction is
worse than saying so.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "TextSlot",
    "assistant_texts",
    "delta_texts",
    "map_choice_strings",
    "map_tool_arguments",
    "request_texts",
    "tool_argument_slots",
    "unclaimed_texts",
    "with_texts",
]

#: Content-part kinds whose ``text`` field carries words. Anything else -- an
#: image, an audio clip -- is passed through untouched, because this library
#: reads text and has nothing to say about the rest.
_TEXTUAL_PART_KINDS = frozenset({"text", "input_text", "output_text"})

#: A path through parsed JSON: object keys and array indices.
Path = tuple[str | int, ...]


@dataclass(frozen=True, slots=True)
class TextSlot:
    """One place a caller's words sit, and how to describe where that was."""

    #: Human-readable location, for diagnostics. Never contains the text.
    where: str
    text: str
    #: Where to put the replacement back. Empty for slots built by hand in a
    #: test; :func:`with_texts` refuses those rather than guessing.
    path: Path = field(default=(), repr=False)


def request_texts(payload: object) -> tuple[TextSlot, ...]:
    """Every string in a chat request that a caller could have written into.

    Order is stable and matches :func:`with_texts`, so the two compose.
    """
    return tuple(_walk_request(payload))


def unclaimed_texts(payload: object) -> tuple[TextSlot, ...]:
    """Every string in a request that :func:`request_texts` did **not** claim.

    The walk above is an allow-list of the fields this module knows, and an
    allow-list of somebody else's evolving API is a list that is out of date
    between releases. The module docstring has always said an unrecognised
    shape is *"left alone and reported"* -- and nothing reported anything, so
    what actually happened was left alone and forwarded. Six shapes went
    upstream verbatim, measured: `messages` as a string, `messages` as an
    object, the legacy `functions` array, `prediction.content`, a content part
    with no `type` key, and a JSON-schema `description`.

    This is the reporting half. It walks the **whole** payload -- every string
    value and every object key, at any depth -- and returns what no slot
    covers, so a caller can decide. `exchange.protect_request` decides by
    refusing when one of them carries something sensitive, which is the
    fail-closed rule reaching the one place it was not applied.

    Object keys are included because a key is a place a caller can write:
    `{"metadata": {"Priya Raman": "..."}}` puts a name somewhere no rewrite
    can reach, and silence about it would be the same defect one level down.
    """
    claimed = {slot.path for slot in request_texts(payload) if slot.path}
    found: list[TextSlot] = []
    for path, text, is_key in _every_string(payload):
        if not text or (not is_key and path in claimed):
            continue
        # A key carries no path. Nothing can rewrite an object key without
        # changing the shape of the request, so it is reported and never
        # offered as a slot -- `with_texts` refuses a pathless slot, which is
        # the same rule seen from the other side.
        found.append(
            TextSlot(
                f"{_describe(path)} (key)" if is_key else _describe(path),
                text,
                () if is_key else path,
            )
        )
    return tuple(found)


def _every_string(node: object, path: Path = ()) -> Iterator[tuple[Path, str, bool]]:
    """Every string in a parsed JSON tree: its path, and whether it is a key.

    Keys and values are reported separately because they can be the same
    string at what would otherwise be the same path. The first version of this
    gave both `("metadata", "Priya Raman")`, so a name written as a key was
    filtered out as already claimed by the walk of its own value -- the exact
    silence this function exists to remove, reproduced inside it.
    """
    if isinstance(node, str):
        yield path, node, False
    elif isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str):
                yield (*path, key), key, True
            yield from _every_string(value, (*path, str(key)))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _every_string(item, (*path, index))


def _describe(path: Path) -> str:
    """A JSON path as a person reads it. Never contains the text."""
    out = ""
    for step in path:
        out += f"[{step}]" if isinstance(step, int) else (f".{step}" if out else str(step))
    return out or "(root)"


def with_texts(payload: object, texts: Sequence[str]) -> dict[str, Any]:
    """Return a copy of ``payload`` with each slot replaced, by path.

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

    result: Any = payload
    for slot, text in zip(slots, texts, strict=True):
        result = _set_at(result, slot.path, text)
    return dict(result)


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


def tool_argument_slots(payload: object, key: str = "message") -> tuple[tuple[Path, str], ...]:
    """Tool-call argument strings in a response, with their paths.

    The reply side of the same rule: a model that answers with a tool call puts
    the values there rather than in ``content``, and an application handed
    ``{"to": "<EMAIL_001>"}`` will send mail to nobody.
    """
    return tuple(_walk_tool_arguments(payload, key))


# -- the request walk ------------------------------------------------------


def _walk_request(payload: object) -> Iterator[TextSlot]:
    if not isinstance(payload, dict):
        return
    yield from _walk_messages(payload.get("messages"))
    yield from _walk_tools(payload.get("tools"))
    # The pre-`tools` spelling of the same thing. Every OpenAI-compatible
    # server still accepts it, and this module walked `tools[].function`
    # *specifically* because a description carries an example address -- while
    # its own predecessor went upstream untouched.
    yield from _walk_functions(payload.get("functions"))
    yield from _walk_metadata(payload.get("metadata"))
    yield from _walk_prediction(payload.get("prediction"))

    # The end-user identifier. OpenAI describes it as an opaque id and callers
    # routinely put an email address or a login in it, which is a value this
    # library exists to keep local. Replacing it costs the upstream nothing it
    # can act on -- the field is opaque to them by definition -- and it does
    # mean their abuse tracking sees a different id per session, which is
    # stated here rather than discovered.
    user = payload.get("user")
    if isinstance(user, str) and user:
        yield TextSlot("user", user, ("user",))


def _walk_messages(messages: object) -> Iterator[TextSlot]:
    if not isinstance(messages, list):
        return
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "?"))
        base: Path = ("messages", index)

        content = message.get("content")
        if isinstance(content, str):
            yield TextSlot(f"messages[{index}].content ({role})", content, (*base, "content"))
        elif isinstance(content, list):
            for part_index, part in enumerate(content):
                text = _part_text(part)
                if text is not None:
                    yield TextSlot(
                        f"messages[{index}].content[{part_index}].text ({role})",
                        text,
                        (*base, "content", part_index, "text"),
                    )

        # The participant's name, which is a name.
        name = message.get("name")
        if isinstance(name, str) and name:
            yield TextSlot(f"messages[{index}].name ({role})", name, (*base, "name"))

        yield from _walk_tool_calls(message.get("tool_calls"), base, role)


def _walk_tool_calls(calls: object, base: Path, role: str) -> Iterator[TextSlot]:
    if not isinstance(calls, list):
        return
    for call_index, call in enumerate(calls):
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        arguments = function.get("arguments")
        if isinstance(arguments, str) and arguments:
            yield TextSlot(
                f"messages[{base[1]}].tool_calls[{call_index}].arguments ({role})",
                arguments,
                (*base, "tool_calls", call_index, "function", "arguments"),
            )


def _walk_functions(functions: object) -> Iterator[TextSlot]:
    """The pre-``tools`` spelling: ``functions[].description`` and its schema.

    Written out rather than delegating to :func:`_walk_tools` because the paths
    differ -- ``functions[0].description`` against
    ``tools[0].function.description`` -- and a slot whose path is wrong writes
    a protected string into the wrong place, which is worse than not walking
    at all.
    """
    if not isinstance(functions, list):
        return
    for index, function in enumerate(functions):
        if not isinstance(function, dict):
            continue
        description = function.get("description")
        if isinstance(description, str) and description:
            yield TextSlot(
                f"functions[{index}].description",
                description,
                ("functions", index, "description"),
            )
        yield from _walk_descriptions(
            function.get("parameters"),
            ("functions", index, "parameters"),
            f"functions[{index}].parameters",
        )


def _walk_prediction(prediction: object) -> Iterator[TextSlot]:
    """Predicted Outputs: a draft the caller supplies to speed up a rewrite.

    It is the caller's own document, which makes it exactly the text this
    library exists to keep local -- and being a *prediction* it is usually the
    full prior version of what is being edited.
    """
    if not isinstance(prediction, dict):
        return
    content = prediction.get("content")
    if isinstance(content, str) and content:
        yield TextSlot("prediction.content", content, ("prediction", "content"))
    elif isinstance(content, list):
        for index, part in enumerate(content):
            text = _part_text(part)
            if text is not None:
                yield TextSlot(
                    f"prediction.content[{index}].text",
                    text,
                    ("prediction", "content", index, "text"),
                )


def _walk_tools(tools: object) -> Iterator[TextSlot]:
    """A tool definition's prose, and nothing else.

    The description is free text and often carries an example -- "e.g.
    to=jane@example.com" -- which is a real address in a real deployment more
    often than anybody intends.

    A schema's ``enum`` values are deliberately left alone. They are the
    contract the model is being asked to satisfy, and replacing one changes
    what it is allowed to emit rather than what it is allowed to see. That is a
    stated gap, not an oversight: if your enum lists real people, the tool
    definition is the wrong place for it.
    """
    if not isinstance(tools, list):
        return
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            continue
        description = function.get("description")
        if isinstance(description, str) and description:
            yield TextSlot(
                f"tools[{index}].function.description",
                description,
                ("tools", index, "function", "description"),
            )
        yield from _walk_descriptions(
            function.get("parameters"),
            ("tools", index, "function", "parameters"),
            f"tools[{index}].parameters",
        )


def _walk_descriptions(node: object, path: Path, where: str) -> Iterator[TextSlot]:
    """Every ``description`` inside a JSON schema, however deep.

    Only ``description``: a schema is full of strings that are structure --
    ``"type": "string"``, a property name, a format -- and replacing one of
    those turns a valid schema into a broken one.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "description" and isinstance(value, str) and value:
                yield TextSlot(f"{where}.description", value, (*path, key))
            elif isinstance(value, dict | list):
                yield from _walk_descriptions(value, (*path, key), f"{where}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, dict | list):
                yield from _walk_descriptions(value, (*path, index), f"{where}[{index}]")


def _walk_metadata(metadata: object) -> Iterator[TextSlot]:
    """Caller-supplied key/value pairs. Free text with a label on it."""
    if not isinstance(metadata, dict):
        return
    for key, value in metadata.items():
        if isinstance(value, str) and value:
            yield TextSlot(f"metadata.{key}", value, ("metadata", key))


def _part_text(part: object) -> str | None:
    """The words in one content part, or ``None``.

    A part carrying ``text`` and **no** ``type`` counts. The field is optional
    in several clients and omitting it is common; requiring it meant a part
    written that way was forwarded verbatim. Erring towards reading a part as
    text is the safe direction -- the cost is a protected string where none
    was needed, and the cost of the other direction is the value going out.
    """
    if not isinstance(part, dict):
        return None
    if "type" not in part and isinstance(part.get("text"), str):
        text = part["text"]
        return text if text else None
    if str(part.get("type", "")) not in _TEXTUAL_PART_KINDS:
        return None
    text = part.get("text")
    return text if isinstance(text, str) else None


def _set_at(node: Any, path: Path, value: str) -> Any:
    """A copy of ``node`` with ``path`` set to ``value``.

    Copies only the containers along the path, so unrelated parts of the
    payload are the same objects they were -- and, more to the point, are not
    quietly reserialised into a shape the caller did not send.
    """
    if not path:
        return value
    step, rest = path[0], path[1:]
    if isinstance(step, int):
        if not isinstance(node, list) or not 0 <= step < len(node):
            raise ValueError(f"cannot replace at {path}: no such index")
        as_list = list(node)
        as_list[step] = _set_at(as_list[step], rest, value)
        return as_list
    if not isinstance(node, dict) or step not in node:
        raise ValueError(f"cannot replace at {path}: no such key")
    as_dict = dict(node)
    as_dict[step] = _set_at(as_dict[step], rest, value)
    return as_dict


# -- the response walk -----------------------------------------------------


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


def _walk_tool_arguments(payload: object, key: str) -> Iterator[tuple[Path, str]]:
    if not isinstance(payload, dict):
        return
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return
    for choice_index, choice in enumerate(choices):
        if not isinstance(choice, dict):
            continue
        holder = choice.get(key)
        if not isinstance(holder, dict):
            continue
        calls = holder.get("tool_calls")
        if not isinstance(calls, list):
            continue
        for call_index, call in enumerate(calls):
            if not isinstance(call, dict):
                continue
            function = call.get("function")
            if not isinstance(function, dict):
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str) and arguments:
                yield (
                    (
                        "choices",
                        choice_index,
                        key,
                        "tool_calls",
                        call_index,
                        "function",
                        "arguments",
                    ),
                    arguments,
                )


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


def map_tool_arguments(
    payload: object, key: str, transform: Callable[[str], str]
) -> dict[str, Any]:
    """Return a copy with every tool-call argument string transformed.

    Separate from :func:`map_choice_strings` because the two are restored
    differently in a stream: content is one continuous run of words, and each
    tool call's arguments are their own run that has to be reassembled on its
    own before a placeholder split across chunks can be recognised.
    """
    if not isinstance(payload, dict):
        return {}
    result: Any = payload
    for path, arguments in _walk_tool_arguments(payload, key):
        result = _set_at(result, path, transform(arguments))
    return dict(result)


def json_survived(before: str, after: str) -> bool:
    """Whether protecting a JSON argument string left it parseable.

    Protection replaces spans of text; a span that crossed a quote or a comma
    would produce something an application cannot read. No rule in this library
    matches across a structural boundary, which is a claim this makes checkable
    at the one place it would matter most.
    """
    try:
        json.loads(before)
    except ValueError:
        return True  # it was not JSON to begin with; nothing was broken
    try:
        json.loads(after)
    except ValueError:
        return False
    return True
