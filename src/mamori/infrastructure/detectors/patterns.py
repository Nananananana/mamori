"""Regular-expression rules.

These carry most of the practical value of the library. They are fast, they are
deterministic, and unlike a model they cannot be talked out of a detection by
the text they are scanning.

They are also, unavoidably, incomplete. Every rule here is a recall/precision
trade-off made on purpose, and each one is annotated with the trade-off it
makes. Read ``docs/threat-model.md`` before assuming a category is covered.

All patterns run against NFKC-normalized text, so a rule written in ASCII also
matches its full-width form.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable
from dataclasses import dataclass

from ...domain import entity_types as t
from ...domain.confidence import CERTAIN, HIGH, LOW, MEDIUM, Confidence
from ...domain.entity_types import EntityType

__all__ = ["DEFAULT_RULES", "PatternRule", "luhn_valid", "my_number_valid"]


@dataclass(frozen=True, slots=True)
class PatternRule:
    """One regex-backed detection rule.

    Args:
        entity_type: What a match means.
        pattern: Compiled pattern.
        confidence: How much to trust a match.
        group: Which group delimits the value. Use a group when the pattern
            needs surrounding context to fire but the context itself is not
            sensitive -- ``password: hunter2`` should redact ``hunter2``, not
            the word ``password``.
        validator: Optional check applied to the matched text. Used for
            checksummed identifiers, where a checksum turns a hopelessly
            false-positive-prone digit run into a reliable signal.
    """

    entity_type: EntityType
    pattern: re.Pattern[str]
    confidence: Confidence = HIGH
    group: int = 0
    validator: Callable[[str], bool] | None = None


def luhn_valid(value: str) -> bool:
    """Luhn checksum, used to keep 16-digit runs from flooding the results."""
    digits = [int(c) for c in value if c.isdigit()]
    if len(digits) < 13:
        return False
    total = 0
    for position, digit in enumerate(reversed(digits)):
        if position % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def my_number_valid(value: str) -> bool:
    """Check digit of a Japanese Individual Number (マイナンバー).

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


def _private_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


_R = re.compile

# --- Contact details -------------------------------------------------------

_EMAIL = PatternRule(
    t.EMAIL,
    _R(
        r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}"
    ),
    CERTAIN,
)

# Requires separators or a mobile prefix. A bare run of ten digits is far more
# often an order number than a phone number, so it is left to the LLM detector.
_PHONE_JP = PatternRule(
    t.PHONE,
    _R(
        r"(?:\+81[\-\s]?\d{1,4}[\-\s]?\d{1,4}[\-\s]?\d{3,4}"
        r"|0[789]0[\-\s]?\d{4}[\-\s]?\d{4}"
        r"|0\d{1,3}[\-\s]\d{1,4}[\-\s]\d{4})"
    ),
    HIGH,
)

# Anchored on 〒 on purpose: NNN-NNNN also matches product codes and dates.
_POSTAL_JP = PatternRule(
    t.POSTAL_CODE,
    _R(r"〒\s*(\d{3}[\-−ー]\d{4})"),
    HIGH,
    group=1,
)

# Prefecture through street number. Deliberately conservative: it will miss
# addresses written without a prefecture.
_ADDRESS_JP = PatternRule(
    t.ADDRESS,
    _R(
        r"(?:東京都|北海道|(?:京都|大阪)府|[一-鿿]{2,3}県)"
        r"[一-鿿぀-ゟ゠-ヿ]{1,12}?[市区町村]"
        r"[一-鿿぀-ゟ゠-ヿ0-9]{0,16}"
        r"(?:\d+(?:[\-−ー]\d+)*(?:号|番地|番)?)?"
    ),
    MEDIUM,
)

_DOB = PatternRule(
    t.DATE_OF_BIRTH,
    _R(
        r"(?:生年月日|誕生日|birth\s?date|date\s?of\s?birth)\s*[:：]?\s*"
        r"(\d{4}\s*[/\-年]\s*\d{1,2}\s*[/\-月]\s*\d{1,2}\s*日?)"
    ),
    HIGH,
    group=1,
)

# --- Checksummed identifiers ----------------------------------------------

_CREDIT_CARD = PatternRule(
    t.CREDIT_CARD,
    _R(r"(?<![\d\-])(?:\d{4}[\-\s]?){3}\d{1,4}(?![\d\-])"),
    CERTAIN,
    validator=luhn_valid,
)

_MY_NUMBER = PatternRule(
    t.MY_NUMBER,
    _R(r"(?<!\d)\d{12}(?!\d)"),
    CERTAIN,
    validator=my_number_valid,
)

# --- Credentials -----------------------------------------------------------
# Vendor-prefixed keys are unambiguous, so they get CERTAIN and, under the
# default policy, stop the request outright.

