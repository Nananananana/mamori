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
    """The worst a dataset is allowed to score under one stance."""

    dataset: str
    stance: Stance
    max_leak_rate: float
    max_over_redaction: float
    min_recall: float
    min_precision: float

    @property
    def label(self) -> str:
        return f"{self.dataset}-{self.stance.value}"


_BALANCED = Stance.BALANCED
_RECALL = Stance.RECALL_FIRST

FLOORS = (
    # -- assembled prompts ---------------------------------------------------
    # A third scale, added in 0.17. Not longer than a document -- *shaped*
    # differently: passages selected out of notes, headers carrying a file
    # path, and structure that must survive untouched. Over-redaction is the
    # number to watch here rather than the leak rate, because the thing being
    # over-redacted is a content hash or an item id, and a package whose id no
    # longer verifies is indistinguishable from one that was tampered with.
    Floor("en-context", _RECALL, 0.100, 0.020, 0.850, 0.950),
    Floor("ja-context", _RECALL, 0.020, 0.010, 0.950, 0.950),
    Floor("zh-context", _RECALL, 0.020, 0.020, 0.950, 0.850),
    # -- the shipping default ------------------------------------------------
    # Sentence fragments. Anchors are close by and there is little ordinary
    # text, so these are the flattering numbers.
    Floor("en-core", _RECALL, 0.015, 0.020, 0.950, 0.900),
    Floor("ja-core", _RECALL, 0.005, 0.040, 0.970, 0.880),
    Floor("zh-core", _RECALL, 0.020, 0.035, 0.950, 0.860),
    # Documents. The same rules on text at the length people actually send:
    # headings, signature blocks, attendee lists, quoted replies. Leak rates
    # are several times higher and these are the honest ones.
    Floor("en-docs", _RECALL, 0.050, 0.030, 0.850, 0.900),
    Floor("ja-docs", _RECALL, 0.010, 0.030, 0.950, 0.900),
    # 0.15 rewrote the right edge of a Chinese name. The first version of
    # that change was a trade -- half the leaks for 0.06 of precision -- and
    # the floors here were about to be written down that way. Then the
    # precision came back too: three follow-up fixes, each measured on its
    # own, left every number on this row better than 0.14 had them. Leak
    # 4.41% -> 2.37%, recall 0.913 -> 0.978, over-redaction 1.84% -> 1.68%,
    # precision 0.894 -> 0.918. The lesson is that the first measurement of
    # a change is not the last word on it.
    Floor("zh-docs", _RECALL, 0.030, 0.020, 0.960, 0.890),
    # -- anchored rules only -------------------------------------------------
    # en-context leaks 47% here, which is worse than en-docs at 20% and is the
    # clearest measurement in the project of what *selection* costs. A passage
    # chosen out of a note arrives without the salutation, the signature block
    # and the form label that made its values detectable: the anchor stayed
    # behind in the part that was not selected. Assembled prompts need the
    # recall-first default more than prose does, and this row is what says so.
    Floor("en-context", _BALANCED, 0.500, 0.010, 0.450, 0.950),
    Floor("ja-context", _BALANCED, 0.020, 0.010, 0.950, 0.950),
    Floor("zh-context", _BALANCED, 0.020, 0.010, 0.950, 0.950),
    Floor("en-core", _BALANCED, 0.035, 0.010, 0.940, 0.970),
    Floor("ja-core", _BALANCED, 0.015, 0.020, 0.970, 0.950),
    Floor("zh-core", _BALANCED, 0.020, 0.020, 0.950, 0.900),
    # en-docs at 20% is not a typo and not a regression. A fifth of the
    # sensitive characters in an English document have no anchor near them --
    # a name in an attendee list, a name under a sign-off, a name after
    # "Reported by:". It is the strongest evidence in the project for why
    # recall-first is the default, and it is pinned here so that it stays
    # visible rather than being quietly discovered by somebody's deployment.
    Floor("en-docs", _BALANCED, 0.250, 0.010, 0.650, 0.970),
    Floor("ja-docs", _BALANCED, 0.010, 0.010, 0.950, 0.950),
    Floor("zh-docs", _BALANCED, 0.030, 0.015, 0.960, 0.950),
)


def report_for(dataset: str, stance: Stance = Stance.RECALL_FIRST) -> EvaluationReport:
    matches = [d for d in bundled_datasets() if d.name == dataset]
    assert matches, f"no bundled dataset named {dataset}"
    return evaluate(matches[0], detectors=list(MamoriConfig(stance=stance).detectors()))


