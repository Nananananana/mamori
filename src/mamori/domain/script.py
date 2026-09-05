"""Which writing systems a text uses.

Used to decide which language packs are worth running. This is not language
identification — it does not tell Chinese from Japanese in a sentence written
only in Han characters, and it does not try. It answers a narrower question
that can be answered exactly: which scripts appear here.

That is enough, because the packs only need a reason to run and a reason to
stand down, and one such reason is decisive: kana appear in Japanese and not in
Chinese.
"""

from __future__ import annotations

import re
from enum import Enum
from functools import lru_cache

__all__ = ["Script", "covered_by", "script_regions", "scripts_in"]


class Script(Enum):
    """A writing system, at the coarseness the locale packs care about."""

    LATIN = "latin"
    KANA = "kana"
    HAN = "han"
    HANGUL = "hangul"
    CYRILLIC = "cyrillic"
    ARABIC = "arabic"
    OTHER = "other"


#: Ordered, non-overlapping codepoint ranges. Half-width katakana is included
#: in KANA so that ﾀﾅｶ counts as Japanese evidence.
_RANGES: tuple[tuple[int, int, Script], ...] = (
    (0x0041, 0x005A, Script.LATIN),
    (0x0061, 0x007A, Script.LATIN),
    (0x00C0, 0x024F, Script.LATIN),
    (0x0400, 0x04FF, Script.CYRILLIC),
    (0x0600, 0x06FF, Script.ARABIC),
    (0x3040, 0x309F, Script.KANA),  # hiragana
    (0x30A0, 0x30FF, Script.KANA),  # katakana
    (0x31F0, 0x31FF, Script.KANA),  # katakana phonetic extensions
    (0x3400, 0x4DBF, Script.HAN),  # CJK extension A
    (0x4E00, 0x9FFF, Script.HAN),  # CJK unified ideographs
    (0xA960, 0xA97F, Script.HANGUL),
    (0xAC00, 0xD7AF, Script.HANGUL),
    (0xF900, 0xFAFF, Script.HAN),  # CJK compatibility ideographs
    (0xFF21, 0xFF3A, Script.LATIN),  # full-width A-Z
    (0xFF41, 0xFF5A, Script.LATIN),  # full-width a-z
    (0xFF66, 0xFF9D, Script.KANA),  # half-width katakana
    (0x1100, 0x11FF, Script.HANGUL),
    (0x20000, 0x2A6DF, Script.HAN),  # CJK extension B
)


def _class_for(*scripts: Script) -> re.Pattern[str]:
    """A character class matching any code point in any of ``scripts``.

    Built from the same table as :func:`_script_of`, so the two cannot
    disagree about a range; :mod:`tests.test_locales` checks them against
    each other anyway, because "built from the same table" is a claim about
    the code and the test is a claim about the behaviour.
    """
    parts = [f"{chr(start)}-{chr(end)}" for start, end, script in _RANGES if script in scripts]
    if not parts:
        # `Script.OTHER` has no ranges: it names what the table does not.
        # An empty class is a syntax error, and the loop this replaced simply
        # never matched -- so neither does this. Found by Hypothesis on the
        # first run, with `wanted={OTHER}`.
        return _NEVER
    return re.compile("[" + "".join(parts) + "]")


#: A pattern that matches nothing, for a script that has no code points.
_NEVER = re.compile(r"(?!)")


#: One pattern per script. Asked with ``search``, each is a C-speed answer to
#: "does this script appear at all", which is the only thing :func:`scripts_in`
#: needs and was previously a Python loop over every character with a
#: twenty-way range comparison inside it -- 185,000 calls to normalise a
#: 6.5KB document once, measured with cProfile.
_BY_SCRIPT: dict[Script, re.Pattern[str]] = {
    script: _class_for(script) for script in {script for _, _, script in _RANGES}
}


@lru_cache(maxsize=4096)
def _script_of(char: str) -> Script | None:
    """Return the script of one character, or ``None`` if it carries no signal.

    Digits, punctuation and whitespace return ``None``: they appear in every
    language and would make every text look like every locale.

    Cached, because a document is made of a few hundred distinct characters
    repeated many thousands of times and the range walk is the same every
    time. 4,096 entries is more distinct characters than any document here
    has, and an eviction costs one range walk.
    """
    code = ord(char)
    for start, end, script in _RANGES:
        if start <= code <= end:
            return script
    return None


def scripts_in(text: str, *, sample_limit: int = 20_000) -> frozenset[Script]:
    """Return the scripts appearing in ``text``.

    Args:
        text: Text to inspect.
        sample_limit: Stop after this many characters. A prompt long enough to
            exceed it has already shown which scripts it uses, and scanning a
            whole document to reach the same answer is wasted work.

    Returns:
        The set of scripts found. Empty for text with no letters at all.
    """
    sample = text[:sample_limit]
    return frozenset(script for script, pattern in _BY_SCRIPT.items() if pattern.search(sample))


#: Where one sentence stops speaking for the next.
#:
#: Sentence-final punctuation and line breaks, in both widths, plus the
#: characters that separate one JSON string from another. A comma is
#: deliberately absent: `本日、会議資料を送付します` is one sentence and the
#: kana at the end of it are evidence about the kanji at the start.
_BOUNDARIES = frozenset("\n\r\u2028\u2029。．.!?！？；;：:\"'`{}[]()（）「」『』")
_BOUNDARY_RE = re.compile("[" + re.escape("".join(sorted(_BOUNDARIES))) + "]")


def script_regions(text: str, scripts: frozenset[Script]) -> tuple[tuple[int, int], ...]:
    """Character ranges where ``scripts`` are the evidence about the text.

    A sentence containing one of those scripts claims itself, and nothing
    further. This is the whole of what makes the Japanese/Chinese decision
    local: one kana character says the words *around* it are Japanese, and it
    says nothing about a passage two sentences later.

    Returns ordered, non-overlapping ranges, empty when none of the scripts
    appear -- which lets a caller tell "nowhere" from "everywhere" without
    inspecting the text again.
    """
    if not scripts or not text:
        return ()

    # Two C-speed scans instead of one Python loop over every character: the
    # boundaries split the text into sentences, and one class match per
    # sentence says whether the evidence is in it. Same answer as the loop it
    # replaced -- a region is a maximal run of sentences, each of which holds
    # at least one character of the scripts -- and `tests/test_locales.py`
    # holds the two implementations against each other.
    evidence = _class_for(*scripts)
    regions: list[tuple[int, int]] = []
    start = 0
    for boundary in _BOUNDARY_RE.finditer(text):
        end = boundary.start()
        if evidence.search(text, start, end):
            regions.append((start, end))
        start = boundary.end()
    if evidence.search(text, start):
        regions.append((start, len(text)))

    merged: list[tuple[int, int]] = []
    for region in regions:
        if merged and region[0] <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], region[1]))
        else:
            merged.append(region)
    return tuple(merged)


def covered_by(regions: tuple[tuple[int, int], ...], start: int, end: int) -> bool:
    """Whether ``[start, end)`` overlaps any region.

    Overlap rather than containment: a name that begins inside Japanese text
    and runs out of it is still in Japanese text, and the point of asking is to
    decide whether to trust a rule set that would be wrong there.
    """
    return any(start < region_end and end > region_start for region_start, region_end in regions)
