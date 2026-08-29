"""Measuring how well the detectors actually work.

Rules are precision/recall trade-offs, and a trade-off nobody measures drifts.
This package turns detector quality into numbers a change can be judged
against, and the bundled datasets pin those numbers in CI so a rule that
improves one language and quietly wrecks another does not land.

    >>> from mamori.evaluation import bundled_datasets, evaluate
    >>> report = evaluate(bundled_datasets("ja")[0])
    >>> round(report.leak_rate, 3) <= 0.2
    True

Read ``leak_rate`` first. It is the fraction of labelled sensitive characters
that were not covered by any detection -- the share of the secret that would
have left the machine.
"""

from __future__ import annotations

from .dataset import (
    DATA_DIR,
    Annotation,
    Dataset,
    Sample,
    bundled_datasets,
    parse_annotated,
)
from .scoring import (
    EvaluationReport,
    MatchMode,
    SampleResult,
    TypeScore,
    evaluate,
    score_sample,
)

__all__ = [
    "DATA_DIR",
    "Annotation",
    "Dataset",
    "EvaluationReport",
    "MatchMode",
    "Sample",
    "SampleResult",
    "TypeScore",
    "bundled_datasets",
    "evaluate",
    "parse_annotated",
    "score_sample",
]
