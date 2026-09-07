"""`covered_by`, which had no test of its own and is asked a million times.

It decides whether a rule's hit falls inside the stretch of text that argued
against that rule's language pack -- a Chinese name rule firing in a paragraph
that is plainly Japanese. Getting it wrong in one direction suppresses a real
detection; in the other it lets a pack speak where the evidence says it should
not.

It was also 26% of a protection: a linear scan over every region, per candidate
entity. 3,281 entities against ~308 regions is a million generator steps. The
regions are sorted and merged, so it is a binary search, and the way to change
that safely is to hold the new one against the old one rather than against an
argument about it.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from mamori.domain.script import Script, covered_by, script_regions

JAPANESE = "田中太郎さんへ。ご連絡ください。\n"
CHINESE = "张伟先生，请与我们联系。\n"


def naive(regions: tuple[tuple[int, int], ...], start: int, end: int) -> bool:
    """What `covered_by` was: overlap against every region in turn."""
    return any(start < region_end and end > region_start for region_start, region_end in regions)


@st.composite
def sorted_regions(draw: st.DrawFn) -> tuple[tuple[int, int], ...]:
    """Regions as `script_regions` produces them: sorted, merged, disjoint."""
    gaps = draw(st.lists(st.tuples(st.integers(0, 20), st.integers(1, 30)), max_size=12))
    regions: list[tuple[int, int]] = []
    cursor = 0
    for gap, width in gaps:
        cursor += gap
        regions.append((cursor, cursor + width))
        cursor += width
    return tuple(regions)


class TestItAnswersWhatItUsedTo:
    @given(regions=sorted_regions(), start=st.integers(0, 400), width=st.integers(1, 40))
    def test_against_the_scan_it_replaced(
        self, regions: tuple[tuple[int, int], ...], start: int, width: int
    ) -> None:
        assert covered_by(regions, start, start + width) == naive(regions, start, start + width)

    def test_nothing_is_covered_by_nothing(self) -> None:
        assert not covered_by((), 0, 5)

    def test_a_span_inside_one_region(self) -> None:
        assert covered_by(((10, 20),), 12, 15)

    def test_a_span_outside_every_region(self) -> None:
        assert not covered_by(((10, 20), (30, 40)), 22, 28)

    def test_a_span_that_begins_inside_and_runs_out(self) -> None:
        """Overlap, not containment: a name that starts in Japanese text and
        runs past the end of it is still in Japanese text."""
        assert covered_by(((10, 20),), 18, 25)

    def test_a_span_that_ends_where_a_region_begins(self) -> None:
        """Half-open on both sides, so touching is not overlapping."""
        assert not covered_by(((10, 20),), 5, 10)
        assert not covered_by(((10, 20),), 20, 25)

    def test_the_region_that_matters_is_not_the_nearest_one(self) -> None:
        """The case a binary search can get wrong: several regions before the
        answer, and the answer is the last one that starts before the span
        ends rather than the first one found."""
        regions = ((0, 5), (10, 15), (20, 25), (30, 35), (40, 45))
        assert covered_by(regions, 41, 43)
        assert not covered_by(regions, 46, 48)
        assert covered_by(regions, 34, 36)


class TestItStillSuppressesWhatItShould:
    """The behaviour underneath, so the property test above cannot be green
    about a `covered_by` nothing calls."""

    def test_a_japanese_paragraph_covers_itself(self) -> None:
        text = JAPANESE * 3
        regions = script_regions(text, frozenset({Script.KANA}))
        assert regions
        assert covered_by(regions, 0, 3)

    def test_a_chinese_sentence_among_japanese_is_not_covered(self) -> None:
        text = JAPANESE + CHINESE + JAPANESE
        regions = script_regions(text, frozenset({Script.KANA}))
        chinese_at = text.index(CHINESE)
        assert not covered_by(regions, chinese_at + 1, chinese_at + 3)
