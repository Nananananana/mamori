"""Domain layer.

Pure Python standard library only. No LLM SDK, no database driver, no HTTP
client may be imported from here -- every security-relevant decision
(resolution, policy, placeholder identity, restoration) lives in this layer and
must stay testable without any external runtime.
"""

from __future__ import annotations

from .confidence import CERTAIN, HIGH, LOW, MEDIUM, Confidence
from .entity_types import BUILTIN_TYPES, Category, EntityType, get_type, register_type
from .mapping import Mapping
from .normalization import NormalizedText, normalize_value
from .occurrences import find_occurrences
from .placeholder import Placeholder
from .placeholder_matching import PlaceholderOccurrence, scan_placeholders
from .policy import Action, PrivacyPolicy
from .resolution import resolve_overlaps
from .sensitive_entity import SensitiveEntity
from .span import Span
from .stance import RuleTier, Stance
from .trust import EndpointPolicy, HostKind, TrustBoundary
from .windowing import Window, windows

__all__ = [
    "BUILTIN_TYPES",
    "CERTAIN",
    "HIGH",
    "LOW",
    "MEDIUM",
    "Action",
    "Category",
    "Confidence",
    "EndpointPolicy",
    "EntityType",
    "HostKind",
    "Mapping",
    "NormalizedText",
    "Placeholder",
    "PlaceholderOccurrence",
    "PrivacyPolicy",
    "RuleTier",
    "SensitiveEntity",
    "Span",
    "Stance",
    "TrustBoundary",
    "Window",
    "find_occurrences",
    "get_type",
    "normalize_value",
    "register_type",
    "resolve_overlaps",
    "scan_placeholders",
    "windows",
]
