"""Quality floors for the bundled datasets.

These are regression guards, not targets. They exist so that a rule change which
improves one language and quietly wrecks another cannot land: a rewritten regex
that raises English recall while dropping half the Japanese names turns the
build red instead of shipping.

The floors sit below the measured numbers with room to spare. Raise them when a
real improvement lands -- that is the whole ratchet. Do **not** lower one to
make a change pass; if a change costs coverage, that is the finding.

Japanese and English are the primary targets and carry the tighter floors.
Chinese is secondary: its personal-name rule is known to be weak, and the floor
there says "do not regress", not "this is good".
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from mamori.evaluation import EvaluationReport, MatchMode, bundled_datasets, evaluate


@dataclass(frozen=True)
class Floor:
    """The worst a language is allowed to score."""

    locale: str
    max_leak_rate: float
    max_over_redaction: float
    min_recall: float
    min_precision: float


# Raised in 0.3.0 after the co-occurrence pass: leak rates fell from 1.4% to
# 0.7% (ja), 7.4% to 2.0% (en) and 1.5% to 0.0% (zh), so the old floors no
# longer defended anything.
FLOORS = (
    Floor("ja", max_leak_rate=0.015, max_over_redaction=0.02, min_recall=0.97, min_precision=0.97),
    Floor("en", max_leak_rate=0.035, max_over_redaction=0.02, min_recall=0.94, min_precision=0.97),
    Floor("zh", max_leak_rate=0.05, max_over_redaction=0.05, min_recall=0.95, min_precision=0.90),
)


def report_for(locale: str) -> EvaluationReport:
    datasets = bundled_datasets(locale)
    assert datasets, f"no bundled dataset for {locale}"
    return evaluate(datasets[0])


@pytest.mark.parametrize("floor", FLOORS, ids=lambda f: f.locale)
class TestQualityFloors:
    def test_leak_rate(self, floor: Floor) -> None:
        """The share of labelled sensitive characters that nothing covered."""
        report = report_for(floor.locale)
        assert report.leak_rate <= floor.max_leak_rate, (
            f"{floor.locale}: {report.leak_rate:.2%} of sensitive characters were not "
            f"covered (floor {floor.max_leak_rate:.2%}); leaking samples: "
            f"{[s.sample_id for s in report.leaking_samples()]}"
        )

    def test_over_redaction(self, floor: Floor) -> None:
        """Ordinary text destroyed. Too much of this and nobody keeps using it."""
        report = report_for(floor.locale)
        assert report.over_redaction_rate <= floor.max_over_redaction, (
            f"{floor.locale}: {report.over_redaction_rate:.2%} of ordinary characters "
            f"were replaced (floor {floor.max_over_redaction:.2%})"
        )

    def test_entity_recall(self, floor: Floor) -> None:
        report = report_for(floor.locale)
        assert report.overall.recall >= floor.min_recall

    def test_entity_precision(self, floor: Floor) -> None:
        report = report_for(floor.locale)
        assert report.overall.precision >= floor.min_precision


class TestPerTypeCoverage:
    """Every labelled type must be found at least sometimes.

    A type scoring zero recall means a rule is missing or broken, and the
    overall average will happily hide it behind the types that do work.
    """

    @pytest.mark.parametrize("locale", ["ja", "en"])
    def test_no_primary_type_is_completely_unfound(self, locale: str) -> None:
        report = report_for(locale)
        dead = [
            name for name, score in report.by_type.items() if score.support and not score.recall
        ]
        assert not dead, f"{locale}: no detection at all for {dead}"

    @pytest.mark.parametrize("locale", ["ja", "en"])
    def test_the_common_types_are_reliable(self, locale: str) -> None:
        """EMAIL and PHONE carry most real traffic and have no excuse."""
        report = report_for(locale)
        for type_name in ("EMAIL", "PHONE"):
            score = report.by_type.get(type_name)
            assert score is not None and score.recall == 1.0, f"{locale}/{type_name}"


class TestExactMatchIsTracked:
    """Boundary quality, reported separately so a drift in it is visible.

    Overlap matching hides a rule that captures three characters too many. That
    is not a leak, but it is answer quality, so it gets its own floor.
    """

    @pytest.mark.parametrize("locale", ["ja", "en"])
    def test_spans_line_up_with_the_labels(self, locale: str) -> None:
        datasets = bundled_datasets(locale)
        report = evaluate(datasets[0], match=MatchMode.EXACT)
        assert report.overall.f1 >= 0.93, (
            f"{locale}: exact-match F1 {report.overall.f1:.3f} -- detections are landing "
            "on the right values with the wrong boundaries"
        )


class TestDatasetHygiene:
    """The datasets ship inside the wheel. Nothing real may be in them."""

    def test_no_sample_contains_a_vendor_prefixed_credential(self) -> None:
        forbidden = ("sk-ant-", "sk-proj-", "AKIA", "ghp_", "github_pat_", "xoxb-", "AIza")
        for dataset in bundled_datasets():
            for sample in dataset:
                for marker in forbidden:
                    assert marker not in sample.text, (
                        f"{dataset.name}/{sample.id} contains {marker!r}; a literal "
                        "credential in a shipped file trips every clone's scanner"
                    )

    def test_no_sample_contains_a_private_key_block(self) -> None:
        for dataset in bundled_datasets():
            for sample in dataset:
                assert "PRIVATE KEY-----" not in sample.text

    def test_every_dataset_declares_itself_synthetic(self) -> None:
        for dataset in bundled_datasets():
            assert dataset.source == "synthetic"
            assert dataset.description

    def test_notes_explain_the_hard_cases(self) -> None:
        """A sample that leaks should say why, or the next reader will 'fix' it."""
        for locale in ("ja", "en"):
            dataset = bundled_datasets(locale)[0]
            report = evaluate(dataset)
            by_id = {sample.id: sample for sample in dataset}
            for leaking in report.leaking_samples():
                assert by_id[leaking.sample_id].note, (
                    f"{dataset.name}/{leaking.sample_id} leaks and has no note explaining it"
                )
