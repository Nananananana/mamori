"""Run several detectors as one."""

from __future__ import annotations

from collections.abc import Sequence

from ...domain.sensitive_entity import SensitiveEntity
from ...ports.detector import Detector

__all__ = ["CompositeDetector"]


class CompositeDetector:
    """Concatenates the results of its children.

    It does not swallow their exceptions. A detector that fails must propagate,
    so the caller can refuse to send anything -- silently dropping one
    detector's results would turn a failure into an under-detection, which is
    the one outcome this library exists to prevent.
    """

    def __init__(self, name: str, detectors: Sequence[Detector]) -> None:
        self._name = name
        self._detectors = tuple(detectors)

    @property
    def name(self) -> str:
        return self._name

    @property
    def detectors(self) -> tuple[Detector, ...]:
        return self._detectors

    def detect(self, text: str) -> Sequence[SensitiveEntity]:
        found: list[SensitiveEntity] = []
        for detector in self._detectors:
            found.extend(detector.detect(text))
        return found
