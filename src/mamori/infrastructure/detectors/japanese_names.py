"""Japanese personal-name rules.

Personal names are the hardest common case in Japanese text: there is no word
boundary to anchor on, and the same characters are a surname in one sentence
and a place in the next. Two complementary rules are used.

**Honorific-anchored.** ``田中さん`` / ``佐藤部長`` -- the suffix is strong
evidence and it sits exactly where the name ends. High precision, and it works
for surnames outside any dictionary.

**Dictionary-anchored.** A run starting with a known surname, optionally
followed by a given name. Catches ``田中太郎`` written with no honorific, at the
cost of missing every surname not in the list.

Neither rule recovers a name written with no honorific and an uncommon
surname. That gap is real and is what a local model is for; see the roadmap in
the README.
"""

from __future__ import annotations

import re

from ...domain import entity_types as t
from ...domain.confidence import HIGH, LOW, MEDIUM
from .patterns import PatternRule

__all__ = ["COMMON_SURNAMES", "NAME_RULES"]

#: The most common Japanese surnames. Not exhaustive by design -- adding rarer
#: surnames raises recall but each one is a new source of false positives on
#: place names and ordinary nouns.
# fmt: off
COMMON_SURNAMES: tuple[str, ...] = (
    "佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村", "小林", "加藤",
    "吉田", "山田", "佐々木", "山口", "松本", "井上", "木村", "林", "斎藤", "斉藤",
    "清水", "山崎", "阿部", "森", "池田", "橋本", "山下", "石川", "中島", "前田",
    "藤田", "後藤", "小川", "岡田", "村上", "長谷川", "近藤", "石井", "斎田", "坂本",
    "遠藤", "藤井", "青木", "福田", "三浦", "西村", "藤原", "太田", "松田", "原田",
    "岡本", "中野", "中川", "小野", "田村", "竹内", "金子", "和田", "中山", "石田",
    "上田", "森田", "原", "柴田", "酒井", "工藤", "横山", "宮崎", "宮本", "内田",
    "高木", "安藤", "島田", "谷口", "大野", "高田", "丸山", "今井", "河野", "藤本",
    "村田", "武田", "上野", "杉山", "増田", "小島", "平野", "大塚", "千葉", "久保",
    "松井", "岩崎", "桜井", "木下", "野口", "松尾", "菊地", "野村", "渡部", "新井",
    "渋谷", "水野", "小松", "菅原", "大西", "市川", "岡", "浜田", "武藤", "本田",
)
# fmt: on

#: Words that look like a name in front of an honorific but are not one.
# fmt: off
_HONORIFIC_STOPWORDS = frozenset(
    {
        "お客", "客", "皆", "神", "王", "貴", "殿", "各", "他", "当", "御",
        "社長", "部長", "課長", "先生", "皆様", "何", "誰",
    }
)

# fmt: off
_HONORIFICS = (
    "さん", "様", "さま", "氏", "君", "くん", "ちゃん", "先生", "殿",
    "部長", "課長", "社長", "専務", "常務", "取締役", "主任", "係長", "次長", "室長",
)
# fmt: on

#: Suffixes that turn a surname-looking run into an organisation or a place.
# fmt: off
_NOT_A_NAME_AFTER = (
    "会社", "商事", "工業", "銀行", "大学", "病院", "株式", "製作所", "建設",
    "電機", "運輸", "市", "区", "町", "村", "県", "府", "都", "駅", "線",
    "川", "山", "寺", "神社", "空港", "港", "島",
)
# fmt: on

_HONORIFIC_ALT = "|".join(_HONORIFICS)
_NOT_NAME_ALT = "|".join(_NOT_A_NAME_AFTER)
_SURNAME_ALT = "|".join(sorted(COMMON_SURNAMES, key=len, reverse=True))


def _not_stopword(value: str) -> bool:
    return value.strip() not in _HONORIFIC_STOPWORDS


#: ``田中さん``, ``佐藤 花子様``. The honorific is matched by lookahead so it
#: stays in the output: ``<PERSON_001>さん`` reads far better to a model than a
#: bare token.
_HONORIFIC_RULE = PatternRule(
    t.PERSON,
    re.compile(r"(?<![一-鿿])([一-鿿]{1,4}(?:[ 　][一-鿿]{1,4})?)(?=" + _HONORIFIC_ALT + r")"),
    HIGH,
    group=1,
    validator=_not_stopword,
)

#: ``田中太郎``, ``田中``. Rejected when followed by an organisation or place
#: suffix, so ``田中商事`` is left for the company rule.
_SURNAME_RULE = PatternRule(
    t.PERSON,
    re.compile(
        r"(?<![一-鿿])(?:" + _SURNAME_ALT + r")"
        r"(?!" + _NOT_NAME_ALT + r")"
        r"(?:[ 　]?[一-鿿]{1,3})?(?![一-鿿])"
    ),
    MEDIUM,
)

#: ``ジョン・スミス`` -- a katakana full name joined by a middle dot.
_KATAKANA_RULE = PatternRule(
    t.PERSON,
    re.compile(r"[ァ-ヶー]{2,10}・[ァ-ヶー]{2,10}"),
    MEDIUM,
)

#: ``Mr. John Smith``. The title is context, not part of the value.
_LATIN_TITLE_RULE = PatternRule(
    t.PERSON,
    re.compile(r"(?:Mr|Mrs|Ms|Dr|Prof)\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})"),
    LOW,
    group=1,
)

NAME_RULES: tuple[PatternRule, ...] = (
    _HONORIFIC_RULE,
    _SURNAME_RULE,
    _KATAKANA_RULE,
    _LATIN_TITLE_RULE,
)
