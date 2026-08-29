"""Recovering placeholders that a model altered.

A model is not obliged to echo a token back the way it received it. These are
the mutations worth surviving, plus the cases where being permissive would be
dangerous.
"""

from __future__ import annotations

import pytest

from mamori.domain.placeholder import Placeholder
from mamori.domain.placeholder_matching import scan_placeholders

KNOWN = frozenset({Placeholder("PERSON", 1), Placeholder("EMAIL", 2)})


def restored_identities(text: str) -> list[tuple[str, int]]:
    return [
        (o.placeholder.entity_type_name, o.placeholder.index)
        for o in scan_placeholders(text, KNOWN)
        if o.known
    ]


class TestSurfaceVariations:
    @pytest.mark.parametrize(
        "surface",
        [
            "<PERSON_001>",
            "PERSON_001",
            "<PERSON_1>",
            "PERSON_1",
            "<person_001>",
            "<Person_001>",
            "[PERSON_001]",
            "{PERSON_001}",
            "＜PERSON_001＞",
            "<PERSON 001>",
            "<PERSON-001>",
            "< PERSON_001 >",
        ],
    )
    def test_a_mangled_placeholder_is_still_identified(self, surface: str) -> None:
        assert restored_identities(f"Dear {surface}, hello.") == [("PERSON", 1)]

    def test_the_canonical_form_is_not_reported_as_tampered(self) -> None:
        found = scan_placeholders("Dear <PERSON_001>.", KNOWN)
        assert found[0].tampered is False

    def test_an_altered_form_is_reported_as_tampered(self) -> None:
        found = scan_placeholders("Dear PERSON_1.", KNOWN)
        assert found[0].tampered is True

    def test_markdown_emphasis_around_a_placeholder(self) -> None:
        assert restored_identities("**<PERSON_001>** replied") == [("PERSON", 1)]

    def test_a_placeholder_adjacent_to_japanese_text(self) -> None:
        assert restored_identities("<PERSON_001>さんへ") == [("PERSON", 1)]

    def test_several_placeholders_in_one_text(self) -> None:
        assert restored_identities("<PERSON_001> at <EMAIL_002>") == [("PERSON", 1), ("EMAIL", 2)]

    def test_the_same_placeholder_repeated(self) -> None:
        assert restored_identities("<PERSON_001> and <PERSON_001>") == [
            ("PERSON", 1),
            ("PERSON", 1),
        ]


class TestSpansAreExact:
    def test_the_span_covers_exactly_the_surface_text(self) -> None:
        text = "Dear <PERSON_001>, regards"
        found = scan_placeholders(text, KNOWN)
        assert text[found[0].span.start : found[0].span.end] == found[0].surface

    def test_the_span_is_exact_for_full_width_brackets(self) -> None:
        """The scanner normalizes to match, then maps the span back."""
        text = "Dear ＜PERSON_001＞ regards"
        found = scan_placeholders(text, KNOWN)
        assert text[found[0].span.start : found[0].span.end] == "＜PERSON_001＞"

    def test_a_bare_form_does_not_swallow_neighbouring_punctuation(self) -> None:
        text = "Regards, PERSON_001."
        found = scan_placeholders(text, KNOWN)
        assert found[0].surface == "PERSON_001"


class TestPrecision:
    def test_ordinary_text_is_not_mistaken_for_a_placeholder(self) -> None:
        assert scan_placeholders("Retry step 2 after error_404 on line 17.", KNOWN) == []

    def test_an_unrelated_bare_identifier_is_ignored(self) -> None:
        assert scan_placeholders("See ticket ABC_123 for details.", KNOWN) == []

    def test_an_unknown_bracketed_placeholder_is_reported_not_resolved(self) -> None:
        found = scan_placeholders("Contact <SECRET_009> now", KNOWN)
        assert len(found) == 1
        assert found[0].known is False

    def test_an_invented_index_of_a_known_type_is_reported(self) -> None:
        """The model made up <PERSON_999>. It must not resolve to anything."""
        found = scan_placeholders("Ask <PERSON_999> instead", KNOWN)
        assert len(found) == 1 and found[0].known is False

    def test_an_invented_index_is_caught_even_unbracketed(self) -> None:
        found = scan_placeholders("Ask PERSON_999 instead", KNOWN)
        assert len(found) == 1 and found[0].known is False

    def test_nothing_known_means_bare_forms_are_ignored(self) -> None:
        assert scan_placeholders("PERSON_001 is here", frozenset()) == []

    def test_index_zero_is_never_a_placeholder(self) -> None:
        assert scan_placeholders("<PERSON_000>", KNOWN) == []

    def test_empty_text(self) -> None:
        assert scan_placeholders("", KNOWN) == []
