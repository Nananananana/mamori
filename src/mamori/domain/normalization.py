"""Offset-preserving text normalization.

Why this exists
---------------
Japanese text mixes full-width and half-width forms, so detection has to run on
a normalized string (``ｔａｎａｋａ＠ｅｘａｍｐｌｅ．ｃｏｍ`` must match the
same pattern as ``tanaka@example.com``). But normalization can change the
*length* of the string, and every replacement has to be applied to the
**original** text -- otherwise the user gets back mangled input.

``NormalizedText`` therefore keeps, for every character of the normalized
string, the range of the original string it came from, so a span found in
normalized coordinates can be mapped back exactly.

Characters that combine
-----------------------
NFKC is defined on *strings*, and applying it one character at a time is not
the same function. ``ﾀ`` + ``ﾞ`` is ``ダ`` to NFKC and is ``タ`` + U+3099 to a
per-character loop -- a base kana followed by a *combining* mark, which is not
in ``[ァ-ヶー]`` and therefore not in any rule this library has.

That was the implementation until 0.32, and it leaked. Half-width katakana is
how Japanese names arrive from a bank statement, a legacy database export or a
fixed-width CSV, and **all 28** voiced and semi-voiced pairs were affected:

    ﾔﾏﾀﾞさん        nothing detected at all
    ﾀﾞｲｽｹさん       ``ﾀﾞ`` left in the text, the rest replaced
    氏名: ﾔﾏﾀﾞ      ``氏名: <PERSON_001>ﾞ`` -- the mark stranded outside the token
    ダイスケ / ﾀﾞｲｽｹ  two placeholders for one person, though ``normalize_value``
                    says they are one identity

So the text is normalized in **groups**: one character, plus every following
character whose own normalized form begins with a combining mark. The offset
map stays exact -- ``ﾀﾞ`` is a clean two-original-characters to one-normalized
group, so a span covering it maps back to both. The old docstring said merging
"would make a character-level offset map ambiguous"; it does not, and the map
below is what says so.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from .span import Span

__all__ = ["NormalizedText", "normalize_value"]


@dataclass(frozen=True, slots=True)
class NormalizedText:
    """A normalized view of a text that can map spans back to the original."""

    original: str = field(repr=False)
    text: str = field(repr=False)
    #: For normalized index i, the original index it starts at.
    _starts: tuple[int, ...] = field(repr=False)
    #: For normalized index i, the original index just past its source char.
    _ends: tuple[int, ...] = field(repr=False)

    @classmethod
    def of(cls, original: str) -> NormalizedText:
        """Normalize ``original`` while recording an offset map."""
        if original.isascii() or _is_identity(original):
            # Every group below is one character folding to itself, so the
            # offset map is the identity: a few C calls instead of a Python
            # loop over every character. ASCII always qualifies; Japanese
            # written the ordinary way -- composed kana, nothing half-width --
            # qualifies too, and `_is_identity` says exactly when.
            positions = tuple(range(len(original)))
            return cls(
                original=original,
                text=original,
                _starts=positions,
                _ends=tuple(range(1, len(original) + 1)),
            )
        return cls._of_slowly(original)

    @classmethod
    def _of_slowly(cls, original: str) -> NormalizedText:
        """The general case: group, fold each group, record where it came from."""
        chunks: list[str] = []
        starts: list[int] = []
        ends: list[int] = []
        index = 0
        length = len(original)
        while index < length:
            # A group is one character plus every following character that
            # normalizes to something beginning with a combining mark. That is
            # what makes `ﾀ` + `ﾞ` fold to `ダ` rather than to a base plus a
            # mark nothing matches.
            stop = index + 1
            while stop < length and _combines_leftwards(original[stop]):
                stop += 1
            folded = unicodedata.normalize("NFKC", original[index:stop])
            if not folded:
                # Defensive. No lone code point folds to nothing -- checked
                # across all 1,114,112 of them -- so a group cannot either
                # without every character in it doing so. Keeping the original
                # is what stops an empty fold from dropping the offsets for
                # those characters.
                folded = original[index:stop]
            chunks.append(folded)
            starts.extend([index] * len(folded))
            ends.extend([stop] * len(folded))
            index = stop
        return cls(
            original=original,
            text="".join(chunks),
            _starts=tuple(starts),
            _ends=tuple(ends),
        )

    def to_original_span(self, start: int, end: int) -> Span:
        """Map a span in normalized coordinates back to the original text."""
        if not 0 <= start < end <= len(self.text):
            raise ValueError(f"span {start}:{end} out of range for normalized text")
        return Span(self._starts[start], self._ends[end - 1])

    def __len__(self) -> int:
        return len(self.text)


def _is_identity(text: str) -> bool:
    """Whether the grouped fold below would leave ``text`` and its offsets alone.

    Two conditions, and the first version had only the first. A text already
    in NFKC folds to itself -- but the grouping still joins a base with any
    following combining mark, and a group of two characters that folds to two
    characters maps *both* back to the pair. `1` + U+3099 is in normal form,
    since nothing composes with a digit, and its offset map is not the
    identity. Hypothesis found it on the first run of
    `tests/test_fast_paths.py`, which holds this shortcut against the loop it
    bypasses.

    So: normal, **and** no combining mark anywhere. Within a normalized
    string a character folds to itself, which is what makes
    ``unicodedata.combining`` the same question as :func:`_combines_leftwards`
    -- the half-width voiced mark that motivates the grouping is not in
    normal form and cannot be present here. The scan is a C call per
    character and short-circuits on the first mark; the loop it replaces is
    ten Python statements per character.
    """
    return unicodedata.is_normalized("NFKC", text) and not any(
        unicodedata.combining(char) for char in text
    )


@lru_cache(maxsize=4096)
def _combines_leftwards(char: str) -> bool:
    """Whether ``char`` attaches to the character before it under NFKC.

    Cached: a document is a few hundred distinct characters repeated many
    thousands of times, and this was asked once per character -- 97,580 times
    for one 6.5KB document, measured. The non-ASCII path keeps its loop and
    loses most of its cost.

    Asked of the **normalized** form, not the raw one. U+FF9E, the half-width
    voiced mark, has combining class 0 itself and folds to U+3099, which has
    class 8 -- so a test on the raw character says no and is wrong for the
    exact case this exists for.
    """
    folded = unicodedata.normalize("NFKC", char)
    return bool(folded) and unicodedata.combining(folded[0]) != 0


def normalize_value(value: str) -> str:
    """Canonical form used to decide whether two detections are the same entity.

    Applies NFKC, strips surrounding whitespace and collapses internal runs of
    whitespace (including full-width spaces), so ``田中太郎``, ``田中 太郎``
    and ``田中　太郎`` share one placeholder.
    """
    folded = unicodedata.normalize("NFKC", value)
    return " ".join(folded.split())
