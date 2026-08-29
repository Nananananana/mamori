"""Shared detection helpers for the rule tests.

Rule tests describe *core* rules, so they run at the balanced stance by
default. That is not the shipping default -- ``PrivacySession`` runs
recall-first -- but a test that pins down "a bare digit run is not a phone
number" is a statement about one rule, and it would be meaningless if a wide
rule two tiers away could satisfy it.

Wide-tier behaviour has its own tests, which pass the stance explicitly.
"""

from __future__ import annotations

from collections.abc import Sequence

from mamori.domain.normalization import NormalizedText
from mamori.domain.stance import Stance
from mamori.infrastructure.detectors import CompositeDetector, default_detectors
from mamori.ports.detector import Detector

__all__ = ["detector_for", "types_in", "values_of"]


def detector_for(
    locales: Sequence[str] | str | None = None,
    stance: Stance = Stance.BALANCED,
) -> Detector:
    """A detector limited to the given language packs, plus the universal rules."""
    return CompositeDetector("test", list(default_detectors(locales, stance=stance)))


def types_in(
    text: str,
    locales: Sequence[str] | str | None = None,
    stance: Stance = Stance.BALANCED,
) -> set[str]:
    """Entity type names detected in ``text``."""
    normalized = NormalizedText.of(text)
    return {e.entity_type.name for e in detector_for(locales, stance).detect(normalized.text)}


def values_of(
    text: str,
    type_name: str,
    locales: Sequence[str] | str | None = None,
    stance: Stance = Stance.BALANCED,
) -> set[str]:
    """Values detected in ``text`` for one entity type."""
    normalized = NormalizedText.of(text)
    return {
        e.value
        for e in detector_for(locales, stance).detect(normalized.text)
        if e.entity_type.name == type_name
    }
