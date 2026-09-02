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


class TestThePlaceholderGrammarIsEnforcedAndNotAssumed:
    """A token is ASCII because construction refuses anything else.

    It was not. `STRICT_PLACEHOLDER_RE` described the form and only `parse`
    consulted it, so `Placeholder("個人名", 1).token` produced `<個人名_001>`
    quite happily -- a token that went into a protected document, into a
    mapping, and into `placeholders[].token` of a `protection-scope` record,
    and that `parse` then refused. The document could never be restored and
    nothing said why.

    A custom detector is all it takes: an entity type named in Japanese, or in
    lower case, or starting with a digit. The library's own detectors all
    happen to use upper-case ASCII, which is why this survived to 0.30.

    The distinction that matters is the one a sibling project put well: a rule
    only the parser knows is **discipline**, and it holds until somebody writes
    a detector. A rule the constructor refuses to break is **structure**.
    """

    @pytest.mark.parametrize(
        "name",
        [
            pytest.param("個人名", id="japanese"),
            pytest.param("张伟", id="chinese"),
            pytest.param("person", id="lower case"),
            pytest.param("9LIVES", id="leading digit"),
            pytest.param("A-B", id="hyphen"),
            pytest.param("", id="empty"),
            pytest.param("A B", id="space"),
            pytest.param("A" * 64, id="too long"),
        ],
    )
    def test_a_name_the_parser_would_refuse_cannot_be_constructed(self, name: str) -> None:
        with pytest.raises(ValueError, match="not a usable entity type name"):
            Placeholder(name, 1)

    @pytest.mark.parametrize("name", ["PERSON", "EMAIL", "A", "MY_TYPE_2", "A" * 63])
    def test_the_names_the_parser_accepts_still_work(self, name: str) -> None:
        assert Placeholder.parse(Placeholder(name, 1).token) == Placeholder(name, 1)

    def test_every_token_this_library_can_build_can_be_read_back(self) -> None:
        """The property the constructor now guarantees, stated as itself. The
        cases above are examples of it; this is the rule."""
        for name in ("PERSON", "NATIONAL_ID", "A1"):
            for index in (1, 42, 999_999):
                token = Placeholder(name, index).token
                assert Placeholder.parse(token) == Placeholder(name, index), token

    def test_an_index_that_would_need_a_seventh_digit_is_refused(self) -> None:
        r"""`\d{1,6}` in the pattern. Index 1000000 formats to `1000000`, which
        `parse` refuses -- the same unrestorable token by a different route."""
        assert Placeholder.parse(Placeholder("PERSON", 999_999).token) is not None
        with pytest.raises(ValueError, match="must be <= 999999"):
            Placeholder("PERSON", 1_000_000)

    def test_the_two_patterns_have_not_drifted_apart(self) -> None:
        """`TYPE_NAME_RE` was split out of `STRICT_PLACEHOLDER_RE`. If one is
        edited and the other is not, the bug this class exists for comes
        straight back."""
        from mamori.domain.placeholder import STRICT_PLACEHOLDER_RE, TYPE_NAME_RE

        assert f"<({TYPE_NAME_RE.pattern})_" in STRICT_PLACEHOLDER_RE.pattern
