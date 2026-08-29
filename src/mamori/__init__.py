"""mamori -- a local-first privacy layer for generative AI.

Detect sensitive values in a prompt, replace them with stable placeholders,
send only the protected text to an external service, and put the real values
back locally when the answer comes home.

    >>> import mamori
    >>> with mamori.PrivacySession() as session:
    ...     result = session.protect("Contact tanaka@example.com by Friday.")
    ...     result.protected_text
    'Contact <EMAIL_001> by Friday.'

See ``SECURITY.md`` for what this does and does not protect against. It reduces
the chance of a leak; it does not eliminate it.
"""

from __future__ import annotations

from .application.results import EntityReport, ProtectionResult, RestorationResult
from .application.session import PrivacySession
from .application.streaming import StreamingRestorer, StreamSummary
from .config import MamoriConfig, load_config_file
from .domain.entity_types import Category, EntityType, register_type
from .domain.placeholder import Placeholder
from .domain.policy import Action, PrivacyPolicy
from .errors import (
    AnonymizationError,
    ConfigurationError,
    DetectionError,
    MamoriError,
    PolicyViolationError,
    RestorationError,
    StorageError,
)

__version__ = "0.5.0"

__all__ = [
    "Action",
    "AnonymizationError",
    "Category",
    "ConfigurationError",
    "DetectionError",
    "EntityReport",
    "EntityType",
    "MamoriConfig",
    "MamoriError",
    "Placeholder",
    "PolicyViolationError",
    "PrivacyPolicy",
    "PrivacySession",
    "ProtectionResult",
    "RestorationError",
    "RestorationResult",
    "StorageError",
    "StreamSummary",
    "StreamingRestorer",
    "__version__",
    "load_config_file",
    "register_type",
]
