"""Value objects: Span, Confidence, EntityType, Placeholder."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from mamori.domain.confidence import Confidence
from mamori.domain.entity_types import BUILTIN_TYPES, Category, EntityType, get_type, register_type
from mamori.domain.placeholder import Placeholder
from mamori.domain.span import Span


class TestSpan:
    def test_length(self) -> None:
        assert Span(3, 8).length == 5

    @pytest.mark.parametrize(("start", "end"), [(-1, 5), (5, 5), (7, 3)])
    def test_rejects_impossible_ranges(self, start: int, end: int) -> None:
        with pytest.raises(ValueError):
            Span(start, end)

    def test_overlap_is_symmetric(self) -> None:
        a, b = Span(0, 5), Span(3, 9)
        assert a.overlaps(b) and b.overlaps(a)

    def test_adjacent_spans_do_not_overlap(self) -> None:
        """Half-open ranges: [0,5) and [5,9) can both be replaced."""
        assert not Span(0, 5).overlaps(Span(5, 9))

    def test_containment(self) -> None:
        assert Span(0, 10).contains(Span(2, 5))
        assert not Span(2, 5).contains(Span(0, 10))


class TestConfidence:
    @pytest.mark.parametrize("value", [-0.01, 1.01, 2.0])
    def test_rejects_out_of_range(self, value: float) -> None:
        with pytest.raises(ValueError):
            Confidence(value)

    def test_orders_by_value(self) -> None:
        assert Confidence(0.5) < Confidence(0.9)


@pytest.fixture
def registry_restored() -> Iterator[None]:
    """Put the entity-type registry back as it was.

    Registering is global and permanent by design -- a deployment declares its
    types once at start-up. In a test suite that makes it shared mutable state,
    and a type registered here changed what a test in another file measured
    three hundred tests later. The leak was real for one release; nobody
    noticed because the two tests happened to run in a harmless order.
    """
    from mamori.domain import entity_types

    saved = dict(entity_types._registry)
    try:
        yield
    finally:
        entity_types._registry.clear()
        entity_types._registry.update(saved)


class TestEntityType:
    @pytest.mark.parametrize("name", ["person", "1PERSON", "PER SON", "PERSON-X", ""])
    def test_rejects_names_that_break_placeholders(self, name: str) -> None:
        with pytest.raises(ValueError):
            EntityType(name)

    def test_rejects_severity_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            EntityType("CUSTOM", Category.PII, severity=101)

    def test_register_and_lookup(self, registry_restored: None) -> None:
        custom = EntityType("PATIENT_ID", Category.PII, 80)
        register_type(custom)
        assert get_type("PATIENT_ID") == custom

    def test_registering_a_conflicting_definition_is_refused(self, registry_restored: None) -> None:
        register_type(EntityType("CASE_NUMBER", Category.PII, 60))
        with pytest.raises(ValueError):
            register_type(EntityType("CASE_NUMBER", Category.SECRET, 90))

    def test_a_registered_type_beats_a_synonym(self, registry_restored: None) -> None:
        """Which is the right precedence, and the reason the leak above was
        visible at all: `CASE_NUMBER` is one of the names a model uses for an
        identifier, so a test that registers it globally silently changes what
        another test measures. A deployment that registers its own
        `CASE_NUMBER` gets its own, and that is correct -- their definition is
        more specific than this library's guess about a model's wording."""
        from mamori.prompts.parsing import parse_detection_response

        text = "Please ask Kenji about it."
        proposal = '{"entities": [{"type": "CASE_NUMBER", "text": "Kenji"}]}'
        assert parse_detection_response(proposal, text).entities[0].entity_type.name == (
            "IDENTIFIER"
        )

        register_type(EntityType("CASE_NUMBER", Category.PII, 60))
        assert parse_detection_response(proposal, text).entities[0].entity_type.name == (
            "CASE_NUMBER"
        )

    def test_builtin_names_match_their_keys(self) -> None:
        assert all(name == entity.name for name, entity in BUILTIN_TYPES.items())


class TestPlaceholder:
    def test_token_is_zero_padded(self) -> None:
        assert Placeholder("PERSON", 1).token == "<PERSON_001>"

    def test_index_beyond_padding_still_works(self) -> None:
        assert Placeholder("PERSON", 1234).token == "<PERSON_1234>"

    def test_parse_round_trip(self) -> None:
        original = Placeholder("EMAIL", 42)
        assert Placeholder.parse(original.token) == original

    @pytest.mark.parametrize("token", ["PERSON_001", "<person_001>", "<PERSON>", "<PERSON_>", ""])
    def test_parse_rejects_non_canonical_forms(self, token: str) -> None:
        assert Placeholder.parse(token) is None

    def test_index_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            Placeholder("PERSON", 0)
