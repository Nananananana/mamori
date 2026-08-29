"""Tamper-tolerant placeholder scanning.

An external LLM is not obliged to echo our placeholders verbatim. Observed
mutations include::

    <PERSON_001>  ->  PERSON_001      (brackets dropped)
    <PERSON_001>  ->  <PERSON_1>      (zero padding lost)
    <PERSON_001>  ->  <person_001>    (case changed)
    <PERSON_001>  ->  ＜PERSON_001＞  (full-width brackets)
    <PERSON_001>  ->  [PERSON_001]    (bracket style changed)
    <PERSON_001>  ->  <PERSON _ 001>  (spaces around the underscores)

Silently failing to restore these leaves the user with a broken answer;
silently restoring *anything* that looks vaguely like a placeholder would let a
malicious response fish for values. So the scanner is permissive about the
*surface form* and strict about the *identity*: a candidate is only substituted
when its canonical ``(TYPE, index)`` pair was actually allocated in this scope.
"""

from __future__ import annotations

import re
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field

from .normalization import NormalizedText
from .placeholder import Placeholder
from .span import Span

__all__ = ["PlaceholderOccurrence", "scan_placeholders"]

_LENIENT_RE = re.compile(
    r"""
    (?:(?P<open>[<\[\{])[^\S

]*)?
    (?P<type>[A-Za-z][A-Za-z0-9]*(?:[^\S

_\-]*[_\-][^\S

]*[A-Za-z0-9]+)*?)
    [^\S

_\-]*[\s_\-][^\S

]*
    (?P<index>\d{1,6})
    (?:[^\S

]*(?P<close>[>\]\}]))?
    """,
    re.VERBOSE,
)

_BRACKET_PAIRS = {"<": ">", "[": "]", "{": "}"}

#: Whatever separated the parts of a type, canonicalised to one underscore.
_WHITESPACE_RUN = re.compile(r"[\s_\-]+")


@dataclass(frozen=True, slots=True)
class PlaceholderOccurrence:
    """A placeholder-shaped run of text found in a response."""

    placeholder: Placeholder
    #: Offsets into the *original* (un-normalized) response text.
    span: Span
    #: The literal text that was matched, as it appeared.
    surface: str = field(repr=False)
    #: True when this ``(type, index)`` pair was allocated in the scope.
    known: bool = False

    @property
    def tampered(self) -> bool:
        """True when the surface form differs from the canonical token."""
        return self.surface != self.placeholder.token


def scan_placeholders(text: str, known: AbstractSet[Placeholder]) -> list[PlaceholderOccurrence]:
    """Find placeholder-shaped runs in ``text``.

    Args:
        text: Response text, as received.
        known: Placeholders allocated in the current scope.

    Returns:
        Non-overlapping occurrences ordered by start offset. Occurrences whose
        identity was never allocated are still returned, with ``known=False``,
        so the caller can report them instead of ignoring them.
    """
    normalized = NormalizedText.of(text)
    known_types = {placeholder.entity_type_name for placeholder in known}
    occurrences: list[PlaceholderOccurrence] = []
    cursor = 0

    for match in _LENIENT_RE.finditer(normalized.text):
        if match.start() < cursor:
            continue
        opening = match.group("open")
        closing = match.group("close")
        bracketed = opening is not None and closing == _BRACKET_PAIRS.get(opening)

        # Spaces inside the token collapse back to underscores, so
        # <COMPANY _ NAME _ 001> and <COMPANY_NAME_001> are the same identity.
        # A thousand generated replies said this was the one mutation the
        # scanner did not survive, and it accounted for every failure.
        type_name = _WHITESPACE_RUN.sub("_", match.group("type")).upper()
        index = int(match.group("index"))
        if index < 1:
            continue
        candidate = Placeholder(type_name, index)
        is_known = candidate in known

        # Precision guard: an unbracketed run is only treated as a placeholder
        # when its type was actually used here. Otherwise ordinary text such as
        # "error_404" or "step 2" would be reported as a stray placeholder.
        if not is_known and not bracketed and type_name not in known_types:
            continue

        if bracketed:
            start, end = match.span()
        else:
            # Keep a lone bracket out of the span so we do not swallow the
            # punctuation around an unbracketed form.
            start, end = match.start("type"), match.end("index")

        span = normalized.to_original_span(start, end)
        occurrences.append(
            PlaceholderOccurrence(
                placeholder=candidate,
                span=span,
                surface=text[span.start : span.end],
                known=is_known,
            )
        )
        cursor = end

    return occurrences
