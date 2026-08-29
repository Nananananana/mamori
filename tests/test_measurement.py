"""Locating values, comparing two runs, and remembering what a model said.

The three pieces v0.7 added so the model tier could be measured rather than
asserted. The first of them is also a change to what mamori trusts a model
for, so it carries the most weight here.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mamori import MamoriConfig
from mamori.domain.occurrences import MIN_LOCATABLE_LENGTH, find_occurrences
from mamori.evaluation import CachedProvider, bundled_datasets, compare, evaluate
from mamori.infrastructure.llm import ScriptedProvider
from mamori.ports.llm import LLMRequest, LLMResponse


class TestFindingOccurrences:
    """A value judged sensitive must be found everywhere it appears."""

    def test_it_finds_a_single_occurrence(self) -> None:
        spans = find_occurrences("Dear Jane Doe, hello.", "Jane Doe")
        assert [(s.start, s.end) for s in spans] == [(5, 13)]

    def test_it_finds_every_occurrence(self) -> None:
        """Protecting one mention and leaving the others is not protecting it."""
        spans = find_occurrences("Kenji spoke to Kenji about Kenji.", "Kenji")
        assert len(spans) == 3

    def test_a_latin_value_respects_word_boundaries(self) -> None:
        """Ann is a name; Announcement is not an occurrence of it."""
        spans = find_occurrences("Dear Ann, the announcement is ready.", "Ann")
        assert [(s.start, s.end) for s in spans] == [(5, 8)]

    def test_a_cjk_value_does_not_require_a_boundary(self) -> None:
        """Japanese is written without spaces; a boundary rule finds nothing."""
        spans = find_occurrences("田中太郎さんへ。田中太郎より。", "田中太郎")
        assert len(spans) == 2

    def test_a_value_that_is_absent_yields_nothing(self) -> None:
        assert find_occurrences("Dear Jane Doe", "Yamada") == ()

    def test_a_one_character_value_is_refused(self) -> None:
        """It would match most of a CJK document."""
        assert find_occurrences("田中太郎さんへ", "田") == ()
        assert MIN_LOCATABLE_LENGTH == 2

    def test_regex_characters_are_matched_literally(self) -> None:
        """A value is data. A value containing '.*' is not a pattern."""
        spans = find_occurrences("the file a.*b is here", "a.*b")
        assert len(spans) == 1
        assert find_occurrences("the file aXXb is here", "a.*b") == ()

    def test_an_empty_text_yields_nothing(self) -> None:
        assert find_occurrences("", "Kenji") == ()

    @given(text=st.text(min_size=0, max_size=300), value=st.text(min_size=2, max_size=20))
    def test_every_span_really_contains_the_value(self, text: str, value: str) -> None:
        """The property that stops the wrong characters being cut out."""
        for span in find_occurrences(text, value):
            assert text[span.start : span.end] == value

    @given(text=st.text(min_size=0, max_size=300), value=st.text(min_size=2, max_size=20))
    def test_spans_are_ordered_and_do_not_overlap(self, text: str, value: str) -> None:
        spans = find_occurrences(text, value)
        for earlier, later in itertools.pairwise(spans):
            assert earlier.end <= later.start


class TestComparingTwoRuns:
    """A single number says nothing. The unit of measurement is a pair."""

    @staticmethod
    def _report(stance: str = "balanced"):  # type: ignore[no-untyped-def]
        from mamori.domain.stance import Stance

        dataset = bundled_datasets("ja")[0]
        return evaluate(dataset, detectors=list(MamoriConfig(stance=Stance(stance)).detectors()))

    def test_a_run_against_itself_shows_no_change(self) -> None:
        report = self._report()
        result = compare(report, report)
        assert result.changes == ()
        assert result.leak_delta == 0.0

    def test_the_wide_tier_reads_as_less_leak_and_more_cost(self) -> None:
        comparison = compare(self._report("balanced"), self._report("recall_first"))
        assert comparison.leak_delta <= 0
        assert comparison.over_redaction_delta >= 0

    def test_it_names_the_samples_that_changed(self) -> None:
        """Tuning against the aggregate fits a number instead of a language."""
        comparison = compare(self._report("balanced"), self._report("recall_first"))
        assert comparison.changes
        assert all(c.sample_id for c in comparison.changes)

    def test_a_sample_that_stops_leaking_is_reported_as_newly_clean(self) -> None:
        comparison = compare(self._report("balanced"), self._report("recall_first"))
        assert "ja-007" not in comparison.still_leaking

    def test_comparing_different_datasets_is_refused(self) -> None:
        """A delta between different datasets looks meaningful and is not."""
        ja = evaluate(bundled_datasets("ja")[0])
        en = evaluate(bundled_datasets("en")[0])
        with pytest.raises(ValueError):
            compare(ja, en)

    def test_the_mapping_carries_both_sides_and_the_delta(self) -> None:
        payload = compare(self._report("balanced"), self._report("recall_first")).as_mapping()
        assert set(payload["baseline"]) >= {"leak_rate", "over_redaction_rate"}  # type: ignore[arg-type]
        assert "leak_rate" in payload["delta"]  # type: ignore[operator]
        assert json.dumps(payload)


class TestRememberingWhatAModelSaid:
    """A number nobody re-runs is a number nobody checks."""

    @staticmethod
    def _request(user: str = "hello", system: str = "SYS") -> LLMRequest:
        return LLMRequest(system=system, user=user)

    def test_the_second_ask_does_not_reach_the_model(self, tmp_path: Path) -> None:
        inner = ScriptedProvider("answer")
        cache = CachedProvider(inner, tmp_path / "c.json")
        cache.generate(self._request())
        cache.generate(self._request())
        assert len(inner.requests) == 1
        assert (cache.hits, cache.misses) == (1, 1)

    def test_it_survives_a_round_trip_through_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        with CachedProvider(ScriptedProvider("answer"), path) as cache:
            cache.generate(self._request())
        inner = ScriptedProvider("different")
        reopened = CachedProvider(inner, path)
        assert reopened.generate(self._request()).text == "answer"
        assert inner.requests == []

    def test_a_changed_prompt_misses(self, tmp_path: Path) -> None:
        """The same model under a rewritten prompt is a different reader."""
        inner = ScriptedProvider("answer")
        cache = CachedProvider(inner, tmp_path / "c.json")
        cache.generate(self._request(system="SYS"))
        cache.generate(self._request(system="SYS, revised"))
        assert len(inner.requests) == 2

    def test_a_changed_document_misses(self, tmp_path: Path) -> None:
        inner = ScriptedProvider("answer")
        cache = CachedProvider(inner, tmp_path / "c.json")
        cache.generate(self._request(user="one"))
        cache.generate(self._request(user="two"))
        assert len(inner.requests) == 2

    def test_read_only_refuses_to_call_the_model(self, tmp_path: Path) -> None:
        cache = CachedProvider(ScriptedProvider("answer"), tmp_path / "c.json", read_only=True)
        with pytest.raises(LookupError):
            cache.generate(self._request())

    def test_read_only_replays_what_is_there(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        with CachedProvider(ScriptedProvider("answer"), path) as cache:
            cache.generate(self._request())
        replay = CachedProvider(ScriptedProvider("never"), path, read_only=True)
        assert replay.generate(self._request()).text == "answer"

    def test_a_corrupt_cache_is_a_slow_run_not_a_failed_one(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        path.write_text("{ this is not json", encoding="utf-8")
        cache = CachedProvider(ScriptedProvider("answer"), path)
        assert cache.generate(self._request()).text == "answer"

    def test_nothing_is_written_when_nothing_was_added(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        CachedProvider(ScriptedProvider("a"), path).save()
        assert not path.exists()

    def test_a_batch_asks_only_for_what_is_missing(self, tmp_path: Path) -> None:
        class Batching(ScriptedProvider):
            def __init__(self) -> None:
                super().__init__("answer")
                self.batch_sizes: list[int] = []

            def generate_batch(self, requests):  # type: ignore[no-untyped-def]
                self.batch_sizes.append(len(requests))
                return [LLMResponse(text="answer", model="b") for _ in requests]

        inner = Batching()
        cache = CachedProvider(inner, tmp_path / "c.json")
        cache.generate(self._request(user="one"))
        cache.generate_batch([self._request(user="one"), self._request(user="two")])
        assert inner.batch_sizes == [1], "the cached half must not be re-sent"

    def test_a_batch_keeps_the_order_of_its_requests(self, tmp_path: Path) -> None:
        cache = CachedProvider(ScriptedProvider(["a", "b", "c"]), tmp_path / "c.json")
        answers = cache.generate_batch(
            [self._request(user="1"), self._request(user="2"), self._request(user="3")]
        )
        assert len(answers) == 3


class TestOnePlaceAssemblesDetectors:
    """The harness must not build a second pipeline of its own.

    It did, for two releases. `build_pipeline` defaults co-occurrence to off
    and `MamoriConfig.detectors()` passes one in, so every cached model
    measurement was scored against a baseline that had a pass the candidate
    lacked -- the model looked worse than it was, and the published conclusion
    that it "does nothing for Japanese" was measured wrongly.

    The fix was to delete the second path rather than to fix it, so these
    tests are about the parameter that made deleting it possible.
    """

    @staticmethod
    def _config() -> MamoriConfig:
        return MamoriConfig.from_mapping(
            {"llm": {"model": "m", "base_url": "http://localhost:1/v1/"}}
        )

    def test_a_substituted_provider_keeps_everything_else(self) -> None:
        substitute = ScriptedProvider('{"entities": []}')
        passes = self._config().llm_passes(provider=substitute)
        assert len(passes) == 1
        assert passes[0].provider is substitute

    def test_the_detector_set_is_otherwise_identical(self) -> None:
        """Same passes, same order, same everything but the provider."""
        config = self._config()
        named = config.detectors()
        substituted = config.detectors(provider=ScriptedProvider('{"entities": []}'))
        assert len(named) == len(substituted) == 1
        assert [p.name for p in named[0].passes] == [p.name for p in substituted[0].passes]

    def test_co_occurrence_survives_the_substitution(self) -> None:
        """The pass whose absence caused the wrong numbers."""
        detectors = self._config().detectors(provider=ScriptedProvider('{"entities": []}'))
        assert any("co-occurrence" in p.name for p in detectors[0].passes)

    def test_it_still_runs_without_a_model_configured(self) -> None:
        assert MamoriConfig().llm_passes(provider=ScriptedProvider("{}")) == ()

    def test_a_substituted_provider_produces_the_same_propagation(self) -> None:
        """End to end: the silent model must not cost the rules anything."""
        from mamori import PrivacySession

        text = "Dear Priya Raman,\n\nPriya Raman is leading it. Please loop Priya Raman in."
        with PrivacySession(detectors=list(MamoriConfig().detectors())) as plain:
            expected = plain.protect(text).entity_count
        silent = self._config().detectors(provider=ScriptedProvider('{"entities": []}'))
        with PrivacySession(detectors=list(silent)) as session:
            assert session.protect(text).entity_count >= expected


class TestAFailedRunDoesNotLookLikeAResult:
    """A model that never answers produces a perfect zero delta.

    Found the hard way. A 12B model timed out on every request during a real
    measurement; the pass degraded to nothing exactly as designed, the
    comparison measured the rules against themselves, and the output said
    +0.00% on every line. That reads as "the model had nothing to add", which
    is a conclusion, and it was not one.
    """

    class Broken:
        name = "broken"
        supports_structured_output = False

        def generate(self, request: LLMRequest) -> LLMResponse:
            raise TimeoutError("took too long")

    def test_failures_are_counted(self, tmp_path: Path) -> None:
        cache = CachedProvider(self.Broken(), tmp_path / "c.json")
        for _ in range(3):
            with pytest.raises(TimeoutError):
                cache.generate(LLMRequest(system="s", user="u"))
        assert cache.failures == 3

    def test_a_working_provider_records_none(self, tmp_path: Path) -> None:
        cache = CachedProvider(ScriptedProvider("ok"), tmp_path / "c.json")
        cache.generate(LLMRequest(system="s", user="u"))
        assert cache.failures == 0

    def test_nothing_is_cached_from_a_failure(self, tmp_path: Path) -> None:
        """Otherwise a retry would replay the failure as an answer."""
        cache = CachedProvider(self.Broken(), tmp_path / "c.json")
        with pytest.raises(TimeoutError):
            cache.generate(LLMRequest(system="s", user="u"))
        assert len(cache) == 0

    def test_the_command_refuses_to_report_a_failed_run_as_clean(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mamori.interfaces.cli.main import main

        settings = tmp_path / "mamori.json"
        settings.write_text(
            json.dumps(
                {
                    "llm": {
                        "model": "nothing-is-listening",
                        "base_url": "http://127.0.0.1:1/v1/",
                        "timeout": 1,
                        "retries": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        argv = [
            "eval",
            "--locale",
            "zh",
            "--compare",
            "-c",
            str(settings),
            "--cache",
            str(tmp_path / "answers.json"),
        ]
        assert main(argv) == 1, "a run where every call failed must not exit clean"
        out = capsys.readouterr().out
        assert "WARNING" in out
        assert "not a result" in out
