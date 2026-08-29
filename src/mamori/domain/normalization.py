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

Known limitation
----------------
Normalization is applied per character, so combining sequences that NFKC would
merge across characters (``カ`` + ``゛`` -> ``ガ``) are *not* merged. Merging
them would make a character-level offset map ambiguous. Detectors must not rely
on such merging.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

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
        chunks: list[str] = []
        starts: list[int] = []
        ends: list[int] = []
        for index, char in enumerate(original):
            folded = unicodedata.normalize("NFKC", char)
            if not folded:
                # NFKC can delete a character (e.g. some format controls).
                # Keep the original so offsets stay total.
                folded = char
            chunks.append(folded)
            starts.extend([index] * len(folded))
            ends.extend([index + 1] * len(folded))
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


def normalize_value(value: str) -> str:
    """Canonical form used to decide whether two detections are the same entity.

    Applies NFKC, strips surrounding whitespace and collapses internal runs of
    whitespace (including full-width spaces), so ``田中太郎``, ``田中 太郎``
    and ``田中　太郎`` share one placeholder.
    """
    folded = unicodedata.normalize("NFKC", value)
    return " ".join(folded.split())
