"""Application layer: orchestration of the domain."""

from __future__ import annotations

from .conversations import Conversation, ConversationRegistry
from .protection import ProtectionService
from .restoration import RestorationService
from .results import EntityReport, ProtectionResult, RestorationResult, mask_preview
from .session import PrivacySession
from .streaming import StreamingRestorer, StreamSummary

__all__ = [
    "Conversation",
    "ConversationRegistry",
    "EntityReport",
    "PrivacySession",
    "ProtectionResult",
    "ProtectionService",
    "RestorationResult",
    "RestorationService",
    "StreamSummary",
    "StreamingRestorer",
    "mask_preview",
]
