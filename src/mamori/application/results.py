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
    #: Whether a plausible value went into the text instead of the token.
    #:
    #: The caller cannot see this from the protected text -- which is the whole
    #: point of a surrogate -- and it decides what may be said about the
    #: entity elsewhere. A token may be named, because it is in the text; a
    #: surrogate may only be counted. See :mod:`mamori.provenance`.
    surrogate: bool = False


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

    @property
    def reversible(self) -> bool:
        """Whether every replacement in this text can be undone.

        False when anything was masked: a mask is a fixed string with no
        mapping behind it, so the value it replaced is gone from this process
        and no restoration will bring it back. That is by design, and the
        point of saying it here is that **the caller cannot see it from the
        text**. `<PERSON_001>` and `[redacted]` look equally replaced.

        It matters to anything downstream that checks the model's answer
        against what was sent. A claim resting on a value that was anonymized
        can be verified after restoration; a claim resting on a masked one can
        never be, and the difference between "unsupported" and "unverifiable"
        is the difference between accusing a model of making something up and
        admitting you cannot tell. The sibling project `tsumugi` needs exactly
        this distinction for its citation checking, which is where the property
        came from.

        A blocked entity does not reach here at all -- protection raises
        instead, so there is no protected text to ask about.
        """
        return all(e.action is not Action.MASK for e in self.entities)

    @property
    def masked_types(self) -> tuple[str, ...]:
        """Types whose values were masked, in first-seen order. Not the values.

        What to tell somebody whose verification just came back unverifiable:
        which kinds of thing they can no longer check, without handing them
        back the values that were removed.
        """
        seen: dict[str, None] = {}
        for entity in self.entities:
            if entity.action is Action.MASK:
                seen.setdefault(entity.entity_type, None)
        return tuple(seen)

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
    #: The surface form, as the response wrote it, which is what a person
    #: reading a warning needs to see.
    unknown: tuple[str, ...] = field(default_factory=tuple)
    #: The same occurrences, canonicalised. A surface is whatever a model
    #: typed; an identity is `(TYPE, index)` and is bounded by the placeholder
    #: grammar. Records and audit lines carry these, so nothing a model wrote
    #: reaches a log verbatim -- see `mamori.provenance.restoration_record`.
    unknown_identities: tuple[Placeholder, ...] = field(default_factory=tuple)
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
