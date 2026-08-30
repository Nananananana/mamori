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

from .application.conversations import Conversation, ConversationRegistry
from .application.results import EntityReport, ProtectionResult, RestorationResult
from .application.session import PrivacySession
from .application.streaming import StreamingRestorer, StreamSummary
from .config import MamoriConfig, load_config_file
from .domain.entity_types import Category, EntityType, register_type
from .domain.placeholder import Placeholder, PlaceholderStyle
from .domain.policy import Action, PrivacyPolicy, Uncertain
from .errors import (
    AnonymizationError,
    ConfigurationError,
    DetectionError,
    MamoriError,
    PolicyViolationError,
    ProviderError,
    RestorationError,
    StorageError,
)
from .llm_settings import LLMSettings

__version__ = "0.25.0"

#: The public API. Everything here is what this package promises; anything
#: reachable only by a deeper import is not, however useful it looks.
#:
#: Audited in 0.25, when nine releases of features turned out to be reachable
#: only by deep import -- `ConversationRegistry` and `LLMSettings` among them,
#: both of which the README tells people to use. `test_api.py` pins this list,
#: so adding a name is now a deliberate act and removing one fails a test.
__all__ = [
    "Action",
    "AnonymizationError",
    "Category",
    "ConfigurationError",
    "Conversation",
    "ConversationRegistry",
    "DetectionError",
    "EntityReport",
    "EntityType",
    "LLMSettings",
    "MamoriConfig",
    "MamoriError",
    "Placeholder",
    "PlaceholderStyle",
    "PolicyViolationError",
    "PrivacyPolicy",
    "PrivacySession",
    "ProtectionResult",
    "ProviderError",
    "RestorationError",
    "RestorationResult",
    "StorageError",
    "StreamSummary",
    "StreamingRestorer",
    "Uncertain",
    "__version__",
    "load_config_file",
    "register_type",
]
