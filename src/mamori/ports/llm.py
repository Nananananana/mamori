"""Local model port.

Deliberately the smallest interface that does the job: a system prompt, a user
message, some knobs, text back. No streaming, no tools, no chat history, no
provider-specific fields.

That narrowness is what keeps the model outside every security decision. A
provider cannot influence resolution, policy, placeholder allocation or
restoration, because it is never asked about them -- it is asked for text, and
:mod:`mamori.prompts.parsing` decides what, if anything, that text was worth.

Capabilities that only some backends have (structured output, for one) are
advertised rather than assumed, so the pipeline can use them where they exist
without an interface that pretends they are universal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = ["LLMProvider", "LLMRequest", "LLMResponse"]


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """One question for a local model."""

    system: str = field(repr=False, default="")
    #: The text being examined. Excluded from ``repr``: it is the user's
    #: document, and this object will end up in a traceback eventually.
    user: str = field(repr=False, default="")
    #: Zero unless you want variety. Detection wants the same answer twice.
    temperature: float = 0.0
    max_tokens: int = 2048
    #: JSON schema the response must satisfy, for providers that enforce one.
    #: Ignored elsewhere; the parser validates either way.
    response_schema: dict[str, object] | None = None
    timeout: float = 30.0


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """What came back."""

    text: str = field(repr=False, default="")
    model: str = ""
    #: Whatever the provider reported. Never contains the prompt or the answer.
    usage: dict[str, int] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.text.strip())


@runtime_checkable
class LLMProvider(Protocol):
    """A local model that can answer one question.

    Implementations raise on failure. A provider that returns empty text to
    signal a problem is indistinguishable from a model that found nothing,
    which is the fail-open shape this library exists to avoid -- although here
    the consequence is bounded: the pass that calls it is allowed to give up
    without stopping the request, because the pattern rules still ran.
    """

    @property
    def name(self) -> str:
        """Stable identifier, recorded alongside results."""
        ...

    @property
    def supports_structured_output(self) -> bool:
        """Whether ``response_schema`` is enforced rather than ignored."""
        ...

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Answer ``request``."""
        ...
