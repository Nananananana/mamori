"""Shared detection helpers for the rule tests."""

from __future__ import annotations

from collections.abc import Sequence

from mamori.domain.normalization import NormalizedText
from mamori.infrastructure.detectors import CompositeDetector, default_detectors
from mamori.ports.detector import Detector

__all__ = ["detector_for", "types_in", "values_of"]


def detector_for(locales: Sequence[str] | str | None = None) -> Detector:
    """A detector limited to the given language packs, plus the universal rules."""
    return CompositeDetector("test", list(default_detectors(locales)))


def types_in(text: str, locales: Sequence[str] | str | None = None) -> set[str]:
    """Entity type names detected in ``text``."""
    normalized = NormalizedText.of(text)
    return {e.entity_type.name for e in detector_for(locales).detect(normalized.text)}


def values_of(text: str, type_name: str, locales: Sequence[str] | str | None = None) -> set[str]:
    """Values detected in ``text`` for one entity type."""
    normalized = NormalizedText.of(text)
    return {
        e.value
        for e in detector_for(locales).detect(normalized.text)
        if e.entity_type.name == type_name
    }
