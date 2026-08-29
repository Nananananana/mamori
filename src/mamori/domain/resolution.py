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

from collections.abc import Iterable, Sequence

from .sensitive_entity import SensitiveEntity

__all__ = ["resolve_overlaps"]


def _preference(entity: SensitiveEntity) -> tuple[int, int, float, int, str, str]:
    return (
        -entity.span.length,
        -entity.entity_type.severity,
        -entity.confidence.value,
        entity.span.start,
        entity.source,
        entity.entity_type.name,
    )


def resolve_overlaps(entities: Iterable[SensitiveEntity]) -> list[SensitiveEntity]:
    """Return a non-overlapping subset, ordered by start offset.

    Duplicate detections (same type and span from different detectors) collapse
    to one.
    """
    ranked = sorted(entities, key=_preference)
    accepted: list[SensitiveEntity] = []
    for candidate in ranked:
        if any(candidate.span.overlaps(kept.span) for kept in accepted):
            continue
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
