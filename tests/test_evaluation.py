"""The evaluation harness itself, and the dataset parser it relies on."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mamori.application.results import EntityReport
from mamori.domain.policy import Action
from mamori.domain.span import Span
from mamori.errors import ConfigurationError
from mamori.evaluation import (
    Dataset,
    MatchMode,
    Sample,
    bundled_datasets,
    evaluate,
    parse_annotated,
    score_sample,
)
from mamori.evaluation.scoring import TypeScore


def prediction(entity_type: str, start: int, end: int, confidence: float = 0.9) -> EntityReport:
    return EntityReport(
        entity_type=entity_type,
        action=Action.ANONYMIZE,
        span=Span(start, end),
        confidence=confidence,
        source="test",
        preview="*",
    )


def dataset_of(*annotated: str) -> Dataset:
    return Dataset.from_payload(
        {
            "format_version": 1,
            "name": "inline",
            "locale": "en",
            "samples": [{"id": f"s{i}", "annotated": a} for i, a in enumerate(annotated)],
        }
    )


class TestParseAnnotated:
    def test_strips_markup_and_computes_spans(self) -> None:
        text, annotations = parse_annotated("Dear [[PERSON:Jane]], hello.")
        assert text == "Dear Jane, hello."
        assert len(annotations) == 1
        assert annotations[0].entity_type == "PERSON"
        assert text[annotations[0].span.start : annotations[0].span.end] == "Jane"

    def test_several_annotations_keep_their_offsets(self) -> None:
        text, annotations = parse_annotated("[[PERSON:Jane]] at [[EMAIL:jane@example.com]] today")
        assert [text[a.span.start : a.span.end] for a in annotations] == [
            "Jane",
            "jane@example.com",
        ]

    def test_offsets_survive_multibyte_text(self) -> None:
        text, annotations = parse_annotated("[[PERSON:田中太郎]]さんへ [[EMAIL:a@b.com]]")
        assert [text[a.span.start : a.span.end] for a in annotations] == ["田中太郎", "a@b.com"]

    def test_text_with_no_markup(self) -> None:
        text, annotations = parse_annotated("nothing to see here")
        assert text == "nothing to see here"
        assert annotations == ()

    def test_annotation_at_the_very_start_and_end(self) -> None:
        text, annotations = parse_annotated("[[PERSON:Ann]] and [[PERSON:Bob]]")
        assert text == "Ann and Bob"
        assert annotations[0].span == Span(0, 3)
        assert annotations[1].span == Span(8, 11)

    def test_an_empty_annotation_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            parse_annotated("[[PERSON:]] hello")

    def test_a_stray_bracket_pair_is_refused(self) -> None:
        """Otherwise a typo silently becomes part of the sample text."""
        with pytest.raises(ConfigurationError):
            parse_annotated("Dear [[PERSON Jane]], hello.")

    def test_a_value_may_contain_a_single_bracket(self) -> None:
        text, annotations = parse_annotated("[[PROJECT_NAME:blue[green]]")
        assert text == "blue[green"
        assert len(annotations) == 1

    def test_annotations_must_not_overlap(self) -> None:
        sample = Sample(
            id="x",
            text="abcdef",
            annotations=parse_annotated("[[PERSON:abc]]def")[1],
        )
        assert sample.sensitive_characters == {0, 1, 2}


class TestDatasetLoading:
    def test_from_payload(self) -> None:
        dataset = dataset_of("Dear [[PERSON:Jane]],")
        assert len(dataset) == 1
        assert dataset.annotation_count == 1
        assert dataset.types() == {"PERSON"}

    def test_ids_are_generated_when_absent(self) -> None:
        dataset = Dataset.from_payload(
            {"format_version": 1, "name": "d", "samples": [{"annotated": "x"}]}
        )
        assert dataset.samples[0].id == "d-000"

    def test_duplicate_ids_are_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="duplicate"):
            Dataset.from_payload(
                {
                    "format_version": 1,
                    "samples": [{"id": "a", "annotated": "x"}, {"id": "a", "annotated": "y"}],
                }
            )

    def test_an_unknown_format_version_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            Dataset.from_payload({"format_version": 99, "samples": []})

    def test_a_sample_without_text_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            Dataset.from_payload({"format_version": 1, "samples": [{"id": "a"}]})

    def test_a_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError):
            Dataset.load(tmp_path / "nope.json")

    def test_round_trip_through_a_file(self, tmp_path: Path) -> None:
        path = tmp_path / "d.json"
        path.write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "name": "d",
                    "locale": "en",
                    "samples": [{"id": "a", "annotated": "Dear [[PERSON:Jane]],"}],
                }
            ),
            encoding="utf-8",
        )
        assert Dataset.load(path).annotation_count == 1


class TestScoreSample:
    def test_a_perfect_match(self) -> None:
        sample = dataset_of("[[PERSON:Jane]] here").samples[0]
        result = score_sample(sample, [prediction("PERSON", 0, 4)])
        assert len(result.matched) == 1
        assert result.missed == ()
        assert result.leaked_characters == 0

    def test_a_missed_label_is_a_leak(self) -> None:
        sample = dataset_of("[[PERSON:Jane]] here").samples[0]
        result = score_sample(sample, [])
        assert len(result.missed) == 1
        assert result.leaked_characters == 4
        assert not result.is_clean

    def test_a_partial_span_counts_as_a_match_and_still_leaks(self) -> None:
        """The whole reason both metric families exist."""
        sample = dataset_of("[[PERSON:Jane Doe]] here").samples[0]
        result = score_sample(sample, [prediction("PERSON", 0, 4)])
        assert len(result.matched) == 1
        assert result.leaked_characters == 4

    def test_exact_mode_refuses_a_partial_span(self) -> None:
        sample = dataset_of("[[PERSON:Jane Doe]] here").samples[0]
        result = score_sample(sample, [prediction("PERSON", 0, 4)], MatchMode.EXACT)
        assert result.missed and result.spurious

    def test_the_right_span_with_the_wrong_type_leaks_nothing(self) -> None:
        """An entity-level miss and a character-level success. Both are true."""
        sample = dataset_of("[[PERSON:Jane]] here").samples[0]
        result = score_sample(sample, [prediction("COMPANY_NAME", 0, 4)])
        assert result.missed and result.spurious
        assert result.leaked_characters == 0

    def test_a_spurious_detection_is_over_redaction(self) -> None:
        sample = dataset_of("nothing here").samples[0]
        result = score_sample(sample, [prediction("PERSON", 0, 7)])
        assert len(result.spurious) == 1
        assert result.over_redacted_characters == 7
        assert result.is_clean

    def test_matching_is_one_to_one(self) -> None:
        """Two predictions over one label must not both count as hits."""
        sample = dataset_of("[[PERSON:Jane Doe]] here").samples[0]
        result = score_sample(sample, [prediction("PERSON", 0, 4), prediction("PERSON", 5, 8)])
        assert len(result.matched) == 1
        assert len(result.spurious) == 1

    def test_matching_is_independent_of_prediction_order(self) -> None:
        sample = dataset_of("[[PERSON:Ann]] and [[PERSON:Bob]]").samples[0]
        forwards = score_sample(sample, [prediction("PERSON", 0, 3), prediction("PERSON", 8, 11)])
        backwards = score_sample(sample, [prediction("PERSON", 8, 11), prediction("PERSON", 0, 3)])
        assert len(forwards.matched) == len(backwards.matched) == 2

    def test_a_sample_with_no_labels_and_no_predictions(self) -> None:
        result = score_sample(dataset_of("plain text").samples[0], [])
        assert result.is_clean
        assert result.over_redacted_characters == 0


class TestTypeScore:
    def test_precision_and_recall(self) -> None:
        score = TypeScore("PERSON", true_positives=3, false_positives=1, false_negatives=1)
        assert score.precision == 0.75
        assert score.recall == 0.75
        assert score.f1 == 0.75
        assert score.support == 4

    def test_nothing_predicted_is_perfect_precision(self) -> None:
        assert TypeScore("PERSON", false_negatives=2).precision == 1.0

    def test_nothing_labelled_is_perfect_recall(self) -> None:
        assert TypeScore("PERSON", false_positives=2).recall == 1.0

    def test_f1_of_a_score_with_nothing_right(self) -> None:
        assert TypeScore("PERSON", false_positives=1, false_negatives=1).f1 == 0.0


class TestEvaluate:
    def test_runs_the_real_pipeline(self) -> None:
        dataset = dataset_of("Dear [[PERSON:Jane Doe]],\n\nsee [[EMAIL:jane@example.com]].")
        report = evaluate(dataset)
        assert report.overall.recall == 1.0
        assert report.leak_rate == 0.0

    def test_credentials_are_measured_rather_than_blocked(self) -> None:
        """A permissive policy, so evaluation reports on what a strict one refuses."""
        dataset = dataset_of("password: [[PASSWORD:hunter2xyz]]")
        report = evaluate(dataset)
        assert report.overall.recall == 1.0

    def test_min_confidence_trades_recall_for_precision(self) -> None:
        dataset = dataset_of("Project: [[PROJECT_NAME:Nightingale]] is on track")
        assert evaluate(dataset).overall.recall == 1.0
        assert evaluate(dataset, min_confidence=0.8).overall.recall == 0.0

    def test_restricting_the_locale_changes_the_result(self) -> None:
        dataset = dataset_of("Dear [[PERSON:Jane Doe]],")
        assert evaluate(dataset, locales=["en"]).leak_rate == 0.0
        assert evaluate(dataset, locales=["ja"]).leak_rate == 1.0

    def test_an_empty_dataset_scores_without_dividing_by_zero(self) -> None:
        report = evaluate(dataset_of())
        assert report.leak_rate == 0.0
        assert report.over_redaction_rate == 0.0
        assert report.coverage == 1.0

    def test_leaking_samples_are_ordered_worst_first(self) -> None:
        dataset = dataset_of(
            "I spoke to [[PERSON:Jane Doe]] yesterday",
            "ask [[PERSON:Bob]] about it",
            "Dear [[PERSON:Ann]],",
        )
        leaking = evaluate(dataset).leaking_samples()
        assert [s.leaked_characters for s in leaking] == sorted(
            (s.leaked_characters for s in leaking), reverse=True
        )

    def test_the_report_names_its_dataset(self) -> None:
        report = evaluate(dataset_of("plain"))
        assert report.dataset == "inline"
        assert report.match_mode is MatchMode.OVERLAP


class TestBundledDatasets:
    def test_all_three_languages_ship(self) -> None:
        assert {d.locale for d in bundled_datasets()} == {"ja", "en", "zh"}

    def test_filtering_by_locale(self) -> None:
        locales = [d.locale for d in bundled_datasets("ja")]
        assert locales and set(locales) == {"ja"}

    def test_an_unknown_locale_yields_nothing(self) -> None:
        assert bundled_datasets("kl") == ()

    def test_every_sample_parses_and_its_spans_line_up(self) -> None:
        for dataset in bundled_datasets():
            for sample in dataset:
                for annotation in sample.annotations:
                    covered = sample.text[annotation.span.start : annotation.span.end]
                    assert covered, f"{dataset.name}/{sample.id} has an empty span"

    def test_no_sample_carries_leftover_markup(self) -> None:
        for dataset in bundled_datasets():
            for sample in dataset:
                assert "[[" not in sample.text
                assert "]]" not in sample.text

    def test_every_dataset_has_enough_ordinary_text_to_measure_against(self) -> None:
        """Without ordinary characters, over-redaction has no denominator.

        Counted in characters rather than in samples, because the two tiers
        supply it differently: the core sets have whole sentences that are
        negative, and the document sets have paragraphs of ordinary prose
        around the values. Both are the same thing to the score.
        """
        for dataset in bundled_datasets():
            sensitive = sum(len(s.sensitive_characters) for s in dataset)
            total = sum(len(s.text) for s in dataset)
            ordinary = total - sensitive
            assert ordinary >= total * 0.4, (
                f"{dataset.name} is {sensitive}/{total} sensitive characters -- "
                "too little ordinary text for over-redaction to mean anything"
            )

    def test_the_primary_languages_are_the_larger_sets(self) -> None:
        """Japanese and English are the primary targets; Chinese is secondary."""
        sizes: dict[str, int] = {}
        for dataset in bundled_datasets():
            sizes[dataset.locale] = sizes.get(dataset.locale, 0) + len(dataset)
        assert sizes["ja"] >= 40
        assert sizes["en"] >= 40
        assert sizes["zh"] >= 20

    def test_both_scales_are_represented(self) -> None:
        """Sentence fragments and documents measure different things.

        A 44-character sample cannot show what a heading does to a name rule,
        what a signature block does to propagation, or what happens to a
        document long enough to be windowed. Measuring only one scale is how
        the rules came to have three bugs that nothing caught for eight
        versions.
        """
        lengths = [len(s.text) for d in bundled_datasets() for s in d]
        assert min(lengths) < 100, "no short samples"
        assert max(lengths) > 800, "no document-scale samples"


class TestToleratedSpans:
    """``[[?TYPE:value]]``: a place the corpus declines to have an opinion.

    The same digit run is an order number to the anchored rules and a possible
    phone number to the wide ones. Both readings are correct for the stance
    that produced them, so scoring either as a mistake publishes a cost that is
    not real. These spans leave both denominators.
    """

    def test_the_marker_is_parsed(self) -> None:
        text, annotations = parse_annotated("Order [[?PHONE:4155550198]] shipped.")
        assert text == "Order 4155550198 shipped."
        assert len(annotations) == 1
        assert annotations[0].tolerated is True
        assert annotations[0].entity_type == "PHONE"

    def test_plain_annotations_are_not_tolerated(self) -> None:
        _, annotations = parse_annotated("Call [[PHONE:415-555-0198]].")
        assert annotations[0].tolerated is False

    def test_required_and_tolerated_are_separated(self) -> None:
        _, annotations = parse_annotated("[[PERSON:Ann]] and [[?PHONE:4155550198]]")
        sample = Sample(id="s", text="x", annotations=annotations)
        assert [a.entity_type for a in sample.required] == ["PERSON"]
        assert [a.entity_type for a in sample.tolerated] == ["PHONE"]

    def test_a_tolerated_span_is_not_required_coverage(self) -> None:
        """Missing one is not a leak."""
        text, annotations = parse_annotated("Order [[?PHONE:4155550198]] shipped.")
        sample = Sample(id="s", text=text, annotations=annotations)
        assert sample.sensitive_characters == frozenset()
        assert sample.tolerated_characters

    def test_finding_one_is_not_over_redaction(self) -> None:
        text, annotations = parse_annotated("Order [[?PHONE:4155550198]] shipped.")
        sample = Sample(id="s", text=text, annotations=annotations)
        found = [prediction("PHONE", 6, 16)]
        score = score_sample(sample, found)
        assert score.over_redacted_characters == 0
        assert score.spurious == ()

    def test_ignoring_one_costs_nothing_either(self) -> None:
        text, annotations = parse_annotated("Order [[?PHONE:4155550198]] shipped.")
        sample = Sample(id="s", text=text, annotations=annotations)
        score = score_sample(sample, [])
        assert score.leaked_characters == 0
        assert score.missed == ()

    def test_a_required_span_next_to_a_tolerated_one_still_counts(self) -> None:
        """Tolerance must not spread to its neighbours."""
        text, annotations = parse_annotated("[[PERSON:Ann]] left order [[?PHONE:4155550198]].")
        sample = Sample(id="s", text=text, annotations=annotations)
        score = score_sample(sample, [])
        assert len(score.missed) == 1
        assert score.leaked_characters == len("Ann")

    def test_the_counts_are_reported_separately(self) -> None:
        dataset = bundled_datasets("en")[0]
        assert dataset.tolerated_count > 0
        assert dataset.annotation_count > dataset.tolerated_count

    def test_the_bundled_sets_use_it_sparingly(self) -> None:
        """A corpus full of tolerated spans measures nothing."""
        for dataset in bundled_datasets():
            required = dataset.annotation_count
            assert dataset.tolerated_count <= required * 0.1, (
                f"{dataset.name}: {dataset.tolerated_count} tolerated against "
                f"{required} required -- the set is becoming an opinion-free zone"
            )

    def test_every_tolerated_span_is_explained(self) -> None:
        """Without a note the next reader deletes the marker as a typo."""
        for dataset in bundled_datasets():
            for sample in dataset:
                if sample.tolerated:
                    assert sample.note, f"{dataset.name}/{sample.id} tolerates a span silently"