@pytest.mark.parametrize("floor", FLOORS, ids=lambda f: f.label)
class TestQualityFloors:
    def test_leak_rate(self, floor: Floor) -> None:
        """The share of labelled sensitive characters that nothing covered."""
        report = report_for(floor.dataset, floor.stance)
        assert report.leak_rate <= floor.max_leak_rate, (
            f"{floor.label}: {report.leak_rate:.2%} of sensitive characters were not "
            f"covered (floor {floor.max_leak_rate:.2%}); leaking samples: "
            f"{[s.sample_id for s in report.leaking_samples()]}"
        )

    def test_over_redaction(self, floor: Floor) -> None:
        """Ordinary text destroyed. Too much of this and nobody keeps using it."""
        report = report_for(floor.dataset, floor.stance)
        assert report.over_redaction_rate <= floor.max_over_redaction, (
            f"{floor.label}: {report.over_redaction_rate:.2%} of ordinary characters "
            f"were replaced (floor {floor.max_over_redaction:.2%})"
        )

    def test_entity_recall(self, floor: Floor) -> None:
        report = report_for(floor.dataset, floor.stance)
        assert report.overall.recall >= floor.min_recall

    def test_entity_precision(self, floor: Floor) -> None:
        report = report_for(floor.dataset, floor.stance)
        assert report.overall.precision >= floor.min_precision


class TestTheTwoScalesDisagree:
    """Fragments and documents do not measure the same thing.

    Publishing only the fragment numbers overstated this library for eight
    versions, and the difference is not noise -- it is what a heading, a
    signature block and an attendee list do to a rule set that was tuned on
    one-line samples.
    """

    @pytest.mark.parametrize(("core", "docs"), [("en-core", "en-docs"), ("zh-core", "zh-docs")])
    def test_documents_leak_more_than_fragments(self, core: str, docs: str) -> None:
        assert report_for(docs).leak_rate > report_for(core).leak_rate

    def test_the_anchored_rules_fall_apart_on_english_documents(self) -> None:
        """The evidence for the recall-first default, stated as a test."""
        balanced = report_for("en-docs", Stance.BALANCED)
        recall = report_for("en-docs", Stance.RECALL_FIRST)
        assert balanced.leak_rate > 0.15
        assert recall.leak_rate < balanced.leak_rate / 4


class TestTheStanceActuallyTrades:
    """The two settings must differ in the direction they claim to.

    A stance that widened coverage without costing anything would mean the
    balanced rules were simply worse, and one that cost something without
    widening coverage would be pure loss. Either is a bug in the tiering.
    """

    @pytest.mark.parametrize(
        "dataset", ["ja-core", "en-core", "zh-core", "ja-docs", "en-docs", "zh-docs"]
    )
    def test_recall_first_never_leaks_more(self, dataset: str) -> None:
        """The property the default rests on: wide rules only ever add."""
        assert report_for(dataset, Stance.RECALL_FIRST).leak_rate <= (
            report_for(dataset, Stance.BALANCED).leak_rate
        )

    @pytest.mark.parametrize("dataset", ["ja-core", "en-core", "en-docs"])
    def test_recall_first_costs_something(self, dataset: str) -> None:
        wide = report_for(dataset, Stance.RECALL_FIRST)
        core = report_for(dataset, Stance.BALANCED)
        assert wide.over_redaction_rate > core.over_redaction_rate

    def test_the_default_is_the_recall_first_one(self) -> None:
        assert MamoriConfig().stance is Stance.RECALL_FIRST

    @pytest.mark.parametrize("dataset", ["ja-core", "zh-core"])
    def test_nothing_leaks_at_all_on_the_fragment_sets(self, dataset: str) -> None:
        """Where the corpus can currently be satisfied completely, it is."""
        assert report_for(dataset).leak_rate == 0.0


class TestPerTypeCoverage:
    """Every labelled type must be found at least sometimes.

    A type scoring zero recall means a rule is missing or broken, and the
    overall average will happily hide it behind the types that do work.
    """

    @pytest.mark.parametrize("dataset", ["ja-core", "en-core", "ja-docs", "en-docs"])
    def test_no_primary_type_is_completely_unfound(self, dataset: str) -> None:
        report = report_for(dataset)
        dead = [
            name for name, score in report.by_type.items() if score.support and not score.recall
        ]
        assert not dead, f"{dataset}: no detection at all for {dead}"

    @pytest.mark.parametrize("dataset", ["ja-core", "en-core", "ja-docs", "en-docs"])
    def test_the_common_types_are_reliable(self, dataset: str) -> None:
        """EMAIL and PHONE carry most real traffic and have no excuse."""
        report = report_for(dataset)
        for type_name in ("EMAIL", "PHONE"):
            score = report.by_type.get(type_name)
            assert score is not None and score.recall == 1.0, f"{dataset}/{type_name}"


class TestExactMatchIsTracked:
    """Boundary quality of the core rules, reported separately.

    Overlap matching hides a rule that captures three characters too many. That
    is not a leak, but it is answer quality, so it gets its own floor -- at the
    balanced stance, because a rule matching on shape alone has no business
    being judged on where its boundaries land.
    """

    @pytest.mark.parametrize("locale", ["ja", "en"])
    def test_spans_line_up_with_the_labels(self, locale: str) -> None:
        fragments = next(d for d in bundled_datasets(locale) if d.name.endswith("-core"))
        report = evaluate(
            fragments,
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
