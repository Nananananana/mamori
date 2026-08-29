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
from ...domain.span import Span
from ...domain.windowing import Window, windows
from ...errors import DetectionError, ProviderError
from ...ports.detection_pass import DetectionContext
from ...ports.llm import BatchLLMProvider, LLMProvider, LLMRequest, LLMResponse
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

        pieces = windows(text, self._max_input)
        requests = [self._request(window.text) for window in pieces]

        try:
            responses = self._ask(requests)
        except Exception as exc:
            if self._require_model:
                raise DetectionError(self._name, exc) from exc
            self._last = ParseOutcome(unparsable=True, rejected=(f"provider: {exc!r}",))
            return []

        found: list[SensitiveEntity] = []
        rejected: list[str] = []
        unparsable = False
        for window, response in zip(pieces, responses, strict=True):
            outcome = parse_detection_response(
                response.text,
                window.text,
                source=self._name,
                confidence=self._confidence,
            )
            rejected.extend(outcome.rejected)
            unparsable = unparsable or outcome.unparsable
            found.extend(_relocated(outcome.entities, window))

        self._last = ParseOutcome(
            entities=tuple(found), rejected=tuple(rejected), unparsable=unparsable
        )

        if unparsable and self._require_model:
            raise DetectionError(self._name, ValueError("; ".join(rejected)))

        already = context.covered()
        return [
            entity
            for entity in _deduplicated(found)
            if not any(index in already for index in range(entity.span.start, entity.span.end))
        ]

    def _request(self, text: str) -> LLMRequest:
        return LLMRequest(
            system=self.rendered_prompt(),
            user=_TEXT_MARKER + "\n" + text,
            response_schema=DETECTION_SCHEMA if self._provider.supports_structured_output else None,
        )

    def _ask(self, requests: Sequence[LLMRequest]) -> Sequence[LLMResponse]:
        """One round trip if the provider can take one, otherwise several.

        A model on a shared machine is dominated by latency, so a provider that
        advertises batching gets the whole document at once. One in this
        process gains nothing from that and does not implement it.
        """
        if len(requests) > 1 and isinstance(self._provider, BatchLLMProvider):
            responses = self._provider.generate_batch(requests)
            if len(responses) != len(requests):
                raise ProviderError(
                    self._provider.name,
                    f"batch returned {len(responses)} answers for {len(requests)} requests",
                )
            return responses
        return [self._provider.generate(request) for request in requests]


def _relocated(entities: Sequence[SensitiveEntity], window: Window) -> list[SensitiveEntity]:
    """Move detections from window coordinates into document coordinates."""
    if not window.offset:
        return list(entities)
    return [
        entity.relocated(Span(*window.locate(entity.span.start, entity.span.end)), entity.value)
        for entity in entities
    ]


def _deduplicated(entities: Sequence[SensitiveEntity]) -> list[SensitiveEntity]:
    """Drop repeats seen in the overlap between two windows.

    Overlap resolution would collapse these anyway, but a duplicate reaching it
    is a duplicate in every count and report on the way, and the overlap exists
    for the library's own reasons rather than the user's.
    """
    seen: set[tuple[str, int, int]] = set()
    unique: list[SensitiveEntity] = []
    for entity in entities:
        key = (entity.entity_type.name, entity.span.start, entity.span.end)
        if key not in seen:
            seen.add(key)
            unique.append(entity)
    return unique
