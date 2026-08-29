"""Finding every place a known value appears in a text.

Two parts of this library need the same thing: a value has been judged
sensitive, and now every occurrence of it must be located. The co-occurrence
pass needs it because a name confirmed by an honorific in line one is the same
name in line nine. The model parser needs it because a model reports *what* it
found far more reliably than *where*.

Doing it with ``str.find`` is wrong in a way that only shows up later. ``Ann``
appears inside ``Announcement``, and replacing that is worse than the miss it
was meant to fix. So Latin-script values are matched on word boundaries, and
CJK values are not, because Chinese and Japanese are written without spaces and
a boundary rule there would find nothing at all.

Pure text matching: no rules, no policy, no configuration.
"""

from __future__ import annotations

import re

from .span import Span

__all__ = ["MIN_LOCATABLE_LENGTH", "find_occurrences"]

#: Characters that participate in a word, for the scripts that have words.
_WORD = "A-Za-z0-9"

#: Values whose first or last character is one of these get a boundary check.
#: A CJK value does not, because there is no boundary to check against.
_BOUNDED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

#: Shorter than this and a value matches too much to be worth locating. One
#: character matches most of a CJK document; two is the shortest that carries
#: any information.
MIN_LOCATABLE_LENGTH = 2


def find_occurrences(
    text: str,
    value: str,
    *,
    min_length: int = MIN_LOCATABLE_LENGTH,
    fold_case: bool = False,
    fold_wrapping: bool = False,
) -> tuple[Span, ...]:
    """Every span of ``text`` that is exactly ``value``.

    Args:
        text: The document, in the coordinates the caller will use.
        value: What to look for. Matched literally, never as a pattern.
        min_length: Values shorter than this return nothing rather than
            matching half the document.
        fold_case: Match ``alex rivera`` where ``Alex Rivera`` was given.

            Off by default, and deliberately so: the co-occurrence pass uses
            this function to decide that two runs of text are the same value,
            and ``Mark`` the name and ``mark`` the verb are not.

            On for restoring a surrogate, where the trade runs the other way. A
            surrogate that is not put back is a plausible sentence about a
            person who does not exist; putting one back because a model
            re-capitalised it costs nothing but the capital letter.
        fold_wrapping: Match a value whose internal spaces became a line break.

            ``Alex\nRivera`` is ``Alex Rivera`` wrapped by whatever was
            rendering it. At most one line break per gap, so this cannot reach
            across a blank line and join two paragraphs into a name.

    Returns:
        Spans in document order. Empty when the value is too short, or absent.
    """
    if len(value) < min_length or not text:
        return ()

    pattern = _wrapped(value) if fold_wrapping and " " in value else re.escape(value)
    if value[0] in _BOUNDED:
        pattern = f"(?<![{_WORD}])" + pattern
    if value[-1] in _BOUNDED:
        pattern = pattern + f"(?![{_WORD}])"
    flags = re.IGNORECASE if fold_case else 0
    return tuple(Span(m.start(), m.end()) for m in re.finditer(pattern, text, flags))


#: One line break at most, with whatever spaces sit either side of it. Enough
#: for a wrapped name, not enough to join two paragraphs into one.
_WRAPPED_GAP = r"[^\S\r\n]*\r?\n?[^\S\r\n]*"


def _wrapped(value: str) -> str:
    """``value`` as a pattern whose spaces may have become a line break."""
    return _WRAPPED_GAP.join(re.escape(part) for part in value.split(" ") if part)
