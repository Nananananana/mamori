"""The shell interface and the JSON mapping file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

from mamori import PrivacySession
from mamori.domain.mapping import Mapping
from mamori.domain.placeholder import Placeholder
from mamori.errors import StorageError
from mamori.infrastructure.storage import InMemoryMappingStore
from mamori.infrastructure.storage.jsonfile import dump_scope, load_scope
from mamori.interfaces.cli.main import main

from .credentials import FAKE_AWS_KEY

SAMPLE = "田中太郎さんへ tanaka@example.com からご連絡がありました。"


class TestInMemoryStore:
    def test_indexes_start_at_one_and_increment(self) -> None:
        store = InMemoryMappingStore()
        assert [store.next_index("s", "PERSON") for _ in range(3)] == [1, 2, 3]

    def test_indexes_are_independent_per_type(self) -> None:
        store = InMemoryMappingStore()
        assert store.next_index("s", "PERSON") == store.next_index("s", "EMAIL") == 1

    def test_indexes_are_independent_per_scope(self) -> None:
        store = InMemoryMappingStore()
        assert store.next_index("a", "PERSON") == store.next_index("b", "PERSON") == 1

    def test_lookup_by_identity_and_by_placeholder(self) -> None:
        store = InMemoryMappingStore()
        mapping = Mapping("s", Placeholder("EMAIL", 1), "EMAIL", "a@example.com", "EMAIL:a")
        store.put(mapping)
        assert store.find_by_identity("s", "EMAIL:a") == mapping
        assert store.find_by_placeholder("s", Placeholder("EMAIL", 1)) == mapping

    def test_a_lookup_in_another_scope_finds_nothing(self) -> None:
        store = InMemoryMappingStore()
        store.put(Mapping("s", Placeholder("EMAIL", 1), "EMAIL", "a@example.com", "EMAIL:a"))
        assert store.find_by_placeholder("other", Placeholder("EMAIL", 1)) is None

    def test_put_is_idempotent(self) -> None:
        store = InMemoryMappingStore()
        mapping = Mapping("s", Placeholder("EMAIL", 1), "EMAIL", "a@example.com", "EMAIL:a")
        store.put(mapping)
        store.put(mapping)
        assert len(store.list_scope("s")) == 1

    def test_purge_is_scoped(self) -> None:
        store = InMemoryMappingStore()
        store.put(Mapping("a", Placeholder("EMAIL", 1), "EMAIL", "x@example.com", "EMAIL:x"))
        store.put(Mapping("b", Placeholder("EMAIL", 1), "EMAIL", "y@example.com", "EMAIL:y"))
        store.purge("a")
        assert store.list_scope("a") == ()
        assert len(store.list_scope("b")) == 1

    def test_purge_resets_the_counters(self) -> None:
        store = InMemoryMappingStore()
        store.next_index("s", "PERSON")
        store.purge("s")
        assert store.next_index("s", "PERSON") == 1


class TestJsonMappingFile:
    def test_round_trip(self, tmp_path: Path) -> None:
        store = InMemoryMappingStore()
        store.put(Mapping("s", Placeholder("EMAIL", 1), "EMAIL", "a@example.com", "EMAIL:a"))
        path = tmp_path / "mapping.json"

        assert dump_scope(store, "s", path) == 1

        loaded = InMemoryMappingStore()
        scope = load_scope(loaded, path)
        assert scope == "s"
        restored = loaded.find_by_placeholder("s", Placeholder("EMAIL", 1))
        assert restored is not None
        assert restored.original_value == "a@example.com"

    def test_resuming_a_conversation_does_not_reuse_a_number(self, tmp_path: Path) -> None:
        """`load` then `protect` used to answer about the wrong person.

        The counter lived beside the mappings and no load touched it. So a
        saved conversation holding `<EMAIL_001>` was read back, the next
        address was minted as `<EMAIL_001>` **again**, the put replaced the
        first mapping, and every earlier use of that token now restored to the
        second value. Nothing reported anything: `unknown` was empty and
        `is_clean` was true, because the placeholder was perfectly well known
        -- it just meant somebody else now.

        Resuming a saved conversation is the entire reason `mamori dump` and
        `mamori load` exist, so this was the flow they were built for.
        """
        path = tmp_path / "mapping.json"
        first = InMemoryMappingStore()
        with PrivacySession(store=first, scope="c1") as session:
            session.protect("mail alice@a.example.com")
            # Inside the block: leaving it purges the scope, and a dump of
            # nothing would load nothing and reuse no number, so this test
            # would pass by having no subject.
            assert dump_scope(first, "c1", path) == 1

        resumed = InMemoryMappingStore()
        load_scope(resumed, path, "c1")
        with PrivacySession(store=resumed, scope="c1") as session:
            protected = session.protect("mail bob@b.example.com")
            assert "<EMAIL_002>" in protected.protected_text, (
                "the resumed conversation minted a number the loaded file already used"
            )
            assert session.restore("<EMAIL_001>").text == "alice@a.example.com"
            assert session.restore("<EMAIL_002>").text == "bob@b.example.com"

    def test_the_file_carries_a_plaintext_warning(self, tmp_path: Path) -> None:
        store = InMemoryMappingStore()
        store.put(Mapping("s", Placeholder("EMAIL", 1), "EMAIL", "a@example.com", "EMAIL:a"))
        path = tmp_path / "mapping.json"
        dump_scope(store, "s", path)
        assert "plain text" in json.loads(path.read_text(encoding="utf-8"))["warning"]

    def test_an_unknown_format_version_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "mapping.json"
        path.write_text(json.dumps({"format_version": 99}), encoding="utf-8")
        with pytest.raises(StorageError):
            load_scope(InMemoryMappingStore(), path)

    def test_a_malformed_placeholder_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "mapping.json"
        path.write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "scope": "s",
                    "mappings": [{"placeholder": "not-a-placeholder", "original_value": "x"}],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(StorageError):
            load_scope(InMemoryMappingStore(), path)

    def test_a_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(StorageError):
            load_scope(InMemoryMappingStore(), tmp_path / "nope.json")


class TestCli:
    def test_inspect_reports_without_emitting_a_protected_text(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["inspect", SAMPLE]) == 0
        out = capsys.readouterr().out
        assert "EMAIL" in out
        assert "<EMAIL_001>" in out
        assert "tanaka@example.com" not in out

    def test_inspect_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["inspect", "--json", SAMPLE]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert {e["type"] for e in payload["entities"]} >= {"EMAIL", "PERSON"}
        assert all("tanaka@example.com" not in json.dumps(e) for e in payload["entities"])

    def test_inspect_reports_credentials_instead_of_refusing(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["inspect", f"key {FAKE_AWS_KEY}"]) == 0
        assert "API_KEY" in capsys.readouterr().out

    def test_inspect_on_clean_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["inspect", "nothing to see here"]) == 0
        assert "no sensitive values" in capsys.readouterr().out

    def test_protect_prints_the_protected_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["protect", SAMPLE]) == 0
        out = capsys.readouterr().out
        assert "<EMAIL_001>" in out
        assert "tanaka@example.com" not in out

    def test_protect_exits_non_zero_and_prints_nothing_when_blocked(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["protect", f"key {FAKE_AWS_KEY}"]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "blocked" in captured.err
        assert FAKE_AWS_KEY not in captured.err

    def test_permissive_lets_a_blocked_document_through(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["protect", "--permissive", f"key {FAKE_AWS_KEY}"]) == 0
        assert FAKE_AWS_KEY not in capsys.readouterr().out

    def test_protect_reads_a_file(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        source = tmp_path / "draft.txt"
        source.write_text(SAMPLE, encoding="utf-8")
        assert main(["protect", "-f", str(source)]) == 0
        assert "<EMAIL_001>" in capsys.readouterr().out

    def test_protect_then_restore_across_two_invocations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mapping = tmp_path / "mapping.json"
        assert main(["protect", "--save-mapping", str(mapping), SAMPLE]) == 0
        protected = capsys.readouterr().out.strip()

        assert main(["restore", "--mapping", str(mapping), protected]) == 0
        assert capsys.readouterr().out.strip() == SAMPLE

    def test_restore_warns_about_an_unknown_placeholder(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mapping = tmp_path / "mapping.json"
        main(["protect", "--save-mapping", str(mapping), SAMPLE])
        capsys.readouterr()

        assert main(["restore", "--mapping", str(mapping), "<PERSON_999> said hello"]) == 0
        assert "unrecognised" in capsys.readouterr().err

    def test_restore_reports_recovery_from_tampering(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mapping = tmp_path / "mapping.json"
        main(["protect", "--save-mapping", str(mapping), SAMPLE])
        capsys.readouterr()

        assert main(["restore", "--mapping", str(mapping), "EMAIL_1 replied"]) == 0
        captured = capsys.readouterr()
        assert "tanaka@example.com" in captured.out
        assert "altered" in captured.err

    def test_policy_lists_the_actions(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["policy"]) == 0
        out = capsys.readouterr().out
        assert "API_KEY" in out and "block" in out
        assert "fail-closed" in out

    def test_demo_runs_a_full_round_trip(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["demo"]) == 0
        out = capsys.readouterr().out
        assert "<PERSON_001>" in out
        assert out.count("田中太郎") >= 2

    def test_a_missing_file_is_an_error_not_a_traceback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["protect", "-f", str(tmp_path / "nope.txt")]) == 1
        assert "error" in capsys.readouterr().err

    def test_no_subcommand_is_a_usage_error(self) -> None:
        with pytest.raises(SystemExit):
            main([])


class TestCliLocales:
    def test_locales_lists_the_packs(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["locales"]) == 0
        out = capsys.readouterr().out
        assert "Japanese" in out and "English" in out and "Chinese" in out

    def test_locales_shows_when_the_chinese_pack_stands_down(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["locales"]) == 0
        assert "not when: kana" in capsys.readouterr().out

    def test_inspect_honours_a_locale_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["inspect", "--locale", "ja", "Dear Jane Doe,"]) == 0
        assert "PERSON" not in capsys.readouterr().out

    def test_inspect_finds_the_name_with_the_right_locale(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["inspect", "--locale", "en", "Dear Jane Doe,"]) == 0
        assert "PERSON" in capsys.readouterr().out

    def test_the_locale_flag_is_repeatable(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["protect", "-l", "ja", "-l", "en", "Dear Jane Doe,"]) == 0
        assert "Jane Doe" not in capsys.readouterr().out

    def test_an_unknown_locale_is_an_error_not_a_traceback(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["inspect", "--locale", "kl", "hello"]) == 1
        assert "unknown locale" in capsys.readouterr().err

    def test_demo_covers_more_than_one_language(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["demo", "--scenario", "roundtrip"]) == 0
        out = capsys.readouterr().out
        assert "ja " in out and "en " in out, "the demo must show both packs firing"
        assert "scripts found:" in out


class TestCliEval:
    def test_eval_reports_the_headline_metrics(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["eval", "--locale", "ja"]) == 0
        out = capsys.readouterr().out
        assert "leak rate" in out
        assert "over-redaction" in out
        assert "ja-core" in out

    def test_eval_covers_every_bundled_dataset_by_default(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["eval"]) == 0
        out = capsys.readouterr().out
        for name in ("ja-core", "en-core", "zh-core"):
            assert name in out

    def test_eval_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["eval", "--locale", "en", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        # By name, not by position: the bundled sets are discovered in sorted
        # order and adding one has moved this index before.
        core = next(entry for entry in payload if entry["dataset"] == "en-core")
        assert 0.0 <= core["leak_rate"] <= 1.0
        assert core["by_type"]

    def test_eval_exact_match_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["eval", "--locale", "ja", "--match", "exact", "--json"]) == 0
        assert json.loads(capsys.readouterr().out)[0]["match"] == "exact"

    def test_eval_show_leaks_names_the_samples(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["eval", "--locale", "en", "--show-leaks"]) == 0
        assert "leaked:" in capsys.readouterr().out

    def test_eval_min_confidence_is_applied(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["eval", "--locale", "ja", "--min-confidence", "1.0", "--json"]) == 0
        strict = json.loads(capsys.readouterr().out)[0]
        assert main(["eval", "--locale", "ja", "--json"]) == 0
        lenient = json.loads(capsys.readouterr().out)[0]
        assert strict["leak_rate"] > lenient["leak_rate"]

    def test_eval_reads_a_dataset_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "d.json"
        path.write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "name": "custom",
                    "locale": "en",
                    "samples": [{"id": "a", "annotated": "Dear [[PERSON:Jane Doe]],"}],
                }
            ),
            encoding="utf-8",
        )
        assert main(["eval", "--dataset", str(path)]) == 0
        assert "custom" in capsys.readouterr().out

    def test_a_locale_with_no_dataset_is_an_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["eval", "--locale", "kl"]) == 1
        assert "no datasets" in capsys.readouterr().err

    def test_a_malformed_dataset_is_an_error_not_a_traceback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        assert main(["eval", "--dataset", str(path)]) == 1
        assert "error" in capsys.readouterr().err


class TestCliConfig:
    def test_config_shows_the_defaults(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["config"]) == 0
        out = capsys.readouterr().out
        assert "(all)" in out
        assert "co-occurrence" in out

    def test_config_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["config", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["default_action"] == "block"
        assert payload["min_confidence"] == 0.0

    def test_flags_win_over_the_defaults(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["config", "--json", "-l", "ja", "--min-confidence", "0.7"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["locales"] == ["ja"]
        assert payload["min_confidence"] == 0.7

    def test_a_config_file_is_read(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "mamori.json"
        path.write_text(json.dumps({"locales": ["en"], "co_occurrence": False}), encoding="utf-8")
        assert main(["config", "--json", "--config", str(path)]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["locales"] == ["en"]
        assert payload["co_occurrence"] is False

    def test_a_flag_beats_the_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "mamori.json"
        path.write_text(json.dumps({"locales": ["en"]}), encoding="utf-8")
        assert main(["config", "--json", "--config", str(path), "-l", "ja"]) == 0
        assert json.loads(capsys.readouterr().out)["locales"] == ["ja"]

    def test_a_bad_config_file_is_an_error_not_a_traceback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "mamori.json"
        path.write_text('{"nope": 1}', encoding="utf-8")
        assert main(["config", "--config", str(path)]) == 1
        assert "unknown configuration key" in capsys.readouterr().err

    def test_protect_honours_the_confidence_floor(self, capsys: pytest.CaptureFixture[str]) -> None:
        text = "张伟先生您好。项目名称: 夜莺。"
        assert main(["protect", "--min-confidence", "0.6", text]) == 0
        assert "夜莺" in capsys.readouterr().out

    def test_protect_honours_the_co_occurrence_toggle(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Japanese: the Chinese fixture stopped isolating propagation in
        # 0.15, when the surname rule began reaching a second mention alone.
        text = "凪沢さんへ\n\n本件は凪沢の担当です。"
        assert main(["protect", "--no-co-occurrence", text]) == 0
        assert "凪沢の担当" in capsys.readouterr().out

        assert main(["protect", text]) == 0
        assert "凪沢の担当" not in capsys.readouterr().out

    def test_inspect_honours_a_config_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "mamori.json"
        path.write_text(json.dumps({"locales": ["ja"]}), encoding="utf-8")
        assert main(["inspect", "--config", str(path), "Dear Jane Doe,"]) == 0
        assert "PERSON" not in capsys.readouterr().out


class TestCliPrompt:
    def test_it_shows_the_external_prompt_by_default(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["prompt"]) == 0
        assert "<PERSON_001>" in capsys.readouterr().out

    def test_it_shows_the_detection_prompt(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["prompt", "detection"]) == 0
        assert "What counts as sensitive" in capsys.readouterr().out

    def test_the_footer_records_version_and_fingerprint(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["prompt", "detection"]) == 0
        err = capsys.readouterr().err
        assert "fingerprint" in err and "guidance rules" in err

    def test_guidance_lists_the_ids(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["prompt", "detection", "--guidance"]) == 0
        out = capsys.readouterr().out
        assert "ja.person.honorific" in out
        assert "disable" in out

    def test_narrowing_the_locale_shortens_it(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["prompt", "detection"]) == 0
        full = len(capsys.readouterr().out)
        assert main(["prompt", "detection", "--locale", "ja"]) == 0
        assert len(capsys.readouterr().out) < full

    def test_an_overlay_from_a_config_file_shows_up(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "mamori.json"
        path.write_text(
            json.dumps(
                {
                    "prompts": {
                        "detection": {
                            "disable": ["en.person.unanchored"],
                            "add": [
                                {"id": "acme.case", "text": "Case numbers look like ACME-12345."}
                            ],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        assert main(["prompt", "detection", "--config", str(path)]) == 0
        out = capsys.readouterr().out
        assert "ACME-12345" in out
        assert "no marker at all" not in out

    def test_an_overlay_marks_local_guidance(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "mamori.json"
        path.write_text(
            json.dumps({"prompts": {"detection": {"add": [{"id": "acme.case", "text": "..."}]}}}),
            encoding="utf-8",
        )
        assert main(["prompt", "detection", "--guidance", "--config", str(path)]) == 0
        assert "*acme.case" in capsys.readouterr().out

    def test_an_unknown_prompt_is_an_error_not_a_traceback(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["prompt", "nope"]) == 1
        assert "unknown prompt" in capsys.readouterr().err


class TestCliStance:
    def test_config_shows_the_stance(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["config", "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["stance"] == "recall_first"

    def test_the_stance_flag_is_honoured(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["config", "--json", "--stance", "balanced"]) == 0
        assert json.loads(capsys.readouterr().out)["stance"] == "balanced"

    def test_protect_finds_more_under_the_default(self, capsys: pytest.CaptureFixture[str]) -> None:
        text = "I spoke to Jane Doe yesterday."
        assert main(["protect", "--stance", "balanced", text]) == 0
        assert "Jane Doe" in capsys.readouterr().out
        assert main(["protect", text]) == 0
        assert "Jane Doe" not in capsys.readouterr().out

    def test_eval_can_score_either_stance(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["eval", "--locale", "ja", "--stance", "balanced", "--json"]) == 0
        balanced = json.loads(capsys.readouterr().out)[0]
        assert main(["eval", "--locale", "ja", "--json"]) == 0
        recall = json.loads(capsys.readouterr().out)[0]
        assert recall["leak_rate"] <= balanced["leak_rate"]
        assert recall["over_redaction_rate"] >= balanced["over_redaction_rate"]


class TestCliLlm:
    """``mamori llm`` answers "where is the model, and will it be used".

    Both halves matter. A team pointing this at a server down the hall needs to
    see that the address was accepted before they send a document through it,
    and a team that accidentally aimed it at a public API needs to find that
    out here rather than never.
    """

    @staticmethod
    def _config(tmp_path: Path, llm: dict[str, object]) -> str:
        path = tmp_path / "mamori.json"
        path.write_text(json.dumps({"llm": llm}), encoding="utf-8")
        return str(path)

    def test_with_no_model_it_says_so_without_failing(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Patterns-only is a complete configuration, not an error."""
        assert main(["llm"]) == 0
        assert "no model configured" in capsys.readouterr().out

    def test_a_model_on_this_machine_reads_as_local(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = self._config(tmp_path, {"model": "qwen2.5:7b"})
        assert main(["llm", "--config", config]) == 0
        out = capsys.readouterr().out
        assert "loopback (this machine)" in out
        assert "qwen2.5:7b" in out

    def test_a_model_on_the_network_reads_as_remote_and_is_allowed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The in-house server case: a different host, still inside the wall."""
        config = self._config(
            tmp_path, {"model": "qwen2.5:72b", "base_url": "http://llm01.corp:8000/v1/"}
        )
        assert main(["llm", "--config", config]) == 0
        out = capsys.readouterr().out
        assert "private (another machine)" in out
        assert "REFUSED" not in out

    def test_a_public_endpoint_is_reported_as_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The whole point of the boundary, surfaced before any document moves."""
        config = self._config(
            tmp_path, {"model": "gpt-4o", "base_url": "https://api.openai.com/v1/"}
        )
        assert main(["llm", "--config", config]) == 1
        out = capsys.readouterr().out
        assert "REFUSED" in out
        assert "trusted_hosts" in out

    def test_a_declared_host_is_admitted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = self._config(
            tmp_path,
            {
                "model": "qwen2.5:7b",
                "base_url": "https://llm.vendor.example.com/v1/",
                "trusted_hosts": ["llm.vendor.example.com"],
            },
        )
        assert main(["llm", "--config", config]) == 0
        assert "REFUSED" not in capsys.readouterr().out

    def test_json_carries_the_verdict(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = self._config(tmp_path, {"model": "m", "base_url": "http://10.0.4.17:8000/v1/"})
        assert main(["llm", "--config", config, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["host_kind"] == "private"
        assert payload["is_remote"] is True
        assert payload["admitted"] is True

    def test_no_api_key_is_ever_printed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The command names the variable. It must never read it out."""
        monkeypatch.setenv("LLM_KEY_FOR_TEST", "super-secret-value")
        config = self._config(tmp_path, {"model": "m", "api_key_env": "LLM_KEY_FOR_TEST"})
        assert main(["llm", "--config", config]) == 0
        assert main(["llm", "--config", config, "--json"]) == 0
        out = capsys.readouterr().out
        assert "LLM_KEY_FOR_TEST" in out
        assert "super-secret-value" not in out

    def test_config_output_mentions_the_model(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = self._config(tmp_path, {"model": "qwen2.5:7b"})
        assert main(["config", "--config", config]) == 0
        assert "qwen2.5:7b" in capsys.readouterr().out
        assert main(["config", "--json", "--config", config]) == 0
        assert json.loads(capsys.readouterr().out)["llm"]["model"] == "qwen2.5:7b"

    def test_config_json_says_none_when_there_is_no_model(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["config", "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["llm"] is None


class TestEvalTakesTheStanceFromTheConfig:
    """`--stance` used to carry a default, so a config file's stance was thrown
    away and every `mamori eval --config` scored recall-first without saying so.

    A setting that is read and then silently overwritten by a default is worse
    than one that is ignored: the file says balanced, the output says nothing,
    and the numbers are somebody else's. It was found by re-measuring a
    published figure and getting the wrong baseline -- 3.50% where the document
    said 20.02% -- which is the only way it could have been found, because
    nothing in the run mentions a stance at all.
    """

    @staticmethod
    def _config(tmp_path: Path, **values: object) -> str:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"locales": ["en"], **values}), encoding="utf-8")
        return str(path)

    def test_the_config_stance_is_used_when_the_flag_is_absent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            main(["eval", "--locale", "en", "--config", self._config(tmp_path, stance="balanced")])
            == 0
        )
        out = capsys.readouterr().out
        # The wide tier is off, so en-docs leaks a fifth of its sensitive text.
        assert "20.02%" in out, out

    def test_the_flag_still_wins_when_it_is_given(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = self._config(tmp_path, stance="balanced")
        assert main(["eval", "--locale", "en", "--config", config, "--stance", "recall_first"]) == 0
        assert "3.50%" in capsys.readouterr().out

    def test_recall_first_is_still_the_default_with_no_config(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["eval", "--locale", "en"]) == 0
        assert "3.50%" in capsys.readouterr().out

    def test_the_compare_baseline_keeps_everything_but_the_model(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The baseline used to be a fresh default config, which dropped the
        locales along with the model and attributed the difference to the
        model. `MamoriConfig.detectors` carries a docstring about the last time
        a hand-rebuilt pipeline did this."""
        config = self._config(tmp_path, stance="balanced")
        assert main(["eval", "--locale", "en", "--config", config, "--compare"]) == 0
        out = capsys.readouterr().out
        assert "20.02%" in out, "the compare baseline lost the stance"


class TestTheCliIsAFilter:
    """`protect` and `restore` write the transformed text and nothing else.

    They used to use `print`, which appends a newline to text that already ends
    with one, so every pass grew the document by a byte: protect once and it
    had one extra, restore it and it had two. A round trip was not byte-exact
    and a pipeline accumulated one per hop.

    That is not tidiness. The sibling projects resolve spans back to byte
    offsets in an original document, and a document that gains a byte at every
    stage is one those offsets no longer describe.
    """

    ROUND_TRIPS: ClassVar[list[object]] = [
        pytest.param("a mail from taro@example.com\n", id="trailing newline"),
        pytest.param("a mail from taro@example.com", id="no trailing newline"),
        pytest.param("From: taro@example.com\nTo: hanako@example.com\n", id="several lines"),
        pytest.param("nothing sensitive here", id="nothing detected"),
    ]

    @pytest.mark.parametrize("original", ROUND_TRIPS)
    def test_a_round_trip_is_byte_exact(
        self, original: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        source = tmp_path / "in.txt"
        source.write_text(original, encoding="utf-8")
        mapping = tmp_path / "map.json"

        assert main(["protect", "-f", str(source), "--save-mapping", str(mapping)]) == 0
        protected = tmp_path / "protected.txt"
        protected.write_text(capsys.readouterr().out, encoding="utf-8")

        assert main(["restore", "-f", str(protected), "--mapping", str(mapping)]) == 0
        assert capsys.readouterr().out == original

    def test_protect_does_not_add_a_trailing_newline(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Stated on its own, because the round-trip test would still pass if
        both commands added one and one of them stripped it."""
        source = tmp_path / "in.txt"
        source.write_text("taro@example.com", encoding="utf-8")
        assert main(["protect", "-f", str(source)]) == 0
        assert capsys.readouterr().out == "<EMAIL_001>"
