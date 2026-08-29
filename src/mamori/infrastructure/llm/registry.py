"""Providers by name, so the client can be swapped from a config file.

The port already made providers interchangeable in Python. What it did not do
was let a team choose one without writing Python: a config file could name a
model but not the thing that talks to it, so switching from an HTTP endpoint to
an in-process model, or from ``urllib`` to a vendor SDK, meant editing code.

A registry closes that. Register a factory under a name, and the name works
everywhere a provider is configured:

    >>> from mamori.infrastructure.llm import available_providers
    >>> "openai_compatible" in available_providers()
    True

A factory takes an :class:`~mamori.ports.llm_endpoint.LLMEndpoint` -- where the
model is, how long to wait, what is allowed -- and returns something satisfying
``LLMProvider``. Nothing here knows about HTTP, and nothing here is tied to a
serving stack.
"""

from __future__ import annotations

from collections.abc import Callable

from ...errors import ConfigurationError
from ...ports.llm import LLMProvider
from ...ports.llm_endpoint import LLMEndpoint

__all__ = [
    "ProviderFactory",
    "available_providers",
    "create_provider",
    "get_provider_factory",
    "register_llm_provider",
]

ProviderFactory = Callable[[LLMEndpoint], LLMProvider]

_REGISTRY: dict[str, ProviderFactory] = {}


def register_llm_provider(name: str, factory: ProviderFactory) -> ProviderFactory:
    """Register a provider factory under ``name``.

    Replaces an existing registration, which is deliberate: a deployment that
    wants its own client for ``openai_compatible`` -- one that speaks through a
    corporate proxy, or adds a header its gateway needs -- should be able to
    substitute it without every call site changing.
    """
    if not name:
        raise ConfigurationError("a provider needs a name")
    _REGISTRY[name] = factory
    return factory


def available_providers() -> tuple[str, ...]:
    """Every registered provider name, sorted."""
    return tuple(sorted(_REGISTRY))


def get_provider_factory(name: str) -> ProviderFactory:
    """Look up a factory.

    Raises:
        ConfigurationError: no provider registered under that name.
    """
    factory = _REGISTRY.get(name)
    if factory is None:
        known = ", ".join(available_providers()) or "(none registered)"
        raise ConfigurationError(f"unknown LLM provider {name!r}; available: {known}")
    return factory


def create_provider(name: str, endpoint: LLMEndpoint) -> LLMProvider:
    """Build a provider by name.

    Raises:
        ConfigurationError: unknown name, or the endpoint is one the provider
            refuses -- outside the trust boundary, most likely.
    """
    return get_provider_factory(name)(endpoint)
