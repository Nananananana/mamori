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

#: Whitespace inside one line, and how much of it a mangled placeholder may
#: carry. **Bounded, and the bound is what makes this scan linear.**
#:
#: Every mutation this scanner exists for inserts at most one space per
#: position -- `< PERSON _ 001 >` is the worst observed. Four is that with
#: room, and it is a limit rather than a preference: unbounded, the engine
#: matched `PERSON`, ran `[^\S\n]*` to the end of a 8,000-space run, failed
#: on the separator, and backtracked once per space. Measured before this
#: line: 9ms at 500 characters, 2,292ms at 8,000 -- four times the work for
#: twice the input, all the way up.
_GAP = r"[^\S\n]{0,4}"

#: The same, where an underscore or hyphen may not be consumed as the gap.
_GAP_NO_JOIN = r"[^\S\n_\-]{0,4}"

#: How long a type name can be, and how many `_`-separated parts it can have.
#: Not chosen: `TYPE_NAME_RE` is `[A-Z][A-Z0-9_]{0,62}`, so 63 characters is
#: the longest name that can ever have been allocated, and 63 characters hold
#: at most 32 parts. A candidate longer than this is not a mangled placeholder
#: -- it is a word that begins like one, and reading the rest of the document
#: to find that out is exactly the cost this bound removes.
_TYPE_TAIL = "{0,62}"
_PARTS = "{0,31}"

_LENIENT_RE = re.compile(
    r"""
    # A bracket, or a boundary. Without one of the two the engine starts a
    # candidate at every position of a long alphanumeric run -- `restore` on a
    # 128KB response holding one base64 blob took 456 seconds, measured, and a
    # model emitting a long token is ordinary rather than adversarial.
    #
    # The alternation matters and the first version got it wrong: a bare
    # lookbehind in front of the optional bracket refused `A<PERSON_001>`,
    # because the character before `<` is alphanumeric. A bracket **is** the
    # boundary; only the unbracketed form needs one in front of it. Found by
    # `test_restore_undoes_protect`, on `田中太郎さんA田中太郎さん`.
    (?:
        (?P<open>[<\[\{])"""
    + _GAP
    + r"""
      |
        (?<![A-Za-z0-9])
    )
    (?P<type>[A-Za-z][A-Za-z0-9]"""
    + _TYPE_TAIL
    + r"""(?:"""
    + _GAP_NO_JOIN
    + r"""[_\-]"""
    + _GAP
    + r"""[A-Za-z0-9]{1,62})"""
    + _PARTS
    + r"""?)
    """
    + _GAP_NO_JOIN
    + r"""[\s_\-]"""
    + _GAP
    + r"""
    (?P<index>\d{1,6})
    (?:"""
    + _GAP
    + r"""(?P<close>[>\]\}]))?
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
        # Built through `parse`, which returns `None` instead of raising.
        # Constructing one directly meant an ordinary long identifier in a
        # model's reply -- `MAXIMUM_NUMBER_OF_..._LIMIT_2`, 66 characters --
        # raised out of `restore` and `feed`, because 0.31 taught `Placeholder`
        # to refuse a type name outside its grammar and this line hands it
        # untrusted text. The precision guard two lines down would have
        # discarded it harmlessly; it never got the chance.
        candidate = Placeholder.parse(f"<{type_name}_{index:03d}>")
        if candidate is None:
            continue
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
