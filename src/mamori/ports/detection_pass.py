"""Detection pass port.

A :class:`~mamori.ports.detector.Detector` looks at a text and reports what it
sees. That is the whole contract, and it is deliberately narrow: a rule set has
no business knowing what other rule sets found.

Some detection is not like that. Once ``田中太郎`` has been confirmed by an
honorific in one sentence, every other occurrence in the same document is the
same person -- and no rule looking at those occurrences in isolation can tell.
The evidence is *what was already found*, which a ``Detector`` cannot see.

A pass is the wider contract: it receives the text **and** what earlier passes
found, and returns whatever it can add. Ordinary detectors are wrapped as the
first pass; passes that reason over prior results come after.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..domain.sensitive_entity import SensitiveEntity

__all__ = ["DetectionContext", "DetectionPass"]


@dataclass(frozen=True, slots=True)
class DetectionContext:
    """What a pass gets to work with.

    Args:
        text: The **normalized** text. Spans returned by a pass are in these
            coordinates, exactly as for a plain detector.
        found: Everything earlier passes reported, in order. Possibly
            overlapping and possibly contradictory -- conflicts are resolved
            once, later, by :mod:`mamori.domain.resolution`.
    """

    text: str = field(repr=False)
    found: tuple[SensitiveEntity, ...] = ()

    def with_more(self, entities: Sequence[SensitiveEntity]) -> DetectionContext:
        """Return a context carrying ``entities`` as well."""
        return DetectionContext(text=self.text, found=(*self.found, *entities))

    def covered(self) -> frozenset[int]:
        """Character indices already claimed by some earlier detection."""
        return frozenset(
            index for entity in self.found for index in range(entity.span.start, entity.span.end)
        )


@runtime_checkable
class DetectionPass(Protocol):
    """One stage of detection.

    Like a detector, a pass that cannot do its job must raise. Returning
    nothing to signal failure is indistinguishable from finding nothing, which
    is the fail-open bug this library exists to avoid.
    """

    @property
    def name(self) -> str:
        """Stable identifier, recorded on every entity this pass produces."""
        ...

    def run(self, context: DetectionContext) -> Sequence[SensitiveEntity]:
        """Return the entities this pass adds. Earlier findings stay."""
        ...
