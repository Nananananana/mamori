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
        name: How this rule is identified in a trace or an audit. Optional
            because naming a hundred rules by hand is a hundred chances to
            name one wrongly; :func:`identify` fills in a stable
            ``pack.TYPE.n`` when nothing was given, which is enough for
            "which rule fired" and "which rule has never fired once".
    """

    entity_type: EntityType
    pattern: re.Pattern[str]
    confidence: Confidence = HIGH
    group: int = 0
    validator: Callable[[str], bool] | None = None
    tier: RuleTier = RuleTier.CORE
    name: str = ""


def compile_rule(
    entity_type: EntityType,
    pattern: str,
    confidence: Confidence = HIGH,
    *,
    group: int = 0,
    validator: Callable[[str], bool] | None = None,
    tier: RuleTier = RuleTier.CORE,
    name: str = "",
) -> PatternRule:
    """Compile ``pattern`` into a rule. Convenience for the locale modules."""
    return PatternRule(
        entity_type=entity_type,
        pattern=re.compile(pattern),
        confidence=confidence,
        name=name,
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

#: The same address with the ``@`` held apart by spaces.
#:
#: ``jane.doe @ example.com`` is not a valid address and is a perfectly ordinary
#: way for one to appear in a document: a line wrapped, a word processor tidying
#: up, somebody spacing it out on purpose. A corpus of adversarially written
#: text found it as the only remaining leak class in English, at 22 documents in
#: 300.
#:
#: MEDIUM rather than CERTAIN, and both sides are required to be address-shaped
#: -- a local part with no spaces in it, a domain with a real suffix -- so that
#: "write to us @ the office" cannot match. One space each side at most: two
#: would let this reach across a line break into an unrelated word.
_SPACED_EMAIL = compile_rule(
    t.EMAIL,
    r"[A-Za-z0-9._%+\-]+[^\S\r\n]@[^\S\r\n][A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}",
    MEDIUM,
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

#: System accounts. A closed set of well-known names that are not people, which
#: is what makes this list defensible where a vocabulary list would not be:
#: nobody coins a new value for the Windows public profile. `runner` and
#: `vagrant` are here because CI logs and build output are full of them and a
#: build agent is not a person.
_NOT_A_USER = (
    "public",
    "default",
    "default user",
    "all users",
    "shared",
    "guest",
    "administrator",
    "admin",
    "root",
    "user",
    "users",
    "ubuntu",
    "ec2-user",
    "vagrant",
    "runner",
    "runneradmin",
    "jenkins",
    "docker",
    "www-data",
    "service",
    "svc",
    "test",
    "temp",
    "tmp",
)


def _is_a_person(value: str) -> bool:
    """Reject the accounts that ship with an operating system or a CI runner."""
    return value.strip().lower() not in _NOT_A_USER


#: The segment after a home root is the account's owner.
#:
#: `/home/p.doe/notes/`, `/Users/sato.hanako/`, `C:\Users\t.mercer\`. This is
#: not prose and no other rule was ever going to reach it, which is why it went
#: unnoticed until prompts started being *assembled*: a retrieval layer names
#: the file each passage came from, and a personal note lives under a personal
#: directory. In a corpus of three hundred rendered context packages this was
#: the single largest leak in Japanese, English and Chinese alike.
#:
#: Only the one segment is replaced. The rest of the path is provenance, the
#: consumer on the other side may be checking it, and a redaction that breaks
#: a checksum costs more than it saves.
#:
#: MEDIUM rather than HIGH: the shape is unambiguous but what it names is not
#: always a person -- a shared account, a role mailbox, a machine. The stoplist
#: takes the ones that are known, and the confidence says the rest out loud.
_HOME_DIRECTORY = compile_rule(
    t.PERSON,
    r"(?:(?<=[/\\])|(?<=^)|(?<=[\s\"\'(<]))"
    r"(?:[A-Za-z]:)?[/\\]?(?:home|Users|users|export[/\\]home)[/\\]"
    r"([A-Za-z0-9][A-Za-z0-9._\-]{1,31})"
    r"(?=[/\\])",
    MEDIUM,
    group=1,
    validator=_is_a_person,
)


# --- Structured payloads --------------------------------------------------
# A prose rule looks for a label in front of a value: `社員番号: A-1234`,
# `Employee ID: A-1234`. In JSON the label is the key, and until 0.18 nothing
# read one -- so a tool call carrying `{"employee_id": "B-12778"}` had the
# identifier sent in the clear while the same value in a sentence was caught.
# In four hundred generated agent turns this was the largest leak, and it is
# not a language problem: an API is written in English keys whatever language
# its values are in.

#: The value of a JSON string, escapes included, capped so that a key cannot
#: swallow a document. `(?:[^"\\]|\\.)` is the standard JSON string body:
#: anything but a quote or a backslash, or a backslash and whatever follows it.
_JSON_VALUE = r'"((?:[^"\\]|\\.){1,200})"'


def _json_key_rule(entity_type: EntityType, *keys: str) -> PatternRule:
    """A rule that reads one family of key names.

    Keys are matched case-insensitively and in the three shapes an API
    actually uses -- ``employee_id``, ``employeeId``, ``employee-id`` -- by
    ignoring the separators rather than listing every spelling.
    """
    alternatives = "|".join(key.replace("_", "[_\\-]?") for key in keys)
    return compile_rule(
        entity_type,
        r'(?i)"(?:' + alternatives + r')"\s*:\s*' + _JSON_VALUE,
        HIGH,
        group=1,
    )


#: Key names whose value is the thing the key says it is.
#:
#: Deliberately not here: a bare ``name``. In JSON it is a tool name, a model
#: name, a field name and a property name far more often than a person, and
#: redacting the name of the function an agent is calling breaks the call. The
#: keys below have one meaning each.
_STRUCTURED_KEYS: tuple[PatternRule, ...] = (
    _json_key_rule(
        t.EMPLOYEE_ID,
        "employee_id",
        "employee_no",
        "employee_number",
        "staff_id",
        "member_id",
        "社員番号",
        "社員ID",
        "工号",
        "员工编号",
    ),
    _json_key_rule(
        t.POSTAL_CODE,
        "postal_code",
        "postcode",
        "zip",
        "zip_code",
        "郵便番号",
        "邮编",
    ),
    _json_key_rule(
        t.PHONE,
        "phone",
        "phone_number",
        "telephone",
        "tel",
        "mobile",
        "mobile_number",
        "電話番号",
        "电话",
    ),
    _json_key_rule(
        t.ADDRESS,
        "address",
        "street_address",
        "postal_address",
        "住所",
        "地址",
    ),
    _json_key_rule(
        t.PERSON,
        "customer",
        "customer_name",
        "full_name",
        "contact_name",
        "recipient",
        "attendee",
        "applicant",
        "氏名",
        "姓名",
        "担当者",
    ),
    # A name split across two keys. Each half on its own is a word -- `Jane`,
    # `Doe`, `太郎` -- and no prose rule was ever going to reach it, because
    # there is no prose: the structure is carrying the meaning that a
    # salutation would carry in a sentence. Both halves are replaced
    # separately and restore separately, which is correct: they are two
    # values in two fields, and reassembling them into one placeholder would
    # put a full name where the application expects a given name.
    _json_key_rule(
        t.PERSON,
        "first_name",
        "last_name",
        "given_name",
        "family_name",
        "surname",
        "forename",
        "middle_name",
        "名",
        "姓",
    ),
    _json_key_rule(
        t.COMPANY_NAME,
        "company",
        "company_name",
        "organisation",
        "organization",
        "会社名",
        "公司名称",
    ),
    _json_key_rule(
        t.DATE_OF_BIRTH,
        "dob",
        "date_of_birth",
        "birth_date",
        "birthday",
        "生年月日",
        "出生日期",
    ),
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
    # The three lookaheads are what make this "a mixed-case run with digits in
    # it" rather than "a long word", and until 0.17 they did not do that. They
    # were written `(?=[^A-Z]*[A-Z])`, which is satisfied by a capital letter
    # ANYWHERE LATER IN THE DOCUMENT: `[^A-Z]*` walks straight past the end of
    # the candidate. Every long lowercase run in a document containing a
    # capital somewhere qualified, which in practice is every document. Bounded
    # to the token's own alphabet, the requirement means what it says.
    #
    # The leading `/` is excluded for the same reason, from the other side: a
    # POSIX path is a long run of these characters, and `/srv/shared/notes/
    # customer-notes` was being reported as a credential. Found in a corpus of
    # assembled prompts, where a path is in the header of every passage.
    # A dot on the left as well as the rest: `github.com/owner/repo/blob/main/...`
    # is a URL, and its path is a long run of exactly these characters. Found by
    # pointing `mamori lint` at this repository's own documentation, which is
    # the sort of thing a linter is for.
    r"(?<![A-Za-z0-9+/=_.\-])(?=[A-Za-z0-9+/_\-]{32,})"
    r"(?=[A-Za-z0-9+/_\-]*[a-z])(?=[A-Za-z0-9+/_\-]*[A-Z])(?=[A-Za-z0-9+/_\-]*[0-9])"
    r"[A-Za-z0-9+_\-][A-Za-z0-9+/_\-]{31,}={0,2}(?![A-Za-z0-9+/=_\-])",
    LOW,
    tier=RuleTier.WIDE,
)

#: Any long digit run. Order numbers look the same, which is the point: under
#: the recall-first stance an order number becoming a placeholder is cheaper
#: than an unformatted account number leaving the machine.
#:
#: The guard rejects an adjacent letter as well as an adjacent digit. Without
#: that, `5b469054284c` -- a content hash, a commit, an item id -- contains a
#: nine-digit run and was reported as one, which redacts a checksum and leaves
#: the document it identifies unverifiable. Digits inside a longer alphanumeric
#: token are part of the token.
_WIDE_DIGIT_RUN = compile_rule(
    t.IDENTIFIER,
    r"(?<![\dA-Za-z\-])\d{8,20}(?![\dA-Za-z\-])",
    LOW,
    tier=RuleTier.WIDE,
)

#: Rules that hold whatever language the text is written in.
UNIVERSAL_RULES: tuple[PatternRule, ...] = (
    _EMAIL,
    _SPACED_EMAIL,
    _PHONE_E164,
    _CREDIT_CARD,
    *_CREDENTIAL_RULES,
    _INTERNAL_URL,
    _INTERNAL_IP,
    _HOME_DIRECTORY,
    *_STRUCTURED_KEYS,
    _WIDE_SECRET,
    _WIDE_DIGIT_RUN,
)


def identify(rules: Sequence[PatternRule], pack: str) -> dict[int, str]:
    """Give every rule in a pack a stable identifier.

    ``en.PERSON.2`` -- the pack, the type, and which rule of that type it is,
    counted in declaration order. Stable across runs and across unrelated
    edits, and it changes when somebody inserts a rule above it, which is the
    honest behaviour: the rule at that position genuinely is a different one.

    Keyed by ``id()`` so a rule object can be looked up without needing to be
    hashable or to carry its own position.
    """
    seen: dict[str, int] = {}
    named: dict[int, str] = {}
    for rule in rules:
        if rule.name:
            named[id(rule)] = rule.name
            continue
        type_name = rule.entity_type.name
        seen[type_name] = seen.get(type_name, 0) + 1
        named[id(rule)] = f"{pack}.{type_name}.{seen[type_name]}"
    return named
