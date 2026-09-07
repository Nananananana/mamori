"""The characters an earlier detection already claimed.

Every pass that reads prior findings asks the same question: *does this span
touch anything already found?* The answer used to be computed by building a
`frozenset` of every covered character index and testing membership one index
at a time.

That is the right answer computed the expensive way, in both directions:

* **Memory.** The set holds one boxed integer per covered character, so its
  size is a property of the *text* rather than of the findings. Measured on a
  100 KB mixed Japanese/English document with 7,377 findings: 70,492 indices,
  **43.5 bytes per input character** -- more than half the peak allocation of
  the whole protection, for a fact that 7,377 pairs of integers already state.
* **Time.** Building it walks every covered character (22.5 ms on that
  document), and every query then walks the span being asked about.

The findings are spans, so keep them as spans: sorted, merged, disjoint, and
searched. Memory becomes a property of how much was found, and a query is a
binary search instead of a walk.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable

__all__ = ["ClaimedSpans"]


class ClaimedSpans:
    """Half-open ranges, kept sorted and merged, asked about by overlap.

    Mutable on purpose: the co-occurrence pass claims each occurrence as it
    accepts it, so that two spellings of the same value cannot both be
    reported over the same characters.
    """

    __slots__ = ("_ends", "_starts")

    def __init__(self, spans: Iterable[tuple[int, int]] = ()) -> None:
        self._starts: list[int] = []
        self._ends: list[int] = []
        for start, end in sorted(spans):
            self.add(start, end)

    def __len__(self) -> int:
        """How many disjoint ranges, which is not how many were added."""
        return len(self._starts)

    def __bool__(self) -> bool:
        return bool(self._starts)

    def overlaps(self, start: int, end: int) -> bool:
        """Whether ``[start, end)`` shares a character with anything claimed.

        The ranges being disjoint and sorted is what makes one comparison
        enough: the last range starting before ``end`` is the only one that
        can overlap, because every earlier range ends at or before that one
        begins.
        """
        index = bisect_left(self._starts, end) - 1
        return index >= 0 and self._ends[index] > start

    def add(self, start: int, end: int) -> None:
        """Claim ``[start, end)``, merging it with anything it touches.

        Empty and reversed ranges are ignored rather than refused. A detector
        that reports one has a bug, but this is not where it is caught -- and
        silently keeping a zero-width range would make ``overlaps`` answer
        about a character that is not there.
        """
        if end <= start:
            return

        # Everything from the first range that reaches past `start` to the
        # last that begins before `end` becomes one range with this one.
        first = bisect_left(self._ends, start)
        last = bisect_left(self._starts, end)
        if first < last:
            start = min(start, self._starts[first])
            end = max(end, self._ends[last - 1])
            del self._starts[first:last]
            del self._ends[first:last]
        # After the deletion `first` is where this range belongs: everything
        # before it ends before `start`, everything at or after it begins at
        # or after `end`.
        self._starts.insert(first, start)
        self._ends.insert(first, end)

    def characters(self) -> frozenset[int]:
        """Every claimed index, for a caller that genuinely wants them.

        This is what the whole class exists to avoid building, and it is here
        because `DetectionContext.covered()` is a published part of the port
        and one caller -- the contract test that checks a pass does not
        re-report -- wants exactly this, over samples a few dozen characters
        long.
        """
        return frozenset(
            index
            for start, end in zip(self._starts, self._ends, strict=True)
            for index in range(start, end)
        )
