"""The audit trail: what may reach a file, and what may not.

The feature exists for an operator who has to answer *what left this machine
last Tuesday, and under which policy*, and had no way to. The risk it
introduces is the reason it took until 0.30: a privacy library that starts
writing files is one bad field away from writing the values it removed.

So most of what follows is not about the happy path. It is about the four ways
a value could get into that file -- a caller passing something that is not a
record, a record with a field nobody vetted, a schema that stopped matching
`provenance`, and the sink itself being handed a free-text message -- and
whether each one is refused.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import mamori.provenance as provenance
from mamori import PrivacySession
from mamori.errors import StorageError
from mamori.infrastructure.audit import JsonlAuditSink
from mamori.infrastructure.audit.jsonl import ACCEPTED_CONTRACTS, LINE_FORMAT, SCHEMA
from mamori.infrastructure.storage import InMemoryMappingStore
from mamori.interfaces.cli.main import main as cli
from mamori.ports.audit_sink import AuditSink
from mamori.provenance import (
    CONTRACT,
    CONTRACT_WITH_SURROGATES,
    ProtectionLedger,
    protection_record,
)

NAME = "田中太郎"
ADDRESS = "tanaka@example.com"
TEXT = f"{NAME}さんに {ADDRESS} で連絡してください。電話は 090-1234-5678 です。"


def protect(**kwargs: Any) -> tuple[PrivacySession, Any]:
    session = PrivacySession(**kwargs)
    return session, session.protect(TEXT)


def surrogates_in(store: InMemoryMappingStore, scope: str) -> list[str]:
    """The plausible values protection substituted, read from the store.

    Not from the result: ``EntityReport.surrogate`` is a flag and the value is
    deliberately absent, which is the property being tested. The store is
    passed in by the test rather than reached for through the session, so this
    uses nothing private.
    """
    return [m.surface for m in store.list_scope(scope) if m.is_surrogate]


def lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class Collecting:
    """A sink that keeps what it was given, for testing the ledger alone."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, record: dict[str, Any]) -> None:
        self.records.append(record)


class Broken:
    def record(self, record: dict[str, Any]) -> None:
        raise StorageError("the disk is full")


