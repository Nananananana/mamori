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
from ..patterns import PatternRule, compile_rule
from .base import LocalePack

__all__ = ["ENGLISH", "ssn_valid"]

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
_FULL_NAME = _NAME + r"(?:\s+" + _NAME + r"){0,2}"

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
        r"(?<![A-Za-z])[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3}"
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

ENGLISH = LocalePack(
    code="en",
    name="English",
    rules=RULES,
    # Latin script is everywhere, including inside Japanese and Chinese
    # documents -- which is exactly when an English name or address is most
    # likely to be the thing nobody remembered to redact.
    triggers=frozenset({Script.LATIN}),
)
