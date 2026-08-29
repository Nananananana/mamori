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

#: The one word class that is not a name at any stance.
#:
#: Every two-character Chinese word can be read as a surname plus a given
#: character, so a stoplist always risks hiding somebody: 高兴 is "happy" and
#: it is also a perfectly ordinary name. That risk is why the wide tier drops
#: the stoplist below, and it stays dropped, with this one exception. 周 is a
#: common surname, 周一 through 周日 is a closed set nobody extends, and no
#: calendar day is anybody's name. Fifty-three spurious detections in a
#: thousand generated documents came from this word class alone.
_NEVER_A_NAME = frozenset({
    "周一", "周二", "周三", "周四", "周五", "周六", "周日", "周末",
})

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
    # Common words that a surname character starts, found the same way.
    "方提", "李子", "王朝", "陈述", "许可", "客服", "患者", "程序",
}) | _NEVER_A_NAME

#: Suffixes that make a surname-looking run an organisation or a place.
#:
#: 山, 江 and 河 were here until 0.15 and are not any more. They end places
#: (中山, 长江) but they also end given names -- 乐山, 建江, 小河 -- and a
#: thousand generated documents lost five names to them while the places they
#: were meant to stop were already covered by the organisation rules. The
#: administrative and street suffixes stay: nobody is called 建村 or 小路.
_NOT_A_NAME_AFTER = (
    "公司", "集团", "银行", "大学", "医院", "工厂", "商行", "有限",
    "省", "市", "区", "县", "镇", "村", "路", "街", "站",
)
# fmt: on

_HONORIFIC_ALT = "|".join(_HONORIFICS)
_NOT_NAME_ALT = "|".join(_NOT_A_NAME_AFTER)
_SURNAME_ALT = "|".join((*COMPOUND_SURNAMES, *COMMON_SURNAMES))


def _not_a_closed_set_word(value: str) -> bool:
    """The wide tier's only filter. See _NEVER_A_NAME for why it is this small."""
    return value not in _NEVER_A_NAME


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
#: A company name may not begin at a function character. The list is a
#: stoplist and is defensible where the katakana one was not: function
#: words are a closed set that nobody coins. Extended in 0.14 after a
#: thousand generated documents produced 甲方联系人为新程科技有限公司 as a
#: single company name -- 为 was missing, so the body ate the clause in
#: front of it. Same class as the English 'Where Umbrella Ltd' bug of 0.9.
_STOP = "的和与及或在这那是给从到由向对把被让为称系即作也都就还已请于至如若先后当该"
_COMPANY_BODY = r"(?:(?![" + _STOP + r"])[一-鿿A-Za-z0-9]){2,20}"

#: Characters that end a name rather than belong to it. A closed set of
#: function words, which is what makes it a defensible list where a vocabulary
#: list would not be -- nobody coins a new particle.
_ENDS_A_NAME = "的了是和与及或在这那给从到由向对把被让为称也都就还已请于至如若"

#: Surnames that are also prepositions. The relaxed right edge is not offered
#: after these, because a preposition is followed by a Han character in almost
#: every sentence it appears in and a surname is not.
_PREPOSITION_SURNAMES = "于向从由对与和"

