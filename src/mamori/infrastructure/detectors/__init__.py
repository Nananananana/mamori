"""Detector adapters."""

from __future__ import annotations

from collections.abc import Sequence

from ...ports.detector import Detector
from .adaptive import AdaptiveLocaleDetector
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
from .regex_detector import RegexDetector

__all__ = [
    "CHINESE",
    "ENGLISH",
    "JAPANESE",
    "UNIVERSAL_RULES",
    "AdaptiveLocaleDetector",
    "CompositeDetector",
    "LocalePack",
    "PatternRule",
    "RegexDetector",
    "available_locales",
    "compile_rule",
    "default_detectors",
    "get_locale",
    "luhn_valid",
    "register_locale",
    "resolve_locales",
]


def default_detectors(locales: Sequence[str] | str | None = None) -> tuple[Detector, ...]:
    """The detector set used when a session is created without one.

    Pattern rules only. They run in microseconds, need no model and no GPU, and
    behave identically on every machine -- which is what makes the result
    reproducible enough to write security tests against.

    Args:
        locales: Language pack codes to enable, or ``None`` for all of them.
            Leaving it at ``None`` is the safer default: an unexpected language
            in a document is exactly when nobody has redacted it by hand.

    Raises:
        ConfigurationError: a code has no registered pack.
    """
    universal = RegexDetector("universal", UNIVERSAL_RULES)
    return (AdaptiveLocaleDetector(resolve_locales(locales), always=[universal]),)
