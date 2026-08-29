"""Ports: the interfaces the application depends on.

Adapters live in :mod:`mamori.infrastructure`. Nothing in this package may
import an adapter.
"""

from __future__ import annotations

from .detection_pass import DetectionContext, DetectionPass
from .detector import Detector
from .llm import LLMProvider, LLMRequest, LLMResponse
from .llm_endpoint import LLMEndpoint
from .mapping_store import MappingStore

__all__ = [
    "DetectionContext",
    "DetectionPass",
    "Detector",
    "LLMEndpoint",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "MappingStore",
]
