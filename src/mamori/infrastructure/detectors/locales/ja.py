"""Japanese rules.

Personal names are the hardest common case: there is no word boundary to anchor
on, and the same characters are a surname in one sentence and a place in the
next. Two complementary rules are used.

**Honorific-anchored.** ``田中さん`` / ``佐藤部長`` -- the suffix is strong
evidence and it sits exactly where the name ends. High precision, and it works
for surnames outside any dictionary.

**Dictionary-anchored.** A run starting with a known surname, optionally
followed by a given name. Catches ``田中太郎`` written with no honorific, at the
cost of missing every surname not in the list.

Neither rule recovers a name written with no honorific and an uncommon surname.
That gap is real and is what a local model is for; see the roadmap.
"""

from __future__ import annotations

from ....domain import entity_types as t
from ....domain.confidence import HIGH, LOW, MEDIUM
from ....domain.script import Script
from ....domain.stance import RuleTier
from ..patterns import PatternRule, compile_rule
from .base import LocalePack

__all__ = ["COMMON_SURNAMES", "JAPANESE", "WIDE_RULES", "my_number_valid"]


def my_number_valid(value: str) -> bool:
    """Check digit of a Japanese Individual Number (個人番号).

    Without this, the rule would be ``\\d{12}`` and would match every order
    number and timestamp in the corpus.
    """
    digits = [int(c) for c in value if c.isdigit()]
    if len(digits) != 12:
        return False
    body, check = digits[:11], digits[11]
    total = 0
    for position in range(1, 12):
        weight = position + 1 if position <= 6 else position - 5
        total += body[11 - position] * weight
    remainder = total % 11
    expected = 0 if remainder <= 1 else 11 - remainder
    return check == expected


# fmt: off
#: The most common Japanese surnames. Not exhaustive by design -- adding rarer
#: surnames raises recall but each one is a new source of false positives on
#: place names and ordinary nouns.
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

#: Words that look like a name in front of an honorific but are not one.
_HONORIFIC_STOPWORDS = frozenset({
    "お客", "客", "皆", "神", "王", "貴", "殿", "各", "他", "当", "御",
    "社長", "部長", "課長", "先生", "皆様", "何", "誰",
})

_HONORIFICS = (
    "さん", "様", "さま", "氏", "君", "くん", "ちゃん", "先生", "殿",
    "部長", "課長", "社長", "専務", "常務", "取締役", "主任", "係長", "次長", "室長",
)

#: Ordinary words that begin with a surname character. 森林 is 森 plus 林, both
#: surnames, and neither is a person here. The list covers the common
#: collisions; it will never cover all of them, which is why the
#: dictionary-anchored rule is only MEDIUM confidence.
_NOT_NAMES = frozenset({
    "森林", "森閑", "林業", "林道", "林立", "林檎",
    "原因", "原則", "原理", "原料", "原点", "原案", "原稿", "原油", "原文",
    "原価", "原本", "原産", "原子", "原作",
    "田舎", "田畑", "石油", "石材", "石炭", "石鹸", "石段",
    "金額", "金融", "金曜", "金庫", "金属",
})

#: Suffixes that turn a surname-looking run into an organisation or a place.
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


def _plausible_name(value: str) -> bool:
    """Reject runs that start with a surname but are not names."""
    candidate = value.strip()
    if candidate in _NOT_NAMES:
        return False
    return not candidate.endswith(_NOT_A_NAME_AFTER)


# The character class is "tempered": it excludes the most common particles,
# because a greedy run of kana would otherwise swallow the rest of the sentence
# -- 株式会社さくら商事の田中さん would come out as one company name ending in
# の田中. The cost is that a company whose name genuinely contains の
# (株式会社さくらの森) is truncated. Under-capturing a company name is
# recoverable; over-capturing hides an unrelated person from every other rule.
# Tempered on particles *and* on the multi-character ones. Single characters
# alone are not enough: excluding か would break さくら, but excluding the
# sequence から stops 有限会社みどりから見積 at みどり while leaving さくら
# intact. Where the two conflict, over-capturing wins -- a company name that
# runs a few characters long is still fully replaced, while one cut short leaks
# its tail.
_COMPANY_STOP = r"の|は|が|を|に|へ|と|で|も|や|から|より|まで|および|ならびに"
_COMPANY_BODY = r"(?:(?!" + _COMPANY_STOP + r")[一-鿿぀-ゟ゠-ヿーA-Za-z0-9]){1,16}"

