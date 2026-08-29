"""Deterministic resolution of overlapping detections.

Several detectors run over the same text, so ``田中太郎(tanaka@example.com)``
produces overlapping and nested spans. Replacing overlapping spans would
corrupt the text, so exactly one detection per character has to win, and the
rule has to be deterministic -- ambiguity here is where correctness bugs and
silent leaks live.

Preference order:

1. Longer span. Replacing a wider span also removes everything inside it, so
   when ``https://git.corp.local/?token=ghp_xxx`` and the token inside it are
   both detected, keeping the URL is the safer of the two outcomes.
2. Higher entity-type severity, when two spans are the same length -- a
   credential beats a person's name.
3. Higher detector confidence.
4. Earlier start offset.
5. Detector name, then type name -- purely to break remaining ties stably.

The containment argument holds because every surviving span is replaced. A
policy that maps a *wide* type to ``ALLOW`` breaks it, which is why ``ALLOW``
should be reserved for types whose extent you are sure about.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .sensitive_entity import SensitiveEntity

__all__ = ["Displacement", "resolve_overlaps", "resolve_overlaps_traced"]


def _preference(entity: SensitiveEntity) -> tuple[int, int, float, int, str, str]:
    return (
        -entity.span.length,
        -entity.entity_type.severity,
        -entity.confidence.value,
        entity.span.start,
        entity.source,
        entity.entity_type.name,
    )


class _Kept:
    """The spans accepted so far, kept sorted so a new one can be checked fast.

    The obvious implementation compares each candidate against everything
    already accepted, which is quadratic and invisible until the document is
    large: 500 KB of prose holds tens of thousands of detections and took
    thirteen seconds, of which twelve were three million span comparisons.

    Accepted spans never overlap each other, so they are totally ordered, and a
    candidate can only collide with the one that starts immediately before it
    or the one that starts immediately after. Two binary searches, and the
    answer is the same one the loop gave.
    """

    __slots__ = ("_entities", "_starts")

    def __init__(self) -> None:
        self._starts: list[int] = []
        self._entities: list[SensitiveEntity] = []

    def blocker(self, entity: SensitiveEntity) -> SensitiveEntity | None:
        """The accepted entity this one collides with, if any."""
        span = entity.span
        position = bisect_right(self._starts, span.start)
        if position and self._entities[position - 1].span.end > span.start:
            return self._entities[position - 1]
        if position < len(self._starts) and self._starts[position] < span.end:
            return self._entities[position]
        return None

    def add(self, entity: SensitiveEntity) -> None:
        position = bisect_right(self._starts, entity.span.start)
        self._starts.insert(position, entity.span.start)
        self._entities.insert(position, entity)


def resolve_overlaps(entities: Iterable[SensitiveEntity]) -> list[SensitiveEntity]:
    """Return a non-overlapping subset, ordered by start offset.

    Duplicate detections (same type and span from different detectors) collapse
    to one.
    """
    ranked = sorted(entities, key=_preference)
    kept = _Kept()
    accepted: list[SensitiveEntity] = []
    for candidate in ranked:
        if kept.blocker(candidate) is not None:
            continue
        kept.add(candidate)
        accepted.append(candidate)
    accepted.sort(key=lambda e: e.span.start)
    return accepted


def assert_non_overlapping(entities: Sequence[SensitiveEntity]) -> None:
    """Raise ``ValueError`` if ``entities`` are not sorted and disjoint.

    Used as an internal invariant check before text replacement.
    """
    previous_end = -1
    for entity in entities:
        if entity.span.start < previous_end:
            raise ValueError(f"overlapping spans after resolution at offset {entity.span.start}")
        previous_end = entity.span.end


@dataclass(frozen=True, slots=True)
class Displacement:
    """One detection that lost its span to another, and to which.

    The losers used to be dropped without a word, which is fine for producing
    text and useless for explaining it. "Why is this a PERSON when a rule said
    it was a COMPANY_NAME?" has an answer, and this is it.
    """

    loser: SensitiveEntity
    winner: SensitiveEntity

    @property
    def reason(self) -> str:
        """Which preference decided it, in the order the module documents."""
        if self.winner.span.length != self.loser.span.length:
            return "wider span"
        if self.winner.entity_type.severity != self.loser.entity_type.severity:
            return "higher severity"
        if self.winner.confidence.value != self.loser.confidence.value:
            return "higher confidence"
        if self.winner.span.start != self.loser.span.start:
            return "earlier in the text"
        return "tie broken by detector name"


def resolve_overlaps_traced(
    entities: Iterable[SensitiveEntity],
) -> tuple[list[SensitiveEntity], list[Displacement]]:
    """Resolve, and say what was displaced by what.

    Identical to :func:`resolve_overlaps` in what it keeps -- the same loop
    over the same structure -- and it additionally records every detection that
    lost, with the one that took its span. Used by ``mamori trace``.
    """
    ranked = sorted(entities, key=_preference)
    kept = _Kept()
    accepted: list[SensitiveEntity] = []
    displaced: list[Displacement] = []
    for candidate in ranked:
        winner = kept.blocker(candidate)
        if winner is not None:
            displaced.append(Displacement(loser=candidate, winner=winner))
            continue
        kept.add(candidate)
        accepted.append(candidate)
    accepted.sort(key=lambda e: e.span.start)
    return accepted, displaced