_CREDENTIAL_RULES = [
    PatternRule(t.API_KEY, _R(r"sk-ant-[A-Za-z0-9_\-]{16,}"), CERTAIN),
    PatternRule(t.API_KEY, _R(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}"), CERTAIN),
    PatternRule(t.API_KEY, _R(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])"), CERTAIN),
    PatternRule(t.API_KEY, _R(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{35}(?![A-Za-z0-9])"), CERTAIN),
    PatternRule(t.ACCESS_TOKEN, _R(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{36,255}"), CERTAIN),
    PatternRule(t.ACCESS_TOKEN, _R(r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{22,255}"), CERTAIN),
    PatternRule(t.ACCESS_TOKEN, _R(r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9\-]{10,}"), CERTAIN),
    PatternRule(
        t.ACCESS_TOKEN,
        _R(r"(?<![A-Za-z0-9])eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
        HIGH,
    ),
    PatternRule(
        t.PRIVATE_KEY,
        _R(
            r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----"
            r"[\s\S]{0,20000}?-----END (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----"
        ),
        CERTAIN,
    ),
    PatternRule(
        t.DATABASE_URL,
        _R(
            r"(?<![A-Za-z0-9])(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|mssql)://[^\s\"'<>]+"
        ),
        CERTAIN,
    ),
    # Assignment form. The value is the group; the keyword is context.
    PatternRule(
        t.PASSWORD,
        _R(
            r"(?i)(?:password|passwd|pwd|パスワード|secret|api[_\-]?key|token)"
            r"\s*[:=]\s*[\"']?([^\s\"'<>,;]{4,200})"
        ),
        MEDIUM,
        group=1,
    ),
]

# --- Internal infrastructure ----------------------------------------------

_INTERNAL_URL = PatternRule(
    t.INTERNAL_URL,
    _R(
        r"https?://(?:localhost|127\.0\.0\.1|\[::1\]|[A-Za-z0-9\-]+"
        r"(?:\.[A-Za-z0-9\-]+)*\.(?:local|internal|intra|corp|lan|test))"
        r"(?::\d{1,5})?(?:/[^\s\"'<>]*)?"
    ),
    HIGH,
)

_INTERNAL_IP = PatternRule(
    t.INTERNAL_IP,
    _R(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"),
    HIGH,
    validator=_private_ip,
)

# --- Organisations ---------------------------------------------------------

# The character class is "tempered": it excludes the most common Japanese
# particles, because a greedy run of kana would otherwise swallow the rest of
# the sentence -- 株式会社さくら商事の田中さん would come out as one company
# name ending in の田中. The cost is that a company whose name genuinely
# contains の (株式会社さくらの森) is truncated. Under-capturing a company name
# is recoverable; over-capturing hides an unrelated person from every other
# rule.
_COMPANY_BODY = r"(?:(?![のはがをにへとでもや])[一-鿿぀-ゟ゠-ヿーA-Za-z0-9]){1,16}"

_COMPANY_JP = PatternRule(
    t.COMPANY_NAME,
    _R(
        r"(?:(?:株式|有限|合同|合名|合資)会社"
        + _COMPANY_BODY
        + r"|"
        + _COMPANY_BODY
        + r"(?:株式|有限|合同|合名|合資)会社)"
    ),
    HIGH,
)

_COMPANY_EN = PatternRule(
    t.COMPANY_NAME,
    _R(
        r"(?<![A-Za-z])[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3}\s*,?\s*(?:Inc|Corp|Ltd|LLC|GmbH|S\.A)\.?(?![A-Za-z])"
    ),
    MEDIUM,
)

_EMPLOYEE_ID = PatternRule(
    t.EMPLOYEE_ID,
    _R(
        r"(?i)(?:社員番号|従業員番号|社員ID|employee\s?(?:id|number))\s*[:：]?\s*([A-Za-z0-9\-]{3,24})"
    ),
    HIGH,
    group=1,
)

_PROJECT_CODE = PatternRule(
    t.PROJECT_NAME,
    _R(r"(?i)(?:プロジェクト(?:名|コード)?|project\s?(?:name|code))\s*[:：]\s*([^\s,;。、]{2,40})"),
    LOW,
    group=1,
)

DEFAULT_RULES: tuple[PatternRule, ...] = (
    _EMAIL,
    _PHONE_JP,
    _POSTAL_JP,
    _ADDRESS_JP,
    _DOB,
    _CREDIT_CARD,
    _MY_NUMBER,
    *_CREDENTIAL_RULES,
    _INTERNAL_URL,
    _INTERNAL_IP,
    _COMPANY_JP,
    _COMPANY_EN,
    _EMPLOYEE_ID,
    _PROJECT_CODE,
)
