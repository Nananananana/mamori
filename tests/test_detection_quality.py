"""Quality floors for the bundled datasets, per stance.

These are regression guards, not targets. They exist so that a rule change which
improves one language and quietly wrecks another cannot land: a rewritten regex
that raises English recall while dropping half the Japanese names turns the
build red instead of shipping.

Both stances are measured, because the trade between them is the point and a
floor on only one half of it would let the other half rot. Read the two sets
together: `recall_first` buys a lower leak rate with a much higher
over-redaction rate, and neither number means anything alone.

The floors sit below the measured values with room to spare. Raise them when a
real improvement lands -- that is the whole ratchet. Do **not** lower one to
make a change pass; if a change costs coverage, that is the finding.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from mamori import MamoriConfig
from mamori.domain.stance import Stance
from mamori.evaluation import EvaluationReport, MatchMode, bundled_datasets, evaluate


@dataclass(frozen=True)
class Floor:
    """The worst a language is allowed to score under one stance."""

    locale: str
    stance: Stance
    max_leak_rate: float
    max_over_redaction: float
    min_recall: float
    min_precision: float

    @property
    def label(self) -> str:
        return f"{self.locale}-{self.stance.value}"


_BALANCED = Stance.BALANCED
_RECALL = Stance.RECALL_FIRST

FLOORS = (
    # Core rules only: anchored, precise, and they miss what has no anchor.
    Floor("ja", _BALANCED, 0.015, 0.02, 0.97, 0.97),
    Floor("en", _BALANCED, 0.035, 0.02, 0.94, 0.97),
    Floor("zh", _BALANCED, 0.050, 0.05, 0.95, 0.90),
    # The shipping default. Leak floors are tight, precision floors are loose,
    # and that asymmetry is the setting doing its job rather than a regression.
    Floor("ja", _RECALL, 0.005, 0.10, 0.97, 0.78),
    Floor("en", _RECALL, 0.015, 0.06, 0.92, 0.85),
    Floor("zh", _RECALL, 0.020, 0.16, 0.95, 0.78),
)


def report_for(locale: str, stance: Stance = Stance.RECALL_FIRST) -> EvaluationReport:
    datasets = bundled_datasets(locale)
    assert datasets, f"no bundled dataset for {locale}"
    return evaluate(datasets[0], detectors=list(MamoriConfig(stance=stance).detectors()))


@pytest.mark.parametrize("floor", FLOORS, ids=lambda f: f.label)
class TestQualityFloors:
    def test_leak_rate(self, floor: Floor) -> None:
        """The share of labelled sensitive characters that nothing covered."""
        report = report_for(floor.locale, floor.stance)
        assert report.leak_rate <= floor.max_leak_rate, (
            f"{floor.label}: {report.leak_rate:.2%} of sensitive characters were not "
            f"covered (floor {floor.max_leak_rate:.2%}); leaking samples: "
            f"{[s.sample_id for s in report.leaking_samples()]}"
        )

    def test_over_redaction(self, floor: Floor) -> None:
        """Ordinary text destroyed. Too much of this and nobody keeps using it."""
        report = report_for(floor.locale, floor.stance)
        assert report.over_redaction_rate <= floor.max_over_redaction, (
            f"{floor.label}: {report.over_redaction_rate:.2%} of ordinary characters "
            f"were replaced (floor {floor.max_over_redaction:.2%})"
        )

    def test_entity_recall(self, floor: Floor) -> None:
        report = report_for(floor.locale, floor.stance)
        assert report.overall.recall >= floor.min_recall

    def test_entity_precision(self, floor: Floor) -> None:
        report = report_for(floor.locale, floor.stance)
        assert report.overall.precision >= floor.min_precision


class TestTheStanceActuallyTrades:
    """The two settings must differ in the direction they claim to.

    A stance that widened coverage without costing anything would mean the
    balanced rules were simply worse, and one that cost something without
    widening coverage would be pure loss. Either is a bug in the tiering.
    """

    @pytest.mark.parametrize("locale", ["ja", "en", "zh"])
    def test_recall_first_never_leaks_more(self, locale: str) -> None:
        """The property the default rests on: wide rules only ever add."""
        wide = report_for(locale, Stance.RECALL_FIRST)
        core = report_for(locale, Stance.BALANCED)
        assert wide.leak_rate <= core.leak_rate

    @pytest.mark.parametrize("locale", ["ja", "en"])
    def test_recall_first_costs_something(self, locale: str) -> None:
        wide = report_for(locale, Stance.RECALL_FIRST)
        core = report_for(locale, Stance.BALANCED)
        assert wide.over_redaction_rate > core.over_redaction_rate

    def test_the_default_is_the_recall_first_one(self) -> None:
        assert MamoriConfig().stance is Stance.RECALL_FIRST

    @pytest.mark.parametrize("locale", ["ja", "zh"])
    def test_nothing_leaks_at_all_under_the_default(self, locale: str) -> None:
        """Where the datasets can currently be satisfied completely, they are."""
        assert report_for(locale).leak_rate == 0.0


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
    """Boundary quality of the core rules, reported separately.

    Overlap matching hides a rule that captures three characters too many. That
    is not a leak, but it is answer quality, so it gets its own floor -- at the
    balanced stance, because a rule matching on shape alone has no business
    being judged on where its boundaries land.
    """

    @pytest.mark.parametrize("locale", ["ja", "en"])
    def test_spans_line_up_with_the_labels(self, locale: str) -> None:
        datasets = bundled_datasets(locale)
        report = evaluate(
            datasets[0],
            detectors=list(MamoriConfig(stance=Stance.BALANCED).detectors()),
            match=MatchMode.EXACT,
        )
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
            report = evaluate(
                dataset, detectors=list(MamoriConfig(stance=Stance.BALANCED).detectors())
            )
            by_id = {sample.id: sample for sample in dataset}
            for leaking in report.leaking_samples():
                assert by_id[leaking.sample_id].note, (
                    f"{dataset.name}/{leaking.sample_id} leaks and has no note explaining it"
                )
