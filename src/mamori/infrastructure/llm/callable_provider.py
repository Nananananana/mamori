"""Bring your own client, or your own model.

Not every model is behind an HTTP endpoint. ``llama-cpp-python`` loads a model
into this process. ``transformers`` does too. A team with a vendor SDK, a
corporate gateway or a message queue in front of their GPU box has a client
already and no interest in a second one.

All of those are one function: text in, text out. This wraps such a function as
a provider, so plugging in a different client library is three lines rather than
a subclass:

    >>> from mamori.infrastructure.llm import CallableProvider
    >>> provider = CallableProvider(lambda r: my_llm(r.system, r.user), name="llama-cpp")
    >>> provider.name
    'llama-cpp'

There is no trust-boundary check here, and there cannot be: the function might
open a socket, might not, and this module cannot tell. **If your function sends
the text somewhere, that somewhere receives it unprotected.** The check exists
on the HTTP provider because there the destination is visible.
"""

from __future__ import annotations

from collections.abc import Callable

from ...errors import ConfigurationError, ProviderError
from ...ports.llm import LLMRequest, LLMResponse

__all__ = ["CallableProvider", "Generate"]

#: Anything that turns a request into text. A bare string is enough; return an
#: :class:`~mamori.ports.llm.LLMResponse` if you have usage numbers to report.
Generate = Callable[[LLMRequest], "str | LLMResponse"]


class CallableProvider:
    """Adapts a plain function into a provider.

    Args:
        generate: Called with the request; returns the model's answer.
        name: Recorded on every entity produced from this provider's answers.
        structured: Whether ``response_schema`` is genuinely enforced. Say
            ``True`` only if your client passes it to something that honours
            it -- the parser validates regardless, and claiming enforcement
            that does not happen buys nothing and misleads a reader.
        model: Reported on the response when the function returns a bare
            string.
    """

    def __init__(
        self,
        generate: Generate,
        *,
        name: str = "callable",
        structured: bool = False,
        model: str = "",
    ) -> None:
        if not callable(generate):
            raise ConfigurationError("CallableProvider needs a callable")
        self._generate = generate
        self._name = name
        self._structured = structured
        self._model = model or name

    @property
    def name(self) -> str:
        return self._name

    @property
    def supports_structured_output(self) -> bool:
        return self._structured

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Call the function.

        Raises:
            ProviderError: the function raised, or returned something that was
                neither a string nor a response. Wrapped rather than
                propagated so a caller handles one exception type whichever
                client is underneath -- and so the detection pass can treat a
                broken in-process model exactly as it treats a broken server.
        """
        try:
            answer = self._generate(request)
        except Exception as exc:
            raise ProviderError(self._name, type(exc).__name__, retryable=False) from None

        if isinstance(answer, LLMResponse):
            return answer
        if isinstance(answer, str):
            return LLMResponse(text=answer, model=self._model)
        raise ProviderError(
            self._name, f"returned {type(answer).__name__}, expected str or LLMResponse"
        )
