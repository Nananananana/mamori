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

from enum import Enum

__all__ = ["Script", "scripts_in"]


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


def _script_of(char: str) -> Script | None:
    """Return the script of one character, or ``None`` if it carries no signal.

    Digits, punctuation and whitespace return ``None``: they appear in every
    language and would make every text look like every locale.
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
    found: set[Script] = set()
    for index, char in enumerate(text):
        if index >= sample_limit:
            break
        script = _script_of(char)
        if script is not None:
            found.add(script)
    return frozenset(found)
