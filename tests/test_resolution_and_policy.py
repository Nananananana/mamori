"""Overlap resolution and policy evaluation."""

from __future__ import annotations

import pytest

from mamori.domain import entity_types as t
from mamori.domain.confidence import HIGH, LOW, MEDIUM
from mamori.domain.entity_types import Category, EntityType
from mamori.domain.policy import Action, PrivacyPolicy
from mamori.domain.resolution import assert_non_overlapping, resolve_overlaps
from mamori.domain.sensitive_entity import SensitiveEntity
from mamori.domain.span import Span


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
