"""Detector adapters."""

from __future__ import annotations

from collections.abc import Sequence

from ...ports.detection_pass import DetectionPass
from ...ports.detector import Detector
from .adaptive import AdaptiveLocaleDetector
from .co_occurrence import DEFAULT_SEED_TYPES, CoOccurrencePass
from .composite import CompositeDetector
from .locales import (
    CHINESE,
    ENGLISH,
    JAPANESE,
    LocalePack,
    available_locales,
    get_locale,
    register_locale,
    resolve_locales,
)
from .patterns import UNIVERSAL_RULES, PatternRule, compile_rule, luhn_valid
from .pipeline import DetectionPipeline, DetectorPass
from .regex_detector import RegexDetector

__all__ = [
    "CHINESE",
    "DEFAULT_SEED_TYPES",
    "ENGLISH",
    "JAPANESE",
    "UNIVERSAL_RULES",
    "AdaptiveLocaleDetector",
    "CoOccurrencePass",
    "CompositeDetector",
    "DetectionPipeline",
    "DetectorPass",
    "LocalePack",
    "PatternRule",
    "RegexDetector",
    "available_locales",
    "build_pipeline",
    "compile_rule",
    "default_detectors",
    "get_locale",
    "luhn_valid",
    "register_locale",
    "resolve_locales",
]


def build_pipeline(
    locales: Sequence[str] | str | None = None,
    *,
    co_occurrence: CoOccurrencePass | None = None,
) -> DetectionPipeline:
    """Assemble the standard detection pipeline.

    Two passes. The first is the pattern rules -- universal ones plus whichever
    language packs the text gives a reason to run. The second, if enabled,
    propagates confidently-detected values to their other mentions in the same
    text.

    Args:
        locales: Language pack codes to enable, or ``None`` for all of them.
        co_occurrence: The second pass, or ``None`` to leave it out. Leaving it
            out costs recall on repeated names; there is no case where it costs
            safety.

    Raises:
        ConfigurationError: a locale code has no registered pack.
    """
    universal = RegexDetector("universal", UNIVERSAL_RULES)
    rules = AdaptiveLocaleDetector(resolve_locales(locales), always=[universal])
    passes: list[DetectionPass] = [DetectorPass(rules, name="rules")]
    if co_occurrence is not None:
        passes.append(co_occurrence)
    return DetectionPipeline(passes, name="detection")


def default_detectors(locales: Sequence[str] | str | None = None) -> tuple[Detector, ...]:
    """The detector set used when a session is created without one.

    Pattern rules and the co-occurrence pass. They run in microseconds, need no
    model and no GPU, and behave identically on every machine -- which is what
    makes the result reproducible enough to write security tests against.

    Args:
        locales: Language pack codes to enable, or ``None`` for all of them.
            Leaving it at ``None`` is the safer default: an unexpected language
            in a document is exactly when nobody has redacted it by hand.

    Raises:
        ConfigurationError: a code has no registered pack.
    """
    return (build_pipeline(locales, co_occurrence=CoOccurrencePass()),)
