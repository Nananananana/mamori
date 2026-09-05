"""Two hot paths rewritten for speed, held against the code they replaced.

cProfile on `protect()` over a 6.5KB document: 185,000 calls to a per-character
script lookup and a per-character normalisation loop, together a third of the
run. Both are now one or two C-speed calls -- `unicodedata.is_normalized` for
the identity case, compiled character classes for the scripts -- and each is
about ten times faster on the documents this library is measured on.

A fast path is a second implementation, and a second implementation is a
disagreement waiting to be found. So the slow implementations are kept here,
verbatim, and Hypothesis drives both with text chosen to be difficult: the
half-width katakana whose voiced mark folds leftwards, decomposed Hangul jamo
that the grouping deliberately does not compose, full-width Latin, combining
marks on their own, and every boundary character the region scan splits on.
"""

from __future__ import annotations

import unicodedata

from hypothesis import given, settings
from hypothesis import strategies as st

from mamori.domain.normalization import NormalizedText, _combines_leftwards
from mamori.domain.script import _BOUNDARIES, _RANGES, Script, script_regions, scripts_in

# -- the implementations that were replaced, kept as the oracle ---------------


def _script_of_reference(char: str) -> Script | None:
    code = ord(char)
    for start, end, script in _RANGES:
        if start <= code <= end:
            return script
    return None


def scripts_in_reference(text: str, *, sample_limit: int = 20_000) -> frozenset[Script]:
    found: set[Script] = set()
    for index, char in enumerate(text):
        if index >= sample_limit:
            break
        script = _script_of_reference(char)
        if script is not None:
            found.add(script)
    return frozenset(found)


def script_regions_reference(text: str, scripts: frozenset[Script]) -> tuple[tuple[int, int], ...]:
    if not scripts or not text:
        return ()
    regions: list[tuple[int, int]] = []
    start = 0
    seen = False
    for index, char in enumerate(text):
        if char in _BOUNDARIES:
            if seen:
                regions.append((start, index))
            start, seen = index + 1, False
            continue
        if _script_of_reference(char) in scripts:
            seen = True
    if seen:
        regions.append((start, len(text)))
    merged: list[tuple[int, int]] = []
    for region in regions:
        if merged and region[0] <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], region[1]))
        else:
            merged.append(region)
    return tuple(merged)


def normalized_reference(original: str) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
    chunks: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    index = 0
    length = len(original)
    while index < length:
        stop = index + 1
        while stop < length and _combines_leftwards(original[stop]):
            stop += 1
        folded = unicodedata.normalize("NFKC", original[index:stop]) or original[index:stop]
        chunks.append(folded)
        starts.extend([index] * len(folded))
        ends.extend([stop] * len(folded))
        index = stop
    return "".join(chunks), tuple(starts), tuple(ends)


# -- text chosen to be difficult ----------------------------------------------

DIFFICULT = (
    "ﾀﾅｶ ﾀﾞ ﾊﾟ"  # half-width katakana, voiced and semi-voiced marks
    "ダ パ が ぱ"  # composed and decomposed kana
    "각 한글"  # decomposed jamo, precomposed syllables
    "ＡＢＣ ａｂｃ １２３"  # full-width Latin and digits
    "é ́ ゙"  # combining marks, with and without a base
    "㍿ Ĳ ﬁ ①"  # compatibility characters that change length
    "田中。abc.かな！ok?（x）「y」\n\r "  # every boundary
    "Иван عمر"  # cyrillic, arabic
)

difficult_text = st.text(
    alphabet=st.sampled_from(list(DIFFICULT) + list("abc 123\n")),
    max_size=80,
)
any_text = st.text(max_size=80)
scripts = st.frozensets(st.sampled_from(list(Script)), max_size=3)

SETTINGS = settings(max_examples=400, deadline=None)


class TestScriptsInAgreesWithTheLoopItReplaced:
    @SETTINGS
    @given(text=difficult_text)
    def test_on_difficult_text(self, text: str) -> None:
        assert scripts_in(text) == scripts_in_reference(text)

    @SETTINGS
    @given(text=any_text)
    def test_on_arbitrary_text(self, text: str) -> None:
        assert scripts_in(text) == scripts_in_reference(text)

    def test_the_sample_limit_is_still_a_limit(self) -> None:
        """The reference stops at the limit; so must the class scan."""
        text = "a" * 20_000 + "田"
        assert scripts_in(text) == frozenset({Script.LATIN})
        assert scripts_in(text, sample_limit=20_001) == frozenset({Script.LATIN, Script.HAN})

    def test_every_range_is_in_exactly_one_class(self) -> None:
        """Both implementations read `_RANGES`; this is the one place that
        checks the classes were built from all of it."""
        for start, end, script in _RANGES:
            for code in (start, (start + end) // 2, end):
                assert scripts_in(chr(code)) == frozenset({script}), hex(code)


class TestScriptRegionsAgreeWithTheLoopTheyReplaced:
    @SETTINGS
    @given(text=difficult_text, wanted=scripts)
    def test_on_difficult_text(self, text: str, wanted: frozenset[Script]) -> None:
        assert script_regions(text, wanted) == script_regions_reference(text, wanted)

    @SETTINGS
    @given(text=any_text, wanted=scripts)
    def test_on_arbitrary_text(self, text: str, wanted: frozenset[Script]) -> None:
        assert script_regions(text, wanted) == script_regions_reference(text, wanted)


class TestTheIdentityFastPathIsTheSlowPath:
    """ASCII text is its own normal form and holds no combining mark, so the
    offset map is the identity.

    The first version said *"already NFKC"* instead of *"ASCII"*, and the
    first run of the test below found `'1゙'`: a digit and a voiced mark, which
    is normal -- nothing composes with a digit -- and which the grouping still
    joins into one group, so both output characters map back to the pair.
    Same text, different offsets. This is why a fast path is held against the
    code it replaced rather than against an argument about it.
    """

    @SETTINGS
    @given(text=difficult_text)
    def test_on_difficult_text(self, text: str) -> None:
        fast = NormalizedText.of(text)
        expected_text, starts, ends = normalized_reference(text)
        assert fast.text == expected_text
        assert fast._starts == starts
        assert fast._ends == ends

    @SETTINGS
    @given(text=any_text)
    def test_on_arbitrary_text(self, text: str) -> None:
        fast = NormalizedText.of(text)
        expected_text, starts, ends = normalized_reference(text)
        assert (fast.text, fast._starts, fast._ends) == (expected_text, starts, ends)

    def test_the_fast_path_is_actually_taken(self) -> None:
        """Otherwise the two tests above compare the slow path with itself."""
        from mamori.domain.normalization import _is_identity

        assert _is_identity("田中太郎さんへ、株式会社さくら商事です。")
        assert not _is_identity("ﾀﾞ")  # not normal
        assert not _is_identity("1゙")  # normal, but a mark

    def test_the_case_that_broke_the_first_version(self) -> None:
        fast = NormalizedText.of("1゙")
        assert fast.text == "1゙"
        assert fast._starts == (0, 0)
        assert fast._ends == (2, 2)
