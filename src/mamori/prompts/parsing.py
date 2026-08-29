"""Turning a model's answer into candidates, or refusing to.

A model asked for JSON returns JSON most of the time. The rest of the time it
returns JSON in a code fence, JSON with a sentence in front of it, JSON with a
trailing comma, or an apology. None of that may reach the pipeline unchecked.

**The value is the answer. Offsets are a hint.**

That is a correction, and it was made by measuring rather than by taste. Asked
for character offsets against 49 English samples, a local 8B model got 0 of 52
right -- while 51 of those 52 values were genuinely in the document, most of
them off by a handful of characters. `'John Smith' said 4..13, actually 4..14`
is a representative failure. Character arithmetic is close to the one thing a
tokeniser-based model cannot do, and the earlier contract asked for it and
threw away every answer that failed.

So a candidate is now validated like this:

- the type must be one that exists, or the candidate is dropped;
- offsets, if given, are used **only** when they already agree with the
  reported value -- a model that can count is not punished for it;
- otherwise the reported value is located in the text, on word boundaries
  where the script has them, and every occurrence becomes a candidate;
- a value that does not appear in the text at all is dropped.

The guarantee is unchanged and is, if anything, stronger: **mamori never
creates a span it did not locate itself**. A hallucinated value is not found
and is discarded, so the pipeline still cannot splice the wrong characters out
of somebody's document -- it simply no longer needs the model to be good at
counting in order to be useful.

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
from ..domain.occurrences import MIN_LOCATABLE_LENGTH, find_occurrences
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
#: because a provider that enforces a schema still cannot check that the value
#: it was handed is really in the document.
#:
#: Offsets are deliberately absent. Requiring them taught models to produce a
#: number rather than to read, and the number was wrong every time it was
#: measured. They are still accepted when volunteered.
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
                "required": ["type", "text"],
                "properties": {
                    "type": {"type": "string"},
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
        result = _entities_from(item, text, source, confidence)
        if isinstance(result, str):
            rejected.append(f"entity {index}: {result}")
        else:
            entities.extend(result)

    return ParseOutcome(entities=tuple(entities), rejected=tuple(rejected))


#: Names a model uses for a type this library already has.
#:
#: Strictness about type names is right -- a model that invents a type has not
#: told anybody anything, and 0.7 showed what happens when everything uncertain
#: lands in one dustbin. But strictness was throwing away *near misses*: in one
#: measured run a 14B model reported 38 entities and 11 were rejected for
#: calling an organisation ``ORG`` and an address ``EMAIL_ADDRESS``. That is
#: 29% of a model's work discarded over spelling.
#:
#: Only where the mapping is unambiguous. Four that a model produced in that
#: same run are deliberately **not** here:
#:
#: ``IP_ADDRESS``
#:     mamori has ``INTERNAL_IP``, which means a *private* address. Mapping the
#:     general name onto it would redact 8.8.8.8, and the point of that type is
#:     that a public address is not sensitive.
#: ``LOCATION``
#:     A country is a location. So is a street address. The two are not the
#:     same kind of thing and the model did not say which it meant.
#: ``CREDENTIAL``
#:     Would map onto ``PASSWORD``, whose action is BLOCK. A fuzzy label should
#:     not be able to stop somebody's request.
#: ``PII``, ``SENSITIVE``
#:     Not a type. A model that says this has restated the question.
#: ``HOSTNAME``, ``INTERNAL_HOSTNAME``
#:     There is no type for a bare host. ``INTERNAL_URL`` is a URL and
#:     ``INTERNAL_IP`` is an address; a name is neither, and inventing a
#:     mapping would put a value under a type whose rules never chose it.
#: ``IDENTITY_NUMBER``
#:     In a Chinese document this is a 身份证号 and ``RESIDENT_ID`` is right.
#:     Everywhere else it is a national identifier of some other country with
#:     some other shape, and ``RESIDENT_ID`` carries a checksum this pass
#:     cannot verify. A type that means "verified Chinese resident id" should
#:     not be assigned on a model's say-so.
_ALIASES = {
    "ORG": "COMPANY_NAME",
    "ORGANIZATION": "COMPANY_NAME",
    "ORGANISATION": "COMPANY_NAME",
    "COMPANY": "COMPANY_NAME",
    "EMAIL_ADDRESS": "EMAIL",
    "E_MAIL": "EMAIL",
    "MAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "TELEPHONE": "PHONE",
    "TELEPHONE_NUMBER": "PHONE",
    "MOBILE": "PHONE",
    "CARD_NUMBER": "CREDIT_CARD",
    "CREDIT_CARD_NUMBER": "CREDIT_CARD",
    "PERSON_NAME": "PERSON",
    "FULL_NAME": "PERSON",
    "NAME": "PERSON",
    "DOB": "DATE_OF_BIRTH",
    "BIRTH_DATE": "DATE_OF_BIRTH",
    "BIRTHDAY": "DATE_OF_BIRTH",
    "POSTCODE": "POSTAL_CODE",
    "ZIP": "POSTAL_CODE",
    "ZIP_CODE": "POSTAL_CODE",
    "STREET_ADDRESS": "ADDRESS",
    "POSTAL_ADDRESS": "ADDRESS",
    "EMPLOYEE_NUMBER": "EMPLOYEE_ID",
    "STAFF_ID": "EMPLOYEE_ID",
    "PROJECT": "PROJECT_NAME",
    # Added after the same measurement was run in Japanese and Chinese, where
    # the tail of near misses is different: 工号 comes back as WORK_NUMBER, and
    # a reference of any kind comes back named after what it references.
    "WORK_NUMBER": "EMPLOYEE_ID",
    "CUSTOMER_NUMBER": "IDENTIFIER",
    "ACCOUNT_NUMBER": "IDENTIFIER",
    "REFERENCE_NUMBER": "IDENTIFIER",
    "CASE_NUMBER": "IDENTIFIER",
    "TICKET_NUMBER": "IDENTIFIER",
    "PROJECT_CODE": "PROJECT_NAME",
    "URL": "INTERNAL_URL",
    "SOCIAL_SECURITY_NUMBER": "SSN",
    "MY_NUMBER": "MY_NUMBER",
}


def _entities_from(
    item: object, text: str, source: str, confidence: Confidence
) -> list[SensitiveEntity] | str:
    """Validate one proposal, and place it in the text.

    Returns the entities it produced, or a string saying why it produced none.
    A single proposal can yield several: a model reporting a name once has
    reported it wherever it appears, and protecting one mention while leaving
    the others is not protecting it.
    """
    if not isinstance(item, dict):
        return "not an object"

    type_name = str(item.get("type", "")).strip().upper()
    if not type_name:
        return "no type"

    entity_type = get_type(type_name) or get_type(_ALIASES.get(type_name, ""))
    if entity_type is None:
        if type_name != OTHER_SENSITIVE.name:
            return f"unknown type {type_name!r}"
        entity_type = OTHER_SENSITIVE

    reported = item.get("text")
    if not isinstance(reported, str) or not reported.strip():
        return "no text field"
    reported = reported.strip()

    hinted = _hinted_span(item, text, reported)
    if hinted is not None:
        return [_entity(entity_type, hinted, reported, confidence, source)]

    spans = find_occurrences(text, reported)
    if not spans:
        if len(reported) < MIN_LOCATABLE_LENGTH:
            return f"value {_elided(reported)} is too short to locate"
        # The check that catches a hallucination. A model can infer a name
        # from an email address and report it as though it were written down;
        # protecting a value the document does not contain would mean cutting
        # characters that are not there.
        return f"value {_elided(reported)} does not appear in the text"

    return [
        _entity(entity_type, span, text[span.start : span.end], confidence, source)
        for span in spans
    ]


def _hinted_span(item: object, text: str, reported: str) -> Span | None:
    """Use the model's offsets only if they already agree with its own answer.

    Almost nothing passes this today, and that is the finding rather than a
    bug. It costs two comparisons and means a model that can count keeps its
    exact span -- including the case the search cannot resolve, where the same
    value appears twice and only one of them was meant.
    """
    if not isinstance(item, dict):
        return None
    try:
        start = int(item["start"])
        end = int(item["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if not 0 <= start < end <= len(text):
        return None
    return Span(start, end) if text[start:end] == reported else None


def _entity(
    entity_type: EntityType,
    span: Span,
    value: str,
    confidence: Confidence,
    source: str,
) -> SensitiveEntity:
    return SensitiveEntity(
        entity_type=entity_type,
        span=span,
        value=value,
        confidence=confidence,
        source=source,
    )


def _elided(value: str) -> str:
    """A rejection reason ends up in diagnostics, so it shows a shape, not a value."""
    if len(value) <= 2:
        return f"{value[:1]!r}..."
    return f"{value[:1]}{'*' * (len(value) - 1)!s}"
