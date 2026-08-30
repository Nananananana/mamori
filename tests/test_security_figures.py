"""The figures in SECURITY.md are the ones `mamori eval` prints today.

Proposal 0002 makes this a condition of 1.0: *the figures in SECURITY.md have
data behind them worth the word "measured"*. Two clauses of that are met and
the third has a part that does not wait on anybody -- **the numbers in the
document have to still be the numbers**.

They were not. Three of the twelve rows had drifted, and the sample counts on
three rows with them, because the table is written by hand and the corpus and
the rules keep moving. The worst was `ja-core`: over-redaction 2.78% against a
real 2.44%, precision 0.925 against 0.955. Nothing was wrong except that the
document had stopped being true, quietly, at some release nobody can name.

A published number that no longer holds is the same defect as a check that
cannot fail. It reads as evidence and is a memory of evidence.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from mamori.evaluation import Dataset, bundled_datasets, evaluate

SECURITY = pathlib.Path(__file__).resolve().parent.parent / "SECURITY.md"

#: `| `en-core` | 53 fragments | 0.62% | 0.71% | 0.980 / 0.980 |`
ROW = re.compile(
    r"^\| `(?P<set>[a-z]{2}-\w+)` \| (?P<count>\d+) \w+ \| "
    r"\*{0,2}(?P<leak>[\d.]+)%\*{0,2} \| "
    r"(?P<over>[\d.]+)% \| "
    r"(?P<precision>[\d.]+) / (?P<recall>[\d.]+) \|$",
    re.MULTILINE,
)


def published() -> dict[str, dict[str, float]]:
    text = SECURITY.read_text(encoding="utf-8")
    return {
        match["set"]: {
            "count": float(match["count"]),
            "leak": float(match["leak"]),
            "over": float(match["over"]),
            "precision": float(match["precision"]),
            "recall": float(match["recall"]),
        }
        for match in ROW.finditer(text)
    }


def test_the_table_was_found_at_all() -> None:
    """A regex that silently matches nothing would make every check below pass.

    The count is not pinned to twelve: adding a dataset should not fail here,
    it should fail in the row-by-row test, which says which set is missing.
    """
    rows = published()
    assert rows, "no figures parsed out of SECURITY.md -- has the table changed shape?"


def test_every_bundled_dataset_has_a_row() -> None:
    missing = sorted({dataset.name for dataset in bundled_datasets()} - set(published()))
    assert not missing, f"measured but not published in SECURITY.md: {missing}"


@pytest.mark.parametrize("dataset", bundled_datasets(), ids=lambda d: d.name)
def test_the_published_figures_are_the_measured_ones(dataset: Dataset) -> None:
    row = published().get(dataset.name)
    assert row is not None, f"{dataset.name} is measured and not in SECURITY.md"

    report = evaluate(dataset)
    measured = {
        "count": float(len(dataset.samples)),
        "leak": round(report.leak_rate * 100, 2),
        "over": round(report.over_redaction_rate * 100, 2),
        "precision": round(report.overall.precision, 3),
        "recall": round(report.overall.recall, 3),
    }

    wrong = {k: (row[k], v) for k, v in measured.items() if abs(row[k] - v) > 1e-9}
    assert not wrong, (
        f"SECURITY.md is out of date for {dataset.name}: "
        + ", ".join(f"{k} says {a} and measures {b}" for k, (a, b) in sorted(wrong.items()))
        + ". Run `mamori eval` and copy the numbers, or explain in the document "
        "why the published figure differs from what the tool reports."
    )
