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

from ..domain.claimed import ClaimedSpans
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
    #: Built on first use and kept, because every pass that reads prior
    #: findings asks about every candidate it has.
    _claimed: ClaimedSpans | None = field(default=None, repr=False, compare=False, hash=False)

    def with_more(self, entities: Sequence[SensitiveEntity]) -> DetectionContext:
        """Return a context carrying ``entities`` as well."""
        return DetectionContext(text=self.text, found=(*self.found, *entities))

    def claimed(self) -> ClaimedSpans:
        """What earlier detections have taken, as ranges.

        Built once per context. The instance is frozen, so this is stored
        through `object.__setattr__` -- the same escape hatch `dataclasses`
        uses for its own `__init__`, and the reason the field is excluded from
        equality and hashing: it is a cache of `found`, not a second fact.
        """
        existing = self._claimed
        if existing is None:
            existing = ClaimedSpans((entity.span.start, entity.span.end) for entity in self.found)
            object.__setattr__(self, "_claimed", existing)
        return existing

    def overlaps(self, start: int, end: int) -> bool:
        """Whether ``[start, end)`` touches anything an earlier pass found.

        The question every consumer of prior findings actually asks. It used
        to be asked of `covered()` one character at a time, which built a set
        holding an integer per covered *character* -- 43.5 bytes per input
        character on a 100 KB document, more than half the peak allocation of
        a whole protection, to state what the spans already stated.
        """
        return self.claimed().overlaps(start, end)

    def covered(self) -> frozenset[int]:
        """Character indices already claimed by some earlier detection.

        Kept because it is part of this port and somebody's pass may read it.
        `overlaps` is the cheaper way to ask the usual question, and every
        pass shipped here uses it.
        """
        return self.claimed().characters()


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
