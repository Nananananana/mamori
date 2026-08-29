"""Chinese rules.

Chinese and Japanese share Han characters, so these rules and the Japanese ones
would fire on each other's text. The pack declares itself suppressed by kana:
hiragana and katakana appear in Japanese and never in Chinese, so their presence
is proof that the Chinese rules would only add noise.

For text written purely in Han, with no kana to settle it, both packs run. That
over-detects, which is the safe direction: an extra placeholder costs answer
quality, a missed name costs the thing this library exists to prevent.

Simplified forms are used throughout. Traditional text still matches the rules
that do not depend on a character list -- identity numbers, phone numbers,
addresses -- and the surname list covers the forms that are written the same in
both.
"""

from __future__ import annotations

from ....domain import entity_types as t
from ....domain.confidence import HIGH, LOW, MEDIUM
from ....domain.script import Script
from ....domain.stance import RuleTier
from ..patterns import PatternRule, compile_rule
from .base import LocalePack

__all__ = ["CHINESE", "COMMON_SURNAMES", "WIDE_RULES", "resident_id_valid"]

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECKS = "10X98765432"


def resident_id_valid(value: str) -> bool:
    """ISO 7064 MOD 11-2 check character of a 居民身份证 number.

    An 18-character run of digits is common in logs and order systems. The check
    character is what makes this rule usable at all: without it the pattern
    would fire on almost every long numeric identifier in a document.
    """
    body = value.strip().upper()
    if len(body) != 18 or not body[:17].isdigit():
        return False
    total = sum(int(digit) * weight for digit, weight in zip(body[:17], _ID_WEIGHTS, strict=True))
    return body[17] == _ID_CHECKS[total % 11]


# fmt: off
#: Common Chinese surnames, single-character. Ordered by frequency; not
#: exhaustive, because every rarer surname added is a new false positive on an
#: ordinary word.
COMMON_SURNAMES: tuple[str, ...] = (
    "王", "李", "张", "刘", "陈", "杨", "黄", "赵", "吴", "周",
    "徐", "孙", "马", "朱", "胡", "郭", "何", "高", "林", "罗",
    "郑", "梁", "谢", "宋", "唐", "许", "韩", "冯", "邓", "曹",
    "彭", "曾", "肖", "田", "董", "袁", "潘", "于", "蒋", "蔡",
    "余", "杜", "叶", "程", "苏", "魏", "吕", "丁", "任", "沈",
    "姚", "卢", "姜", "崔", "钟", "谭", "陆", "汪", "范", "金",
    "石", "廖", "贾", "夏", "韦", "付", "方", "邹", "孟", "熊",
    "秦", "邱", "江", "尹", "薛", "段", "雷", "侯", "龙", "史",
    "陶", "黎", "贺", "顾", "毛", "郝", "龚", "邵", "万", "钱",
    "严", "覃", "武", "戴", "莫", "孔", "向", "汤",
)

#: Two-character surnames. Listed separately so they are matched before their
#: first character is taken for a single-character surname.
COMPOUND_SURNAMES: tuple[str, ...] = (
    "欧阳", "司马", "诸葛", "上官", "司徒", "独孤", "慕容", "令狐", "皇甫",
    "尉迟", "长孙", "宇文", "夏侯", "东方", "澹台",
)

_HONORIFICS = (
    "先生", "女士", "小姐", "老师", "同学", "经理", "总监", "主任",
    "医生", "教授", "博士", "律师", "工程师", "部长", "科长", "总裁", "董事长",
)

#: Two-character words that begin with a surname character. Chinese has no
#: word boundary, so the dictionary rule cannot tell 张伟 (a name) from 高兴
#: (happy) by shape alone. This list covers the common collisions; it will
#: never cover all of them, which is why that rule is LOW confidence.
_NOT_NAMES = frozenset({
    "高兴", "方便", "于是", "万一", "万分", "白天", "白色", "江湖", "石头",
    "毛病", "马上", "马路", "金额", "金融", "严重", "严格", "武器", "向上",
    "向下", "任何", "任务", "程度", "叶子", "余额", "田地", "董事", "段落",
    "史上", "夏天", "常见", "汤圆", "龙头", "孔子", "熊猫", "钱包", "钟点",
    "陆续", "范围", "方案", "方式", "方向", "方法", "方面", "史料", "石油",
    "黄色", "毛巾", "叶片", "谢谢", "宋代", "唐代", "秦代", "汉代",
})

#: Suffixes that make a surname-looking run an organisation or a place.
_NOT_A_NAME_AFTER = (
    "公司", "集团", "银行", "大学", "医院", "工厂", "商行", "有限",
    "省", "市", "区", "县", "镇", "村", "路", "街", "站", "山", "江", "河",
)
# fmt: on

_HONORIFIC_ALT = "|".join(_HONORIFICS)
_NOT_NAME_ALT = "|".join(_NOT_A_NAME_AFTER)
_SURNAME_ALT = "|".join((*COMPOUND_SURNAMES, *COMMON_SURNAMES))


