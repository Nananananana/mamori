"""English rules.

English personal names are, counter-intuitively, harder than Japanese ones. A
Japanese name carries its own evidence -- an honorific, or a surname written in
kanji that is rarely anything else. An English name is two capitalised words,
and so is every product, city, department and sentence opener. A rule that
matched capitalised bigrams would flag most of a business email.

So every name rule here is anchored on something that only precedes a name: a
title, a salutation, a sign-off, or an explicit label. Names that appear in the
middle of a sentence with no such marker are not detected, and no amount of
regex will change that -- it needs a model, which is what the deep-scan tier in
the roadmap is for.
"""

from __future__ import annotations

from ....domain import entity_types as t
from ....domain.confidence import HIGH, LOW, MEDIUM
from ....domain.script import Script
from ....domain.stance import RuleTier
from ..patterns import PatternRule, compile_rule
from .base import LocalePack

__all__ = ["ENGLISH", "WIDE_RULES", "ssn_valid"]

#: Areas that no Social Security Number uses. Cheap, and it removes most of the
#: dates and part numbers that share the NNN-NN-NNNN shape.
_INVALID_SSN_AREAS = frozenset({"000", "666"})


def ssn_valid(value: str) -> bool:
    """Structural validity of a US Social Security Number.

    There is no checksum, so this only rejects the ranges the SSA never issues:
    area 000, 666 and 900-999; group 00; serial 0000. It is a weak filter, which
    is why the rule also requires the hyphenated form -- nine bare digits are an
    order number far more often than an SSN.
    """
    digits = [c for c in value if c.isdigit()]
    if len(digits) != 9:
        return False
    area, group, serial = "".join(digits[:3]), "".join(digits[3:5]), "".join(digits[5:])
    if area in _INVALID_SSN_AREAS or area[0] == "9":
        return False
    return group != "00" and serial != "0000"


_TITLES = r"(?:Mr|Mrs|Ms|Miss|Dr|Prof|Sir|Madam)"
_NAME = r"[A-Z][a-z]+(?:['\-][A-Z]?[a-z]+)*"
#: Whitespace that is not a line break. A name is written on one line, and
#: joining name-words with ``\s+`` makes a heading and the first word of the
#: next paragraph into "Firstname Lastname" -- which never happens in a
#: 44-character sample and happens in every document with headings in it.
_GAP = r"[^\S\r\n]+"

#: Words a sentence starts with, spelled out here so the company rule can
#: refuse to begin at one. "Where Umbrella Ltd discloses..." is a company name
#: with an ordinary word stuck to the front of it, and because the wider span
#: wins overlap resolution the ordinary word gets redacted too. Invisible in a
#: one-line sample where the company name starts the sentence; unavoidable in
#: prose, where it usually does not.
_OPENER = (
    r"(?:The|A|An|This|That|These|Those|Our|Your|Their|Its|His|Her|We|I|You|"
    r"He|She|It|They|There|Here|Where|When|While|Whereas|If|Each|Any|All|Both|"
    r"Either|Neither|Please|Note|Where|Such|Said|Between|With|For|From|To|By|"
    r"Under|Upon|Subject|Notices|Charges|Payment|Confidentiality|Termination)"
)

_FULL_NAME = _NAME + r"(?:" + _GAP + _NAME + r"){0,2}"

_STREET_TYPES = (
    r"Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct"
    r"|Place|Pl|Terrace|Way|Parkway|Pkwy|Square|Sq"
)

