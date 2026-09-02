"""Where a record of what was protected goes, if anywhere.

An operator asking *what left this machine last Tuesday, and under which
policy* has had no answer. Nothing in this library survives the process:
`DecisionTrace` explains a request still in hand, `mamori audit` summarises a
corpus, and `mamori.protection-scope/1` states what one protection did and is
handed to a caller who has nowhere to put it.

**The reason for the gap is a good decision, which is why the fix is narrow.**
This package has no logging — `import logging` appears nowhere in `src` — and
that is what makes *"a protected value never appears in a log line, because
nothing ever writes one"* true by construction rather than by discipline.

So this is not a logger, and the difference is not stylistic:

    a logger   takes whatever a caller passes it. Whether it stays clean is a
               promise about everybody's future code
    a sink     takes a `protection-scope` record and nothing else. The record
               is defined by ADR 0032, carries no protected value, has a
               schema, and has a conformance suite that validates real emitted
               bytes

The narrowness is the safety. A sink that also accepted a message would be a
logger with a longer name, and the first person in a hurry would use the
message.

**A record is not safe to log**, either, and the sink cannot enforce that.
`{"kind": "NATIONAL_ID", "count": 1}` describes a document to somebody who
holds it and points at one to somebody who does not. A record inherits the
classification of the text it describes; an implementation that writes to a
directory chosen for logs has probably chosen wrong.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["AuditSink"]


@runtime_checkable
class AuditSink(Protocol):
    """Receives one `mamori.protection-scope/1` record per protection.

    **An implementation that cannot record should raise.** It is the wrong
    object to decide otherwise: whether a full disk should stop a protection
    depends on why the operator turned auditing on, and a file writer does not
    know that. `ProtectionLedger` does, and it is where the choice lives.

    The reason it is not simply *"never raise, auditing is bookkeeping"* is
    that an audit trail which drops what it cannot write has holes in it and
    nothing that shows where. That failure mode is worse than a loud one, and
    a sink that swallows is the only place it can be introduced.
    """

    def record(self, record: dict[str, Any]) -> None:
        """Take one record.

        Args:
            record: A `mamori.protection-scope/1` document, exactly as
                :func:`mamori.provenance.protection_record` produced it.
                Callers do not add fields: the schema refuses unknown
                properties, and the reason it refuses them is that a field
                nobody argued about is a field nobody checked against
                ADR 0032.
        """
        ...
