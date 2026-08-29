"""Cutting a long text into pieces a model can be asked about.

A model has a context limit, and a document can be longer than it. There are
three things to do about that and only one of them is acceptable.

**Truncate** — scan the first N characters and report success. The pass that
did this would say it found nothing wrong with a document it never read, which
is the exact failure this library exists to prevent.

**Refuse** — scan nothing. Honest, and what mamori did before: the pattern
rules still run, so the guarantee holds, but the improvement silently stops
applying at the length where documents get interesting.

**Window** — cut the text into overlapping pieces and ask about each. The
overlap is the whole difficulty: an entity lying across a cut is, to each
piece, a fragment. ``tanaka@exa`` and ``mple.com`` are not an email address to
anybody. So the windows overlap by enough that any entity of ordinary length
appears whole in at least one of them, and cuts prefer a line or sentence
boundary, where an entity is least likely to be standing.

Windows are returned with their offsets, because a detection found at position
12 of the third window is not at position 12 of the document. Getting that
arithmetic wrong would corrupt the text at replacement time, so it lives here,
in one function, with the offset carried alongside the text rather than
recomputed by each caller.

This module is pure text arithmetic: no model, no I/O, nothing to configure
beyond two numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Window", "windows"]

#: Characters of overlap between neighbouring windows. Comfortably longer than
#: any single entity this library detects -- a database URL with credentials in
#: it is the longest, and it does not approach this -- so an entity cut by one
#: boundary is whole inside its neighbour.
DEFAULT_OVERLAP = 400

#: Where a cut is allowed to slide to, as a fraction of the window. A cut looks
#: backwards for a paragraph or sentence boundary, but only this far: past it,
#: honouring the boundary would cost more window than it saves.
_SEEK_FRACTION = 0.25

#: Preferred cut points, best first. A blank line separates topics, a newline
#: separates lines, and the sentence enders cover both the ASCII and the CJK
#: forms because a Japanese document contains no ASCII full stops at all.
_BOUNDARIES = ("\n\n", "\n", "。", "．", ". ", "！", "？", "、", ", ")


@dataclass(frozen=True, slots=True)
class Window:
    """A piece of a text, and where it starts in the original."""

    offset: int
    text: str

    @property
    def end(self) -> int:
        return self.offset + len(self.text)

    def locate(self, start: int, end: int) -> tuple[int, int]:
        """Translate a span inside this window to the original coordinates."""
        return self.offset + start, self.offset + end


def windows(text: str, size: int, overlap: int = DEFAULT_OVERLAP) -> tuple[Window, ...]:
    """Cut ``text`` into overlapping windows of at most ``size`` characters.

    A text that already fits comes back as one window at offset zero, which is
    the common case and costs nothing.

    Args:
        text: The document, in the coordinates the caller will use.
        size: The most any one window may contain.
        overlap: How much of the previous window each window repeats. Clamped
            below ``size`` -- an overlap at least as large as the window would
            never advance, and the loop would not terminate.

    Raises:
        ValueError: ``size`` is not positive, or ``overlap`` is negative.
    """
    if size <= 0:
        raise ValueError("window size must be positive")
    if overlap < 0:
        raise ValueError("overlap may not be negative")
    if len(text) <= size:
        return (Window(0, text),) if text else ()

    # Leave room to advance even in the worst case. Half the window is the
    # least aggressive bound that still guarantees progress.
    overlap = min(overlap, size // 2)
    seek = int(size * _SEEK_FRACTION)

    result: list[Window] = []
    start = 0
    while start < len(text):
        end = start + size
        if end >= len(text):
            result.append(Window(start, text[start:]))
            break
        cut = _boundary_before(text, end, seek)
        result.append(Window(start, text[start:cut]))
        start = max(cut - overlap, start + 1)
    return tuple(result)


def _boundary_before(text: str, end: int, seek: int) -> int:
    """The nicest place to cut at or shortly before ``end``.

    Falls back to ``end`` itself. A hard cut mid-word is not a correctness
    problem -- the overlap covers it -- so there is no reason to search far.
    """
    floor = max(end - seek, 1)
    for boundary in _BOUNDARIES:
        found = text.rfind(boundary, floor, end)
        if found != -1:
            return found + len(boundary)
    return end
