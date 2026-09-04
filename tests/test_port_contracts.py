"""The bundled adapters, run against the port conformance suites."""

from __future__ import annotations

from mamori.domain.sensitive_entity import SensitiveEntity
from mamori.domain.stance import Stance
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
    #: A `DetectorPass` wraps a plain `Detector`, whose contract is
    #: deliberately narrow: it is handed a text and nothing else. Declared
    #: rather than skipped by accident.
    consumes_prior_findings = False

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

    def sample(self) -> str:
        """A name settled by an honorific in one sentence and unanchored in the
        next -- the case this pass exists for.

        The contract's default text is not it. There the rules already find
        both occurrences of the name, so this pass correctly adds nothing, and
        a coverage check over nothing passes while checking nothing. That was
        the fifth vacuous case in this contract and the only one that was not
        a skip.

        English rather than Chinese, which was the first attempt: the Chinese
        pack has a rule for a *repeated* surname, so both mentions are found by
        rules at either stance and this pass is genuinely redundant there. The
        salutation is the anchor, the second mention has none, and propagation
        is the only thing that reaches it.
        """
        return "Dear Jane Doe,\nthe report from Jane Doe is attached."

    def seeds(self, text: str) -> tuple[SensitiveEntity, ...]:
        """Whatever the rules find first, which is what the pipeline hands it.

        At the **balanced** stance, deliberately. The wide tier reports a
        Chinese surname plus one or two characters wherever it appears, so at
        the recall-first stance the rules already find both mentions and this
        pass correctly adds nothing -- which made the coverage check below pass
        while checking nothing. The balanced stance is where propagation is the
        only thing that finds the second mention, and is the case the pass was
        written for.
        """
        return tuple(
            DetectorPass(
                AdaptiveLocaleDetector(
                    [JAPANESE, ENGLISH, CHINESE],
                    always=[RegexDetector("universal", UNIVERSAL_RULES)],
                    stance=Stance.BALANCED,
                )
            ).run(DetectionContext(text=text))
        )
