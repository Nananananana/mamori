"""The pass that asks a local model.

This is the tier that reaches what shape cannot: an English name in running
prose, a Chinese given name, a codename that looks like an ordinary word. It
runs last, sees what the rules already found, and adds to it.

Three properties hold whatever the model does, and they are the reason a model
can be let near this at all:

**It only ever adds.** The pass returns proposals; it cannot remove a pattern
rule's finding, veto a policy decision or alter a placeholder. Text that talks
the model out of reporting anything gets the pipeline back to where it was
without the model — which is the state every previous release shipped in.

**Its output is checked against the text.** Offsets must lie inside it and the
reported value must be exactly the characters between them, so a hallucinated
span is dropped rather than spliced out of somebody's document.

**Its failure is not the request's failure.** A model that is slow, missing or
broken is a degraded detector, not a stopped pipeline — unlike a *rule* failing,
which stops everything. The asymmetry is deliberate: rules are the guarantee,
the model is the improvement, and making the improvement load-bearing would
mean a privacy tool that stops working when Ollama is not running.

``require_model=True`` inverts that last one for deployments where the model is
part of the promise.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...domain.confidence import Confidence
from ...domain.sensitive_entity import SensitiveEntity
from ...errors import DetectionError
from ...ports.detection_pass import DetectionContext
from ...ports.llm import LLMProvider, LLMRequest
from ...prompts.library import DETECTION_PROMPT_ID, PromptLibrary, default_library
from ...prompts.parsing import (
    DETECTION_SCHEMA,
    MODEL_CONFIDENCE,
    ParseOutcome,
    parse_detection_response,
)

__all__ = ["LLMDetectionPass"]

_TEXT_MARKER = "---TEXT---"


class LLMDetectionPass:
    """Proposes candidates from a local model.

    Args:
        provider: The model.
        library: Where the detection prompt comes from, overlays included.
        locales: Keep only guidance for these languages, or ``None`` for all.
            Narrowing shortens the prompt, which matters on a small local
            model with a short context.
        confidence: Assigned to every surviving candidate. Sits below the
            anchored pattern rules and above the shape-only ones.
        require_model: Turn a provider failure into a stopped request. Off by
            default.
        max_input_characters: Refuse to send more than this. A prompt longer
            than the model's context is silently truncated by most servers,
            and a silently truncated privacy scan is worse than none.
        name: Recorded on every entity this pass produces.
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        library: PromptLibrary | None = None,
        locales: Sequence[str] | None = None,
        confidence: Confidence = MODEL_CONFIDENCE,
        require_model: bool = False,
        max_input_characters: int = 8000,
        name: str = "llm",
    ) -> None:
        self._provider = provider
        self._library = library if library is not None else default_library()
        self._locales = tuple(locales) if locales is not None else None
        self._confidence = confidence
        self._require_model = require_model
        self._max_input = max_input_characters
        self._name = name
        self._last: ParseOutcome | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    @property
    def last_outcome(self) -> ParseOutcome | None:
        """What the most recent response parsed to. For diagnostics only."""
        return self._last

    def rendered_prompt(self) -> str:
        """The exact system prompt this pass sends. Inspectable on purpose."""
        return self._library.render(DETECTION_PROMPT_ID, self._locales).text

    def run(self, context: DetectionContext) -> Sequence[SensitiveEntity]:
        text = context.text
        if not text.strip():
            return []

        if len(text) > self._max_input:
            # Refusing beats truncating. A scan that quietly covered the first
            # 8000 characters reports success on a document it never read.
            if self._require_model:
                raise DetectionError(
                    self._name,
                    ValueError(f"text is {len(text)} characters, limit is {self._max_input}"),
                )
            return []

        request = LLMRequest(
            system=self.rendered_prompt(),
            user=f"{_TEXT_MARKER}\n{text}",
            response_schema=DETECTION_SCHEMA if self._provider.supports_structured_output else None,
        )

        try:
            response = self._provider.generate(request)
        except Exception as exc:
            if self._require_model:
                raise DetectionError(self._name, exc) from exc
            self._last = ParseOutcome(unparsable=True, rejected=(f"provider: {exc!r}",))
            return []

        outcome = parse_detection_response(
            response.text,
            text,
            source=self._name,
            confidence=self._confidence,
        )
        self._last = outcome

        if outcome.unparsable and self._require_model:
            raise DetectionError(self._name, ValueError("; ".join(outcome.rejected)))

        already = context.covered()
        return [
            entity
            for entity in outcome.entities
            if not any(index in already for index in range(entity.span.start, entity.span.end))
        ]
