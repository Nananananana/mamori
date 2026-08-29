"""Entity taxonomy.

``EntityType`` is deliberately *not* an ``Enum``: users must be able to register
their own types (spec 2.5) without patching the library. It is a frozen value
object with a validated name, a category and a severity used for deterministic
conflict resolution between overlapping detections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

__all__ = ["BUILTIN_TYPES", "Category", "EntityType", "get_type", "register_type"]

_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,62}$")


class Category(str, Enum):
    """Top-level grouping. Privacy and security are *not* the same concept."""

    PII = "PII"
    SECRET = "SECRET"  # noqa: S105 - a category name, not a credential
    COMPANY_CONFIDENTIAL = "COMPANY_CONFIDENTIAL"
    BUSINESS_SENSITIVE = "BUSINESS_SENSITIVE"
    INTERNAL = "INTERNAL"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class EntityType:
    """A kind of sensitive information.

    Args:
        name: Uppercase identifier. Becomes part of the placeholder token, so it
            is restricted to ``[A-Z][A-Z0-9_]*`` to keep placeholders parseable.
        category: Top-level grouping used for policy defaults.
        severity: 0-100. Higher wins when two detections overlap.
    """

    name: str
    category: Category = Category.OTHER
    severity: int = 50

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ValueError(f"invalid entity type name: {self.name!r}")
        if not 0 <= self.severity <= 100:
            raise ValueError(f"severity out of range: {self.severity}")

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name


def _t(name: str, category: Category, severity: int) -> EntityType:
    return EntityType(name=name, category=category, severity=severity)


# --- PII -------------------------------------------------------------------
PERSON = _t("PERSON", Category.PII, 70)
EMAIL = _t("EMAIL", Category.PII, 75)
PHONE = _t("PHONE", Category.PII, 75)
ADDRESS = _t("ADDRESS", Category.PII, 70)
POSTAL_CODE = _t("POSTAL_CODE", Category.PII, 60)
DATE_OF_BIRTH = _t("DATE_OF_BIRTH", Category.PII, 65)
CREDIT_CARD = _t("CREDIT_CARD", Category.PII, 95)

# National identifiers keep their local names rather than collapsing into one
# NATIONAL_ID. Each has its own format and its own checksum, and <SSN_001> tells
# a reader more than <NATIONAL_ID_001> would.
MY_NUMBER = _t("MY_NUMBER", Category.PII, 95)  # Japan, 個人番号
SSN = _t("SSN", Category.PII, 95)  # United States
RESIDENT_ID = _t("RESIDENT_ID", Category.PII, 95)  # China, 居民身份证

# --- Secrets ---------------------------------------------------------------
API_KEY = _t("API_KEY", Category.SECRET, 100)
ACCESS_TOKEN = _t("ACCESS_TOKEN", Category.SECRET, 100)
PASSWORD = _t("PASSWORD", Category.SECRET, 100)
PRIVATE_KEY = _t("PRIVATE_KEY", Category.SECRET, 100)
DATABASE_URL = _t("DATABASE_URL", Category.SECRET, 95)

# --- Company confidential --------------------------------------------------
COMPANY_NAME = _t("COMPANY_NAME", Category.COMPANY_CONFIDENTIAL, 55)
EMPLOYEE_ID = _t("EMPLOYEE_ID", Category.COMPANY_CONFIDENTIAL, 70)
PROJECT_NAME = _t("PROJECT_NAME", Category.COMPANY_CONFIDENTIAL, 55)

# --- Internal infrastructure ----------------------------------------------
INTERNAL_IP = _t("INTERNAL_IP", Category.INTERNAL, 65)
INTERNAL_URL = _t("INTERNAL_URL", Category.INTERNAL, 60)

# --- Structural ------------------------------------------------------------
#: Text in the *input* that already looks like one of our placeholders. It is
#: re-mapped so that restoration can never confuse it with a real placeholder.
PLACEHOLDER_LITERAL = _t("TEXT", Category.OTHER, 100)

BUILTIN_TYPES: dict[str, EntityType] = {
    t.name: t
    for t in (
        PERSON,
        EMAIL,
        PHONE,
        ADDRESS,
        POSTAL_CODE,
        DATE_OF_BIRTH,
        CREDIT_CARD,
        MY_NUMBER,
        SSN,
        RESIDENT_ID,
        API_KEY,
        ACCESS_TOKEN,
        PASSWORD,
        PRIVATE_KEY,
        DATABASE_URL,
        COMPANY_NAME,
        EMPLOYEE_ID,
        PROJECT_NAME,
        INTERNAL_IP,
        INTERNAL_URL,
        PLACEHOLDER_LITERAL,
    )
}

_registry: dict[str, EntityType] = dict(BUILTIN_TYPES)


def register_type(entity_type: EntityType) -> EntityType:
    """Register a custom entity type so it can be looked up by name.

    Raises:
        ValueError: if a *different* type is already registered under that name.
    """
    existing = _registry.get(entity_type.name)
    if existing is not None and existing != entity_type:
        raise ValueError(
            f"entity type already registered with different settings: {entity_type.name}"
        )
    _registry[entity_type.name] = entity_type
    return entity_type


def get_type(name: str) -> EntityType | None:
    """Look up a registered entity type by name."""
    return _registry.get(name)
