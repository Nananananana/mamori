"""Overlap resolution and policy evaluation."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mamori.domain import entity_types as t
from mamori.domain.confidence import HIGH, LOW, MEDIUM
from mamori.domain.entity_types import Category, EntityType
from mamori.domain.policy import Action, PrivacyPolicy
from mamori.domain.resolution import assert_non_overlapping, resolve_overlaps
from mamori.domain.sensitive_entity import SensitiveEntity
from mamori.domain.span import Span

SETTINGS = settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])


def entity(
    entity_type: EntityType,
    start: int,
    end: int,
    *,
    value: str = "x",
    confidence: object = HIGH,
    source: str = "test",
) -> SensitiveEntity:
    return SensitiveEntity(
        entity_type=entity_type,
        span=Span(start, end),
        value=value,
        confidence=confidence,  # type: ignore[arg-type]
        source=source,
    )


class TestResolveOverlaps:
    def test_disjoint_detections_all_survive(self) -> None:
        resolved = resolve_overlaps([entity(t.EMAIL, 10, 20), entity(t.PERSON, 0, 4)])
        assert [e.span.start for e in resolved] == [0, 10]

    def test_result_is_ordered_by_offset(self) -> None:
        resolved = resolve_overlaps(
            [entity(t.EMAIL, 30, 40), entity(t.PERSON, 0, 4), entity(t.PHONE, 10, 22)]
        )
        assert [e.span.start for e in resolved] == [0, 10, 30]

    def test_the_wider_span_wins(self) -> None:
        """It also removes what is inside it, so it is the safer outcome."""
        resolved = resolve_overlaps([entity(t.PERSON, 4, 6), entity(t.COMPANY_NAME, 0, 9)])
        assert len(resolved) == 1
        assert resolved[0].entity_type is t.COMPANY_NAME

    def test_severity_breaks_a_tie_between_equal_spans(self) -> None:
        resolved = resolve_overlaps([entity(t.PERSON, 0, 10), entity(t.API_KEY, 0, 10)])
        assert [e.entity_type for e in resolved] == [t.API_KEY]

    def test_confidence_breaks_a_tie_between_equal_spans_and_severity(self) -> None:
        custom = EntityType("DUPE", Category.PII, 70)
        resolved = resolve_overlaps(
            [
                entity(custom, 0, 5, confidence=LOW, source="a"),
                entity(custom, 0, 5, confidence=MEDIUM, source="b"),
            ]
        )
        assert len(resolved) == 1
        assert resolved[0].source == "b"

    def test_identical_detections_from_two_detectors_collapse(self) -> None:
        resolved = resolve_overlaps(
            [entity(t.EMAIL, 0, 18, source="regex"), entity(t.EMAIL, 0, 18, source="llm")]
        )
        assert len(resolved) == 1

    def test_a_losing_span_does_not_block_a_later_disjoint_one(self) -> None:
        resolved = resolve_overlaps(
            [entity(t.COMPANY_NAME, 0, 9), entity(t.PERSON, 4, 6), entity(t.EMAIL, 20, 30)]
        )
        assert [e.entity_type for e in resolved] == [t.COMPANY_NAME, t.EMAIL]

    def test_ordering_of_the_input_does_not_change_the_outcome(self) -> None:
        detections = [
            entity(t.PERSON, 4, 6),
            entity(t.COMPANY_NAME, 0, 9),
            entity(t.EMAIL, 20, 30),
        ]
        first = resolve_overlaps(detections)
        second = resolve_overlaps(list(reversed(detections)))
        assert first == second

    def test_empty_input(self) -> None:
        assert resolve_overlaps([]) == []

    def test_output_is_always_replaceable(self) -> None:
        resolved = resolve_overlaps(
            [entity(t.PERSON, 0, 5), entity(t.EMAIL, 3, 12), entity(t.PHONE, 11, 20)]
        )
        assert_non_overlapping(resolved)


class TestTheFastPathAgreesWithTheObviousOne:
    """Resolution stopped comparing every candidate against every kept span.

    That loop was the definition of the rule for twenty releases, so the test
    for the replacement is not "does it look right" but "does it return exactly
    what the loop returned", on inputs drawn to collide as much as possible.
    """

    @staticmethod
    def naive(entities: list[SensitiveEntity]) -> list[SensitiveEntity]:
        """What the function did before 0.22, kept here as the specification."""
        from mamori.domain.resolution import _preference

        ranked = sorted(entities, key=_preference)
        accepted: list[SensitiveEntity] = []
        for candidate in ranked:
            if any(candidate.span.overlaps(kept.span) for kept in accepted):
                continue
            accepted.append(candidate)
        accepted.sort(key=lambda e: e.span.start)
        return accepted

    @staticmethod
    def entity(start: int, end: int, kind: EntityType, confidence: object) -> SensitiveEntity:
        return SensitiveEntity(
            entity_type=kind,
            span=Span(start, end),
            value="x" * (end - start),
            confidence=confidence,  # type: ignore[arg-type]
        )

    @SETTINGS
    @given(
        spans=st.lists(
            st.tuples(st.integers(0, 60), st.integers(1, 12)),
            min_size=0,
            max_size=40,
        ),
        kinds=st.lists(st.sampled_from([t.PERSON, t.EMAIL, t.PHONE]), min_size=1, max_size=3),
    )
    def test_same_answer_for_any_pile_of_overlapping_spans(
        self, spans: list[tuple[int, int]], kinds: list[EntityType]
    ) -> None:
        entities = [
            self.entity(
                start, start + length, kinds[index % len(kinds)], [HIGH, MEDIUM, LOW][index % 3]
            )
            for index, (start, length) in enumerate(spans)
        ]
        assert resolve_overlaps(entities) == self.naive(entities)

    def test_same_answer_when_everything_starts_together(self) -> None:
        """The case the binary search has to get right: equal starts."""
        entities = [self.entity(10, 10 + length, t.PERSON, HIGH) for length in (1, 2, 3, 4, 5)]
        assert resolve_overlaps(entities) == self.naive(entities)

    def test_same_answer_for_nested_spans(self) -> None:
        entities = [
            self.entity(0, 40, t.PERSON, LOW),
            self.entity(10, 20, t.EMAIL, HIGH),
            self.entity(12, 14, t.PHONE, HIGH),
            self.entity(41, 50, t.EMAIL, HIGH),
        ]
        assert resolve_overlaps(entities) == self.naive(entities)

    def test_the_traced_variant_keeps_the_same_set(self) -> None:
        from mamori.domain.resolution import resolve_overlaps_traced

        entities = [
            self.entity(0, 10, t.PERSON, LOW),
            self.entity(5, 15, t.EMAIL, HIGH),
            self.entity(20, 30, t.PHONE, HIGH),
        ]
        kept, displaced = resolve_overlaps_traced(entities)
        assert kept == resolve_overlaps(entities)
        assert [d.loser for d in displaced] == [e for e in entities if e not in kept]


class TestAssertNonOverlapping:
    def test_raises_on_overlap(self) -> None:
        with pytest.raises(ValueError):
            assert_non_overlapping([entity(t.PERSON, 0, 5), entity(t.EMAIL, 3, 9)])


class TestPrivacyPolicy:
    def test_a_named_rule_beats_a_category_default(self) -> None:
        policy = PrivacyPolicy(
            rules={"EMAIL": Action.ALLOW},
            category_defaults={Category.PII: Action.ANONYMIZE},
        )
        assert policy.action_for(t.EMAIL) is Action.ALLOW
        assert policy.action_for(t.PERSON) is Action.ANONYMIZE

    def test_a_category_default_beats_the_fallback(self) -> None:
        policy = PrivacyPolicy(
            category_defaults={Category.PII: Action.MASK}, default_action=Action.BLOCK
        )
        assert policy.action_for(t.PERSON) is Action.MASK

    def test_an_unknown_type_falls_through_to_block(self) -> None:
        """Fail-closed: nobody had an opinion, so it does not leave the machine."""
        policy = PrivacyPolicy()
        assert policy.action_for(EntityType("SOMETHING_NEW")) is Action.BLOCK

    def test_default_policy_pseudonymizes_pii(self) -> None:
        policy = PrivacyPolicy.default()
        assert policy.action_for(t.PERSON) is Action.ANONYMIZE
        assert policy.action_for(t.EMAIL) is Action.ANONYMIZE

    def test_default_policy_blocks_credentials(self) -> None:
        policy = PrivacyPolicy.default()
        for credential in (t.API_KEY, t.PASSWORD, t.ACCESS_TOKEN, t.PRIVATE_KEY, t.DATABASE_URL):
            assert policy.action_for(credential) is Action.BLOCK

    def test_default_policy_never_blocks_placeholder_literals(self) -> None:
        """Otherwise ordinary prose with angle brackets would stop the request."""
        assert PrivacyPolicy.default().action_for(t.PLACEHOLDER_LITERAL) is Action.ANONYMIZE

    def test_permissive_policy_blocks_nothing(self) -> None:
        policy = PrivacyPolicy.permissive()
        assert policy.action_for(t.API_KEY) is Action.ANONYMIZE
        assert policy.action_for(EntityType("SOMETHING_NEW")) is Action.ANONYMIZE

    def test_with_rule_does_not_mutate_the_original(self) -> None:
        base = PrivacyPolicy.default()
        derived = base.with_rule("PERSON", Action.BLOCK)
        assert base.action_for(t.PERSON) is Action.ANONYMIZE
        assert derived.action_for(t.PERSON) is Action.BLOCK


class TestConfidenceFloor:
    """The coverage/quality dial. Default 0.0, and it must stay there."""

    def test_the_default_accepts_everything(self) -> None:
        assert PrivacyPolicy.default().min_confidence == 0.0
        assert PrivacyPolicy.default().accepts(0.0)

    def test_a_floor_rejects_what_is_below_it(self) -> None:
        policy = PrivacyPolicy.default().with_min_confidence(0.7)
        assert not policy.accepts(0.5)
        assert policy.accepts(0.7)
        assert policy.accepts(0.9)

    @pytest.mark.parametrize("value", [-0.01, 1.01])
    def test_an_out_of_range_floor_is_refused(self, value: float) -> None:
        with pytest.raises(ValueError):
            PrivacyPolicy(min_confidence=value)

    def test_with_min_confidence_does_not_mutate_the_original(self) -> None:
        base = PrivacyPolicy.default()
        base.with_min_confidence(0.9)
        assert base.min_confidence == 0.0

    def test_with_rule_carries_the_floor_across(self) -> None:
        policy = PrivacyPolicy.default().with_min_confidence(0.6).with_rule("EMAIL", Action.ALLOW)
        assert policy.min_confidence == 0.6
        assert policy.action_for(t.EMAIL) is Action.ALLOW
