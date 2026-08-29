"""Result objects returned to callers.

None of these carry raw sensitive values. ``EntityReport.preview`` is masked so
that a report can be logged or shown in a UI without re-introducing the leak
the library exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.placeholder import Placeholder
from ..domain.placeholder_matching import PlaceholderOccurrence
from ..domain.policy import Action
from ..domain.span import Span
from .trace import DecisionTrace

__all__ = ["EntityReport", "ProtectionResult", "RestorationResult", "mask_preview"]


def mask_preview(value: str, keep: int = 1) -> str:
    """Return a masked preview: enough to recognise, not enough to leak.

    ``田中太郎`` -> ``田***``, ``tanaka@example.com`` -> ``t*****************``.
    """
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "*" * (len(value) - keep)


@dataclass(frozen=True, slots=True)
class EntityReport:
    """What happened to one detected entity. Contains no raw value."""

    entity_type: str
    action: Action
    span: Span
    confidence: float
    source: str
    #: Masked form of the original value.
    preview: str
    #: Set when the action was ``ANONYMIZE``.
    placeholder: str | None = None


@dataclass(frozen=True, slots=True)
class ProtectionResult:
    """Outcome of protecting one text."""

    #: Safe to send to an external service.
    protected_text: str
    entities: tuple[EntityReport, ...] = ()
    #: Scope the placeholders were allocated in; needed to restore.
    scope: str = ""
    #: Everything the pipeline considered and what became of it. ``None``
    #: unless the caller asked, because it costs a list of every candidate.
    trace: DecisionTrace | None = None

    @property
    def entity_count(self) -> int:
        return len(self.entities)

    @property
    def anonymized_count(self) -> int:
        return sum(1 for e in self.entities if e.action is Action.ANONYMIZE)

    def counts_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entity in self.entities:
            counts[entity.entity_type] = counts.get(entity.entity_type, 0) + 1
        return counts


@dataclass(frozen=True, slots=True)
class RestorationResult:
    """Outcome of restoring one response."""

    #: The response with known placeholders replaced by their original values.
    text: str
    #: Placeholders that were found and replaced.
    restored: tuple[PlaceholderOccurrence, ...] = ()
    #: Placeholder-shaped text that was never allocated. Not substituted.
    unknown: tuple[str, ...] = field(default_factory=tuple)
    #: Placeholders allocated in the scope that the response did not mention.
    #: Usually harmless -- the model simply did not need them.
    missing: tuple[Placeholder, ...] = field(default_factory=tuple)

    @property
    def tampered(self) -> tuple[PlaceholderOccurrence, ...]:
        """Restored placeholders whose surface form the model had altered."""
        return tuple(o for o in self.restored if o.tampered)

    @property
    def is_clean(self) -> bool:
        """True when every placeholder in the response was recognised."""
        return not self.unknown
