"""Every `mamori.<name>/<n>` in the source is accounted for.

A sibling put the general form well, having found the same defect in three
mechanisms at once:

    Adding a member to a set -- how many mechanisms does that turn red?
    If zero, the set will be silent for the next member too.

Measured here, and the answer was **zero**. Three contract identifiers existed
in `src`, one had a schema, and nothing anywhere noticed. `mamori.audit-line/1`
was written the same day this was measured, published in the README with an
example, and shipped without a schema -- not by an oversight anybody could see,
but because naming a new contract was not a decision the build made anyone
take.

So this file makes it one. A new identifier fails until it is placed in
:data:`DECLARED` below, and placing it means saying which of the two kinds it
is:

    **published**  somebody outside this package may hold one of these
                   documents. It ships a schema, so they can validate without
                   a network fetch or a copy that drifts.
    **internal**   a version marker inside a byte range only mamori reads.
                   No schema, because there is no second party to agree with,
                   and each one says why it is not the first kind.

The distinction is not decorative. It decides whether changing the format is a
release note or a breaking change, and the entry that cannot say which is the
one that will be got wrong.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import mamori

PACKAGE_ROOT = Path(mamori.__file__).parent

#: `mamori.protection-scope/1`, `mamori.audit-line/1`. Deliberately loose about
#: the suffix so that `/1+surrogate` is found too -- a variant identifier is
#: exactly the kind of member that gets added without being declared.
IDENTIFIER = re.compile(r"\bmamori\.[a-z][a-z0-9-]*/\d+[a-z+-]*\b")

#: Every identifier this package defines, and what kind it is. Adding one to
#: the source without adding it here fails, which is the entire point.
DECLARED: dict[str, str] = {
    "mamori.protection-scope/1": "published",
    "mamori.protection-scope/1+surrogate": "published",
    "mamori.audit-line/1": "published",
    # The return half of protection-scope. Published for the same reason and
    # more sharply: a protection record without its restoration record is a
    # visible absence, and a consumer that cannot validate the second half
    # would have to decide for itself what an absent one meant.
    "mamori.restoration-scope/1": "published",
    # A magic string **inside the ciphertext** of an encrypted mapping file.
    # Internal rather than published: nobody but mamori can read the bytes it
    # sits in, so there is no second party for a schema to be an agreement
    # with. It marks the payload version for a future mamori that has to read a
    # file an older one wrote -- which is versioning, not a contract.
    "mamori.encrypted-mapping/1": "internal",
}

#: Which schema file backs each published identifier. Variants of one contract
#: share a document: `/1` and `/1+surrogate` are two cases of the same schema,
#: which is how the schema can say that one has `protected` empty and the other
#: does not.
SCHEMA_FILE = {
    "mamori.protection-scope/1": "protection-scope-1.json",
    "mamori.protection-scope/1+surrogate": "protection-scope-1.json",
    "mamori.audit-line/1": "audit-line-1.json",
    "mamori.restoration-scope/1": "restoration-scope-1.json",
}


def source_files() -> list[Path]:
    return [p for p in sorted(PACKAGE_ROOT.rglob("*.py")) if "__pycache__" not in p.parts]


def found_in_source() -> set[str]:
    found: set[str] = set()
    for path in source_files():
        found |= set(IDENTIFIER.findall(path.read_text(encoding="utf-8")))
    return found


def load(name: str) -> dict[str, Any]:
    from importlib import resources

    text = (resources.files("mamori.schemas") / name).read_text(encoding="utf-8")
    loaded: dict[str, Any] = json.loads(text)
    return loaded


FOUND = sorted(found_in_source())


def test_the_source_was_actually_read() -> None:
    """Every check below is *no identifier is undeclared*, which an empty scan
    satisfies completely."""
    assert len(source_files()) > 50
    assert len(FOUND) >= 3, f"only found {FOUND}; has the naming convention changed?"


@pytest.mark.parametrize("identifier", FOUND)
def test_every_identifier_in_the_source_is_declared(identifier: str) -> None:
    assert identifier in DECLARED, (
        f"{identifier!r} appears in the source and is not declared in this file. "
        "Add it, and say which kind it is: 'published' means somebody outside "
        "this package may hold one of these documents, and it needs a schema "
        "shipped as package data; 'internal' means a version marker inside "
        "bytes only mamori reads, and the entry says why that is so.\n\n"
        "This test exists because the answer to 'how many mechanisms does "
        "adding a contract turn red' was zero, and mamori.audit-line/1 shipped "
        "without a schema the same day."
    )


@pytest.mark.parametrize("identifier", sorted(DECLARED))
def test_every_declared_identifier_is_still_in_the_source(identifier: str) -> None:
    """The other direction. A declaration outliving the thing it declares is a
    registry that reads as current and is a memory."""
    assert identifier in FOUND, (
        f"{identifier!r} is declared here and no longer appears in the source. "
        "If it was removed, remove it here too -- in the same change, so the "
        "two never disagree."
    )


PUBLISHED = sorted(name for name, kind in DECLARED.items() if kind == "published")


@pytest.mark.parametrize("identifier", PUBLISHED)
class TestEveryPublishedContractShipsADocument:
    def test_a_schema_is_shipped_for_it(self, identifier: str) -> None:
        schema = load(SCHEMA_FILE[identifier])
        assert schema["$schema"].endswith("2020-12/schema")

    def test_the_schema_admits_the_identifier(self, identifier: str) -> None:
        """A schema that does not accept the name it is registered under is
        two documents pretending to be one."""
        schema = load(SCHEMA_FILE[identifier])
        rendered = json.dumps(schema, ensure_ascii=False)
        assert identifier in rendered, f"{SCHEMA_FILE[identifier]} never mentions {identifier}"

    def test_it_names_its_encoding(self, identifier: str) -> None:
        """A contract that does not name its encoding is one its own producer
        eventually gets wrong. A sibling wrote its JSON report in the
        platform's locale encoding, could not parse it back, and published a
        hash over bytes that were not in the file -- with nothing violated,
        because nothing had been stated."""
        rendered = json.dumps(load(SCHEMA_FILE[identifier]), ensure_ascii=False)
        assert "UTF-8" in rendered

    def test_the_document_on_disk_is_valid_json_schema(self, identifier: str) -> None:
        pytest.importorskip("jsonschema")
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(load(SCHEMA_FILE[identifier]))


def test_a_shipped_schema_is_not_an_orphan() -> None:
    """The third direction: a schema file nobody registered. It would validate
    nothing, be shipped in every wheel, and read as a contract."""
    from importlib import resources

    shipped = {
        entry.name
        for entry in resources.files("mamori.schemas").iterdir()
        if entry.name.endswith(".json")
    }
    assert shipped == set(SCHEMA_FILE.values()), (
        f"unregistered: {sorted(shipped - set(SCHEMA_FILE.values()))}; "
        f"registered but not shipped: {sorted(set(SCHEMA_FILE.values()) - shipped)}"
    )


def test_a_real_audit_line_validates_against_its_own_schema() -> None:
    """The registry is bookkeeping until something checks the bytes. This
    writes a line the way the sink writes one and validates it, so a schema
    that describes a format nobody emits fails here."""
    pytest.importorskip("jsonschema")
    import tempfile

    from jsonschema import Draft202012Validator

    from mamori import PrivacySession
    from mamori.infrastructure.audit import JsonlAuditSink
    from mamori.provenance import ProtectionLedger

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "audit.jsonl"
        with PrivacySession(locales=["ja"]) as session:
            ProtectionLedger(JsonlAuditSink(path)).record(
                session.protect("田中太郎さんに tanaka@example.com"), session=session
            )
        (raw,) = path.read_text(encoding="utf-8").splitlines()

    Draft202012Validator(load("audit-line-1.json")).validate(json.loads(raw))