def _plausible_name(value: str) -> bool:
    """Reject runs that start with a surname but are not names.

    The lookahead in the rule only inspects the character straight after the
    surname, so it catches 王氏 but not 江苏省, where the giveaway sits two
    characters later. Checking the whole match covers both.
    """
    candidate = value.strip()
    if candidate in _NOT_NAMES:
        return False
    return not candidate.endswith(_NOT_A_NAME_AFTER)


# Tempered like the Japanese company rule, for the same reason: a greedy run of
# Han characters has no word boundary to stop it and would swallow the rest of
# the sentence. 的 and 和 are the particles that matter most here.
_COMPANY_BODY = r"(?:(?![的和与及或在这那是给从到由向对把被让])[一-鿿A-Za-z0-9]){2,20}"

RULES: tuple[PatternRule, ...] = (
    # Mainland mobile numbers are unambiguous: 11 digits starting 1[3-9].
    compile_rule(t.PHONE, r"(?<!\d)1[3-9]\d{9}(?!\d)", HIGH),
    # Landlines need the separator, as everywhere else.
    compile_rule(t.PHONE, r"(?<![\d\-])0\d{2,3}[\-\s]\d{7,8}(?![\d\-])", HIGH),
    compile_rule(
        t.RESIDENT_ID,
        r"(?<![0-9A-Za-z])\d{17}[0-9Xx](?![0-9A-Za-z])",
        HIGH,
        validator=resident_id_valid,
    ),
    # Six bare digits are a part number as often as a postcode, so a label is
    # required.
    compile_rule(t.POSTAL_CODE, r"邮[编政编码]{1,2}\s*[:：]?\s*(\d{6})(?!\d)", HIGH, group=1),
    compile_rule(
        t.DATE_OF_BIRTH,
        r"(?:出生(?:日期|年月)?|生日)\s*[:：]?\s*"
        r"(\d{4}\s*[/\-年]\s*\d{1,2}\s*[/\-月]\s*\d{1,2}\s*日?)",
        HIGH,
        group=1,
    ),
    # Province or municipality through street number.
    compile_rule(
        t.ADDRESS,
        r"(?:北京|上海|天津|重庆|香港|澳门|[一-鿿]{2,3}(?:省|自治区))?"
        r"[一-鿿]{2,8}?(?:市|自治州)[一-鿿]{2,8}?(?:区|县|镇)"
        r"[一-鿿0-9]{0,20}?(?:路|街|道|巷|号|弄)[0-9一-鿿]{0,12}",
        MEDIUM,
    ),
    compile_rule(
        t.COMPANY_NAME,
        _COMPANY_BODY + r"(?:股份有限公司|有限责任公司|有限公司|集团有限公司|集团|公司)",
        HIGH,
    ),
    compile_rule(
        t.EMPLOYEE_ID,
        r"(?:员工(?:编号|号|工号)?|工号|职工编号)\s*[:：]?\s*([A-Za-z0-9\-]{3,24})",
        HIGH,
        group=1,
    ),
    compile_rule(
        t.PROJECT_NAME,
        r"(?:项目(?:名称|代号|编号)?)\s*[:：]\s*([^\s,;。、]{2,40})",
        LOW,
        group=1,
    ),
    # 张先生, 李明经理. Anchored on a known surname rather than on a preceding
    # boundary, because Chinese has none: 请联系李明经理 offers nothing to
    # anchor the left edge of the name to except the surname itself. The
    # honorific is matched by lookahead so it stays in the output.
    compile_rule(
        t.PERSON,
        r"(?:" + _SURNAME_ALT + r")[一-鿿]{0,2}(?=" + _HONORIFIC_ALT + r")",
        HIGH,
    ),
    # 张伟, 欧阳修. Surname plus a one or two character given name, rejected
    # when what follows makes it an organisation or a place, and when the whole
    # run is a common word. LOW confidence: this is the least precise rule in
    # the library, and deliberately so -- a spurious placeholder costs answer
    # quality, a missed name costs what the library exists to prevent.
    compile_rule(
        t.PERSON,
        r"(?:" + _SURNAME_ALT + r")"
        r"(?!" + _NOT_NAME_ALT + r")"
        r"[一-鿿]{1,2}(?![一-鿿])",
        LOW,
        validator=_plausible_name,
    ),
)

# --- Wide tier ------------------------------------------------------------

WIDE_RULES: tuple[PatternRule, ...] = (
    # The surname rule without the ordinary-word stoplist. 高兴 comes back as a
    # person, and so does the name the stoplist would have swallowed.
    compile_rule(
        t.PERSON,
        r"(?:" + _SURNAME_ALT + r")[一-鿿]{1,2}(?![一-鿿])",
        LOW,
        tier=RuleTier.WIDE,
    ),
    # Six bare digits, no 邮编 label.
    compile_rule(
        t.POSTAL_CODE,
        r"(?<!\d)\d{6}(?!\d)",
        LOW,
        tier=RuleTier.WIDE,
    ),
)

CHINESE = LocalePack(
    code="zh",
    name="Chinese",
    rules=RULES + WIDE_RULES,
    triggers=frozenset({Script.HAN}),
    # Kana never appear in Chinese. Their presence settles the ambiguity that
    # Han characters alone leave open.
    suppressed_by=frozenset({Script.KANA}),
)
