"""The return half of the record, and what it must not carry.

`mamori.protection-scope/1` says what was replaced on the way out. Nothing
said what came back. So a deployment holding an audit trail could show that a
value had been protected and could not show that the answer about it was
restored, that a placeholder came back mangled, or that the answer contained a
token nobody had ever minted -- which is the one thing in the round trip that
is worth an alert.

`mamori.restoration-scope/1` is that half, joined on `scope`. The two together
are the lineage of one round trip -- original, protected, answer, restored --
and neither carries a value.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from mamori import PrivacySession
from mamori.provenance import (
    RESTORATION_CONTRACT,
    RESTORATION_SCHEMA,
    ProtectionLedger,
    protection_record,
    restoration_record,
)

EMAIL = "tanaka@example.com"
NAME = "Jane Doe"
TEXT = f"Mail {EMAIL} and call {NAME} about the invoice."


def round_trip(answer: str = "") -> tuple[dict[str, Any], dict[str, Any], str]:
    """Protect, answer, restore -- and both records, plus the scope."""
    with PrivacySession() as session:
        protected = session.protect(TEXT)
        reply = answer or f"I have emailed {protected.protected_text}"
        restored = session.restore(reply)
        return (
            protection_record(protected, session=session),
            restoration_record(restored, scope=session.scope),
            session.scope,
        )


class TestWhatItEmitsValidates:
    def test_the_schema_is_a_schema(self) -> None:
        Draft202012Validator.check_schema(RESTORATION_SCHEMA)

    def test_an_ordinary_round_trip(self) -> None:
        _, restoration, _ = round_trip()
        Draft202012Validator(RESTORATION_SCHEMA).validate(restoration)

    def test_an_answer_that_mentions_nothing(self) -> None:
        _, restoration, _ = round_trip("Thanks, that is all done.")
        Draft202012Validator(RESTORATION_SCHEMA).validate(restoration)
        assert restoration["restored"] == []
        assert len(restoration["unused"]) == 2, restoration

    def test_an_answer_carrying_a_token_nobody_minted(self) -> None:
        _, restoration, _ = round_trip("Also see <SSN_9> for the rest.")
        Draft202012Validator(RESTORATION_SCHEMA).validate(restoration)
        assert restoration["clean"] is False
        assert restoration["unknown"] == [{"token": "<SSN_009>", "kind": "SSN"}]

    def test_it_survives_a_json_round_trip(self) -> None:
        """A record that only validates in memory is not a record."""
        _, restoration, _ = round_trip()
        Draft202012Validator(RESTORATION_SCHEMA).validate(
            json.loads(json.dumps(restoration, ensure_ascii=False))
        )


class TestNothingRestoredGetsOut:
    """The same test `protection_record` passes: everything in the record is
    derivable from the protected text by somebody who already holds it."""

    @pytest.mark.parametrize(
        "answer",
        [
            "I have emailed <EMAIL_001> and will call <PERSON_001>.",
            "Done: < PERSON _ 001 > and [EMAIL_001].",
            "Nothing to report.",
            "Also <SSN_9> and <PERSON_042>.",
        ],
        ids=["plain", "mangled", "silent", "invented"],
    )
    def test_no_original_value_appears(self, answer: str) -> None:
        _, restoration, _ = round_trip(answer)
        rendered = json.dumps(restoration, ensure_ascii=False)
        assert EMAIL not in rendered
        assert NAME not in rendered
        assert "tanaka" not in rendered

    def test_the_answer_itself_is_not_in_the_record(self) -> None:
        """A restored answer is the sensitive artefact, not evidence about one."""
        _, restoration, _ = round_trip("The invoice for <PERSON_001> is overdue by 40 days.")
        rendered = json.dumps(restoration)
        assert "invoice" not in rendered
        assert "overdue" not in rendered

    def test_a_surface_form_a_model_typed_is_not_in_the_record(self) -> None:
        """`unknown` carries the identity, not the surface.

        `result.unknown` holds `< S S N _ 9 >` as the answer wrote it, which is
        what a person reading a warning needs to see. An audit line is not that
        place: a surface is whatever a model produced, and putting it in a log
        verbatim puts model output into somebody's log. The identity is
        `(TYPE, index)` and is bounded by the placeholder grammar.
        """
        with PrivacySession() as session:
            protected = session.protect(TEXT)
            assert protected.protected_text
            restored = session.restore("see < SSN _ 9 > please")
            assert restored.unknown == ("< SSN _ 9 >",), restored.unknown
            record = restoration_record(restored, scope=session.scope)
        assert "< SSN _ 9 >" not in json.dumps(record)
        assert record["unknown"] == [{"token": "<SSN_009>", "kind": "SSN"}]


class TestTheTwoHalvesJoin:
    def test_they_share_a_scope_and_nothing_else_identifying(self) -> None:
        protection, restoration, scope = round_trip()
        assert protection["scope"] == restoration["scope"] == scope

    def test_a_token_protected_and_then_restored_is_the_same_token(self) -> None:
        """The join that makes the pair a lineage rather than two rows."""
        protection, restoration, _ = round_trip()
        minted = {entry["token"] for entry in protection["placeholders"]}
        returned = {entry["token"] for entry in restoration["restored"]}
        assert returned <= minted, returned - minted
        assert returned, "the answer used no placeholder, so this compared nothing"

    def test_an_unused_token_was_one_that_was_minted(self) -> None:
        protection, restoration, _ = round_trip("Thanks, that is all done.")
        minted = {entry["token"] for entry in protection["placeholders"]}
        unused = {entry["token"] for entry in restoration["unused"]}
        assert unused == minted


class TestTheInvariantTheSchemaCannotCheck:
    def test_tampered_is_a_subset_of_restored(self) -> None:
        _, restoration, _ = round_trip("Done: < PERSON _ 001 > and <EMAIL_001>.")
        restored = {entry["token"] for entry in restoration["restored"]}
        tampered = {entry["token"] for entry in restoration["tampered"]}
        assert tampered, "nothing was mangled, so this checked no subset"
        assert tampered <= restored

    def test_a_token_mentioned_twice_is_recorded_once(self) -> None:
        """A count of mentions would be a shape of the answer's wording."""
        _, restoration, _ = round_trip("<PERSON_001>, <PERSON_001> and <PERSON_001> again.")
        assert restoration["restored"] == [{"token": "<PERSON_001>", "kind": "PERSON"}]


