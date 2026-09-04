"""Two algorithms that need a library, and the switch that selects them.

0.31 made secret detection a named choice. 0.32 does the same for the two
questions the standard library cannot answer well:

    nlp     a personal name with no anchor beside it -- what `SECURITY.md`
            calls the largest single gap in this library
    phone   whether a run of digits is a telephone number, which a regular
            expression cannot know and a numbering plan can

`NlpPass` is tested against a fake recogniser so it runs everywhere, and the
spaCy adapter only where spaCy is installed. That split is deliberate: the
pass is where the bookkeeping bugs live and the adapter is where the
environment problems live, and mixing them means a missing model hides a
mapping bug.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from mamori import MamoriConfig
from mamori.domain import entity_types as t
from mamori.domain.confidence import Confidence
from mamori.domain.span import Span
from mamori.domain.stance import Stance
from mamori.errors import ConfigurationError, DetectionError
from mamori.infrastructure.detectors import NlpPass, PhoneNumberPass
from mamori.infrastructure.detectors.recognizers import (
    DEFAULT_NLP_ALGORITHM,
    DEFAULT_PHONE_ALGORITHM,
    available_nlp_algorithms,
    available_phone_algorithms,
    nlp_passes,
    phone_passes,
    register_nlp_algorithm,
)
from mamori.ports.detection_pass import DetectionContext
from mamori.ports.nlp_recognizer import NlpRecognizer, RecognizedEntity

from .contracts import DetectionPassContract


class Fake:
    """A recogniser that reports whatever it was told to, at fixed offsets."""

    name = "fake"

    def __init__(self, entities: Sequence[RecognizedEntity] = ()) -> None:
        self._entities = tuple(entities)

    def entities(self, text: str) -> Sequence[RecognizedEntity]:
        return self._entities


class Broken:
    name = "broken"

    def entities(self, text: str) -> Sequence[RecognizedEntity]:
        raise RuntimeError("the model did not load")


def found_by(pass_: NlpPass, text: str, prior: Sequence[object] = ()) -> list[object]:
    return list(pass_.run(DetectionContext(text=text, found=tuple(prior))))  # type: ignore[arg-type]


class TestTheRecognizerPort:
    def test_the_fake_satisfies_it(self) -> None:
        assert isinstance(Fake(), NlpRecognizer)

    def test_it_carries_no_value(self) -> None:
        """A recogniser reports *where*. The application reads the characters,
        so a recogniser cannot report a span and a value that disagree -- which
        is the failure that puts the wrong characters back into a document."""
        assert not hasattr(RecognizedEntity("PERSON", Span(0, 1)), "value")


class Adapting:
    """A recogniser that reports the first four characters, when there are four.

    A fixed span would be outside every hostile input the contract feeds it --
    and a real recogniser never reports a span outside the text it was given,
    so a fake that does is testing the pass against something no
    implementation does.
    """

    name = "adapting"

    def entities(self, text: str) -> Sequence[RecognizedEntity]:
        return [RecognizedEntity("PERSON", Span(0, 4))] if len(text) >= 4 else []


class TestNlpPassContract(DetectionPassContract):
    #: A recogniser that reports something, so the coverage check has findings
    #: to feed back. `Fake()` with no entities reports nothing, and a check
    #: over nothing checks nothing.
    def make_pass(self) -> NlpPass:
        return NlpPass(Adapting())

    def sample(self) -> str:
        return "田中太郎さんへ tanaka@example.com"


class TestWhatThePassDoesWithALabel:
    def test_a_person_becomes_a_person(self) -> None:
        text = "I spoke to Sarah Okonkwo yesterday."
        start = text.index("Sarah")
        pass_ = NlpPass(Fake([RecognizedEntity("PERSON", Span(start, start + 13))]))
        (entity,) = found_by(pass_, text)
        assert entity.entity_type is t.PERSON  # type: ignore[attr-defined]
        assert entity.value == "Sarah Okonkwo"  # type: ignore[attr-defined]

    def test_a_bio_prefix_is_stripped(self) -> None:
        """`B-PER` is what a CoNLL-style transformer emits."""
        pass_ = NlpPass(Fake([RecognizedEntity("B-PER", Span(0, 5))]))
        assert found_by(pass_, "Sarah says hello")

    def test_an_unmapped_label_is_ignored(self) -> None:
        """A model that grows a new label must not start producing entities
        nobody decided about."""
        pass_ = NlpPass(Fake([RecognizedEntity("MONEY", Span(0, 5))]))
        assert found_by(pass_, "£5.00 please") == []

    def test_org_is_not_mapped_by_default(self) -> None:
        """It was, for one afternoon. `en_core_web_sm` tags "The Quarterly
        Business Review" and "Social Security Number" as organisations -- the
        exact two phrases the English stoplist exists to reject."""
        pass_ = NlpPass(Fake([RecognizedEntity("ORG", Span(0, 5))]))
        assert found_by(pass_, "Acme says hello") == []

    def test_a_caller_can_map_it_anyway(self) -> None:
        pass_ = NlpPass(Fake([RecognizedEntity("ORG", Span(0, 4))]), labels={"ORG": t.COMPANY_NAME})
        (entity,) = found_by(pass_, "Acme says hello")
        assert entity.entity_type is t.COMPANY_NAME  # type: ignore[attr-defined]

    def test_a_model_is_worth_medium_confidence(self) -> None:
        """A checksum is CERTAIN and an anchor is HIGH. Sitting below both is
        what lets `min_confidence` drop a model's opinion."""
        pass_ = NlpPass(Fake([RecognizedEntity("PERSON", Span(0, 5))]))
        (entity,) = found_by(pass_, "Sarah says hello")
        assert entity.confidence == Confidence(0.7)  # type: ignore[attr-defined]

    def test_a_low_score_is_dropped(self) -> None:
        pass_ = NlpPass(Fake([RecognizedEntity("PERSON", Span(0, 5), score=0.2)]), min_score=0.5)
        assert found_by(pass_, "Sarah says hello") == []

    def test_the_source_says_a_model_found_it(self) -> None:
        pass_ = NlpPass(Fake([RecognizedEntity("PERSON", Span(0, 5))]))
        (entity,) = found_by(pass_, "Sarah says hello")
        assert entity.source == "nlp:fake"  # type: ignore[attr-defined]


