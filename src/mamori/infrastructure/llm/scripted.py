"""A provider that answers from a script.

Tests must not depend on a model being installed, and they must not depend on a
model being *right*. What needs testing is the pipeline around it: that a
hallucinated span is dropped, that a refusal degrades rather than stops, that a
proposal survives to become a placeholder.

So this returns whatever it is told to, including malformed answers, and
records what it was asked.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ...ports.llm import LLMRequest, LLMResponse

__all__ = ["ScriptedProvider"]


class ScriptedProvider:
    """Returns queued answers in order, then repeats the last one."""

    def __init__(
        self,
        answers: Sequence[str] | str = "",
        *,
        name: str = "scripted",
        structured: bool = False,
        on_call: Callable[[LLMRequest], None] | None = None,
    ) -> None:
        self._answers = [answers] if isinstance(answers, str) else list(answers)
        self._name = name
        self._structured = structured
        self._on_call = on_call
        self.requests: list[LLMRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def supports_structured_output(self) -> bool:
        return self._structured

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self._on_call is not None:
            self._on_call(request)
        if not self._answers:
            return LLMResponse(text="", model=self._name)
        answer = self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]
        return LLMResponse(text=answer, model=self._name)


class FailingProvider:
    """Raises. For checking that a broken model degrades rather than stops."""

    def __init__(self, error: Exception | None = None, *, name: str = "failing") -> None:
        self._error = error or RuntimeError("model unavailable")
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def supports_structured_output(self) -> bool:
        return False

    def generate(self, request: LLMRequest) -> LLMResponse:
        raise self._error