RULES: tuple[PatternRule, ...] = (
    # Requires separators or a mobile prefix. A bare run of ten digits is far
    # more often an order number than a phone number.
    compile_rule(
        t.PHONE,
        r"(?:0[789]0[\-\s]?\d{4}[\-\s]?\d{4}|0\d{1,3}[\-\s]\d{1,4}[\-\s]\d{4})",
        HIGH,
    ),
    # Anchored on 〒 on purpose: NNN-NNNN also matches product codes and dates.
    compile_rule(t.POSTAL_CODE, r"〒\s*(\d{3}[\-−ー]\d{4})", HIGH, group=1),
    # Prefecture through street number. Deliberately conservative: it misses
    # addresses written without a prefecture.
    compile_rule(
        t.ADDRESS,
        r"(?:東京都|北海道|(?:京都|大阪)府|[一-鿿]{2,3}県)"
        r"[一-鿿぀-ゟ゠-ヿ]{1,12}?[市区町村]"
        # The locality name excludes digits so the block-number group below can
        # take them. Letting it swallow digits truncates 千代田1-1 to 千代田1,
        # which reads as a complete address and silently leaks the rest.
        r"[一-鿿぀-ゟ゠-ヿ]{0,16}"
        r"(?:\d+(?:[\-−ー]\d+)*(?:丁目|番地|号|番)?)*",
        MEDIUM,
    ),
    compile_rule(
        t.DATE_OF_BIRTH,
        r"(?:生年月日|誕生日)\s*[:：]?\s*"
        r"(\d{4}\s*[/\-年]\s*\d{1,2}\s*[/\-月]\s*\d{1,2}(?:\s*日)?)",
        HIGH,
        group=1,
    ),
    compile_rule(t.MY_NUMBER, r"(?<!\d)\d{12}(?!\d)", HIGH, validator=my_number_valid),
    compile_rule(
        t.COMPANY_NAME,
        r"(?:(?:株式|有限|合同|合名|合資)会社"
        + _COMPANY_BODY
        + r"|"
        + _COMPANY_BODY
        + r"(?:株式|有限|合同|合名|合資)会社)",
        HIGH,
    ),
    # 社員番号は入社時にA-44881を付与予定です -- the label, a clause, then the
    # value. Exactly the Chinese 工号预留为 fix from 0.15, in the other
    # language, found the same way and missed thirty times in a thousand
    # documents. The gap is capped and may not contain punctuation, so the
    # label cannot reach across a sentence into an unrelated number.
    compile_rule(
        t.EMPLOYEE_ID,
        r"(?:社員番号|従業員番号|社員ID)\s*(?:は|が)?\s*"
        r"(?:[ぁ-んァ-ヶ一-鿿]{0,6})?\s*[:：]?\s*([A-Za-z0-9\-]{3,24})",
        HIGH,
        group=1,
    ),
    compile_rule(
        t.PROJECT_NAME,
        r"プロジェクト(?:名|コード)?\s*[:：]\s*([^\s,;。、]{2,40})",
        LOW,
        group=1,
    ),
    # プロジェクトあおぞら -- the word "project" is the anchor whether or not a
    # colon follows it, and in a heading it usually does not.
    #
    # The particles are excluded from the name's own characters, not only from
    # its first one. Until 0.17 the guard was on the first character only and
    # the body ran to the next space or punctuation, so プロジェクト鶴の残作業は?
    # produced a codename called 鶴の残作業は? -- the whole question. Two costs,
    # and the second is the worse one: the sentence disappears, and the same
    # project in two sentences gets two different placeholders because the two
    # spans differ, so the model cannot tell they are the same project and a
    # quotation restores to a different string than the passage it came from.
    #
    # One character is enough after an anchor this strong: プロジェクト鶴 is a
    # codename, and requiring two lost it entirely once the particles stopped
    # padding the match out.
    compile_rule(
        t.PROJECT_NAME,
        r"プロジェクト(?![名コード])(?![のはがをにでとやへも、。])"
        r"([^\s,;。、:：？?！!のはがをにでとやへも]{1,20})",
        LOW,
        group=1,
    ),
    # 田中さん, 佐藤 花子様, 西村さくら様. The honorific is matched by lookahead
    # so it stays in the output: <PERSON_001>さん reads far better to a model
    # than a bare token.
    #
    # The hiragana tail was added in 0.17. さくら, ゆき, あおい and ひかり are
    # ordinary given names and every rule here wanted Han or katakana, so
    # 西村さくら様 was invisible while 西村花子様 was found -- a gap nobody
    # would have predicted from reading the rules, and one a corpus of Han-only
    # given names could not show.
    #
    # It is offered here and at the label rule below, and nowhere else. After a
    # bare surname a hiragana run is a particle far more often than a name --
    # 田中はよく… -- so this needs the honorific as evidence. The engine
    # backtracks out of the tail when it would swallow the honorific itself, so
    # 田中さん is still 田中.
    compile_rule(
        t.PERSON,
        r"(?<![一-鿿])([一-鿿]{1,4}(?:[ 　][一-鿿]{1,4})?(?:[ 　]?[ぁ-ん]{2,4})?)"
        r"(?=" + _HONORIFIC_ALT + r")",
        HIGH,
        group=1,
        validator=_not_stopword,
    ),
    # 田中太郎, 田中. Rejected when followed by an organisation or place suffix,
    # so 田中商事 is left for the company rule.
    compile_rule(
        t.PERSON,
        r"(?<![一-鿿])(?:" + _SURNAME_ALT + r")"
        r"(?!" + _NOT_NAME_ALT + r")"
        # The given name may not run into an honorific, and the match may end
        # where one begins. Without both halves, 佐藤花子様 comes back as a
        # four-character name ending in 様, and the model is asked to write to
        # somebody called "Hanako-sama-san".
        r"(?:[ 　]?(?:(?!" + _HONORIFIC_ALT + r")[一-鿿]){1,3})?"
        r"(?=" + _HONORIFIC_ALT + r"|[^一-鿿]|$)",
        MEDIUM,
        validator=_plausible_name,
    ),
    # ジョン・スミス -- a katakana full name joined by a middle dot. The dot is
    # a Japanese convention for foreign personal names specifically, which
    # makes it evidence rather than shape.
    compile_rule(t.PERSON, r"[ァ-ヶー]{2,10}・[ァ-ヶー]{2,10}", MEDIUM),
    # ジョンさん, マイケル様. An honorific is the same evidence an honorific
    # always is, and until 0.9 no rule applied it to katakana at all -- so
    # ジョンさん was missed while ホスト and プール were reported as people.
    compile_rule(
        t.PERSON,
        r"(?<![ァ-ヶー])[ァ-ヶ][ァ-ヶー・]{1,14}(?=" + _HONORIFIC_ALT + r")",
        MEDIUM,
    ),
    # 氏名: マイケル, 担当: ジョン. A label is evidence too.
    compile_rule(
        t.PERSON,
        r"(?:氏名|名前|担当者?|宛先|差出人|報告者)\s*[:：]\s*"
        r"([ァ-ヶ][ァ-ヶー・]{1,14})",
        MEDIUM,
        group=1,
    ),
    # 差出人: 横山, 報告者: 清水. The same label, a Han name. Added in 0.13
    # after `ja-doc-006` leaked one twice: the label rule reached katakana and
    # stopped there, which is the sort of gap that only shows up in a document
    # with a header block in it.
    compile_rule(
        t.PERSON,
        r"(?:氏名|名前|担当者?|宛先|差出人|報告者|申請者|作成者)\s*[:：]\s*"
        r"([一-鿿]{1,4}(?:[ 　][一-鿿]{1,4})?(?:[ 　]?[ぁ-ん]{2,4})?)",
        MEDIUM,
        group=1,
    ),
    # お客様番号, 会員番号. The employee-id rule had the internal labels and
    # not the customer-facing ones, so `ja-doc-006` leaked that too.
    compile_rule(
        t.EMPLOYEE_ID,
        r"(?:お客様番号|顧客番号|会員番号|受付番号|整理番号)\s*(?:は|が)?\s*[:：]?\s*"
        r"([A-Za-z0-9\-]{3,24})",
        HIGH,
        group=1,
    ),
)

