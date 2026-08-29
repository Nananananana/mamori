"""Model adapters, and the registry that makes them interchangeable.

Two shapes ship. ``openai_compatible`` talks HTTP to anything exposing the
OpenAI chat API -- Ollama on a laptop, vLLM on the company's GPU box, the
difference being a hostname. ``callable`` wraps a function, for a model loaded
into this process or a client library somebody already has.

Register your own with :func:`register_llm_provider` and it becomes usable from
a config file by name, alongside the built-in ones.
"""

from __future__ import annotations

from .callable_provider import CallableProvider, Generate
from .openai_compatible import OpenAICompatibleProvider, open_ai_compatible_factory
from .registry import (
    ProviderFactory,
    available_providers,
    create_provider,
    get_provider_factory,
    register_llm_provider,
)
from .scripted import FailingProvider, ScriptedProvider

__all__ = [
    "CallableProvider",
    "FailingProvider",
    "Generate",
    "OpenAICompatibleProvider",
    "ProviderFactory",
    "ScriptedProvider",
    "available_providers",
    "create_provider",
    "get_provider_factory",
    "open_ai_compatible_factory",
    "register_llm_provider",
]

register_llm_provider("openai_compatible", open_ai_compatible_factory)
