"""The bundled adapters, run against the port conformance suites."""

from __future__ import annotations

from mamori.domain.sensitive_entity import SensitiveEntity
from mamori.infrastructure.detectors import (
    CHINESE,
    ENGLISH,
    JAPANESE,
    UNIVERSAL_RULES,
    AdaptiveLocaleDetector,
    CompositeDetector,
    CoOccurrencePass,
    DetectorPass,
    RegexDetector,
    default_detectors,
)
from mamori.infrastructure.storage import InMemoryMappingStore
from mamori.ports.detection_pass import DetectionContext, DetectionPass
from mamori.ports.detector import Detector
from mamori.ports.mapping_store import MappingStore

from .contracts import DetectionPassContract, DetectorContract, MappingStoreContract


class TestUniversalRegexDetector(DetectorContract):
    def make_detector(self) -> Detector:
        return RegexDetector("universal", UNIVERSAL_RULES)


class TestJapanesePack(DetectorContract):
    def make_detector(self) -> Detector:
        return RegexDetector("ja", JAPANESE.rules)


class TestEnglishPack(DetectorContract):
    def make_detector(self) -> Detector:
        return RegexDetector("en", ENGLISH.rules)


class TestChinesePack(DetectorContract):
    def make_detector(self) -> Detector:
        return RegexDetector("zh", CHINESE.rules)


class TestAdaptiveLocaleDetector(DetectorContract):
    def make_detector(self) -> Detector:
        return AdaptiveLocaleDetector(
            [JAPANESE, ENGLISH, CHINESE],
            always=[RegexDetector("universal", UNIVERSAL_RULES)],
        )


class TestCompositeDetector(DetectorContract):
    def make_detector(self) -> Detector:
        return CompositeDetector("all", list(default_detectors()))


class TestEmptyCompositeDetector(DetectorContract):
    """A composite with no children is still a valid detector that finds nothing."""

    def make_detector(self) -> Detector:
        return CompositeDetector("empty", [])


class TestInMemoryMappingStore(MappingStoreContract):
    def make_store(self) -> MappingStore:
        return InMemoryMappingStore()


class TestRulesPass(DetectionPassContract):
    def make_pass(self) -> DetectionPass:
        return DetectorPass(
            AdaptiveLocaleDetector(
                [JAPANESE, ENGLISH, CHINESE],
                always=[RegexDetector("universal", UNIVERSAL_RULES)],
            ),
            name="rules",
        )


class TestCoOccurrencePassContract(DetectionPassContract):
    def make_pass(self) -> DetectionPass:
        return CoOccurrencePass()

    def seeds(self, text: str) -> tuple[SensitiveEntity, ...]:
        """Whatever the rules find first, which is what the pipeline hands it."""
        return tuple(
            DetectorPass(
                AdaptiveLocaleDetector(
                    [JAPANESE, ENGLISH, CHINESE],
                    always=[RegexDetector("universal", UNIVERSAL_RULES)],
                )
            ).run(DetectionContext(text=text))
        )
