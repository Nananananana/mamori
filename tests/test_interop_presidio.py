"""Presidio's shapes, spoken by mamori.

A privacy layer is adopted or not on one question: how much has to be rewritten
to try it. Presidio is what most teams already have, and every line downstream
of it -- a dashboard, a notebook, a stored fixture, the code that decides what
to do with a finding -- reads `.entity_type`, `.start`, `.end` and `.score`.

So these are compatibility tests rather than feature tests. What they pin is
that an existing Presidio caller can change one import and keep working, and
that the one place mamori deliberately differs is loud rather than silent.
"""

from __future__ import annotations

import json

import pytest

from mamori import MamoriConfig
from mamori.domain.stance import Stance
from mamori.errors import PolicyViolationError
from mamori.interop.presidio import (
    AnalyzerEngine,
    AnonymizerEngine,
    PresidioRecognizer,
    RecognizerResult,
    from_presidio,
    to_presidio,
)

from .credentials import FAKE_AWS_KEY

TEXT = "Dear Jane Doe, mail jane.doe@example.com or call 415-555-0198."


class TestTheAnalyzerFacade:
    def test_it_returns_presidio_shaped_findings(self) -> None:
        for finding in AnalyzerEngine().analyze(TEXT, language="en"):
            assert isinstance(finding.entity_type, str)
            assert 0 <= finding.start < finding.end <= len(TEXT)
            assert 0.0 <= finding.score <= 1.0

    def test_the_offsets_point_at_the_value(self) -> None:
        """The one thing a caller does with a finding is slice the text with
        it. An off-by-one here is the whole feature failing quietly."""
        found = {f.entity_type: TEXT[f.start : f.end] for f in AnalyzerEngine().analyze(TEXT)}
        assert found["EMAIL"] == "jane.doe@example.com"
        assert found["PERSON"] == "Jane Doe"

    def test_the_language_argument_selects_a_pack(self) -> None:
        assert AnalyzerEngine().analyze("Dear Jane Doe,", language="en")

    def test_omitting_the_language_is_allowed_and_safer(self) -> None:
        """Presidio requires it. mamori does not, and the default -- every
        pack -- is the safer one: an unexpected language is exactly the
        document nobody redacted by hand."""
        assert AnalyzerEngine().analyze("田中太郎さんへ")

    def test_the_entities_filter(self) -> None:
        found = AnalyzerEngine().analyze(TEXT, entities=["EMAIL"])
        assert {f.entity_type for f in found} == {"EMAIL"}

    def test_the_score_threshold(self) -> None:
        every = AnalyzerEngine().analyze(TEXT)
        assert all(f.score >= 0.95 for f in AnalyzerEngine().analyze(TEXT, score_threshold=0.95))
        assert len(AnalyzerEngine().analyze(TEXT, score_threshold=0.95)) <= len(every)

    def test_unknown_keyword_arguments_are_accepted(self) -> None:
        """Presidio's constructor takes `nlp_engine`, `registry`,
        `supported_languages`. A facade that raised on them would fail on the
        line that is hardest to change -- the one somebody already has."""
        engine = AnalyzerEngine(nlp_engine=object(), supported_languages=["en"])
        assert engine.analyze(TEXT, return_decision_process=True)

    def test_a_credential_is_reported_rather_than_refused(self) -> None:
        """`analyze` answers a question about a text. `protect` is the step
        that can refuse, and a Presidio caller expects a finding back."""
        found = AnalyzerEngine().analyze(f"key {FAKE_AWS_KEY}")
        assert "API_KEY" in {f.entity_type for f in found}

    def test_the_configuration_reaches_it(self) -> None:
        """Everything mamori can be told to do is still available -- the facade
        is a shape, not a reduced library."""
        wide = AnalyzerEngine(MamoriConfig(stance=Stance.RECALL_FIRST))
        narrow = AnalyzerEngine(MamoriConfig(stance=Stance.BALANCED))
        text = "I spoke to Jane Doe yesterday"
        assert "PERSON" in {f.entity_type for f in wide.analyze(text, language="en")}
        assert "PERSON" not in {f.entity_type for f in narrow.analyze(text, language="en")}