#: What follows a surname.
#:
#: Chinese has no spaces, so the right edge of a name has to be guessed. Until
#: 0.15 the rules required a non-Han character after it, which is unambiguous
#: and wrong: a name is followed by a verb or a particle far more often than by
#: punctuation, so 张伟汇报了进度 and 李明的报告 matched nothing at all. A
#: thousand generated documents missed 104 names that way.
#:
#: The first alternative is the old behaviour and still preferred: one or two
#: characters ending where the Han run ends. The second applies when the name
#: runs into the next word -- one character, and a second only if it is not a
#: function word. 李明的 gives 李明, 王小明说 gives 王小明, and 张伟汇报 gives
#: 张伟汇, which is one character too many. Over-redaction rather than a leak
#: is the direction this library errs in.
_GIVEN_NAME = (
    r"(?:[一-鿿]{1,2}(?![一-鿿])"
    # Two guards, both on the relaxed alternative only -- the strict one never
    # needed either, because a Han character after the name was already enough
    # to reject it.
    #
    # It is not offered after a surname that is also a preposition. 于, 向,
    # 从, 由 and 对 are surnames and they are also the commonest words in
    # 关于上次, 指向旧地址, 向管委会汇报. What is given up is a 于-surnamed
    # name that runs into the next word; what is bought is that ordinary prose
    # stops reading as names.
    #
    # And it still refuses an organisation or a place: 王氏集团 is a company,
    # and without the second guard the surname plus one character reads it as
    # somebody called 王氏.
    r"|(?<![" + _PREPOSITION_SURNAMES + r"])"
    r"(?![" + _ENDS_A_NAME + r"])[一-鿿](?!" + _NOT_NAME_ALT + r"))"
)


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
    # The label does not always sit against its value: 工号预留为 A-1234
    # and 工号已定为 A-1234 both put a verb in between. Same shape as the
    # Japanese 社員番号は fix in 0.14, found the same way. The gap is
    # capped at four characters and may not contain punctuation or a line
    # break, so the label cannot reach across a clause into an unrelated
    # number.
    compile_rule(
        t.EMPLOYEE_ID,
        r"(?:员工(?:编号|号|工号)?|工号|职工编号)"
        r"(?:[一-鿿]{0,4})?\s*[:：]?\s*([A-Za-z0-9\-]{3,24})",
        HIGH,
        group=1,
    ),
    compile_rule(
        t.PROJECT_NAME,
        r"(?:项目(?:名称|代号|编号)?)\s*[:：]\s*([^\s,;。、]{2,40})",
        LOW,
        group=1,
    ),
    # 项目夜莺 -- the word "project" is the anchor with or without a colon, and
    # in a heading there usually is not one. Mirrors the Japanese rule added in
    # 0.9; `zh-doc-002` leaked a codename for two releases because only one of
    # the two languages got it.
    compile_rule(
        t.PROJECT_NAME,
        r"项目(?!名称|代号|编号)(?![的是在和与或])([^\s,;。、:：]{2,20})",
        LOW,
        group=1,
    ),
    # 客户编号, 会员号. The employee-id rule had the internal labels only.
    compile_rule(
        t.EMPLOYEE_ID,
        r"(?:客户编号|客户号|会员编号|会员号|受理号|流水号)\s*[:：]?\s*"
        r"([A-Za-z0-9\-]{3,24})",
        HIGH,
        group=1,
    ),
    # A "not preceded by a Han character" guard was tried here in 0.13, to stop
    # 里程碑 being read as a person called 程碑. It improved zh-core precision
    # from 0.903 to 0.933 and cost nothing measurable -- and it was reverted
    # anyway, because a probe outside the corpus showed 这是张伟。 and
    # 昨天和王强，我们谈过。 losing their names entirely. Chinese has no spaces,
    # so a name is usually preceded by a Han character, and the datasets happen
    # to place theirs after punctuation. Trading a visible false positive for
    # invisible misses is the wrong direction for this library.
    #
    # This is the case regular expressions cannot settle, and the reason the
    # optional morphological adapter is on the roadmap. zh-doc-005 and
    # zh-doc-006 exist so that the next attempt is measurable.
    # A 负责人：/收件人： label rule was written for 0.13 and measured out
    # again the same day. It changed neither the leak rate nor recall on
    # zh-docs -- the surname rule already reaches every name a label
    # introduces, because Chinese personal names begin with a character from a
    # closed set -- and it cost precision by reading 收件人：客服 as a person
    # called 客服, which is a department. A label is weaker evidence than a
    # surname dictionary here, which is the opposite of the Japanese case.
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
        r"(?!" + _NOT_NAME_ALT + r")" + _GIVEN_NAME,
        LOW,
        validator=_plausible_name,
    ),
)

# --- Wide tier ------------------------------------------------------------

WIDE_RULES: tuple[PatternRule, ...] = (
    # The surname rule without the ordinary-word stoplist. 高兴 comes back as a
    # person, and so does the name the stoplist would have swallowed.
    # The lookbehind is the fragment guard. 程 is a surname and 里程碑 is a
    # milestone, so without it the rule reports 程碑 -- the tail of a word,
    # which is never a name in any language. The wide tier accepts noise by
    # design (高兴 comes back as a person and that is the trade), but a match
    # starting in the middle of a word is a bug rather than a trade.
    compile_rule(
        t.PERSON,
        # The strict boundary stays here. The core rule below has a dictionary
        # and a stoplist behind it and can afford the relaxed right edge; this
        # one has neither, and relaxing it tripled over-redaction without
        # adding coverage the core rule did not already have.
        r"(?:" + _SURNAME_ALT + r")[一-鿿]{1,2}(?![一-鿿])",
        LOW,
        tier=RuleTier.WIDE,
        # Not the whole stoplist -- see _NEVER_A_NAME. This tier exists to
        # over-report, and 高兴 really could be somebody.
        validator=_not_a_closed_set_word,
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