class TestThePassTreatsAModelAsUntrustedInput:
    def test_a_span_outside_the_text_is_refused(self) -> None:
        """A model is not this library's code. A span it invents would splice
        characters that are not there."""
        pass_ = NlpPass(Fake([RecognizedEntity("PERSON", Span(0, 500))]))
        with pytest.raises(DetectionError, match="outside the text"):
            found_by(pass_, "short")

    def test_a_recognizer_that_raises_stops_the_request(self) -> None:
        """Fail closed. A model that did not load must not report nothing --
        the caller cannot tell that from a clean document."""
        with pytest.raises(DetectionError, match="did not load"):
            found_by(NlpPass(Broken()), "anything at all")

    def test_it_does_not_claim_what_a_rule_already_has(self) -> None:
        """An anchor beats a model."""
        from mamori.domain.sensitive_entity import SensitiveEntity

        text = "Dear Sarah Okonkwo,"
        prior = SensitiveEntity(entity_type=t.PERSON, span=Span(5, 18), value="Sarah Okonkwo")
        pass_ = NlpPass(Fake([RecognizedEntity("PERSON", Span(5, 18))]))
        assert found_by(pass_, text, [prior]) == []


class TestTheSwitch:
    def test_the_defaults_are_what_shipped_before(self) -> None:
        assert MamoriConfig().nlp == DEFAULT_NLP_ALGORITHM == "none"
        assert MamoriConfig().phone == DEFAULT_PHONE_ALGORITHM == "patterns"

    def test_the_defaults_add_no_pass(self) -> None:
        assert nlp_passes("none") == ()
        assert phone_passes("patterns") == ()

    @pytest.mark.parametrize(
        ("key", "value"),
        [("nlp", "spcay"), ("phone", "phonenumbrs")],
    )
    def test_a_misspelling_is_refused_when_the_file_is_read(self, key: str, value: str) -> None:
        """Not silently the default. A config claiming it runs a model, and a
        scanner that does not, is the worst outcome available."""
        with pytest.raises(ConfigurationError, match="unknown"):
            MamoriConfig.from_mapping({key: value})

    def test_from_the_environment(self) -> None:
        assert MamoriConfig.from_env({"MAMORI_PHONE": "phonenumbers"}).phone == "phonenumbers"

    def test_the_default_is_listed_first(self) -> None:
        assert available_nlp_algorithms()[0] == DEFAULT_NLP_ALGORITHM
        assert available_phone_algorithms()[0] == DEFAULT_PHONE_ALGORITHM

    def test_a_fourth_recognizer_is_a_call(self) -> None:
        register_nlp_algorithm("fake", lambda: (NlpPass(Fake()),))
        try:
            assert "fake" in available_nlp_algorithms()
            assert MamoriConfig.from_mapping({"nlp": "fake"}).nlp == "fake"
            (only,) = nlp_passes("fake")
            assert isinstance(only, NlpPass)
        finally:
            from mamori.infrastructure.detectors import recognizers

            del recognizers._NLP._factories["fake"]

    def test_it_reaches_the_session(self) -> None:
        register_nlp_algorithm(
            "always", lambda: (NlpPass(Fake([RecognizedEntity("PERSON", Span(0, 5))])),)
        )
        try:
            config = MamoriConfig(stance=Stance.BALANCED, nlp="always")
            assert "PERSON" in config.session().inspect("Zzzzz was here")
            assert "PERSON" not in MamoriConfig(stance=Stance.BALANCED).session().inspect(
                "Zzzzz was here"
            )
        finally:
            from mamori.infrastructure.detectors import recognizers

            del recognizers._NLP._factories["always"]


