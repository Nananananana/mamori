"""Cutting a long text into pieces, and putting the offsets back.

Two properties carry everything else. **Coverage**: every character of the
document appears in some window, or the model was never asked about it and the
scan is quietly partial. **Locatability**: a span found inside a window maps
back to the same characters in the document, or replacement cuts the wrong
text out of somebody's file.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mamori.domain.windowing import DEFAULT_OVERLAP, Window, windows


class TestTheEasyCase:
    """A text that fits must cost nothing at all."""

    def test_a_short_text_is_one_window(self) -> None:
        assert windows("hello", 100) == (Window(0, "hello"),)

    def test_a_text_exactly_at_the_limit_is_one_window(self) -> None:
        assert len(windows("x" * 100, 100)) == 1

    def test_one_character_over_the_limit_splits(self) -> None:
        assert len(windows("x" * 101, 100)) > 1

    def test_empty_text_produces_nothing_to_ask_about(self) -> None:
        assert windows("", 100) == ()


class TestCoverage:
    """Every character must be inside some window."""

    def test_the_windows_reconstruct_the_document(self) -> None:
        text = "".join(f"line {i} of the document.\n" for i in range(200))
        covered = set()
        for window in windows(text, 300):
            covered.update(range(window.offset, window.end))
        assert covered == set(range(len(text)))

    def test_no_window_exceeds_the_size(self) -> None:
        text = "x" * 5000
        assert all(len(w.text) <= 300 for w in windows(text, 300))

    def test_each_window_is_a_real_slice_of_the_text(self) -> None:
        text = "".join(f"sentence {i}. " for i in range(400))
        for window in windows(text, 250):
            assert text[window.offset : window.end] == window.text

    @given(
        text=st.text(min_size=0, max_size=2000),
        size=st.integers(min_value=1, max_value=200),
    )
    def test_coverage_holds_for_any_text(self, text: str, size: int) -> None:
        covered: set[int] = set()
        for window in windows(text, size):
            assert len(window.text) <= size
            assert text[window.offset : window.end] == window.text
            covered.update(range(window.offset, window.end))
        assert covered == set(range(len(text)))

    @given(text=st.text(min_size=0, max_size=1500), size=st.integers(1, 120))
    def test_it_always_terminates_and_moves_forward(self, text: str, size: int) -> None:
        pieces = windows(text, size)
        offsets = [w.offset for w in pieces]
        assert offsets == sorted(offsets)
        assert len(set(offsets)) == len(offsets), "a repeated offset means no progress"


class TestOverlap:
    """An entity lying across a cut must be whole in some window.

    This is the entire reason the windows overlap. ``tanaka@exa`` and
    ``mple.com`` are not an email address to anybody.
    """

    def test_a_value_spanning_a_cut_survives_intact_somewhere(self) -> None:
        email = "tanaka@example.com"
        # Place the value right where a naive cut would land.
        text = "x" * 995 + " " + email + " " + "y" * 1000
        pieces = windows(text, 1000)
        assert any(email in window.text for window in pieces)

    @given(position=st.integers(min_value=100, max_value=1900))
    def test_any_ordinary_value_survives_wherever_it_sits(self, position: int) -> None:
        value = "tanaka@example.com"
        text = "x" * position + value + "y" * 2000
        assert any(value in w.text for w in windows(text, 500))

    def test_the_overlap_is_bounded_so_it_cannot_stall(self) -> None:
        """An overlap at least as wide as the window would never advance."""
        pieces = windows("x" * 1000, 100, overlap=10_000)
        assert len(pieces) < 100


class TestCutPoints:
    """Cuts prefer a boundary, because an entity is least likely to stand there."""

    def test_it_prefers_a_line_break(self) -> None:
        text = "a" * 90 + "\n" + "b" * 200
        assert windows(text, 100)[0].text.endswith("\n")

    def test_it_prefers_a_japanese_full_stop(self) -> None:
        """A Japanese document contains no ASCII full stops at all."""
        text = "あ" * 90 + "。" + "い" * 200
        assert windows(text, 100)[0].text.endswith("。")

    def test_a_hard_cut_is_acceptable_when_there_is_no_boundary(self) -> None:
        """Not a correctness problem: the overlap covers it."""
        pieces = windows("x" * 500, 100)
        assert pieces[0].text == "x" * 100

    def test_it_does_not_search_far_for_a_boundary(self) -> None:
        """Honouring a distant boundary costs more window than it saves."""
        text = "." + "x" * 400
        assert len(windows(text, 100)[0].text) > 50


class TestLocate:
    def test_a_span_maps_back_to_the_same_characters(self) -> None:
        text = "".join(f"item {i} here. " for i in range(300))
        needle = "item 250 here"
        for window in windows(text, 400):
            if needle in window.text:
                local = window.text.index(needle)
                start, end = window.locate(local, local + len(needle))
                assert text[start:end] == needle
                return
        pytest.fail("the fixture never appeared in a window")

    def test_the_first_window_needs_no_shift(self) -> None:
        window = Window(0, "hello")
        assert window.locate(1, 3) == (1, 3)

    def test_end_is_the_offset_plus_the_length(self) -> None:
        assert Window(50, "abc").end == 53


class TestBadArguments:
    def test_a_zero_window_is_refused(self) -> None:
        with pytest.raises(ValueError):
            windows("text", 0)

    def test_a_negative_window_is_refused(self) -> None:
        with pytest.raises(ValueError):
            windows("text", -10)

    def test_a_negative_overlap_is_refused(self) -> None:
        with pytest.raises(ValueError):
            windows("text", 10, overlap=-1)

    def test_the_default_overlap_clears_any_entity_this_library_detects(self) -> None:
        """A database URL with credentials in it is the longest, by a distance."""
        longest = "postgres://appuser:s3cret@db.example.com:5432/orders"
        assert DEFAULT_OVERLAP > len(longest) * 2
