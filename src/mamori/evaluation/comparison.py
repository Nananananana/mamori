"""Two configurations over the same data, and what changed between them.

Every number this library publishes is a trade, and a single report shows only
one side of it. "The model tier reaches 0.2% leak rate" says nothing until it
sits beside what the rules alone reached and what the difference cost.

So the unit of measurement here is a **pair**. A baseline and a candidate, run
over the same samples, with the deltas computed and -- the part that makes it
useful rather than merely honest -- the individual samples that changed listed
by name.

That last part is what a prompt is tuned against. An aggregate that moves from
2.0% to 1.4% tells you something worked; a list saying `en-006` and `en-027`
are now covered and `en-007` newly lost three characters of ordinary text tells
you *what*, and whether you believe it. Tuning against the aggregate alone is
how a prompt gets fitted to a number instead of to a language.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .scoring import EvaluationReport, SampleResult

__all__ = ["Comparison", "SampleChange", "compare"]


@dataclass(frozen=True, slots=True)
class SampleChange:
    """One sample that scored differently under the candidate."""

    sample_id: str
    #: Characters that leaked before and no longer do. Positive is an
    #: improvement, because these are characters that would have left.
    leak_fixed: int = 0
    #: Characters that leak now and did not before. This should be zero for a
    #: candidate that only adds detections, and a non-zero value is a finding
    #: rather than a rounding error.
    leak_introduced: int = 0
    #: Ordinary characters newly replaced. The cost side.
    over_redaction_added: int = 0
    #: Ordinary characters no longer replaced.
    over_redaction_removed: int = 0

    @property
    def is_improvement(self) -> bool:
        return self.leak_fixed > 0 and self.leak_introduced == 0

    @property
    def is_regression(self) -> bool:
        return self.leak_introduced > 0

    def describe(self) -> str:
        parts: list[str] = []
        if self.leak_fixed:
            parts.append(f"-{self.leak_fixed} leaked")
        if self.leak_introduced:
            parts.append(f"+{self.leak_introduced} LEAKED")
        if self.over_redaction_added:
            parts.append(f"+{self.over_redaction_added} over-redacted")
        if self.over_redaction_removed:
            parts.append(f"-{self.over_redaction_removed} over-redacted")
        return ", ".join(parts)


@dataclass(frozen=True, slots=True)
class Comparison:
    """A baseline and a candidate, over the same dataset."""

    baseline: EvaluationReport
    candidate: EvaluationReport
    baseline_name: str = "baseline"
    candidate_name: str = "candidate"
    changes: tuple[SampleChange, ...] = field(default_factory=tuple)

    @property
    def leak_delta(self) -> float:
        """Change in leak rate. Negative is better, and is the point."""
        return self.candidate.leak_rate - self.baseline.leak_rate

    @property
    def over_redaction_delta(self) -> float:
        """Change in over-redaction. Positive is what the improvement cost."""
        return self.candidate.over_redaction_rate - self.baseline.over_redaction_rate

    @property
    def recall_delta(self) -> float:
        return self.candidate.overall.recall - self.baseline.overall.recall

    @property
    def precision_delta(self) -> float:
        return self.candidate.overall.precision - self.baseline.overall.precision

    @property
    def improvements(self) -> tuple[SampleChange, ...]:
        return tuple(c for c in self.changes if c.is_improvement)

    @property
    def regressions(self) -> tuple[SampleChange, ...]:
        """Samples that leak now and did not before.

        For a candidate that only *adds* detections this must be empty, and it
        is worth checking rather than assuming: a detection that overlaps a
        label differently can change which prediction wins overlap resolution,
        and a wider span winning can move a boundary in an unhelpful direction.
        """
        return tuple(c for c in self.changes if c.is_regression)

    @property
    def newly_clean(self) -> tuple[str, ...]:
        """Samples that leaked nothing at all under the candidate."""
        before = {s.sample_id for s in self.baseline.leaking_samples()}
        after = {s.sample_id for s in self.candidate.leaking_samples()}
        return tuple(sorted(before - after))

    @property
    def still_leaking(self) -> tuple[str, ...]:
        return tuple(sorted(s.sample_id for s in self.candidate.leaking_samples()))

    @property
    def is_worth_it(self) -> bool:
        """A blunt heuristic, offered as a starting point and nothing more.

        A candidate earns its place if it covers characters that would have
        left the machine and introduces none. Whether the over-redaction it
        costs is acceptable is a judgement about a deployment, not a number
        this module can compute, so it deliberately does not appear here.
        """
        return self.leak_delta < 0 and not self.regressions

    def as_mapping(self) -> dict[str, object]:
        return {
            "dataset": self.candidate.dataset,
            "baseline": {
                "name": self.baseline_name,
                "leak_rate": self.baseline.leak_rate,
                "over_redaction_rate": self.baseline.over_redaction_rate,
                "precision": self.baseline.overall.precision,
                "recall": self.baseline.overall.recall,
            },
            "candidate": {
                "name": self.candidate_name,
                "leak_rate": self.candidate.leak_rate,
                "over_redaction_rate": self.candidate.over_redaction_rate,
                "precision": self.candidate.overall.precision,
                "recall": self.candidate.overall.recall,
            },
            "delta": {
                "leak_rate": self.leak_delta,
                "over_redaction_rate": self.over_redaction_delta,
                "precision": self.precision_delta,
                "recall": self.recall_delta,
            },
            "newly_clean": list(self.newly_clean),
            "still_leaking": list(self.still_leaking),
            "regressions": [
                {"sample_id": c.sample_id, "detail": c.describe()} for c in self.regressions
            ],
            "changed": [{"sample_id": c.sample_id, "detail": c.describe()} for c in self.changes],
        }


def compare(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
    *,
    baseline_name: str = "baseline",
    candidate_name: str = "candidate",
) -> Comparison:
    """Pair two reports over the same dataset.

    Raises:
        ValueError: The reports are not about the same dataset. Comparing
            across datasets would produce deltas that look meaningful and are
            not, which is worse than refusing.
    """
    if baseline.dataset != candidate.dataset:
        raise ValueError(
            f"cannot compare {baseline.dataset!r} with {candidate.dataset!r}: "
            "a delta between different datasets means nothing"
        )

    before = {s.sample_id: s for s in baseline.samples}
    changes: list[SampleChange] = []
    for after in candidate.samples:
        original = before.get(after.sample_id)
        if original is None:
            continue
        change = _change(original, after)
        if change is not None:
            changes.append(change)

    return Comparison(
        baseline=baseline,
        candidate=candidate,
        baseline_name=baseline_name,
        candidate_name=candidate_name,
        changes=tuple(changes),
    )


def _change(before: SampleResult, after: SampleResult) -> SampleChange | None:
    leak = before.leaked_characters - after.leaked_characters
    over = after.over_redacted_characters - before.over_redacted_characters
    if not leak and not over:
        return None
    return SampleChange(
        sample_id=after.sample_id,
        leak_fixed=max(leak, 0),
        leak_introduced=max(-leak, 0),
        over_redaction_added=max(over, 0),
        over_redaction_removed=max(-over, 0),
    )
