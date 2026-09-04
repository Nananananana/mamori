"""Recovering placeholders that a model altered.

A model is not obliged to echo a token back the way it received it. These are
the mutations worth surviving, plus the cases where being permissive would be
dangerous.
"""

from __future__ import annotations

import time
from typing import ClassVar

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


class TestSpacesInsideTheToken:
    """`<COMPANY _ NAME _ 001>` -- the one mutation the scanner did not survive.

    A thousand generated replies found it in 0.14: every other mangling
    (brackets dropped, case changed, full-width, zero padding lost) restored
    correctly, and this one accounted for every single failure. 195 of 1002
    replies came back wrong because of it.
    """

    KNOWN = frozenset({Placeholder("COMPANY_NAME", 1), Placeholder("PERSON", 1)})

    def test_spaces_around_the_underscores_still_resolve(self) -> None:
        found = scan_placeholders("about <COMPANY _ NAME _ 001> today", self.KNOWN)
        assert [o.placeholder for o in found] == [Placeholder("COMPANY_NAME", 1)]
        assert found[0].known

    def test_a_single_part_type_with_spaces(self) -> None:
        found = scan_placeholders("<PERSON _ 001>", self.KNOWN)
        assert found and found[0].placeholder == Placeholder("PERSON", 1)

    def test_the_whole_run_is_replaced_not_part_of_it(self) -> None:
        found = scan_placeholders("x <COMPANY _ NAME _ 001> y", self.KNOWN)
        assert found[0].surface == "<COMPANY _ NAME _ 001>"

    def test_it_does_not_span_a_line_break(self) -> None:
        """Otherwise a type could swallow a paragraph looking for its index."""
        found = scan_placeholders("Dear PERSON\n\n001 units shipped", self.KNOWN)
        assert not [o for o in found if o.known]

    def test_ordinary_prose_is_still_not_a_placeholder(self) -> None:
        """The precision guard has to survive the wider pattern."""
        for text in ("error_404 on line 17", "step 2 of 3", "Retry after 30 seconds"):
            assert not [o for o in scan_placeholders(text, self.KNOWN) if o.known]

    def test_an_unallocated_identity_is_reported_not_substituted(self) -> None:
        found = scan_placeholders("<SOME _ THING _ 001>", self.KNOWN)
        assert all(not o.known for o in found)


class TestTheScanStaysLinear:
    """A model's answer is input, and this scans all of it.

    `scan_placeholders` ran `finditer` with an unbounded type name, so the
    engine started a candidate at every position of a long alphanumeric run
    and read to the end of it each time. Measured on `restore`:

        prose      8KB     3.9ms      128KB       65ms
        one run    8KB  1,297.5ms     128KB  455,890ms

    Four times the work for twice the input, all the way up -- quadratic, not
    exponential, and quite enough. A 128KB answer containing one base64 blob
    took seven and a half minutes, and a model that emits a long token is
    ordinary rather than adversarial: in the proxy it holds a request thread
    for that whole time.

    The bounds in `_LENIENT_RE` are what these tests are about. They are not
    tuning: a type name is `[A-Z][A-Z0-9_]{0,62}`, so 63 characters is the
    longest that can ever have been allocated, and a candidate longer than
    that is a word that begins like a placeholder rather than one.
    """

    #: Generous by a factor of about five hundred. Before the bounds, the
    #: 200,000-character case took roughly a thousand seconds; after them it
    #: takes a fifth of one. A wall-clock assertion is usually a bad idea and
    #: is the right one here, because the thing being asserted is time and the
    #: margin is three orders of magnitude.
    BUDGET_SECONDS = 5.0

    SHAPES: ClassVar[dict[str, str]] = {
        "one alphanumeric run": "a" * 200_000,
        "a base64 blob": "here it is: " + ("QUJDREVGR0hJSktMTU5PUFFSU1Q" * 7_500),
        "hex": "f0" * 100_000,
        "a word then spaces": "PERSON" + " " * 200_000 + "!",
        "bracket then run": "<" + "A" * 200_000,
        "underscored run": ("PERSON_" * 28_000),
        "digits": "1" * 200_000,
    }

    @pytest.mark.parametrize("shape", sorted(SHAPES))
    def test_a_long_answer_is_scanned_in_linear_time(self, shape: str) -> None:
        text = self.SHAPES[shape]
        start = time.perf_counter()
        scan_placeholders(text, KNOWN)
        elapsed = time.perf_counter() - start
        assert elapsed < self.BUDGET_SECONDS, (
            f"{shape}: {len(text)} characters took {elapsed:.1f}s. Something in "
            "_LENIENT_RE lost its bound; the scan is quadratic again."
        )

    def test_doubling_the_input_does_not_quadruple_the_work(self) -> None:
        """The shape of the curve, not one point on it.

        A budget alone would pass on a faster machine with the bounds removed.
        This measures the ratio, which is a property of the pattern rather than
        of the hardware: linear is about 2, the old pattern was about 4.
        """

        def seconds(size: int) -> float:
            text = "a" * size
            start = time.perf_counter()
            scan_placeholders(text, KNOWN)
            return time.perf_counter() - start

        small = min(seconds(50_000) for _ in range(3))
        large = min(seconds(200_000) for _ in range(3))
        # Four times the input. Linear gives about 4, quadratic about 16.
        assert large < small * 8, (
            f"50k took {small * 1000:.1f}ms and 200k took {large * 1000:.1f}ms, "
            f"a factor of {large / small:.1f} for four times the input"
        )

    def test_the_mutations_it_exists_for_still_match(self) -> None:
        """The bounds must not have bought speed with tolerance.

        Every surface form in the class above is here again on purpose: this
        is the list that says the pattern was narrowed and not broken.
        """
        for surface in (
            "<PERSON_001>",
            "PERSON_001",
            "[PERSON_001]",
            "{PERSON_001}",
            "< PERSON_001 >",
            "<PERSON _ 001>",
            "<person_001>",
            "<PERSON_1>",
        ):
            found = scan_placeholders(f"Dear {surface}, hello", KNOWN)
            assert [(o.placeholder.entity_type_name, o.placeholder.index) for o in found] == [
                ("PERSON", 1)
            ], surface

    def test_a_candidate_in_the_middle_of_a_word_is_not_one(self) -> None:
        """What the boundary check changed, stated rather than discovered.

        `xyzPERSON_001` used to be read as a placeholder starting at `PERSON`.
        It is not one -- a placeholder this library emitted never begins inside
        a word -- and refusing it is what makes the scan linear.
        """
        assert scan_placeholders("xyzPERSON_001 arrived", KNOWN) == []
        assert scan_placeholders("xyz PERSON_001 arrived", KNOWN) != []