class TestPhoneNumbers:
    """Measured against the rules that ship. `SECURITY.md`: *unseparated digit
    runs are deliberately not matched -- an order number looks identical.*"""

    def setup_method(self) -> None:
        pytest.importorskip("phonenumbers")

    def config(self) -> MamoriConfig:
        return MamoriConfig(stance=Stance.BALANCED, phone="phonenumbers")

    @pytest.mark.parametrize(
        "text",
        [
            "電話は090-1234-5678です",
            "call (415) 555-0198 tomorrow",
            "reach me on +81 90 1234 5678",
            "请拨打13812345678",
        ],
        ids=["ja separated", "us formatted", "international", "zh mobile"],
    )
    def test_what_the_rules_already_find_is_still_found(self, text: str) -> None:
        assert "PHONE" in self.config().session().inspect(text)

    def test_an_unseparated_number_the_rules_miss(self) -> None:
        """The documented gap, closed by a plan rather than a wider shape."""
        text = "ring 07911123456 please"
        assert "PHONE" not in MamoriConfig(stance=Stance.BALANCED).session().inspect(text)
        assert "PHONE" in self.config().session().inspect(text)

    def test_an_order_number_is_correctly_not_a_number(self) -> None:
        """The half a wider regular expression cannot give. Recall and
        precision improve together, which is what a checksum does."""
        assert self.config().session().inspect("order 98765432109 shipped") == ()

    def test_it_is_a_high_confidence_detection(self) -> None:
        """A plan accepting a number is an anchor, not a shape."""
        from mamori.domain.confidence import HIGH

        pass_ = PhoneNumberPass()
        (entity,) = list(pass_.run(DetectionContext(text="call (415) 555-0198")))
        assert entity.confidence == HIGH

    def test_at_least_one_region_is_required(self) -> None:
        with pytest.raises(ValueError, match="region"):
            PhoneNumberPass(regions=())


class TestPhonePassContract(DetectionPassContract):
    def make_pass(self) -> PhoneNumberPass:
        pytest.importorskip("phonenumbers")
        return PhoneNumberPass()

    def sample(self) -> str:
        return "call (415) 555-0198 tomorrow"


class TestSpacyWhenItIsInstalled:
    """The adapter, only where spaCy and a model are present. Everything above
    runs everywhere; this is the part that can be absent."""

    def recognizer(self) -> object:
        pytest.importorskip("spacy")
        from mamori.infrastructure.detectors import SpacyRecognizer

        try:
            return SpacyRecognizer()
        except ConfigurationError as exc:
            pytest.skip(str(exc))

    def test_it_satisfies_the_port(self) -> None:
        assert isinstance(self.recognizer(), NlpRecognizer)

    @pytest.mark.parametrize(
        "text",
        [
            "I spoke to Sarah Okonkwo yesterday about the contract.",
            "Attendees: Yuki Tanaka, Marcus Lindqvist, Fatima Al-Rashid.",
            "Reported by: Nguyen Thi Hoa",
        ],
        ids=["in prose", "in a list", "after a label"],
    )
    def test_it_finds_names_the_balanced_stance_misses(self, text: str) -> None:
        """The whole reason it exists, stated as the comparison rather than as
        a claim about the model."""
        self.recognizer()
        plain = MamoriConfig(stance=Stance.BALANCED).session()
        smart = MamoriConfig(stance=Stance.BALANCED, nlp="spacy").session()
        assert "PERSON" not in plain.inspect(text)
        assert "PERSON" in smart.inspect(text)

    @pytest.mark.parametrize(
        "text",
        ["The Quarterly Business Review is Monday.", "Social Security Number is required."],
        ids=["a heading", "a labelled phrase"],
    )
    def test_it_does_not_pay_the_wide_tier_price(self, text: str) -> None:
        """The recall-first stance buys these names by accepting false
        positives. A recogniser is supposed to buy them without that, and this
        is what says so."""
        self.recognizer()
        smart = MamoriConfig(stance=Stance.BALANCED, nlp="spacy").session()
        assert "PERSON" not in smart.inspect(text)

    def test_a_missing_model_is_refused_when_the_session_is_built(self) -> None:
        pytest.importorskip("spacy")
        from mamori.infrastructure.detectors import SpacyRecognizer

        with pytest.raises(ConfigurationError, match="spacy download"):
            SpacyRecognizer("no_such_model_exists")


class TestTheZeroDependencyPromiseHolds:
    def test_neither_library_is_imported_unless_asked_for(self) -> None:
        """The promise is that `import mamori` needs nothing. A module-level
        import in either adapter would break it for everybody, and the lazy
        import is easy to undo by accident."""
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, mamori; from mamori import PrivacySession;"
                "PrivacySession().protect('Dear Jane Doe, mail x@example.com');"
                "print([m for m in ('spacy', 'phonenumbers') if m in sys.modules])",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip().endswith("[]"), result.stdout