RULES: tuple[PatternRule, ...] = (
    # North American numbering plan, and the common UK shapes. Separators or
    # parentheses are required: ten bare digits are usually not a phone number.
    compile_rule(
        t.PHONE,
        r"(?<![\d\-])(?:\(\d{3}\)\s?\d{3}[\-\s]\d{4}|\d{3}[\-.\s]\d{3}[\-.\s]\d{4})(?![\d\-])",
        HIGH,
    ),
    compile_rule(
        t.PHONE,
        r"(?<![\d\-])0\d{2,4}\s\d{3,4}\s\d{3,4}(?![\d\-])",
        MEDIUM,
    ),
    compile_rule(t.SSN, r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)", HIGH, validator=ssn_valid),
    compile_rule(
        t.SSN,
        r"(?i)(?:ssn|social\s+security(?:\s+number)?)\s*[:#]?\s*(\d{3}-?\d{2}-?\d{4})",
        HIGH,
        group=1,
        validator=ssn_valid,
    ),
    # ZIP+4 is unambiguous. A bare five-digit ZIP is not, so it needs a label.
    compile_rule(t.POSTAL_CODE, r"(?<!\d)\d{5}-\d{4}(?!\d)", HIGH),
    compile_rule(
        t.POSTAL_CODE,
        r"(?i)(?:zip(?:\s*code)?|postal\s*code|postcode)\s*[:#]?\s*"
        r"([A-Z0-9]{2,4}\s?[A-Z0-9]{3,4}|\d{5}(?:-\d{4})?)",
        HIGH,
        group=1,
    ),
    # UK postcode. Distinctive enough to stand on its own.
    compile_rule(
        t.POSTAL_CODE,
        r"(?<![A-Z0-9])[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}(?![A-Z0-9])",
        MEDIUM,
    ),
    compile_rule(
        t.DATE_OF_BIRTH,
        r"(?i)(?:date\s+of\s+birth|birth\s*date|born\s+on|d\.?o\.?b\.?)\s*[:]?\s*"
        r"([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{1,4}[/\-]\d{1,2}[/\-]\d{1,4})",
        HIGH,
        group=1,
    ),
    # Street address: number, street name, street type. Misses apartment lines
    # written separately, and anything without a street type.
    compile_rule(
        t.ADDRESS,
        r"(?<!\d)\d{1,6}\s+(?:[A-Z][A-Za-z.'\-]*\s+){1,4}(?:" + _STREET_TYPES + r")\b\.?",
        MEDIUM,
    ),
    compile_rule(
        t.COMPANY_NAME,
        r"(?<![A-Za-z])(?!" + _OPENER + r"\s)"
        r"[A-Z][A-Za-z0-9&.\-]*(?:" + _GAP + r"(?!" + _OPENER + r"\s)[A-Z][A-Za-z0-9&.\-]*){0,3}"
        r"\s*,?\s*(?:Inc|Corp|Corporation|Company|Ltd|Limited|LLC|LLP|PLC|GmbH|S\.A|AG|NV|BV)"
        r"\.?(?![A-Za-z])",
        MEDIUM,
    ),
    compile_rule(
        t.EMPLOYEE_ID,
        r"(?i)(?:employee\s*(?:id|number|no\.?)|staff\s*(?:id|number))\s*[:#]?\s*"
        r"([A-Za-z0-9\-]{3,24})",
        HIGH,
        group=1,
    ),
    # Project Nightingale, in a heading, with no colon. The Japanese rule for
    # this landed in 0.9 and the Chinese one in 0.13; English went without
    # until a thousand generated documents missed it thirty times. The same
    # asymmetry, a third time, which is an argument for generating rather than
    # hand-writing a corpus.
    compile_rule(
        t.PROJECT_NAME,
        r"(?:[Pp]roject|[Cc]odename)\s+(?!name\b|code\b)([A-Z][A-Za-z0-9\-]{2,30})",
        LOW,
        group=1,
    ),
    compile_rule(
        t.PROJECT_NAME,
        r"(?i)(?:project|codename|code\s*name)\s*[:#]\s*([^\s,;.]{2,40})",
        LOW,
        group=1,
    ),
    # Title-anchored: Mr. John Smith.
    compile_rule(t.PERSON, _TITLES + r"\.?\s+(" + _FULL_NAME + r")", HIGH, group=1),
    # Salutation-anchored: Dear Jane Doe, / Hi Jane,
    compile_rule(
        t.PERSON,
        r"(?i)(?:dear|hi|hello|hey)\s+(?-i:(" + _FULL_NAME + r"))(?=\s*[,\n])",
        HIGH,
        group=1,
    ),
    # Sign-off-anchored: Regards,\nJane Doe
    compile_rule(
        t.PERSON,
        r"(?i)(?:regards|sincerely|best|thanks|cheers|yours\s+truly)\s*,\s*\n+\s*"
        r"(?-i:(" + _FULL_NAME + r"))",
        MEDIUM,
        group=1,
    ),
    # Label-anchored: Name: Jane Doe
    compile_rule(
        t.PERSON,
        r"(?i)(?:full\s+name|name|contact|attn|attention)\s*[:]\s*(?-i:(" + _FULL_NAME + r"))",
        MEDIUM,
        group=1,
    ),
)

