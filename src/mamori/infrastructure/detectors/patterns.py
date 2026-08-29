"""The rule type, shared validators, and the language-independent rules.

Anything whose format is the same everywhere lives here: email addresses, card
numbers, credentials, private addresses. Anything that depends on the language
of the text lives in :mod:`mamori.infrastructure.detectors.locales`.

These rules carry most of the practical value of the library. They are fast,
they are deterministic, and unlike a model they cannot be talked out of a
detection by the text they are scanning.

They are also, unavoidably, incomplete. Every rule is a recall/precision
trade-off made on purpose, and each carries a comment saying which way it
leans. Read ``docs/threat-model.md`` before assuming a category is covered.

All patterns run against NFKC-normalized text, so a rule written in ASCII also
matches its full-width form.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ...domain import entity_types as t
from ...domain.confidence import CERTAIN, HIGH, LOW, MEDIUM, Confidence
from ...domain.entity_types import EntityType
from ...domain.stance import RuleTier, Stance

__all__ = ["UNIVERSAL_RULES", "PatternRule", "compile_rule", "luhn_valid", "rules_for"]


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
    tier: RuleTier = RuleTier.CORE


def compile_rule(
    entity_type: EntityType,
    pattern: str,
    confidence: Confidence = HIGH,
    *,
    group: int = 0,
    validator: Callable[[str], bool] | None = None,
    tier: RuleTier = RuleTier.CORE,
) -> PatternRule:
    """Compile ``pattern`` into a rule. Convenience for the locale modules."""
    return PatternRule(
        entity_type=entity_type,
        pattern=re.compile(pattern),
        confidence=confidence,
        group=group,
        validator=validator,
        tier=tier,
    )


def rules_for(rules: Sequence[PatternRule], stance: Stance) -> tuple[PatternRule, ...]:
    """The subset of ``rules`` that runs under ``stance``."""
    return tuple(rule for rule in rules if stance.includes(rule.tier))


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


# A URL ends where URL-legal characters end. Matching "anything but
# whitespace" is fine in English and wrong everywhere else: it swallows the
# 「にあります。」 that follows the link in a Japanese sentence, and the
# over-captured text is then replaced along with the URL.
_URL_TAIL = r"[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]*"


def _private_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


# --- Contact details -------------------------------------------------------

_EMAIL = compile_rule(
    t.EMAIL,
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}",
    CERTAIN,
)

# E.164 with an explicit country code. Locale packs add their own national
# formats; this catches the internationalised form wherever it appears.
_PHONE_E164 = compile_rule(
    t.PHONE,
    r"\+\d{1,3}[\-\s]?\(?\d{1,4}\)?[\-\s]?\d{2,4}[\-\s]?\d{2,4}(?:[\-\s]?\d{2,4})?",
    MEDIUM,
)

# --- Checksummed identifiers ----------------------------------------------

_CREDIT_CARD = compile_rule(
    t.CREDIT_CARD,
    r"(?<![\d\-])(?:\d{4}[\-\s]?){3}\d{1,4}(?![\d\-])",
    CERTAIN,
    validator=luhn_valid,
)

# --- Credentials -----------------------------------------------------------
# Vendor-prefixed keys are unambiguous, so they get CERTAIN and, under the
# default policy, stop the request outright.


def _looks_like_a_secret(value: str) -> bool:
    """Whether a word after "the password is" is a credential or a sentence.

    "the password is hunter2spring" is a credential. "the password is short"
    and "my password is fine" are people talking *about* a password, and
    blocking those would stop a request over an ordinary sentence -- the most
    disruptive false positive this library can produce, because BLOCK does not
    degrade, it refuses.

    So a prose match needs some evidence of being a secret rather than a word:
    a digit, a capital, a symbol, or enough length that no plain word reaches
    it. A short all-lowercase password is missed by this, which is the right
    way round -- the `password: value` rule beside it has a separator to lean
    on and needs no such test.
    """
    if len(value) >= 12:
        return True
    return any(c.isdigit() or c.isupper() or not c.isalnum() for c in value)


_CREDENTIAL_RULES = (
    compile_rule(t.API_KEY, r"sk-ant-[A-Za-z0-9_\-]{16,}", CERTAIN),
    compile_rule(t.API_KEY, r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}", CERTAIN),
    compile_rule(t.API_KEY, r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])", CERTAIN),
    compile_rule(t.API_KEY, r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{35}(?![A-Za-z0-9])", CERTAIN),
    compile_rule(t.ACCESS_TOKEN, r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{36,255}", CERTAIN),
    compile_rule(t.ACCESS_TOKEN, r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{22,255}", CERTAIN),
    compile_rule(t.ACCESS_TOKEN, r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9\-]{10,}", CERTAIN),
    compile_rule(
        t.ACCESS_TOKEN,
        r"(?<![A-Za-z0-9])eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}",
        HIGH,
    ),
    compile_rule(
        t.PRIVATE_KEY,
        r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----"
        r"[\s\S]{0,20000}?-----END (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----",
        CERTAIN,
    ),
    compile_rule(
        t.DATABASE_URL,
        r"(?<![A-Za-z0-9])(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|mssql)"
        r"://" + _URL_TAIL,
        CERTAIN,
    ),
    # Assignment form. The value is the group; the keyword is context. The
    # keyword list is multilingual on purpose: a config file written by a
    # Japanese or Chinese team still says `password=` in code, and パスワード or
    # 密码 in the prose around it.
    compile_rule(
        t.PASSWORD,
        r"(?i)(?:password|passwd|pwd|secret|api[_\-]?key|token|パスワード|密码|密碼)"
        r"\s*[:=：]\s*[\"']?([^\s\"'<>,;]{4,200})",
        MEDIUM,
        group=1,
    ),
    # "the password is hunter2spring", パスワードは kaigi2026spring.
    # Prose, not configuration -- and the commoner of the two ways somebody
    # pastes a credential into a chat window. Written separately from the
    # `key: value` rule above because the separator is a word rather than a
    # colon, and because the value has to stop at a comma or a full stop
    # instead of running to the end of the sentence.
    compile_rule(
        t.PASSWORD,
        r"(?i)(?:password|passphrase|passcode)\s+(?:is|was|=)\s+"
        r"[\"']?([^\s\"'<>,;]{4,200}?)(?=[\s,.;:!?\"']|$)",
        MEDIUM,
        group=1,
        validator=_looks_like_a_secret,
    ),
    compile_rule(
        t.PASSWORD,
        r"(?:パスワード|暗証番号)\s*(?:は|が)\s*[\"'「]?([^\s\"'」、。<>,;]{4,200})",
        MEDIUM,
        group=1,
        validator=_looks_like_a_secret,
    ),
    compile_rule(
        t.PASSWORD,
        r"(?:密码|密碼)\s*(?:是|为|為)\s*[\"'「]?([^\s\"'」、。<>,;]{4,200})",
        MEDIUM,
        group=1,
        validator=_looks_like_a_secret,
    ),
)

# --- Internal infrastructure ----------------------------------------------


_INTERNAL_URL = compile_rule(
    t.INTERNAL_URL,
    r"https?://(?:localhost|127\.0\.0\.1|\[::1\]|[A-Za-z0-9\-]+"
    r"(?:\.[A-Za-z0-9\-]+)*\.(?:local|internal|intra|corp|lan|test))"
    r"(?::\d{1,5})?(?:/" + _URL_TAIL + r")?",
    HIGH,
)

_INTERNAL_IP = compile_rule(
    t.INTERNAL_IP,
    # The trailing guard rejects a dot only when a digit follows it, so that
    # "1.2.3.4.5" cannot match its first four parts while "on 10.0.4.31."
    # still does. Refusing every trailing dot -- which is what this rule did
    # until 0.9 -- loses every address that ends a sentence, which is most of
    # them in a document and none of them in a one-line sample.
    r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d)(?!\.\d)",
    HIGH,
    validator=_private_ip,
)

# --- Wide tier ------------------------------------------------------------
# Shape with no anchor. Each of these finds something no core rule can, and each
# also fires on ordinary text. They run only under the recall-first stance.

#: A long run of key-shaped characters. This is the documented gap in secret
#: detection -- a credential with no vendor prefix and no keyword next to it --
#: and it is a gap precisely because base64 payloads, hashes and content IDs
#: look identical. Requires a mix of cases and digits, which removes most prose.
_WIDE_SECRET = compile_rule(
    t.API_KEY,
    r"(?<![A-Za-z0-9+/=_\-])(?=[A-Za-z0-9+/_\-]{32,})"
    r"(?=[^a-z]*[a-z])(?=[^A-Z]*[A-Z])(?=[^0-9]*[0-9])"
    r"[A-Za-z0-9+/_\-]{32,}={0,2}(?![A-Za-z0-9+/=_\-])",
    LOW,
    tier=RuleTier.WIDE,
)

#: Any long digit run. Order numbers look the same, which is the point: under
#: the recall-first stance an order number becoming a placeholder is cheaper
#: than an unformatted account number leaving the machine.
_WIDE_DIGIT_RUN = compile_rule(
    t.IDENTIFIER,
    r"(?<![\d\-])\d{8,20}(?![\d\-])",
    LOW,
    tier=RuleTier.WIDE,
)

#: Rules that hold whatever language the text is written in.
UNIVERSAL_RULES: tuple[PatternRule, ...] = (
    _EMAIL,
    _PHONE_E164,
    _CREDIT_CARD,
    *_CREDENTIAL_RULES,
    _INTERNAL_URL,
    _INTERNAL_IP,
    _WIDE_SECRET,
    _WIDE_DIGIT_RUN,
)
