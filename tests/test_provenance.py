"""``mamori.protection-scope/1``: what it says, and what it must never say.

These validate **what mamori actually writes**, serialised and read back, not
a record assembled from value objects in the test. A sibling project froze a
contract whose reference implementation had only ever been checked against
documents built by hand, and the first run against real emitted bytes found a
genuine bug. A schema is a claim about output; check the output.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from mamori import PrivacySession
from mamori.domain.policy import Action, PrivacyPolicy
from mamori.errors import ConfigurationError
from mamori.provenance import (
    CONTRACT,
    CONTRACT_WITH_SURROGATES,
    SCHEMA,
    policy_hash,
    protection_record,
)

JA = "田中太郎さんのメールは tanaka@example.com、電話は 090-1234-5678 です。"
EN = "Contact Jane Doe at jane.doe@example.com or on 555-0142."

VALUES = (
    "田中太郎",
    "tanaka@example.com",
    "090-1234-5678",
    "Jane Doe",
    "jane.doe@example.com",
    "555-0142",
)


def emitted(session: PrivacySession, text: str, **kwargs: object) -> dict[str, Any]:
    """Protect, build the record, and put it through JSON as bytes.

    The round trip is the point. Anything that only holds together as Python
    objects -- a set, a Counter, a dataclass, a non-string key -- fails here
    and not in production.
    """
    result = session.protect(text)
    record = protection_record(result, session=session, **kwargs)  # type: ignore[arg-type]
    raw = json.dumps(record, ensure_ascii=False).encode("utf-8")
    return {"record": json.loads(raw.decode("utf-8")), "raw": raw, "result": result}


class TestWhatMamoriEmitsValidates:
    def test_the_schema_is_itself_valid(self) -> None:
        Draft202012Validator.check_schema(SCHEMA)

    @pytest.mark.parametrize("text", [JA, EN])
    def test_placeholder_mode(self, text: str) -> None:
        out = emitted(PrivacySession(locales=["ja", "en"]), text)
        Draft202012Validator(SCHEMA).validate(out["record"])
        assert out["record"]["mode"] == "placeholder"
        assert out["record"]["protected"] == []

    def test_surrogate_and_mixed_modes(self) -> None:
        session = PrivacySession(locales=["ja"], surrogate_types=["PERSON"])
        out = emitted(session, JA)
        Draft202012Validator(SCHEMA).validate(out["record"])
        # PERSON is surrogated and EMAIL is not, which is the ordinary
        # configuration rather than an edge case: surrogates are enabled per
        # entity type.
        assert out["record"]["mode"] == "mixed"
        assert {"kind": "PERSON", "count": 1} in out["record"]["protected"]
        assert all(p["kind"] != "PERSON" for p in out["record"]["placeholders"])

    def test_masked_values_are_counted_and_reversible_is_false(self) -> None:
        policy = PrivacyPolicy.default().with_rule("PHONE", Action.MASK)
        out = emitted(PrivacySession(locales=["ja"], policy=policy), JA)
        Draft202012Validator(SCHEMA).validate(out["record"])
        assert out["record"]["reversible"] is False
        assert {"kind": "PHONE", "count": 1} in out["record"]["masked"]

    def test_a_document_with_nothing_in_it_still_validates(self) -> None:
        out = emitted(PrivacySession(locales=["en"]), "The meeting is on Tuesday.")
        Draft202012Validator(SCHEMA).validate(out["record"])
        assert out["record"]["mode"] == "placeholder"
        assert out["record"]["reversible"] is True


class TestNothingProtectedGetsOut:
    """The property the whole document exists for."""

    @pytest.mark.parametrize("text", [JA, EN])
    def test_no_original_value_appears_in_the_bytes(self, text: str) -> None:
        out = emitted(PrivacySession(locales=["ja", "en"]), text)
        for value in VALUES:
            assert value.encode("utf-8") not in out["raw"]

    def test_no_surrogate_appears_in_the_bytes(self) -> None:
        """The sharp case. A surrogate is a plausible value sitting in the
        text unannounced; naming it would say which names are invented, and by
        elimination which are real."""
        session = PrivacySession(locales=["ja"], surrogate_types=["PERSON"])
        out = emitted(session, JA)
        substituted = out["result"].protected_text
        # Whatever stands where 田中太郎 stood, it is in the protected text and
        # it must not be in the record. Take it from the text rather than
        # naming it, so this keeps working when the pools change.
        surrogate = substituted[: substituted.index("さん")]
        assert surrogate and surrogate != "田中太郎"
        assert surrogate.encode("utf-8") not in out["raw"]

    def test_the_only_free_text_is_tokens(self) -> None:
        """Structural, so it catches a field nobody thought about.

        Every string in the record is one of: the contract, the producer, the
        scope, the mode, a hash, a stance, a token, or an entity type name.
        A value that got in some other way has nowhere to hide.
        """
        out = emitted(PrivacySession(locales=["ja", "en"]), JA, recall="recall_first")
        record = out["record"]
        accounted = {
            record["contract"],
            record["by"],
            record["scope"],
            record["mode"],
            record.get("recall", ""),
            record.get("policy_hash", ""),
        }
        for item in record["placeholders"]:
            assert item["token"].startswith("<") and item["token"].endswith(">")
            accounted |= {item["token"], item["kind"]}
        for group in ("protected", "masked"):
            for item in record[group]:
                accounted.add(item["kind"])

        def strings(node: object) -> list[str]:
            if isinstance(node, str):
                return [node]
            if isinstance(node, dict):
                return [s for v in node.values() for s in strings(v)]
            if isinstance(node, list):
                return [s for v in node for s in strings(v)]
            return []

        assert set(strings(record)) - {""} <= accounted - {""}


class TestTheInvariantsTheSchemaCannotCheck:
    """JSON Schema 2020-12 cannot compare two properties of one object, so
    these are the consumer's job -- and mamori must not be the one to break
    them."""

    def test_every_token_listed_is_in_the_protected_text(self) -> None:
        out = emitted(PrivacySession(locales=["ja", "en"]), JA)
        for item in out["record"]["placeholders"]:
            assert item["token"] in out["result"].protected_text

    def test_the_record_names_the_scope_it_was_allocated_in(self) -> None:
        session = PrivacySession(locales=["ja"], scope="request-4471")
        out = emitted(session, JA)
        assert out["record"]["scope"] == "request-4471" == out["result"].scope

    @pytest.mark.parametrize(
        ("surrogate_types", "expected"),
        [([], "placeholder"), (["PERSON"], "mixed")],
    )
    def test_mode_is_surrogate_or_mixed_exactly_when_protected_is_not_empty(
        self, surrogate_types: list[str], expected: str
    ) -> None:
        session = PrivacySession(locales=["ja"], surrogate_types=surrogate_types)
        record = emitted(session, JA)["record"]
        assert record["mode"] == expected
        assert bool(record["protected"]) == (record["mode"] in {"surrogate", "mixed"})


class TestTellingOurTokenFromTheUsersOwn:
    """The use that is not convenience.

    ``<PERSON_001>`` is a string a person can type. Without the enumeration a
    consumer seeing one in a quotation has to guess whether it is a protection
    or a literal, and both wrong guesses are quiet.
    """

    def test_a_token_the_user_typed_is_not_claimed_as_ours(self) -> None:
        session = PrivacySession(locales=["en"])
        out = emitted(
            session,
            "The template still says <PERSON_001> here, and Jane Doe signed it.",
        )
        listed = {item["token"]: item["kind"] for item in out["record"]["placeholders"]}

        # The literal the user typed is itself an entity, so it leaves the text
        # under a token of its own. What the record calls <PERSON_001> is then
        # unambiguously the one mamori minted -- for Jane Doe, who was never
        # written down anywhere in it.
        assert listed == {"<TEXT_001>": "TEXT", "<PERSON_001>": "PERSON"}
        assert "<PERSON_001>" in out["result"].protected_text
        assert b"Jane Doe" not in out["raw"]

    def test_every_token_in_the_text_is_accounted_for(self) -> None:
        """Neither direction may be silent: a token in the body that the record
        does not list is a value a consumer cannot attribute, and a token in
        the record that is not in the body describes another document."""
        import re

        out = emitted(PrivacySession(locales=["ja", "en"]), JA)
        in_text = set(re.findall(r"<[A-Z_]+_\d+>", out["result"].protected_text))
        listed = {item["token"] for item in out["record"]["placeholders"]}
        assert in_text == listed


class TestPolicyHashIsOverSettingsOnly:
    """A hash that depends on the document is an oracle for guessing at it."""

    def test_the_same_policy_over_different_documents_hashes_the_same(self) -> None:
        session = PrivacySession(locales=["ja", "en"])
        first = emitted(session, JA)["record"]["policy_hash"]
        second = emitted(session, EN)["record"]["policy_hash"]
        third = emitted(session, "Nothing sensitive at all.")["record"]["policy_hash"]
        assert first == second == third

    def test_a_different_policy_hashes_differently(self) -> None:
        default = policy_hash(PrivacyPolicy.default())
        masked = policy_hash(PrivacyPolicy.default().with_rule("PHONE", Action.MASK))
        surrogates = policy_hash(PrivacyPolicy.default(), surrogate_types=frozenset({"PERSON"}))
        assert len({default, masked, surrogates}) == 3

    def test_it_is_a_named_digest(self) -> None:
        assert policy_hash(PrivacyPolicy.default()).startswith("sha256:")


class TestAScopeMayNotQuoteTheDocument:
    """Otherwise the oracle just moves from ``policy_hash`` to ``scope``.

    The scope is repeated into every place the record goes, on the grounds
    that it carries no content. A caller who names a scope after its subject
    is not reading the docstring that says not to.
    """

    def test_a_scope_containing_a_detected_value_is_refused(self) -> None:
        session = PrivacySession(locales=["ja"], scope="tanaka@example.com-run")
        with pytest.raises(ConfigurationError, match="scope contains a detected"):
            session.protect(JA)

    def test_an_ordinary_scope_is_fine(self) -> None:
        session = PrivacySession(locales=["ja"], scope="nightly-batch-0031")
        assert session.protect(JA).protected_text

    def test_a_very_short_value_does_not_trip_it(self) -> None:
        """Refusing on a one-character collision would teach callers to route
        around the check, which costs more than it buys."""
        session = PrivacySession(locales=["en"], scope="run-a-1")
        assert session.protect("Meeting at 3pm.").protected_text


class TestTheContractIsFrozen:
    def test_the_identifier_is_the_one_consumers_pin(self) -> None:
        assert CONTRACT == "mamori.protection-scope/1"
        assert CONTRACT_WITH_SURROGATES == "mamori.protection-scope/1+surrogate"
        assert SCHEMA["properties"]["contract"]["enum"] == [
            CONTRACT,
            CONTRACT_WITH_SURROGATES,
        ]

    def test_the_record_declares_it(self) -> None:
        out = emitted(PrivacySession(locales=["en"]), EN)
        assert out["record"]["contract"] == CONTRACT

    def test_the_shipped_schema_is_what_validates_the_output(self) -> None:
        """The schema is package data, so a consumer validates against the one
        this version emits rather than one fetched or pinned and drifting."""
        assert SCHEMA["$schema"].endswith("2020-12/schema")
        assert set(SCHEMA["required"]) == {
            "contract",
            "by",
            "scope",
            "reversible",
            "mode",
            "placeholders",
            "protected",
            "masked",
        }

    def test_a_record_built_without_a_session_validates_too(self) -> None:
        result = PrivacySession(locales=["en"]).protect(EN)
        record = protection_record(result, by="iriguchi/0.1.0")
        Draft202012Validator(SCHEMA).validate(json.loads(json.dumps(record)))
        assert record["by"] == "iriguchi/0.1.0"
        assert "recall" not in record  # Absent, not defaulted.


class TestSurrogatesGetTheirOwnContract:
    """The rule a consumer had to remember, turned into a check it already has.

    "A consumer that understands only placeholders must refuse the other modes"
    is obeyed once per consumer, per version, forever. A different contract
    identifier is obeyed zero times: refusing an unrecognised contract is the
    first thing any consumer of this document already does.
    """

    def test_tokens_only_declares_the_plain_contract(self) -> None:
        out = emitted(PrivacySession(locales=["ja", "en"]), JA)
        assert out["record"]["contract"] == CONTRACT

    @pytest.mark.parametrize("surrogate_types", [["PERSON"], ["PERSON", "EMAIL"]])
    def test_any_surrogate_declares_the_other_one(self, surrogate_types: list[str]) -> None:
        session = PrivacySession(locales=["ja"], surrogate_types=surrogate_types)
        out = emitted(session, JA)
        assert out["record"]["contract"] == CONTRACT_WITH_SURROGATES
        Draft202012Validator(SCHEMA).validate(out["record"])

    def test_the_schema_refuses_a_plain_contract_carrying_surrogates(self) -> None:
        """This is invariant 3 moved out of the documentation. Splitting the
        identifier turned a comparison of two properties -- which JSON Schema
        2020-12 cannot do -- into two discrete cases, which it can."""
        forged = {
            "contract": CONTRACT,
            "by": "someone/1.0",
            "scope": "s",
            "reversible": True,
            "mode": "mixed",
            "placeholders": [],
            "protected": [{"kind": "PERSON", "count": 1}],
            "masked": [],
        }
        with pytest.raises(ValidationError):
            Draft202012Validator(SCHEMA).validate(forged)

    def test_the_schema_refuses_the_surrogate_contract_with_no_surrogates(self) -> None:
        forged = {
            "contract": CONTRACT_WITH_SURROGATES,
            "by": "someone/1.0",
            "scope": "s",
            "reversible": True,
            "mode": "placeholder",
            "placeholders": [{"token": "<PERSON_001>", "kind": "PERSON"}],
            "protected": [],
            "masked": [],
        }
        with pytest.raises(ValidationError):
            Draft202012Validator(SCHEMA).validate(forged)


class TestTheIdentifiersAndTheSchemaNameTheSameThing:
    """Five places carry the version of this contract, and they are joined by
    convention.

    `CONTRACT`, the schema's `title`, the filename in its `$id`, the filename
    on disk, and the `enum` a record is validated against. Only the last pair
    was checked. Bumping the contract to `/2` would leave four of them saying
    `1`, every other test would pass -- the emitter validates its output
    against the schema, the schema is internally consistent, and neither knows
    the identifier is written down anywhere else.

    A sibling project found this shape in its own contract and put it as: the
    two halves are joined by convention, and this is the only place they meet.

    The comparison rule has to be written per project, because each joins them
    differently. Here there are two identifiers over one schema, so there is a
    second thing to say: `+surrogate` is a **variant of the same version**, not
    an identifier of its own. If that ever stops being true it needs its own
    schema, and this test is where that argument has to be had.
    """

    @staticmethod
    def _version(text: str) -> str:
        match = re.search(r"protection-scope[-/](\d+)", text)
        assert match, f"no contract version in {text!r}"
        return match.group(1)

    def test_every_place_that_names_a_version_names_the_same_one(self) -> None:
        from mamori.provenance import _SCHEMA_FILE

        versions = {
            "CONTRACT": self._version(CONTRACT),
            "CONTRACT_WITH_SURROGATES": self._version(CONTRACT_WITH_SURROGATES),
            "schema title": self._version(SCHEMA["title"]),
            "schema $id": self._version(SCHEMA["$id"]),
            "filename": self._version(_SCHEMA_FILE),
        }
        assert len(set(versions.values())) == 1, (
            f"the contract version is written in five places and they disagree: "
            f"{versions}. All five move together or none of them do."
        )

    def test_the_surrogate_contract_is_a_variant_and_not_a_second_contract(self) -> None:
        """One schema serves both identifiers, and nothing else says so."""
        assert CONTRACT_WITH_SURROGATES.startswith(CONTRACT + "+"), (
            f"{CONTRACT_WITH_SURROGATES!r} no longer reads as a variant of "
            f"{CONTRACT!r}. Two contracts that are not variants of each other "
            "should not be sharing one schema file."
        )
        assert SCHEMA["properties"]["contract"]["enum"] == [
            CONTRACT,
            CONTRACT_WITH_SURROGATES,
        ], "the schema admits a different set of identifiers than the module exports"

    def test_the_title_is_the_plain_contract(self) -> None:
        """Checked here as well as in CI, because a check that only runs on a
        runner is a check a local run cannot fail."""
        assert SCHEMA["title"] == CONTRACT
