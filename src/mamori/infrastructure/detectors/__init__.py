"""Detector adapters."""

from __future__ import annotations

from ...ports.detector import Detector
from .composite import CompositeDetector
from .japanese_names import COMMON_SURNAMES, NAME_RULES
from .patterns import DEFAULT_RULES, PatternRule, luhn_valid, my_number_valid
from .regex_detector import RegexDetector

__all__ = [
    "COMMON_SURNAMES",
    "DEFAULT_RULES",
    "NAME_RULES",
    "CompositeDetector",
    "PatternRule",
    "RegexDetector",
    "default_detectors",
    "luhn_valid",
    "my_number_valid",
]


def default_detectors() -> tuple[Detector, ...]:
    """The detector set used when a session is created without one.

    Pattern rules only. They run in microseconds, need no model and no GPU, and
    behave identically on every machine -- which is what makes the result
    reproducible enough to write security tests against.
    """
    return (
        RegexDetector("regex", DEFAULT_RULES),
        RegexDetector("jp-name", NAME_RULES),
    )
