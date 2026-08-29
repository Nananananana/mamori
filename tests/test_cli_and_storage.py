"""The shell interface and the JSON mapping file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
