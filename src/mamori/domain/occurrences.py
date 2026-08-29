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
    text: str, value: str, *, min_length: int = MIN_LOCATABLE_LENGTH
) -> tuple[Span, ...]:
    """Every span of ``text`` that is exactly ``value``.

    Args:
        text: The document, in the coordinates the caller will use.
        value: What to look for. Matched literally, never as a pattern.
        min_length: Values shorter than this return nothing rather than
            matching half the document.

    Returns:
        Spans in document order. Empty when the value is too short, or absent.
    """
    if len(value) < min_length or not text:
        return ()

    pattern = re.escape(value)
    if value[0] in _BOUNDED:
        pattern = f"(?<![{_WORD}])" + pattern
    if value[-1] in _BOUNDED:
        pattern = pattern + f"(?![{_WORD}])"
    return tuple(Span(m.start(), m.end()) for m in re.finditer(pattern, text))
