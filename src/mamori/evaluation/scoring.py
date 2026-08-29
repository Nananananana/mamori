"""Scoring a detector against labelled data.

Two families of metric are reported, because they answer different questions and
neither one alone is honest.

**Entity level** -- precision, recall and F1 over whole entities. The familiar
numbers, useful for comparing rule sets and for spotting a type nobody covers.

**Character level** -- ``leak_rate`` and ``over_redaction_rate``. These are the
ones that matter here. What a privacy layer is actually judged on is *how many
sensitive characters left the machine* and *how much ordinary text it destroyed
on the way*, not whether an entity boundary was one character out. A detector
that finds ``田中`` inside ``田中太郎`` scores badly on exact entity match and
still leaks two characters; the character metrics say exactly that.

The two also disagree in a useful direction. A detection with the wrong *type*
but the right span is an entity-level miss and a character-level success -- the
value was still removed. When those numbers diverge, the labels or the taxonomy
need looking at, not the rules.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from ..application.results import EntityReport
from ..application.session import PrivacySession
from ..domain.policy import PrivacyPolicy
from ..domain.span import Span
from ..ports.detector import Detector
from .dataset import Annotation, Dataset, Sample

__all__ = [
    "EvaluationReport",
    "MatchMode",
    "SampleResult",
    "TypeScore",
    "evaluate",
    "score_sample",
]


class MatchMode(Enum):
    """How closely a prediction has to line up with a label to count."""

    #: Same type, same span. Strict, and arguably too strict for this domain.
    EXACT = "exact"
    #: Same type, spans overlap at all. The default: catching part of a value
    #: is a different outcome from missing it entirely, and the character
    #: metrics quantify the part that was missed.
    OVERLAP = "overlap"


@dataclass(frozen=True, slots=True)
class TypeScore:
    """Counts for one entity type, or for everything at once."""

    entity_type: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def support(self) -> int:
        """How many labels of this type exist."""
        return self.true_positives + self.false_negatives

    @property
    def predicted(self) -> int:
        return self.true_positives + self.false_positives

    @property
    def precision(self) -> float:
        """Of what was detected, how much was right. 1.0 when nothing was."""
        return self.true_positives / self.predicted if self.predicted else 1.0

    @property
    def recall(self) -> float:
        """Of what should have been detected, how much was. 1.0 when nothing was labelled."""
        return self.true_positives / self.support if self.support else 1.0

    @property
    def f1(self) -> float:
        precision, recall = self.precision, self.recall
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)

    def merged(self, other: TypeScore, entity_type: str | None = None) -> TypeScore:
        return TypeScore(
            entity_type=entity_type or self.entity_type,
            true_positives=self.true_positives + other.true_positives,
            false_positives=self.false_positives + other.false_positives,
            false_negatives=self.false_negatives + other.false_negatives,
        )


@dataclass(frozen=True, slots=True)
class SampleResult:
    """What happened on one sample."""

    sample_id: str
    matched: tuple[tuple[Annotation, EntityReport], ...] = ()
    #: Labels nothing was detected for. These are the leaks.
    missed: tuple[Annotation, ...] = ()
    #: Detections with no label. These cost answer quality, not safety.
    spurious: tuple[EntityReport, ...] = ()
    sensitive_characters: int = 0
    leaked_characters: int = 0
    ordinary_characters: int = 0
    over_redacted_characters: int = 0

    @property
    def is_clean(self) -> bool:
        """True when nothing leaked. Spurious detections are allowed."""
        return self.leaked_characters == 0


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """The result of running a detector over a dataset."""

    dataset: str
    locale: str
    match_mode: MatchMode
    overall: TypeScore
    by_type: dict[str, TypeScore] = field(default_factory=dict)
    samples: tuple[SampleResult, ...] = ()
    sensitive_characters: int = 0
    leaked_characters: int = 0
    ordinary_characters: int = 0
    over_redacted_characters: int = 0

    @property
    def leak_rate(self) -> float:
        """Fraction of labelled sensitive characters that were not covered.

        The headline number. 0.0 means every labelled value was replaced.
        """
        if not self.sensitive_characters:
            return 0.0
        return self.leaked_characters / self.sensitive_characters

    @property
    def coverage(self) -> float:
        """``1 - leak_rate``. What fraction of the sensitive text was removed."""
        return 1.0 - self.leak_rate

    @property
    def over_redaction_rate(self) -> float:
        """Fraction of ordinary characters that were replaced anyway.

        The cost side of the trade. High values mean answers degrade, which is
        how a privacy layer stops being used -- and an unused layer has a leak
        rate of 1.0.
        """
        if not self.ordinary_characters:
            return 0.0
        return self.over_redacted_characters / self.ordinary_characters

    @property
    def clean_samples(self) -> int:
        """Samples where nothing leaked at all."""
        return sum(1 for sample in self.samples if sample.is_clean)

    def leaking_samples(self) -> tuple[SampleResult, ...]:
        """Samples that leaked, worst first. Where to start reading."""
        return tuple(
            sorted(
                (sample for sample in self.samples if not sample.is_clean),
                key=lambda s: (-s.leaked_characters, s.sample_id),
            )
        )


def _covered(spans: Sequence[Span]) -> set[int]:
    return {index for span in spans for index in range(span.start, span.end)}


def _matches(annotation: Annotation, prediction: EntityReport, mode: MatchMode) -> bool:
    if annotation.entity_type != prediction.entity_type:
        return False
    if mode is MatchMode.EXACT:
        return annotation.span == prediction.span
    return annotation.span.overlaps(prediction.span)


def score_sample(
    sample: Sample,
    predictions: Sequence[EntityReport],
    mode: MatchMode = MatchMode.OVERLAP,
) -> SampleResult:
    """Compare one sample's labels against one detector run.

    Matching is greedy and deterministic: labels are considered in offset order,
    and each takes the first still-unclaimed prediction it matches.
    """
    ordered_predictions = sorted(predictions, key=lambda p: (p.span.start, -p.span.length))
    claimed: set[int] = set()
    matched: list[tuple[Annotation, EntityReport]] = []
    missed: list[Annotation] = []

    for annotation in sorted(sample.annotations, key=lambda a: a.span.start):
        for index, prediction in enumerate(ordered_predictions):
            if index in claimed or not _matches(annotation, prediction, mode):
                continue
            claimed.add(index)
            matched.append((annotation, prediction))
            break
        else:
            missed.append(annotation)

    spurious = tuple(
        prediction for index, prediction in enumerate(ordered_predictions) if index not in claimed
    )

    sensitive = sample.sensitive_characters
    predicted_chars = _covered([prediction.span for prediction in ordered_predictions])
    ordinary_count = len(sample.text) - len(sensitive)

    return SampleResult(
        sample_id=sample.id,
        matched=tuple(matched),
        missed=tuple(missed),
        spurious=spurious,
        sensitive_characters=len(sensitive),
        leaked_characters=len(sensitive - predicted_chars),
        ordinary_characters=ordinary_count,
        over_redacted_characters=len(predicted_chars - sensitive),
    )


def evaluate(
    dataset: Dataset,
    *,
    detectors: Sequence[Detector] | None = None,
    locales: Sequence[str] | str | None = None,
    match: MatchMode = MatchMode.OVERLAP,
    min_confidence: float = 0.0,
) -> EvaluationReport:
    """Run a detector configuration over a dataset and score it.

    The detectors run through the real protection pipeline -- normalization,
    detection, span mapping, overlap resolution -- rather than a shortcut, so
    the numbers describe what a caller actually gets. The policy is permissive
    so that credentials are measured rather than refused.

    Args:
        dataset: Labelled samples.
        detectors: Replaces the default detector set entirely.
        locales: Language packs to enable, or ``None`` for all of them.
        match: How closely a prediction must line up with a label.
        min_confidence: Drop predictions below this confidence before scoring.
            Sweeping this traces the precision/recall trade-off of the rules.
    """
    results: list[SampleResult] = []
    by_type: dict[str, TypeScore] = {}
    overall = TypeScore("ALL")

    for sample in dataset:
        with PrivacySession(
            detectors=detectors,
            locales=locales,
            policy=PrivacyPolicy.permissive(),
        ) as session:
            predictions = [
                report
                for report in session.protect(sample.text).entities
                if report.confidence >= min_confidence
            ]

        result = score_sample(sample, predictions, match)
        results.append(result)

        for annotation, _ in result.matched:
            by_type[annotation.entity_type] = by_type.get(
                annotation.entity_type, TypeScore(annotation.entity_type)
            ).merged(TypeScore(annotation.entity_type, true_positives=1))
        for annotation in result.missed:
            by_type[annotation.entity_type] = by_type.get(
                annotation.entity_type, TypeScore(annotation.entity_type)
            ).merged(TypeScore(annotation.entity_type, false_negatives=1))
        for prediction in result.spurious:
            by_type[prediction.entity_type] = by_type.get(
                prediction.entity_type, TypeScore(prediction.entity_type)
            ).merged(TypeScore(prediction.entity_type, false_positives=1))

        overall = overall.merged(
            TypeScore(
                "ALL",
                true_positives=len(result.matched),
                false_positives=len(result.spurious),
                false_negatives=len(result.missed),
            )
        )

    return EvaluationReport(
        dataset=dataset.name,
        locale=dataset.locale,
        match_mode=match,
        overall=overall,
        by_type=dict(sorted(by_type.items())),
        samples=tuple(results),
        sensitive_characters=sum(r.sensitive_characters for r in results),
        leaked_characters=sum(r.leaked_characters for r in results),
        ordinary_characters=sum(r.ordinary_characters for r in results),
        over_redacted_characters=sum(r.over_redacted_characters for r in results),
    )