class TestTheContractIsFrozen:
    def test_the_identifier(self) -> None:
        assert RESTORATION_CONTRACT == "mamori.restoration-scope/1"
        assert RESTORATION_SCHEMA["properties"]["contract"]["const"] == RESTORATION_CONTRACT

    def test_the_required_fields(self) -> None:
        """Adding one is a breaking change for every consumer. This is where
        that becomes a decision instead of a diff."""
        assert set(RESTORATION_SCHEMA["required"]) == {
            "contract",
            "by",
            "scope",
            "clean",
            "restored",
            "tampered",
            "unknown",
            "unused",
        }

    def test_no_field_carries_a_free_string(self) -> None:
        """Every token in the record matches the placeholder grammar.

        The pattern is the guarantee: a record cannot carry an arbitrary run
        of text under a key that looks like a token, whoever built it.
        """
        pattern = RESTORATION_SCHEMA["$defs"]["token"]["properties"]["token"]["pattern"]
        assert pattern == r"^<[A-Z][A-Z0-9_]{0,62}_[0-9]{1,6}>$"
        with pytest.raises(Exception):  # noqa: B017 - any validation failure will do
            Draft202012Validator(RESTORATION_SCHEMA).validate(
                {
                    "contract": RESTORATION_CONTRACT,
                    "by": "mamori/0.0.0",
                    "scope": "s",
                    "clean": True,
                    "restored": [{"token": "tanaka@example.com", "kind": "EMAIL"}],
                    "tampered": [],
                    "unknown": [],
                    "unused": [],
                }
            )


class TestTheLedgerWritesBothHalves:
    class Sink:
        def __init__(self) -> None:
            self.rows: list[dict[str, Any]] = []

        def record(self, document: dict[str, Any]) -> None:
            self.rows.append(document)

    def test_one_sink_two_contracts(self) -> None:
        sink = self.Sink()
        ledger = ProtectionLedger(sink, by="billing-import/2.1")
        with PrivacySession() as session:
            protected = session.protect(TEXT)
            ledger.record(protected, session=session)
            ledger.record_restoration(
                session.restore(f"emailed {protected.protected_text}"), scope=session.scope
            )
        assert [row["contract"] for row in sink.rows] == [
            "mamori.protection-scope/1",
            RESTORATION_CONTRACT,
        ]
        assert {row["scope"] for row in sink.rows} == {session.scope}
        assert {row["by"] for row in sink.rows} == {"billing-import/2.1"}
        assert ledger.written == 2

    def test_a_failing_sink_counts_the_return_half_too(self) -> None:
        """The counter is the only thing that says an audit trail has a hole
        in it, and it must not have a hole of its own."""

        class Broken:
            def record(self, document: dict[str, Any]) -> None:
                raise OSError("read-only")

        ledger = ProtectionLedger(Broken(), strict=False)
        with PrivacySession() as session:
            protected = session.protect(TEXT)
            ledger.record(protected, session=session)
            ledger.record_restoration(session.restore("nothing"), scope=session.scope)
        assert ledger.dropped == 2
        assert ledger.written == 0
