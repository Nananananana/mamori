"""Second mention of a value already confirmed elsewhere.

Real documents introduce a person once with enough evidence to be sure, and
then refer to them repeatedly with none:

    尊敬的張伟先生：              <- an honorific settles it
    ...
    关于该项目，张伟已确认。       <- nothing here says this is a name
    ...
    请张伟在周五前回复。          <- nor here

No rule looking at the later mentions in isolation can tell them from ordinary
words. The evidence is that the same string was confirmed earlier in the same
text, which is exactly what a pass -- unlike a detector -- can see.

This is the cheapest large gain available in every language, and it is the
largest one available in Chinese, where there is nothing else to anchor on. It
needs no model, no dictionary and no network, and it is fully deterministic.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...domain import entity_types as t
from ...domain.entity_types import EntityType
from ...domain.occurrences import find_occurrences
from ...domain.sensitive_entity import SensitiveEntity
from ...domain.span import Span
from ...ports.detection_pass import DetectionContext

__all__ = ["DEFAULT_SEED_TYPES", "CoOccurrencePass"]

#: Types worth propagating. A repeated name or company is the same one; a
#: repeated *phone number* is already caught by its own rule everywhere it
#: appears, so seeding from it buys nothing and only risks noise.
DEFAULT_SEED_TYPES: frozenset[EntityType] = frozenset(
    {t.PERSON, t.COMPANY_NAME, t.PROJECT_NAME, t.EMPLOYEE_ID}
)


class CoOccurrencePass:
    """Propagates confidently-detected values to their other occurrences.

    Args:
        min_confidence: How sure an earlier detection must be before its value
            is trusted as a seed. The default only accepts the high-precision
            anchors -- an honorific, a title, a salutation -- so a shaky guess
            cannot multiply itself across the document.
        seed_types: Which entity types propagate.
        min_length: Values shorter than this are ignored. A one-character seed
            matches most of a CJK document.
        name: Recorded on every entity this pass produces, so a report says
            plainly which mentions were found by propagation.
    """

    def __init__(
        self,
        *,
        min_confidence: float = 0.85,
        seed_types: frozenset[EntityType] = DEFAULT_SEED_TYPES,
        min_length: int = 2,
        name: str = "co-occurrence",
    ) -> None:
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError(f"min_confidence out of range: {min_confidence}")
        if min_length < 1:
            raise ValueError(f"min_length must be >= 1, got {min_length}")
        self._min_confidence = min_confidence
        self._seed_types = frozenset(seed_types)
        self._min_length = min_length
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def min_confidence(self) -> float:
        return self._min_confidence

    def run(self, context: DetectionContext) -> Sequence[SensitiveEntity]:
        seeds = self._seeds(context)
        if not seeds:
            return []

        covered = context.covered()
        added: list[SensitiveEntity] = []

        for value, seed in seeds.items():
            for span in self._occurrences(context.text, value):
                if any(index in covered for index in range(span.start, span.end)):
                    continue
                added.append(
                    SensitiveEntity(
                        entity_type=seed.entity_type,
                        span=span,
                        value=value,
                        confidence=seed.confidence,
                        source=self._name,
                    )
                )
                covered |= set(range(span.start, span.end))
        return added

    # -- internals ---------------------------------------------------------

    def _seeds(self, context: DetectionContext) -> dict[str, SensitiveEntity]:
        """The values worth looking for again, longest first.

        Longest first so that when both ``田中太郎`` and ``田中`` were
        confirmed, the full name claims its occurrences before the surname can
        take the first two characters of them.
        """
        candidates = [
            entity
            for entity in context.found
            if entity.entity_type in self._seed_types
            and entity.confidence.value >= self._min_confidence
            and len(entity.value) >= self._min_length
        ]
        candidates.sort(key=lambda e: (-len(e.value), e.span.start))
        seeds: dict[str, SensitiveEntity] = {}
        for entity in candidates:
            seeds.setdefault(entity.value, entity)
        return seeds

    def _occurrences(self, text: str, value: str) -> list[Span]:
        """Shared with the model parser, which locates values for the same reason."""
        return list(find_occurrences(text, value, min_length=self._min_length))