# --- Wide tier ------------------------------------------------------------

WIDE_RULES: tuple[PatternRule, ...] = (
    # A bare run of katakana used to be here, filtered by a stoplist of
    # loanwords. It was removed in 0.9 after the document set measured it: 37
    # false positives across eight documents -- ホスト, プール, ゲートウェイ,
    # ノード, エンジニア -- and not one true positive that the anchored rules
    # above did not already have.
    #
    # The stoplist could not have been fixed by adding words. Japanese business
    # writing borrows freely and coins new loanwords constantly, so any such
    # list encodes one author's vocabulary and is wrong for the next document.
    # A bare katakana run is not weak evidence of a name; it is no evidence of
    # one, and the wide tier is for weak evidence rather than for none.
    #
    # What replaced it is anchored: a middle dot, an honorific, or a label.
    # A digit run starting 0, unseparated. Order numbers look the same; the
    # core rule refuses them for that reason.
    compile_rule(
        t.PHONE,
        r"(?<![\d\-])0\d{9,10}(?![\d\-])",
        LOW,
        tier=RuleTier.WIDE,
    ),
    # Any surname-initial run, without the organisation and place guards the
    # core rule applies. Catches 田中商事 as a person, which is wrong, and
    # catches a name in front of a word the guard list happens to contain,
    # which is the point.
    compile_rule(
        t.PERSON,
        r"(?<![一-鿿])(?:" + _SURNAME_ALT + r")[一-鿿]{1,3}(?![一-鿿])",
        LOW,
        tier=RuleTier.WIDE,
    ),
    # NNN-NNNN without the 〒 marker.
    compile_rule(
        t.POSTAL_CODE,
        r"(?<![\d\-])\d{3}[\-−ー]\d{4}(?![\d\-])",
        LOW,
        tier=RuleTier.WIDE,
    ),
)

JAPANESE = LocalePack(
    code="ja",
    name="Japanese",
    rules=RULES + WIDE_RULES,
    # Kana are decisive. Han alone could be either Japanese or Chinese, so the
    # Japanese pack runs on it too and over-detects rather than missing.
    triggers=frozenset({Script.KANA, Script.HAN}),
)
