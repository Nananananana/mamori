"""Turning a model's answer into candidates, or refusing to.

A model asked for JSON returns JSON most of the time. The rest of the time it
returns JSON in a code fence, JSON with a sentence in front of it, JSON with a
trailing comma, or an apology. None of that may reach the pipeline unchecked.

Every field is validated against the text it claims to describe:

- the type must be one that exists, or the candidate is dropped;
- the offsets must lie inside the text, in order;
- the reported value must be **exactly** the characters between them.

That last check is the one that matters. A model that hallucinates a span
produces an entity whose value and offsets disagree, and an entity like that
would splice the wrong characters out of the user's text. It is cheaper to
verify than to trust, and the verification is three lines.

Nothing here decides anything. A candidate that survives is a *proposal*, added
to the same pile the pattern rules contribute to, and resolved and policed by
the same deterministic code. A model that is talked into silence removes its own
proposals and nothing else.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from ..domain.confidence import Confidence
from ..domain.entity_types import Category, EntityType, get_type
from ..domain.sensitive_entity import SensitiveEntity
from ..domain.span import Span

__all__ = [
    "DETECTION_SCHEMA",
    "MODEL_CONFIDENCE",
    "ParseOutcome",
    "parse_detection_response",
]

#: The contract the prompt states, in the form a structured-output API wants.
#: Passed to providers that support it; the validation below runs either way,
#: because a provider that enforces a schema still cannot check that the
#: offsets describe the text.
DETECTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["entities"],
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "start", "end", "text"],
                "properties": {
                    "type": {"type": "string"},
                    "start": {"type": "integer", "minimum": 0},
                    "end": {"type": "integer", "minimum": 1},
                    "text": {"type": "string"},
                },
            },
        }
    },
}

#: Anything sensitive that fits no registered type. Blocked by the default
#: policy, which is the right outcome: a model saying "this matters and I
#: cannot name it" should stop the request, not be quietly dropped.
OTHER_SENSITIVE = EntityType("OTHER_SENSITIVE", Category.OTHER, 80)

#: Where a model proposal sits relative to the rules. Below an anchored
#: pattern -- a checksum beats a judgement -- and above a shape-only one, so
#: a model reading a sentence outranks a regex matching two capital letters.
MODEL_CONFIDENCE: Final = Confidence(0.6)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True, slots=True)
class ParseOutcome:
    """What survived, and what did not.

    The rejections are counted rather than raised. A model that gets one
    candidate wrong should not cost the nine it got right, and the counts are
    what tells an operator the prompt or the model needs attention.
    """

    entities: tuple[SensitiveEntity, ...] = ()
    #: Reasons candidates were dropped, most useful first.
    rejected: tuple[str, ...] = ()
    #: True when the response could not be read as JSON at all.
    unparsable: bool = False

    @property
    def is_clean(self) -> bool:
        return not self.rejected and not self.unparsable


def _extract_json(raw: str) -> object | None:
    """Find the JSON object in a response that may be wrapped in prose."""
    for candidate in _candidates(raw):
        try:
            parsed: object = json.loads(candidate)
        except ValueError:
            continue
        return parsed
    return None


def _candidates(raw: str) -> Sequence[str]:
    text = raw.strip()
    found = [text]
    fenced = _FENCE_RE.search(text)
    if fenced:
        found.append(fenced.group(1).strip())
    braced = _OBJECT_RE.search(text)
    if braced:
        found.append(braced.group(0))
    return found


def parse_detection_response(
    raw: str,
    text: str,
    *,
    source: str = "llm",
    confidence: Confidence = MODEL_CONFIDENCE,
) -> ParseOutcome:
    """Validate a detection response against the text it describes.

    Args:
        raw: The model's answer, as received.
        text: The text it was asked about, in the coordinates it was given.
        source: Recorded on every surviving entity.
        confidence: Assigned to every surviving entity. Model output is a
            proposal, so this sits below the anchored pattern rules and above
            the shape-only ones: the resolver should prefer a rule with a
            checksum behind it, and a model reading a sentence should outrank a
            regex matching two capital letters.
    """
    payload = _extract_json(raw)
    if not isinstance(payload, dict):
        return ParseOutcome(unparsable=True, rejected=("response was not JSON",))

    items = payload.get("entities")
    if not isinstance(items, list):
        return ParseOutcome(unparsable=True, rejected=("no entities array",))

    entities: list[SensitiveEntity] = []
    rejected: list[str] = []

    for index, item in enumerate(items):
        result = _entity_from(item, text, source, confidence)
        if isinstance(result, str):
            rejected.append(f"entity {index}: {result}")
        else:
            entities.append(result)

    return ParseOutcome(entities=tuple(entities), rejected=tuple(rejected))


def _entity_from(
    item: object, text: str, source: str, confidence: Confidence
) -> SensitiveEntity | str:
    if not isinstance(item, dict):
        return "not an object"

    type_name = str(item.get("type", "")).strip().upper()
    if not type_name:
        return "no type"

    entity_type = get_type(type_name)
    if entity_type is None:
        if type_name != OTHER_SENSITIVE.name:
            return f"unknown type {type_name!r}"
        entity_type = OTHER_SENSITIVE

    try:
        start = int(item["start"])
        end = int(item["end"])
    except (KeyError, TypeError, ValueError):
        return "offsets missing or not integers"

    if not 0 <= start < end <= len(text):
        return f"offsets {start}:{end} outside the text"

    covered = text[start:end]
    reported = item.get("text")
    if not isinstance(reported, str):
        return "no text field"
    if reported != covered:
        # The check that catches a hallucinated span. Without it the pipeline
        # would splice these offsets out of the user's document.
        return "text does not match the offsets"

    return SensitiveEntity(
        entity_type=entity_type,
        span=Span(start, end),
        value=covered,
        confidence=confidence,
        source=source,
    )
