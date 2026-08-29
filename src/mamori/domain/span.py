"""Half-open character range within a text."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Span"]


@dataclass(frozen=True, slots=True, order=True)
class Span:
    """A half-open ``[start, end)`` character range."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"span start must be >= 0, got {self.start}")
        if self.end <= self.start:
            raise ValueError(f"span end must be > start, got {self.start}:{self.end}")

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: Span) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: Span) -> bool:
        return self.start <= other.start and other.end <= self.end
