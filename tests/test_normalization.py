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


class TestCharactersThatCombine:
    """`ﾀ` + `ﾞ` is `ダ` to NFKC and was `タ` + U+3099 to this module.

    NFKC is defined on strings; applying it one character at a time is a
    different function. The half-width voiced mark folds to a *combining* mark
    with class 8, which is not in `[ァ-ヶー]` and therefore in no rule this
    library has -- so a Japanese name written in half-width katakana was
    invisible, or worse, half-replaced.

    Half-width katakana is not exotic. It is how names arrive from a bank
    statement, a legacy database export and a fixed-width CSV, and
    `domain/script.py` already counts it as Japanese evidence. All 28 voiced
    and semi-voiced pairs were affected.
    """

    def test_a_voiced_pair_folds_the_way_nfkc_folds_it(self) -> None:
        assert NormalizedText.of("ﾀﾞ").text == "ダ"

    def test_the_whole_word(self) -> None:
        assert NormalizedText.of("ﾀﾅｶﾀﾞｲｽｹ").text == "タナカダイスケ"

    def test_it_agrees_with_nfkc_on_the_whole_string(self) -> None:
        """The property, rather than an example: this module and `unicodedata`
        must produce the same text, or a rule written against one is being run
        against the other."""
        import unicodedata

        for sample in ("ﾀﾅｶﾀﾞｲｽｹ", "ﾊﾟﾝ", "ｳﾞｧｲｵﾘﾝ", "ﾔﾏﾀﾞ ﾀﾛｳ", "田中太郎", "ｔｅｓｔ"):
            assert NormalizedText.of(sample).text == unicodedata.normalize("NFKC", sample)

    def test_the_offset_map_covers_both_characters(self) -> None:
        """The old docstring said merging would make the map ambiguous. It is
        a clean two-to-one group, and a span over it maps back to both -- which
        is what stops the mark being stranded outside the placeholder."""
        normalized = NormalizedText.of("氏名: ﾔﾏﾀﾞ")
        start = normalized.text.index("ヤマダ")
        span = normalized.to_original_span(start, start + 3)
        assert normalized.original[span.start : span.end] == "ﾔﾏﾀﾞ"

    def test_a_combining_mark_on_a_latin_letter_composes_too(self) -> None:
        assert NormalizedText.of("café").text == "café"

    @pytest.mark.parametrize("mark", ["ﾞ", "ﾟ"])
    def test_every_pair_that_nfkc_composes_is_composed_here(self, mark: str) -> None:
        import unicodedata

        for base in "ｦｳｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾊﾋﾌﾍﾎ":
            pair = base + mark
            expected = unicodedata.normalize("NFKC", pair)
            assert NormalizedText.of(pair).text == expected, pair

    def test_a_lone_mark_is_still_mapped(self) -> None:
        """Nothing precedes it. The map has to stay total whatever the input."""
        normalized = NormalizedText.of("ﾞ")
        assert normalized.text
        assert normalized.to_original_span(0, 1).start == 0


class TestHalfWidthNamesReachTheDetectors:
    """The end-to-end failure, stated as itself. The normalization tests above
    would all pass with a rule set that never looked at katakana."""

    @pytest.mark.parametrize(
        "text",
        ["ﾔﾏﾀﾞさん", "ﾀﾞｲｽｹさんが担当です。", "氏名: ﾔﾏﾀﾞ", "ﾀﾅｶ･ﾀﾞｲｽｹさんに連絡してください。"],
        ids=["surname", "given name", "labelled", "full name"],
    )
    def test_a_half_width_name_is_protected(self, text: str) -> None:
        from mamori import PrivacySession

        with PrivacySession() as session:
            assert "<PERSON_" in session.protect(text).protected_text

    def test_nothing_of_the_name_is_left_behind(self) -> None:
        """`氏名: <PERSON_001>ﾞ` -- the mark stranded outside the token, which
        is document corruption as well as a leak."""
        from mamori import PrivacySession

        with PrivacySession() as session:
            out = session.protect("氏名: ﾔﾏﾀﾞ").protected_text
        assert "ﾞ" not in out and "ﾀ" not in out

    def test_the_same_person_written_both_ways_gets_one_placeholder(self) -> None:
        """`normalize_value` always said these were one identity. Detection
        could not agree, because it never saw the composed form."""
        from mamori import PrivacySession

        with PrivacySession() as session:
            out = session.protect("ダイスケさんとﾀﾞｲｽｹさん").protected_text
        assert out.count("<PERSON_001>") == 2

    def test_full_width_still_works(self) -> None:
        from mamori import PrivacySession

        with PrivacySession() as session:
            out = session.protect("タナカ・ダイスケさんに連絡してください。").protected_text
        assert out.startswith("<PERSON_001>")
