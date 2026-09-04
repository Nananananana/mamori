"""Detector adapters."""

from __future__ import annotations

from collections.abc import Sequence

from ...domain.stance import RuleTier, Stance
from ...ports.detection_pass import DetectionPass
from ...ports.detector import Detector
from .adaptive import AdaptiveLocaleDetector
from .algorithms import AlgorithmRegistry
from .co_occurrence import DEFAULT_SEED_TYPES, CoOccurrencePass
from .composite import CompositeDetector
from .entropy_pass import EntropyPass
from .gliner import GlinerRecognizer
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
from .nlp import NlpPass, SpacyRecognizer
from .patterns import (
    UNIVERSAL_RULES,
    PatternRule,
    compile_rule,
    luhn_valid,
    rules_for,
)
from .phone import PhoneNumberPass
from .pipeline import DetectionPipeline, DetectorPass
from .recognizers import (
    available_nlp_algorithms,
    available_phone_algorithms,
    nlp_passes,
    phone_passes,
    register_nlp_algorithm,
    register_phone_algorithm,
)
from .regex_detector import RegexDetector
from .secrets import available_secret_algorithms, register_secret_algorithm, secret_passes

__all__ = [
    "CHINESE",
    "DEFAULT_SEED_TYPES",
    "ENGLISH",
    "JAPANESE",
    "UNIVERSAL_RULES",
    "AdaptiveLocaleDetector",
    "AlgorithmRegistry",
    "CoOccurrencePass",
    "CompositeDetector",
    "DetectionPipeline",
    "DetectorPass",
    "EntropyPass",
    "GlinerRecognizer",
    "LocalePack",
    "NlpPass",
    "PatternRule",
    "PhoneNumberPass",
    "RegexDetector",
    "RuleTier",
    "SpacyRecognizer",
    "Stance",
    "available_locales",
    "available_nlp_algorithms",
    "available_phone_algorithms",
    "available_secret_algorithms",
    "build_pipeline",
    "compile_rule",
    "default_detectors",
    "get_locale",
    "luhn_valid",
    "nlp_passes",
    "phone_passes",
    "register_locale",
    "register_nlp_algorithm",
    "register_phone_algorithm",
    "register_secret_algorithm",
    "resolve_locales",
    "rules_for",
    "secret_passes",
]


def build_pipeline(
    locales: Sequence[str] | str | None = None,
    *,
    co_occurrence: CoOccurrencePass | None = None,
    stance: Stance = Stance.RECALL_FIRST,
    extra_passes: Sequence[DetectionPass] = (),
    patterns: Sequence[PatternRule] = (),
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
        patterns: Rules this deployment wrote, already compiled and already
            checked -- see
            :func:`~mamori.infrastructure.detectors.custom.compile_custom_rules`.
            They run in the first pass, beside the universal rules.

    Raises:
        ConfigurationError: a locale code has no registered pack.
    """
    universal = RegexDetector("universal", rules_for(UNIVERSAL_RULES, stance))
    # Custom rules run beside the universal ones and not after them: an
    # organisation's rule is a rule, arbitrated by the same resolution as
    # everything else. Running them in a later pass would have made them lose
    # every overlap to a built-in rule, which is precisely backwards for
    # somebody who wrote one because the built-ins were not enough.
    always: list[Detector] = [universal]
    if patterns:
        always.append(RegexDetector("custom", rules_for(patterns, stance)))
    rules = AdaptiveLocaleDetector(resolve_locales(locales), always=always, stance=stance)
    passes: list[DetectionPass] = [DetectorPass(rules, name="rules")]
    if co_occurrence is not None:
        passes.append(co_occurrence)
    passes.extend(extra_passes)
    return DetectionPipeline(passes, name="detection")


def default_detectors(
    locales: Sequence[str] | str | None = None,
    *,
    stance: Stance = Stance.RECALL_FIRST,
) -> tuple[Detector, ...]:
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
    return (build_pipeline(locales, co_occurrence=CoOccurrencePass(), stance=stance),)
