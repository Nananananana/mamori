"""Offset-preserving normalization.

The invariant that matters: a span found in normalized coordinates must map
back to the exact substring of the *original* text. If it does not, every
replacement is off by a few characters and the user gets back mangled input.
"""

from __future__ import annotations

import pytest

from mamori.domain.normalization import NormalizedText, normalize_value


class TestNormalizedText:
    def test_full_width_ascii_is_folded(self) -> None:
        normalized = NormalizedText.of("ｔａｎａｋａ＠ｅｘａｍｐｌｅ．ｃｏｍ")
        assert normalized.text == "tanaka@example.com"

    def test_full_width_digits_are_folded(self) -> None:
        assert NormalizedText.of("０９０－１２３４").text == "090-1234"

    def test_span_maps_back_to_the_original_substring(self) -> None:
        original = "連絡先は ｔａｎａｋａ＠ｅｘａｍｐｌｅ．ｃｏｍ です"
        normalized = NormalizedText.of(original)
        start = normalized.text.index("tanaka@example.com")
        span = normalized.to_original_span(start, start + len("tanaka@example.com"))
        assert original[span.start : span.end] == "ｔａｎａｋａ＠ｅｘａｍｐｌｅ．ｃｏｍ"

    def test_span_maps_back_when_normalization_expands_a_character(self) -> None:
        """㍿ normalizes to 株式会社: one original char becomes four."""
        original = "㍿さくら商事"
        normalized = NormalizedText.of(original)
        assert normalized.text == "株式会社さくら商事"
        span = normalized.to_original_span(0, 4)
        assert original[span.start : span.end] == "㍿"

    def test_a_span_covering_an_expansion_and_its_neighbours(self) -> None:
        original = "㍿さくら"
        normalized = NormalizedText.of(original)
        span = normalized.to_original_span(0, len(normalized.text))
        assert original[span.start : span.end] == original

    def test_plain_ascii_is_left_alone(self) -> None:
        original = "Contact tanaka@example.com now"
        normalized = NormalizedText.of(original)
        assert normalized.text == original
        span = normalized.to_original_span(8, 26)
        assert original[span.start : span.end] == "tanaka@example.com"

    def test_offset_map_covers_every_normalized_character(self) -> None:
        normalized = NormalizedText.of("㍿ｔｅｓｔ日本語123")
        for index in range(len(normalized.text)):
            span = normalized.to_original_span(index, index + 1)
            assert 0 <= span.start < span.end <= len(normalized.original)

    @pytest.mark.parametrize(("start", "end"), [(-1, 3), (0, 0), (0, 10_000)])
    def test_out_of_range_spans_are_refused(self, start: int, end: int) -> None:
        normalized = NormalizedText.of("abcdef")
        with pytest.raises(ValueError):
            normalized.to_original_span(start, end)

    def test_empty_text(self) -> None:
        assert NormalizedText.of("").text == ""

    def test_original_is_kept_verbatim(self) -> None:
        original = "㍿ｔｅｓｔ"
        assert NormalizedText.of(original).original == original


class TestNormalizeValue:
    @pytest.mark.parametrize("written", ["田中太郎", "田中 太郎", "田中　太郎", " 田中  太郎 "])
    def test_spacing_variants_collapse_to_one_identity(self, written: str) -> None:
        assert normalize_value(written) == "田中 太郎" or normalize_value(written) == "田中太郎"

    def test_the_same_name_written_two_ways_shares_an_identity(self) -> None:
        assert normalize_value("田中 太郎") == normalize_value("田中　太郎")

    def test_full_width_ascii_folds(self) -> None:
        assert normalize_value("ＡＢＣ") == "ABC"

    def test_different_people_keep_different_identities(self) -> None:
        assert normalize_value("田中太郎") != normalize_value("田中次郎")