# --- Wide tier ------------------------------------------------------------
# The documented gaps, addressed the only way shape allows: by accepting the
# false positives that made them gaps in the first place.

# fmt: off
#: Words that appear title-cased in ordinary business English. A capitalised
#: bigram containing any of these is a heading, a date or a sentence opener
#: rather than a name. Without the list, "The Quarterly Business Review" and
#: "Social Security Number" both come back as people.
_NOT_NAME_WORDS = frozenset({
    "The", "A", "An", "This", "That", "These", "Those", "Our", "Your", "Their",
    "We", "I", "You", "He", "She", "It", "They", "There", "Here", "Please",
    "Thanks", "Thank", "Regards", "Sincerely", "Best", "Dear", "Hi", "Hello",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
    "Quarterly", "Business", "Review", "Report", "Meeting", "Project", "Team",
    "Security", "Number", "Social", "Company", "Department", "Office", "Manager",
    "Account", "Invoice", "Order", "Customer", "Client", "Service", "Support",
    "Product", "Release", "Version", "Update", "Status", "Summary", "Notes",
    "Attached", "Subject", "Re", "Fwd", "Cc", "Bcc", "To", "From", "Date",
    "Note", "Action", "Next", "Steps", "Agenda", "Minutes", "Draft", "Final",
    "New", "Old", "First", "Second", "Third", "Last", "Annual", "Monthly",
    "Weekly", "Daily", "North", "South", "East", "West", "Group", "Board",
    # Legal suffixes. Nobody is called Ltd. Without these the wide name rule
    # reads "Umbrella Ltd" as a person and, being the wider span, takes it from
    # the anchored company rule -- so the value is protected under the wrong
    # type, with the wrong placeholder, under a different policy category.
    "Ltd", "Limited", "Inc", "Corp", "Corporation", "Co", "LLC",
    "LLP", "PLC", "GmbH", "AG", "SA", "NV", "BV", "Pty", "Holdings",
    "Partners", "Associates", "Ventures", "Industries", "Technologies",
    "Contract", "Agreement", "Policy", "Terms", "Conditions", "Data", "System",
})
# fmt: on


def _plausible_latin_name(value: str) -> bool:
    return not (set(value.split()) & _NOT_NAME_WORDS)


WIDE_RULES: tuple[PatternRule, ...] = (
    # Two capitalised words. Also every product, city, department and sentence
    # opener -- which is exactly why the core rules are all anchored. Under a
    # recall-first stance this is the difference between finding a name in
    # running prose and not; the stoplist buys back most of the precision.
    compile_rule(
        t.PERSON,
        r"(?<![A-Za-z0-9.])" + _NAME + r"(?:" + _GAP + _NAME + r"){1,2}(?![A-Za-z0-9])",
        LOW,
        validator=_plausible_latin_name,
        tier=RuleTier.WIDE,
    ),
    # Ten bare digits. An order number looks identical; a phone number written
    # without separators is invisible to every other rule.
    compile_rule(
        t.PHONE,
        r"(?<![\d\-])\d{10}(?![\d\-])",
        LOW,
        tier=RuleTier.WIDE,
    ),
    # Nine bare digits that survive the SSA range check.
    compile_rule(
        t.SSN,
        r"(?<!\d)\d{9}(?!\d)",
        LOW,
        validator=ssn_valid,
        tier=RuleTier.WIDE,
    ),
    # A five-digit ZIP with a state abbreviation in front of it. Weakly
    # anchored rather than unanchored, because bare five-digit runs are
    # overwhelmingly part numbers.
    compile_rule(
        t.POSTAL_CODE,
        r"(?<![A-Z])[A-Z]{2}\s+(\d{5})(?!\d)",
        LOW,
        group=1,
        tier=RuleTier.WIDE,
    ),
)

ENGLISH = LocalePack(
    code="en",
    name="English",
    rules=RULES + WIDE_RULES,
    # Latin script is everywhere, including inside Japanese and Chinese
    # documents -- which is exactly when an English name or address is most
    # likely to be the thing nobody remembered to redact.
    triggers=frozenset({Script.LATIN}),
)
