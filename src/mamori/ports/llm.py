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

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = ["BatchLLMProvider", "LLMProvider", "LLMRequest", "LLMResponse"]


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
    #: Seconds for this one request, when it needs less than the endpoint
    #: allows. ``None`` means "whatever the endpoint is configured for", which
    #: is the answer almost every caller wants.
    #:
    #: This was ``30.0`` until 0.23, and a provider takes the *smaller* of the
    #: two -- so an endpoint configured for three hundred seconds got thirty,
    #: and `llm.timeout` above thirty did nothing at all. On hardware where a
    #: local model needs ninety seconds for a document that is the difference
    #: between a model tier and a model tier that never answers, and because
    #: the pass degrades to nothing by design, the symptom was silence.
    timeout: float | None = None


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


@runtime_checkable
class BatchLLMProvider(Protocol):
    """A provider that would rather be asked several things at once.

    Optional, and advertised by implementing it rather than by a flag -- the
    same shape as ``supports_structured_output``. Callers use it when it is
    there and loop over :meth:`LLMProvider.generate` when it is not, so no
    existing provider has to change and no caller has to care.

    It exists because a long document is scanned in windows, and a shared model
    on another machine is dominated by round trips: ten windows is ten times
    the latency for one document, and a server that can take them together
    should be allowed to. A provider wrapping a model in this process gains
    nothing from it and should not implement it.

    The contract is positional. ``len(responses) == len(requests)``, in order,
    so a caller can pair the answer with the window it was about. A provider
    that cannot answer one request must still occupy its place -- with an empty
    response -- or raise for the batch.
    """

    def generate_batch(self, requests: Sequence[LLMRequest]) -> Sequence[LLMResponse]:
        """Answer every request, in order."""
        ...
