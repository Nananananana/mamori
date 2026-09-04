"""One protection per line, appended to a file.

The only implementation of :class:`~mamori.ports.audit_sink.AuditSink` that
ships here. A file writer, and nothing else: a sink that grew a second backend
would need a second argument about what may reach it, and that argument is the
part worth keeping small.

**Every record is validated against the shipped schema before it is written.**
That is not defensive coding. The schema is what makes *"this file holds no
protected value"* checkable rather than promised, and a sink that wrote
whatever it was handed would move the guarantee from the format to the caller
-- which is exactly the difference between this and a logger.

**A line is an envelope around a record, not a record.**

    {"line": "mamori.audit-line/1", "at": "...", "record": {...}}

The reason is the one question this feature exists to answer -- *what left this
machine last Tuesday* -- and a `protection-scope` record cannot answer it,
because it has no time in it and must not grow one. ADR 0032 says a record
states what is derivable from the artifact it describes, and nothing else; when
a protection happened is a fact about the event, not about the text. Putting it
in the record would mean the invariant now has one exception, and an invariant
with one exception is a thing people argue about instead of check. So the time
goes outside, where the sink owns the format and the contract stays frozen.

**The file inherits the classification of the documents it describes.** A line
saying ``{"kind": "NATIONAL_ID", "count": 1}`` tells somebody holding the
document nothing they did not already have, and tells somebody who does not
hold it which file is worth taking. A directory chosen for logs is the wrong
directory for this, and the mode below says so as loudly as a mode can.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...errors import StorageError

__all__ = ["LINE_FORMAT", "JsonlAuditSink"]

#: What one line of this file is. Separate from the record's own contract
#: identifier, and versioned separately, because they can change for unrelated
#: reasons: this one is a file format, that one is a statement about a
#: document.
LINE_FORMAT = "mamori.audit-line/1"

_SCHEMA_FILE = "protection-scope-1.json"
_RESTORATION_SCHEMA_FILE = "restoration-scope-1.json"


def _load_schema(name: str = _SCHEMA_FILE) -> dict[str, Any]:
    """Read the frozen contract document out of package data.

    **Loaded here rather than imported from `mamori.provenance`**, which also
    has it, and where sharing would obviously belong. `provenance` reads the
    application; infrastructure is inside that, so importing it from here would
    run the dependency backwards and `tests/test_architecture` would say so.
    `schemas/` holds no code, so reading the bytes reaches for no layer at all.

    The copy is not left to trust: `test_audit_sink` asserts this schema and
    the identifiers below are what `provenance` publishes.
    """
    from importlib import resources

    text = (resources.files("mamori.schemas") / name).read_text(encoding="utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


SCHEMA: dict[str, Any] = _load_schema()

#: The return half, added in 0.33. Same file, because *what left this machine
#: last Tuesday* and *what came back and what became of it* are one question
#: asked twice, and answering the second from a different file would mean
#: joining two logs to learn whether a protected value was ever restored.
RESTORATION_SCHEMA: dict[str, Any] = _load_schema(_RESTORATION_SCHEMA_FILE)

#: Which contract identifiers this sink takes -- read out of the schemas rather
#: than written down again, so a future ``/2`` cannot be accepted here without
#: first passing through the document that defines what a ``/2`` may contain.
#:
#: **Widening this is a decision, not a convenience.** A contract belongs here
#: only once it has been through the derivability test ADR 0032 sets: nothing
#: in a record that a holder of the artifact could not already work out.
#: `restoration-scope/1` was written against that test -- which is why it
#: carries canonical placeholder identities and not the surface forms a model
#: typed -- and `tests/test_audit_sink` pins these identifiers against what
#: `provenance` publishes, so the two cannot drift apart in silence.
_RESTORATION_CONTRACT: str = RESTORATION_SCHEMA["properties"]["contract"]["const"]

ACCEPTED_CONTRACTS: frozenset[str] = frozenset(SCHEMA["properties"]["contract"]["enum"]) | {
    _RESTORATION_CONTRACT
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JsonlAuditSink:
    """Append to a file, one JSON document per line.

    JSON Lines rather than a JSON array, because an array has to be rewritten
    to be appended to, and a crash halfway through rewriting an audit file
    loses the audit file.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        validate: bool = True,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """
        Args:
            path: Where to append. Created owner-only where the platform has
                such a thing. Parent directories are **not** created: a
                mistyped path that quietly makes a tree is how an audit file
                ends up somewhere nobody looks.
            validate: Check each record against the shipped schema first.
                Defaults on. Turning it off is a decision to write unchecked
                documents into a file whose entire claim is that its contents
                were checked; it is here for a caller who has already validated
                and is writing in a loop.
            clock: Injected here rather than read in the domain, the same way
                :class:`~mamori.domain.retention.Retention` takes its ``now``
                from the store. A test that cannot say what time it is has to
                assert on the shape of a timestamp instead of its value.
        """
        self._path = Path(path)
        self._validate = validate
        self._clock = clock

    @property
    def path(self) -> Path:
        return self._path

    def record(self, record: dict[str, Any]) -> None:
        """Append one record.

        Raises:
            StorageError: the record is not a `protection-scope` document, or
                it could not be written. **Both are refused rather than
                skipped**: a sink that silently drops what it cannot write is
                an audit trail with holes in it and no way to see them. What to
                do about the refusal is
                :class:`~mamori.provenance.ProtectionLedger`'s decision, not
                this object's -- one of them knows whether protection should
                stop, and it is not the file writer.
        """
        if self._validate:
            self._refuse_anything_that_is_not_a_record(record)

        try:
            line = json.dumps(
                {"line": LINE_FORMAT, "at": self._stamp(), "record": record},
                ensure_ascii=False,
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise StorageError(
                "an audit record must be JSON-serialisable; this one is not"
            ) from exc

        try:
            self._append(line)
        except OSError as exc:
            raise StorageError(f"could not append to the audit file: {self._path}") from exc

    def _stamp(self) -> str:
        """The time, in UTC, to the millisecond.

        UTC and not local time: an audit file that says ``09:15`` and not which
        09:15 is a file two people read differently. Milliseconds because two
        protections in the same second are ordinary and the file has no other
        ordering than the one the lines are in.
        """
        moment = self._clock()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")

    def _append(self, line: str) -> None:
        """Append, creating the file owner-only if it is not there yet.

        The mode is given at creation rather than applied afterwards, so there
        is no window in which the file exists and is group-readable. Windows
        ignores it and the file takes the directory's ACL, which makes this an
        improvement where it applies and not a claim where it does not.
        """
        descriptor = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    @staticmethod
    def _refuse_anything_that_is_not_a_record(record: dict[str, Any]) -> None:
        """Validate against the schema this package ships.

        The structural checks run first and run everywhere. `jsonschema` is a
        development dependency, so on an ordinary install the full validation
        below is absent -- and the two checks that stop a free-text field are
        the two that do not need it.
        """
        if not isinstance(record, dict):
            raise StorageError("an audit record must be a mapping")

        contract = record.get("contract")
        if contract not in ACCEPTED_CONTRACTS:
            raise StorageError(
                "this sink takes mamori.protection-scope and "
                "mamori.restoration-scope records and nothing else. It is not a "
                "log: what may appear in one of these is settled by ADR 0032, and "
                "a record that does not name the contract has not been through that."
            )

        # The record's own schema, chosen by the contract it declares. Not
        # the union of both: a protection record carrying `clean`, or a
        # restoration record carrying `masked`, is a record whose producer has
        # confused the two halves, and a check that accepted either field
        # anywhere would be the one place that did not notice.
        schema = RESTORATION_SCHEMA if contract == _RESTORATION_CONTRACT else SCHEMA

        unknown = sorted(set(record) - set(schema["properties"]))
        if unknown:
            raise StorageError(
                f"an audit record carries fields {contract} does not define: "
                f"{unknown}. The schema refuses unknown properties because a field "
                "nobody argued about is a field nobody checked against ADR 0032 -- "
                "which is where 'this file holds no protected value' comes from."
            )

        try:
            from jsonschema import Draft202012Validator
        except ModuleNotFoundError:  # pragma: no cover - depends on the install
            return
        errors = sorted(Draft202012Validator(schema).iter_errors(record), key=str)
        if errors:
            raise StorageError(
                f"an audit record does not validate against the shipped schema: {errors[0].message}"
            )
