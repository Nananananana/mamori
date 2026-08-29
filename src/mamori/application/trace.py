"""Why something was replaced, and why something else was not.

Every detection has always carried which rule found it and how sure that rule
was. Nothing surfaced it consistently, so the two questions every user asks
first had no answer:

- *Why was this redacted?* — answerable from the result, awkwardly.
- *Why was this **not** redacted?* — not answerable at all, and it is the one
  that matters, because a miss is the failure this library exists to prevent.

A trace records every candidate the pipeline considered and what became of it.
Four things can happen to a detection and only one of them is visible in the
output, so the other three are what this is for: dropped for confidence,
overruled by a correction, or displaced by an overlapping detection that won.

**A trace contains previews, never values.** It is the sort of thing somebody
pastes into a bug report, and a diagnostic that leaks the document it was
diagnosing would be a poor joke. The same masking the entity reports use
applies here, and a test pins it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from ..domain.span import Span

__all__ = ["DecisionTrace", "Outcome", "TracedDecision"]


class Outcome(str, Enum):
    """What became of one candidate."""

    KEPT = "kept"
    #: Below the configured minimum confidence, so never considered at all.
    BELOW_CONFIDENCE = "below confidence"
    #: The operator ruled this value not sensitive.
    CORRECTED_AWAY = "corrected away"
    #: An overlapping detection won the span.
    DISPLACED = "displaced"


@dataclass(frozen=True, slots=True)
class TracedDecision:
    """One candidate, and what happened to it."""

    entity_type: str
    span: Span
    #: Masked. Never the value.
    preview: str
    source: str
    confidence: float
    outcome: Outcome
    #: Why, when the outcome needs one. "lost to PERSON (wider span)".
    detail: str = ""

    def describe(self) -> str:
        where = f"{self.span.start}:{self.span.end}"
        line = f"{where:<10}{self.entity_type:<16}{self.source:<14}{self.confidence:.2f}  "
        line += self.outcome.value
        return line + (f" -- {self.detail}" if self.detail else "")


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    """Everything the pipeline considered for one text."""

    decisions: tuple[TracedDecision, ...] = ()
    characters: int = 0

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.decisions)

    def __len__(self) -> int:
        return len(self.decisions)

    def with_outcome(self, outcome: Outcome) -> tuple[TracedDecision, ...]:
        return tuple(d for d in self.decisions if d.outcome is outcome)

    @property
    def kept(self) -> tuple[TracedDecision, ...]:
        return self.with_outcome(Outcome.KEPT)

    @property
    def discarded(self) -> tuple[TracedDecision, ...]:
        """Everything considered and not kept. The interesting half."""
        return tuple(d for d in self.decisions if d.outcome is not Outcome.KEPT)

    def rules_that_fired(self) -> dict[str, int]:
        """Which rule sets contributed, and how much."""
        counts: dict[str, int] = {}
        for decision in self.decisions:
            counts[decision.source] = counts.get(decision.source, 0) + 1
        return counts

    def as_mapping(self) -> dict[str, object]:
        return {
            "characters": self.characters,
            "considered": len(self.decisions),
            "kept": len(self.kept),
            "decisions": [
                {
                    "entity_type": d.entity_type,
                    "start": d.span.start,
                    "end": d.span.end,
                    "preview": d.preview,
                    "source": d.source,
                    "confidence": d.confidence,
                    "outcome": d.outcome.value,
                    "detail": d.detail,
                }
                for d in self.decisions
            ],
        }


@dataclass
class TraceBuilder:
    """Collects decisions while the pipeline runs.

    Mutable on purpose and short-lived: it exists for the length of one
    ``protect`` call and produces a frozen :class:`DecisionTrace`.
    """

    decisions: list[TracedDecision] = field(default_factory=list)

    def record(
        self,
        entity_type: str,
        span: Span,
        preview: str,
        source: str,
        confidence: float,
        outcome: Outcome,
        detail: str = "",
    ) -> None:
        self.decisions.append(
            TracedDecision(
                entity_type=entity_type,
                span=span,
                preview=preview,
                source=source,
                confidence=confidence,
                outcome=outcome,
                detail=detail,
            )
        )

    def build(self, characters: int) -> DecisionTrace:
        ordered = sorted(self.decisions, key=lambda d: (d.span.start, d.span.end))
        return DecisionTrace(decisions=tuple(ordered), characters=characters)


def summarise(trace: DecisionTrace) -> Sequence[str]:
    """A few lines saying what happened, for somebody reading a terminal."""
    lines = [
        f"{len(trace)} candidate(s) considered, {len(trace.kept)} kept",
    ]
    for outcome in (Outcome.DISPLACED, Outcome.BELOW_CONFIDENCE, Outcome.CORRECTED_AWAY):
        found = trace.with_outcome(outcome)
        if found:
            lines.append(f"  {len(found)} {outcome.value}")
    return lines
