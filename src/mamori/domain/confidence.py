"""Detector confidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = ["CERTAIN", "HIGH", "LOW", "MEDIUM", "Confidence"]


@dataclass(frozen=True, slots=True, order=True)
class Confidence:
    """A detector's confidence in a detection, in ``[0.0, 1.0]``."""

    value: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"confidence must be within [0, 1], got {self.value}")


CERTAIN: Final = Confidence(1.0)
HIGH: Final = Confidence(0.9)
MEDIUM: Final = Confidence(0.7)
LOW: Final = Confidence(0.5)
