"""The detection pipeline and the co-occurrence pass.

The pipeline exists so that detection can be assembled, reordered and switched
off rather than hardcoded, and the co-occurrence pass is the reason it had to:
it needs to see what earlier passes found, which the plain detector contract
deliberately does not allow.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from mamori import PrivacySession
from mamori.domain import entity_types as t
from mamori.domain.confidence import CERTAIN, HIGH, LOW, MEDIUM, Confidence
from mamori.domain.normalization import NormalizedText
from mamori.domain.sensitive_entity import SensitiveEntity
from mamori.domain.span import Span
from mamori.infrastructure.detectors import (
    CoOccurrencePass,
    DetectionPipeline,
    DetectorPass,
    RegexDetector,
    build_pipeline,
)
from mamori.ports.detection_pass import DetectionContext, DetectionPass


class RecordingPass:
    """Reports one fixed entity and remembers what it was shown."""

    def __init__(self, name: str, span: Span, entity_type: object = t.PERSON) -> None:
        self._name = name
        self._span = span
        self._type = entity_type
        self.seen: list[int] = []

    @property
    def name(self) -> str:
        return self._name

    def run(self, context: DetectionContext) -> Sequence[SensitiveEntity]:
        self.seen.append(len(context.found))
        return [
            SensitiveEntity(
                entity_type=self._type,  # type: ignore[arg-type]
                span=self._span,
                value=context.text[self._span.start : self._span.end],
                confidence=CERTAIN,
                source=self._name,
            )
        ]


def entity(
    value: str,
    start: int,
    entity_type: object = t.PERSON,
    confidence: Confidence = HIGH,
) -> SensitiveEntity:
    return SensitiveEntity(
        entity_type=entity_type,  # type: ignore[arg-type]
        span=Span(start, start + len(value)),
        value=value,
        confidence=confidence,
        source="seed",
    )


def run_pass(pass_: DetectionPass, text: str, found: Sequence[SensitiveEntity] = ()) -> list[str]:
    added = pass_.run(DetectionContext(text=text, found=tuple(found)))
    return [text[e.span.start : e.span.end] for e in added]


class TestDetectionContext:
    def test_with_more_accumulates(self) -> None:
        context = DetectionContext(text="abcdef")
        assert context.with_more([entity("ab", 0)]).found[0].value == "ab"

    def test_with_more_does_not_mutate(self) -> None:
        context = DetectionContext(text="abcdef")
        context.with_more([entity("ab", 0)])
        assert context.found == ()

    def test_covered_reports_claimed_indices(self) -> None:
        context = DetectionContext(text="abcdef", found=(entity("bc", 1),))
        assert context.covered() == {1, 2}

    def test_covered_on_an_empty_context(self) -> None:
        assert DetectionContext(text="abc").covered() == frozenset()


class TestDetectionPipeline:
    def test_it_is_a_detector(self) -> None:
        from mamori.ports.detector import Detector

        assert isinstance(build_pipeline(), Detector)

    def test_passes_run_in_order_and_see_what_came_before(self) -> None:
        first = RecordingPass("first", Span(0, 2))
        second = RecordingPass("second", Span(3, 5))
        DetectionPipeline([first, second]).detect("ab cd ef")
        assert first.seen == [0]
        assert second.seen == [1]

    def test_results_accumulate(self) -> None:
        pipeline = DetectionPipeline(
            [RecordingPass("a", Span(0, 2)), RecordingPass("b", Span(3, 5))]
        )
        assert len(pipeline.detect("ab cd ef")) == 2

    def test_an_empty_pipeline_finds_nothing(self) -> None:
        assert DetectionPipeline([]).detect("田中太郎さんへ") == []

    def test_a_failing_pass_propagates(self) -> None:
        class Broken:
            name = "broken"

            def run(self, context: DetectionContext) -> Sequence[SensitiveEntity]:
                raise RuntimeError("model unavailable")

        with pytest.raises(RuntimeError):
            DetectionPipeline([Broken()]).detect("anything")

    def test_passes_are_exposed_for_inspection(self) -> None:
        pipeline = build_pipeline(co_occurrence=CoOccurrencePass())
        assert [p.name for p in pipeline.passes] == ["rules", "co-occurrence"]

    def test_co_occurrence_can_be_left_out(self) -> None:
        assert [p.name for p in build_pipeline(co_occurrence=None).passes] == ["rules"]


class TestDetectorPass:
    def test_it_adapts_a_detector(self) -> None:
        detector = RegexDetector("universal", ())
        assert DetectorPass(detector).name == "universal"

    def test_the_name_can_be_overridden(self) -> None:
        assert DetectorPass(RegexDetector("x", ()), name="rules").name == "rules"

    def test_it_does_not_hand_the_detector_prior_findings(self) -> None:
        """The narrow contract stays the default: most rules are better off blind."""
        seen: list[str] = []

        class Nosy:
            name = "nosy"

            def detect(self, text: str) -> Sequence[SensitiveEntity]:
                seen.append(text)
                return []

        DetectorPass(Nosy()).run(DetectionContext(text="abc", found=(entity("a", 0),)))
        assert seen == ["abc"]


class TestCoOccurrencePass:
    def test_a_confirmed_value_is_found_again(self) -> None:
        text = "田中太郎さんへ。なお田中太郎の担当です。"
        seeds = [entity("田中太郎", 0)]
        assert run_pass(CoOccurrencePass(), text, seeds) == ["田中太郎"]

    def test_every_later_occurrence_is_found(self) -> None:
        text = "張三さん。張三が確認。張三まで。"
        assert len(run_pass(CoOccurrencePass(), text, [entity("張三", 0)])) == 2

    def test_it_does_not_report_what_is_already_covered(self) -> None:
        text = "田中太郎さんへ"
        assert run_pass(CoOccurrencePass(), text, [entity("田中太郎", 0)]) == []

    def test_a_low_confidence_seed_does_not_propagate(self) -> None:
        """A shaky guess must not multiply itself across the document."""
        text = "高兴。高兴。高兴。"
        assert run_pass(CoOccurrencePass(), text, [entity("高兴", 0, confidence=LOW)]) == []

    def test_the_seed_threshold_is_configurable(self) -> None:
        text = "候補。候補。"
        seeds = [entity("候補", 0, confidence=MEDIUM)]
        assert run_pass(CoOccurrencePass(), text, seeds) == []
        assert run_pass(CoOccurrencePass(min_confidence=0.5), text, seeds) == ["候補"]

    def test_word_boundaries_are_respected_in_latin_text(self) -> None:
        """Seeding on Ann must not match inside Announcement."""
        text = "Dear Ann, the Announcement is ready. Ann will send it."
        found = run_pass(CoOccurrencePass(), text, [entity("Ann", 5)])
        assert found == ["Ann"]

    def test_a_latin_seed_inside_a_longer_word_is_not_matched(self) -> None:
        text = "Bob and Bobby are different people."
        assert run_pass(CoOccurrencePass(), text, [entity("Bob", 0)]) == []

    def test_only_the_configured_types_propagate(self) -> None:
        text = "090-1234-5678 と 090-1234-5678"
        seeds = [entity("090-1234-5678", 0, entity_type=t.PHONE)]
        assert run_pass(CoOccurrencePass(), text, seeds) == []

    def test_short_values_are_ignored(self) -> None:
        """A one-character seed matches most of a CJK document."""
        text = "林林林林林"
        assert run_pass(CoOccurrencePass(), text, [entity("林", 0)]) == []

    def test_the_minimum_length_is_configurable(self) -> None:
        text = "林林林"
        found = run_pass(CoOccurrencePass(min_length=1), text, [entity("林", 0)])
        assert len(found) == 2

    def test_the_longest_seed_claims_its_occurrences_first(self) -> None:
        text = "田中太郎さん。田中太郎へ。"
        seeds = [entity("田中太郎", 0), entity("田中", 0)]
        assert run_pass(CoOccurrencePass(), text, seeds) == ["田中太郎"]

    def test_propagated_entities_name_the_pass(self) -> None:
        text = "張三さん。張三が確認。"
        added = CoOccurrencePass().run(DetectionContext(text=text, found=(entity("張三", 0),)))
        assert all(e.source == "co-occurrence" for e in added)

    def test_it_inherits_the_seed_confidence(self) -> None:
        text = "張三さん。張三が確認。"
        added = CoOccurrencePass().run(
            DetectionContext(text=text, found=(entity("張三", 0, confidence=CERTAIN),))
        )
        assert all(e.confidence == CERTAIN for e in added)

    def test_no_seeds_means_no_work(self) -> None:
        assert run_pass(CoOccurrencePass(), "nothing here", []) == []

    @pytest.mark.parametrize("value", [-0.1, 1.1])
    def test_an_out_of_range_threshold_is_refused(self, value: float) -> None:
        with pytest.raises(ValueError):
            CoOccurrencePass(min_confidence=value)

    def test_a_zero_minimum_length_is_refused(self) -> None:
        with pytest.raises(ValueError):
            CoOccurrencePass(min_length=0)


class TestCoOccurrenceEndToEnd:
    def test_a_name_anchored_once_is_protected_everywhere(self) -> None:
        text = "尊敬的张伟先生：\n本次评审由张伟主持。\n请张伟回复。"
        with PrivacySession() as session:
            protected = session.protect(text)
            assert "张伟" not in protected.protected_text
            assert protected.protected_text.count("<PERSON_001>") == 3
            assert session.restore(protected.protected_text).text == text

    def test_it_can_be_switched_off(self) -> None:
        from mamori import MamoriConfig

        text = "尊敬的张伟先生：\n本次评审由张伟主持。"
        with MamoriConfig(co_occurrence=False).session() as session:
            protected = session.protect(text)
        assert "张伟" in protected.protected_text

    def test_switching_it_off_never_leaks_more_than_leaving_it_on(self) -> None:
        """The pass only ever adds detections; it cannot remove one."""
        from mamori import MamoriConfig

        text = "Dear Jane Doe,\n\nJane Doe will attend. Regards,\nBob"
        with MamoriConfig(co_occurrence=False).session() as off:
            without = off.protect(text).entity_count
        with PrivacySession() as on:
            with_pass = on.protect(text).entity_count
        assert with_pass >= without

    def test_the_report_says_which_mentions_came_from_propagation(self) -> None:
        from mamori import MamoriConfig
        from mamori.domain.stance import Stance

        # Balanced, so the wide English rule does not reach the second mention
        # on its own and the propagation is what is being observed.
        text = "Dear Priya Raman,\n\nPriya Raman is leading it."
        with MamoriConfig(stance=Stance.BALANCED).session() as session:
            sources = {e.source for e in session.protect(text).entities}
        assert "co-occurrence" in sources

    def test_a_single_mention_gains_nothing(self) -> None:
        text = "Dear Jane Doe,\n\nplease confirm."
        with PrivacySession() as session:
            entities = session.protect(text).entities
        assert sum(1 for e in entities if e.source == "co-occurrence") == 0

    def test_spans_still_line_up_with_the_original_text(self) -> None:
        text = "ｔａｎａｋａ＠ｅｘａｍｐｌｅ．ｃｏｍ / 田中太郎さん / 田中太郎"
        with PrivacySession() as session:
            protected = session.protect(text)
            assert session.restore(protected.protected_text).text == text

    def test_the_pipeline_output_still_resolves_to_disjoint_spans(self) -> None:
        text = "株式会社さくら商事の田中太郎さん。田中太郎は株式会社さくら商事の担当。"
        normalized = NormalizedText.of(text)
        found = build_pipeline(co_occurrence=CoOccurrencePass()).detect(normalized.text)
        assert found
        with PrivacySession() as session:
            assert session.restore(session.protect(text).protected_text).text == text


class TestIntrospection:
    """The parts have to be visible, or 'switchable' is only a claim."""

    def test_the_pipeline_reports_its_name(self) -> None:
        assert DetectionPipeline([], name="custom").name == "custom"

    def test_a_detector_pass_exposes_its_detector(self) -> None:
        detector = RegexDetector("universal", ())
        assert DetectorPass(detector).detector is detector

    def test_the_co_occurrence_pass_reports_its_threshold(self) -> None:
        assert CoOccurrencePass(min_confidence=0.6).min_confidence == 0.6

    def test_a_custom_pass_can_replace_the_built_in_one(self) -> None:
        """Switching a stage out must not require touching anything else."""
        marker = RecordingPass("custom", Span(0, 2))
        pipeline = DetectionPipeline([marker], name="custom")
        with PrivacySession(detectors=[pipeline]) as session:
            assert session.protect("ab cd").entities[0].source == "custom"
