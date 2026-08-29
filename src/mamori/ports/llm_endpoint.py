"""Where a model is and how to reach it, separated from what talks to it.

Two things vary independently and were tangled together in the first version:

- **Where the model runs.** This laptop, or a GPU box in the server room. The
  difference is a hostname and a timeout, not a different class.
- **What speaks to it.** ``urllib`` against an OpenAI-compatible endpoint, a
  vendor SDK, ``llama-cpp-python`` in the same process. Genuinely different
  code.

``LLMEndpoint`` is the first: a description, with no behaviour and no network
knowledge, that any provider can be built from. A provider factory is the
second. Splitting them is what makes ``provider: "openai_compatible"`` and
``provider: "my_sdk_adapter"`` interchangeable in a config file, pointed at the
same server.

The API key is named, not carried. ``api_key_env`` holds the name of an
environment variable, so a configuration file that gets committed -- and one
will -- contains the string ``LLM_API_KEY`` rather than the key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..domain.trust import EndpointPolicy, TrustBoundary

__all__ = ["LLMEndpoint"]

#: Ollama's default. The most common thing somebody already has running.
DEFAULT_BASE_URL = "http://localhost:11434/v1/"


@dataclass(frozen=True, slots=True)
class LLMEndpoint:
    """Where a model lives and how to talk to it.

    Args:
        model: Name the server knows, e.g. ``qwen2.5:7b``.
        base_url: Root of the API. Defaults to Ollama on this machine.
        api_key_env: Name of an environment variable holding a key, if the
            server wants one. **Not the key.**
        timeout: Seconds for one attempt. The default is generous because a
            model on a shared server can queue behind other work.
        retries: Attempts after the first, for transient failures only. Applied
            wherever the model is: a server on this machine can be busy loading
            weights just as one across the network can be busy with somebody
            else's work.
        backoff: Seconds before the first retry, doubling after that.
        policy: Which endpoints are allowed at all.
        options: Anything a specific provider needs and the others do not.
            Provider-specific settings belong here rather than growing this
            class, which every provider has to understand.
    """

    model: str
    base_url: str = DEFAULT_BASE_URL
    api_key_env: str = ""
    timeout: float = 60.0
    retries: int = 2
    backoff: float = 0.5
    policy: EndpointPolicy = field(default_factory=EndpointPolicy)
    options: dict[str, object] = field(default_factory=dict)

    @property
    def is_remote(self) -> bool:
        """Whether the model is on another machine.

        Reported rather than acted on. Retries do not depend on it -- a local
        server can be busy too -- but a caller choosing a timeout, or a
        diagnostic explaining why the first request took nine seconds, wants
        to know.
        """
        from ..domain.trust import HostKind

        return self.policy.classify(self.base_url) is not HostKind.LOOPBACK

    def api_key(self) -> str | None:
        """Read the key from the environment, if one was named."""
        return os.environ.get(self.api_key_env) if self.api_key_env else None

    def normalised_base_url(self) -> str:
        return self.base_url if self.base_url.endswith("/") else self.base_url + "/"

    def with_policy(self, boundary: TrustBoundary) -> LLMEndpoint:
        """Return a copy with a different trust boundary."""
        from dataclasses import replace

        return replace(self, policy=EndpointPolicy(boundary, self.policy.trusted_hosts))