class TestTheFileNeverHoldsAValue:
    """The property the whole feature is judged on."""

    def test_no_protected_value_reaches_the_bytes(self, tmp_path: Path) -> None:
        """Asserted against the file on disk, not against the record object.
        Everything between the two is what a test on the object would miss."""
        path = tmp_path / "audit.jsonl"
        session, result = protect()
        ProtectionLedger(JsonlAuditSink(path)).record(result, session=session)

        raw = path.read_bytes()
        for secret in (NAME, ADDRESS, "090-1234-5678"):
            assert secret.encode("utf-8") not in raw, f"{secret!r} reached the audit file"

    def test_nor_does_a_surrogate(self, tmp_path: Path) -> None:
        """A surrogate is a plausible value, which makes it the one thing in a
        result that looks safe to write and is not. It is counted, never named.

        The substituted strings are read out of the mapping store, because
        ``EntityReport.surrogate`` is a flag and the value itself is
        deliberately not on the result. Which means this test could pass by
        finding nothing -- so it asserts it found something first.
        """
        path = tmp_path / "audit.jsonl"
        store = InMemoryMappingStore()
        session, result = protect(surrogate_types=["PERSON"], store=store)
        ProtectionLedger(JsonlAuditSink(path)).record(result, session=session)

        substituted = surrogates_in(store, session.scope)
        assert substituted, (
            "no surrogate was substituted, so this checked nothing -- the "
            "assertion below would have looped over an empty list and passed."
        )
        raw = path.read_text(encoding="utf-8")
        for value in substituted:
            assert value not in raw, f"a surrogate reached the audit file: {value!r}"

    def test_a_counted_entry_can_only_ever_carry_a_kind_and_a_count(self, tmp_path: Path) -> None:
        """The structural half of the test above. The one above depends on a
        pool having produced a value; this holds whether or not it did."""
        session, result = protect(surrogate_types=["PERSON"])
        record = protection_record(result, session=session)
        for entry in record["protected"] + record["masked"]:
            assert set(entry) == {"kind", "count"}
            assert isinstance(entry["count"], int)

    def test_the_original_text_is_not_in_it_either(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        session, result = protect()
        ProtectionLedger(JsonlAuditSink(path)).record(result, session=session)
        assert TEXT not in path.read_text(encoding="utf-8")


class TestItRefusesWhatIsNotARecord:
    """A sink that took a message would be a logger with a longer name."""

    def test_a_free_text_message_is_refused(self, tmp_path: Path) -> None:
        sink = JsonlAuditSink(tmp_path / "audit.jsonl")
        with pytest.raises(StorageError, match="and nothing else"):
            sink.record({"message": f"protected {NAME}"})

    def test_nothing_is_written_when_it_refuses(self, tmp_path: Path) -> None:
        """A refusal that had already appended would be the leak itself."""
        path = tmp_path / "audit.jsonl"
        with pytest.raises(StorageError):
            JsonlAuditSink(path).record({"message": NAME})
        assert not path.exists()

    def test_an_unknown_contract_is_refused(self, tmp_path: Path) -> None:
        sink = JsonlAuditSink(tmp_path / "audit.jsonl")
        with pytest.raises(StorageError, match="ADR 0032"):
            sink.record({"contract": "mamori.protection-scope/2"})

    def test_a_vetted_record_with_one_extra_field_is_refused(self, tmp_path: Path) -> None:
        """The realistic leak. Not somebody passing a string -- somebody adding
        `"sample"` or `"original"` to a document that is otherwise correct,
        because it was useful and the sink took it."""
        session, result = protect()
        record = protection_record(result, session=session)
        record["sample"] = NAME

        with pytest.raises(StorageError, match="the contract does not define"):
            JsonlAuditSink(tmp_path / "audit.jsonl").record(record)

    def test_the_refusal_names_the_field(self, tmp_path: Path) -> None:
        session, result = protect()
        record = protection_record(result, session=session)
        record["original_text"] = TEXT
        with pytest.raises(StorageError) as raised:
            JsonlAuditSink(tmp_path / "audit.jsonl").record(record)
        assert "original_text" in str(raised.value)
        assert TEXT not in str(raised.value), "the refusal quoted the value it refused"

    def test_a_non_mapping_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(StorageError, match="must be a mapping"):
            JsonlAuditSink(tmp_path / "audit.jsonl").record(["not", "a", "record"])  # type: ignore[arg-type]

    def test_the_schema_itself_is_enforced_and_not_just_the_field_names(
        self, tmp_path: Path
    ) -> None:
        """`protected` non-empty under the plain contract is exactly the case
        the schema's `if`/`then` exists for, and it is the one a field-name
        check cannot see."""
        pytest.importorskip("jsonschema")
        session, result = protect()
        record = protection_record(result, session=session)
        record["contract"] = CONTRACT
        record["protected"] = [{"kind": "PERSON", "count": 1}]

        with pytest.raises(StorageError, match="does not validate"):
            JsonlAuditSink(tmp_path / "audit.jsonl").record(record)


class TestTheCopyOfTheSchemaIsTheSameSchema:
    """The sink loads the contract from package data rather than importing
    `provenance`, because infrastructure may not reach it. That is a layering
    fix that creates a drift risk, and these are what make the risk checkable
    instead of a comment saying it should be fine."""

    def test_the_schema_matches(self) -> None:
        assert SCHEMA == provenance.SCHEMA

    def test_the_accepted_identifiers_are_the_published_ones(self) -> None:
        assert ACCEPTED_CONTRACTS == {CONTRACT, CONTRACT_WITH_SURROGATES}

    def test_the_sink_does_not_import_provenance(self) -> None:
        """The rule this arrangement exists to keep. `test_architecture` checks
        it too; this says why, next to the thing it constrains."""
        source = Path(JsonlAuditSink.__module__.replace(".", "/") + ".py")
        text = (Path("src") / source).read_text(encoding="utf-8")
        assert "import provenance" not in text
        assert "from ...provenance" not in text


class TestTheLine:
    def test_one_line_per_protection(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        ledger = ProtectionLedger(JsonlAuditSink(path))
        session = PrivacySession()
        for _ in range(3):
            ledger.record(session.protect(TEXT), session=session)
        assert len(lines(path)) == 3

    def test_it_appends_rather_than_replaces(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        session, result = protect()
        for _ in range(2):
            ProtectionLedger(JsonlAuditSink(path)).record(result, session=session)
        assert len(lines(path)) == 2, "a second sink on the same path truncated the first"

    def test_the_record_sits_inside_an_envelope(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        session, result = protect()
        ProtectionLedger(JsonlAuditSink(path)).record(result, session=session)

        (line,) = lines(path)
        assert line["line"] == LINE_FORMAT
        assert line["record"]["contract"] in ACCEPTED_CONTRACTS

    def test_the_time_is_on_the_envelope_and_not_in_the_record(self, tmp_path: Path) -> None:
        """ADR 0032 says a record states what is derivable from the artifact.
        When a protection happened is not, so the contract does not grow a
        field for it and the sink carries it instead."""
        path = tmp_path / "audit.jsonl"
        session, result = protect()
        ProtectionLedger(JsonlAuditSink(path)).record(result, session=session)

        (line,) = lines(path)
        assert "at" in line
        assert "at" not in line["record"]
        assert "at" not in SCHEMA["properties"]

    def test_the_time_is_utc_whatever_the_clock_says(self, tmp_path: Path) -> None:
        """A file that says 09:15 and not which 09:15 is a file two people read
        differently."""
        path = tmp_path / "audit.jsonl"
        tokyo = timezone(timedelta(hours=9))
        moment = datetime(2026, 9, 3, 18, 15, 0, tzinfo=tokyo)
        session, result = protect()
        ProtectionLedger(JsonlAuditSink(path, clock=lambda: moment)).record(result, session=session)

        (line,) = lines(path)
        assert line["at"] == "2026-09-03T09:15:00.000+00:00"

    def test_a_naive_clock_is_read_as_utc_rather_than_guessed(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        moment = datetime(2026, 9, 3, 9, 15, 0)
        session, result = protect()
        ProtectionLedger(JsonlAuditSink(path, clock=lambda: moment)).record(result, session=session)
        assert lines(path)[0]["at"] == "2026-09-03T09:15:00.000+00:00"

    def test_lines_carry_milliseconds(self, tmp_path: Path) -> None:
        """Two protections in the same second are ordinary, and the file has no
        ordering other than the one the lines are in."""
        path = tmp_path / "audit.jsonl"
        session, result = protect()
        ProtectionLedger(JsonlAuditSink(path)).record(result, session=session)
        stamp = lines(path)[0]["at"]
        assert len(stamp.split(".")[1].split("+")[0]) == 3, stamp


class TestTheLedger:
    def test_it_carries_the_deployment_facts_onto_every_record(self) -> None:
        sink = Collecting()
        ledger = ProtectionLedger(sink, by="billing-import/2.1", recall="strict")
        session = PrivacySession()
        for _ in range(2):
            ledger.record(session.protect(TEXT), session=session)

        assert [r["by"] for r in sink.records] == ["billing-import/2.1"] * 2
        assert [r["recall"] for r in sink.records] == ["strict"] * 2

    def test_a_policy_fingerprint_comes_from_the_session(self) -> None:
        sink = Collecting()
        session, result = protect()
        ProtectionLedger(sink).record(result, session=session)
        assert sink.records[0]["policy_hash"].startswith("sha256:")

    def test_no_session_means_no_fingerprint_rather_than_a_default(self) -> None:
        """A record that guesses is worse than one that is silent."""
        sink = Collecting()
        _, result = protect()
        ProtectionLedger(sink).record(result)
        assert "policy_hash" not in sink.records[0]

    def test_no_recall_means_the_record_says_nothing_about_recall(self) -> None:
        sink = Collecting()
        session, result = protect()
        ProtectionLedger(sink).record(result, session=session)
        assert "recall" not in sink.records[0]

    def test_it_counts_what_it_wrote(self) -> None:
        sink = Collecting()
        ledger = ProtectionLedger(sink)
        session = PrivacySession()
        for _ in range(3):
            ledger.record(session.protect(TEXT), session=session)
        assert (ledger.written, ledger.dropped) == (3, 0)


class TestWhatHappensWhenTheSinkFails:
    def test_strict_is_the_default_and_it_raises(self) -> None:
        """An audit trail is worth having because it is complete. One that
        fails open is a file that reads like evidence and is not."""
        session, result = protect()
        with pytest.raises(StorageError, match="disk is full"):
            ProtectionLedger(Broken()).record(result, session=session)

    def test_lenient_keeps_going_and_says_how_much_it_lost(self) -> None:
        session, result = protect()
        ledger = ProtectionLedger(Broken(), strict=False)
        for _ in range(2):
            ledger.record(result, session=session)
        assert (ledger.written, ledger.dropped) == (0, 2)

    def test_the_record_comes_back_even_when_it_was_dropped(self) -> None:
        """So the caller has something left to do with it, and so the return
        value never becomes the way to ask whether the write succeeded."""
        session, result = protect()
        record = ProtectionLedger(Broken(), strict=False).record(result, session=session)
        assert record["contract"] in ACCEPTED_CONTRACTS

    def test_a_missing_directory_is_an_error_and_not_a_created_tree(self, tmp_path: Path) -> None:
        """A mistyped path that quietly makes a directory is how an audit file
        ends up somewhere nobody looks."""
        path = tmp_path / "nope" / "audit.jsonl"
        session, result = protect()
        with pytest.raises(StorageError, match="could not append"):
            ProtectionLedger(JsonlAuditSink(path)).record(result, session=session)
        assert not path.parent.exists()


def test_the_file_writer_satisfies_the_port() -> None:
    assert isinstance(JsonlAuditSink("x.jsonl"), AuditSink)


def test_a_collecting_sink_satisfies_it_too() -> None:
    """The port is structural, so a caller can send records anywhere without
    subclassing anything of ours. If this ever needs an import from mamori,
    the port has stopped being a protocol."""
    assert isinstance(Collecting(), AuditSink)


class TestTheCommandLineFlag:
    """`mamori protect --audit PATH`. The reason the sink is reachable at all
    for somebody who is not writing Python."""

    def read(self, path: Path) -> list[dict[str, Any]]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_it_appends_a_record(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        assert cli(["protect", TEXT, "--audit", str(path)]) == 0
        (line,) = self.read(path)
        assert line["record"]["contract"] in ACCEPTED_CONTRACTS
        assert line["record"]["placeholders"]

    def test_two_runs_are_two_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        for _ in range(2):
            assert cli(["protect", TEXT, "--audit", str(path)]) == 0
        assert len(self.read(path)) == 2

    def test_the_file_holds_no_value_from_the_document(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        cli(["protect", TEXT, "--audit", str(path)])
        raw = path.read_bytes()
        for secret in (NAME, ADDRESS, "090-1234-5678"):
            assert secret.encode("utf-8") not in raw

    def test_audit_by_names_the_pipeline(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        cli(["protect", TEXT, "--audit", str(path), "--audit-by", "billing-import/2.1"])
        assert self.read(path)[0]["record"]["by"] == "billing-import/2.1"

    def test_the_default_by_names_this_mamori(self, tmp_path: Path) -> None:
        import mamori

        path = tmp_path / "audit.jsonl"
        cli(["protect", TEXT, "--audit", str(path)])
        assert self.read(path)[0]["record"]["by"] == f"mamori/{mamori.__version__}"

    def test_the_record_says_which_stance_the_rules_ran_under(self, tmp_path: Path) -> None:
        """`recall` is the field an operator needs to read a row from six
        months ago and know what the detectors were doing. The library cannot
        invent it -- a session does not hold the stance -- but the CLI knows,
        because it built the settings."""
        path = tmp_path / "audit.jsonl"
        cli(["protect", TEXT, "--audit", str(path), "--stance", "balanced"])
        assert self.read(path)[0]["record"]["recall"] == "balanced"

    def test_a_path_that_cannot_be_written_stops_the_command(self, tmp_path: Path) -> None:
        """Strict, and this is what strict is for: the alternative is a run
        that prints protected text, exits 0, and leaves nothing in the file the
        operator turned on in order to have something."""
        path = tmp_path / "nope" / "audit.jsonl"
        assert cli(["protect", TEXT, "--audit", str(path)]) != 0

    def test_a_blocked_document_writes_no_record(self, tmp_path: Path) -> None:
        """Nothing was protected, so there is nothing to say a protection
        happened about. A record here would be a line asserting a protection
        that did not occur."""
        from .credentials import FAKE_AWS_KEY

        path = tmp_path / "audit.jsonl"
        assert cli(["protect", f"key {FAKE_AWS_KEY}", "--audit", str(path)]) == 2
        assert not path.exists()

    def test_it_is_off_unless_asked_for(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole feature is opt-in. A library that started writing files
        because it was upgraded would be the defect, not the feature.

        Run from an empty working directory, because a default path is how
        this would actually go wrong -- not a file appearing in `tmp_path`,
        but one appearing wherever the command happened to be run.
        """
        monkeypatch.chdir(tmp_path)
        assert cli(["protect", TEXT]) == 0
        assert not list(tmp_path.iterdir()), (
            f"protect wrote {[p.name for p in tmp_path.iterdir()]} without being asked"
        )