class TestTheAnonymizerFacade:
    def test_it_replaces_and_can_put_back(self) -> None:
        with AnonymizerEngine().anonymize(TEXT) as out:
            assert "Jane Doe" not in out.text
            assert out.restore(out.text) == TEXT

    def test_the_placeholders_are_numbered_and_that_is_the_difference(self) -> None:
        """Presidio writes `<PERSON>` and the original is gone. Hiding that to
        look more alike would throw away the property this library exists for,
        and would do it silently."""
        with AnonymizerEngine().anonymize(TEXT) as out:
            assert "<PERSON_001>" in out.text

    def test_the_items_are_presidio_shaped(self) -> None:
        with AnonymizerEngine().anonymize(TEXT) as out:
            assert all(isinstance(item, RecognizerResult) for item in out.items)

    def test_analyzer_results_are_accepted_and_change_nothing(self) -> None:
        """Presidio splits analysis and anonymisation across two calls. mamori
        runs one pipeline in which resolution and policy see every candidate
        together, so honouring a caller-supplied subset would apply a policy to
        findings that never went through it. Passing them is harmless."""
        findings = AnalyzerEngine().analyze(TEXT)
        with AnonymizerEngine().anonymize(TEXT, analyzer_results=findings) as with_them:
            with AnonymizerEngine().anonymize(TEXT) as without:
                assert with_them.text == without.text

    def test_operators_are_accepted_and_ignored(self) -> None:
        with AnonymizerEngine().anonymize(TEXT, operators={"PERSON": object()}) as out:
            assert "<PERSON_001>" in out.text

    def test_it_fails_closed_on_a_credential(self) -> None:
        """Unlike `analyze`, this one is a step towards sending something."""
        with pytest.raises(PolicyViolationError):
            AnonymizerEngine().anonymize(f"key {FAKE_AWS_KEY}")

    def test_closing_discards_the_mapping(self) -> None:
        out = AnonymizerEngine().anonymize(TEXT)
        anonymized = out.text
        out.close()
        assert out.restore(anonymized) == anonymized


class TestTheJsonShape:
    """For a pipeline that speaks Presidio over a wire rather than in process."""

    def test_a_finding_serialises_to_presidios_keys(self) -> None:
        (finding, *_) = AnalyzerEngine().analyze(TEXT)
        payload = json.loads(json.dumps(finding.to_dict()))
        assert set(payload) == {"entity_type", "start", "end", "score", "analysis_explanation"}

    def test_it_never_carries_the_value(self) -> None:
        """A finding says *where*. One that carried the value would be one that
        leaks the moment somebody logs it."""
        rendered = json.dumps([f.to_dict() for f in AnalyzerEngine().analyze(TEXT)])
        assert "jane.doe@example.com" not in rendered
        assert "Jane Doe" not in rendered


class TestReadingPresidiosOutput:
    """The other direction: findings somebody else produced."""

    def test_real_objects_duck_type(self) -> None:
        class TheirResult:
            entity_type, start, end, score = "PERSON", 5, 13, 0.85

        (entity,) = from_presidio([TheirResult()])
        assert entity.label == "PERSON"
        assert (entity.span.start, entity.span.end) == (5, 13)
        assert entity.score == 0.85

    def test_a_mapping_loaded_from_json_works(self) -> None:
        """The commonest thing anybody actually has."""
        (entity,) = from_presidio([{"entity_type": "EMAIL", "start": 0, "end": 4, "score": 1.0}])
        assert entity.label == "EMAIL"

    def test_a_missing_score_defaults_to_certain(self) -> None:
        (entity,) = from_presidio([{"entity_type": "PERSON", "start": 0, "end": 4}])
        assert entity.score == 1.0

    def test_the_round_trip(self) -> None:
        """`to_presidio` then `from_presidio` must land on the same spans, or
        one of the two is lying about coordinates."""
        with MamoriConfig().session() as session:
            protected = session.protect(TEXT)
        there = to_presidio(protected)
        back = from_presidio(there)
        assert [(e.span.start, e.span.end) for e in back] == [(f.start, f.end) for f in there]


class TestPresidioAsARecognizer:
    def test_it_satisfies_the_port(self) -> None:
        from mamori.ports.nlp_recognizer import NlpRecognizer

        class Stub:
            def analyze(self, text: str, language: str) -> list[dict[str, object]]:
                return [{"entity_type": "PERSON", "start": 0, "end": 4, "score": 0.9}]

        assert isinstance(PresidioRecognizer(Stub()), NlpRecognizer)

    def test_it_translates_what_presidio_reports(self) -> None:
        class Stub:
            def analyze(self, text: str, language: str) -> list[dict[str, object]]:
                return [{"entity_type": "PERSON", "start": 0, "end": 4, "score": 0.9}]

        (entity,) = PresidioRecognizer(Stub()).entities("Jane says hello")
        assert entity.label == "PERSON"

    def test_it_is_registered_as_an_algorithm(self) -> None:
        from mamori.infrastructure.detectors.recognizers import available_nlp_algorithms

        assert "presidio" in available_nlp_algorithms()

    def test_selecting_it_is_a_configuration_value(self) -> None:
        assert MamoriConfig.from_mapping({"nlp": "presidio"}).nlp == "presidio"

    def test_a_missing_install_is_refused_with_the_extra_named(self) -> None:
        """The error has to say what to install. A bare `ModuleNotFoundError`
        three frames down is the shape this project refuses elsewhere."""
        import importlib.util

        from mamori.errors import ConfigurationError

        if importlib.util.find_spec("presidio_analyzer") is not None:  # pragma: no cover
            assert PresidioRecognizer().name.startswith("presidio/")
            return
        with pytest.raises(ConfigurationError, match=r"mamori\[presidio\]"):
            PresidioRecognizer()
