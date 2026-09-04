"""What was protected, stated without handing back what it protected.

Five sibling projects need to say "this text has been through mamori, by this
version, in this scope, and it can (or cannot) be put back". Two of them were
doing it by importing :class:`~mamori.application.session.PrivacySession` and
reading its result objects, which couples them to a Python signature for
something that is a *statement*, not a computation.

`mamori.protection-scope/1` is that statement as a document. It carries no
values, so a consumer that only needs to describe a protection no longer needs
the library that performed one. Restoration still does, and always will --
that part is what mamori *is*.

The rule that decides what may go in, from
:doc:`ADR 0032 </adr/0032-state-the-protection-without-importing-it>`:

    **A record may state anything derivable from the artifact it describes,
    and nothing else.**

Stated as a test rather than as a list of permitted fields, because it settles
cases nobody has thought of yet -- and because it gives opposite answers for
the two substitution modes, which a flat rule would have got wrong:

**A token is in the text.** Anybody holding ``<PERSON_001>さんへ`` recovers the
whole list with one regular expression, so listing tokens discloses nothing.
It also does something no consumer can do for itself: distinguish a token
**mamori minted** from a token that was **in the user's input already**.
``<PERSON_001>`` is a string a person can type, and every wrong guess about one
is quiet -- a real quotation reported as a placeholder, or a placeholder
restored that never stood for anything.

**A surrogate is not in the text**, in the sense that the text does not
announce it -- that is the whole of ADR 0026, ``surrogates trade obviousness
for readability``. Listing surrogates would say which names are invented,
and by elimination which are real, and would mark the exact spans that held a
real value. So surrogates contribute a **kind and a count, and no strings**.

Never included, in any mode: offsets or lengths in the original (a length is a
value's shape, and for a national ID the shape is most of it), previews (masked
is not absent), confidences and rule identifiers (they describe the value), and
any hash keyed by original text (for short values from a known set that is not
a one-way function, it is a lookup table with extra steps).

That list is what the test yields *in this domain*, and it is not part of the
test. What makes the offset rule absolute here is that **protected text is
always live** -- the original still exists, and so does a mapping that reaches
it. A sibling applying the same test to records that point at something already
gone keeps the spans, and is not applying it more loosely. Borrow the test;
re-derive the prohibitions.

**A record is not safe to log.** The derivability test protects a reader *who
holds the protected text*. Provenance travels into manifests and audit logs
precisely because it is believed to be harmless, and to a reader who does not
hold the document ``{"kind": "NATIONAL_ID", "count": 1}`` is not a description
of something they already have -- it is a pointer to which file is worth
taking. **A record inherits the classification of the text it describes.**
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from .domain.policy import Action

if TYPE_CHECKING:  # pragma: no cover
    from .application.results import ProtectionResult, RestorationResult
    from .application.session import PrivacySession
    from .domain.placeholder import Placeholder
    from .domain.policy import PrivacyPolicy
    from .ports.audit_sink import AuditSink

__all__ = [
    "CONTRACT",
    "CONTRACT_WITH_SURROGATES",
    "RESTORATION_CONTRACT",
    "RESTORATION_SCHEMA",
    "SCHEMA",
    "ProtectionLedger",
    "policy_hash",
    "protection_record",
    "restoration_record",
]

#: The frozen contract identifier, for a record whose values were **all**
#: replaced by tokens. A consumer that does not recognise a contract must
#: refuse the record rather than read the fields it happens to know.
CONTRACT = "mamori.protection-scope/1"

#: The identifier for a record that contains at least one **surrogate**.
#:
#: A separate name, rather than a flag inside the same one, because the danger
#: it guards against is a consumer reading ``placeholders`` and believing the
#: document fully enumerated when part of it was replaced by plausible values
#: instead. Stated as a rule -- "a consumer that understands only placeholders
#: must refuse the other modes" -- that has to be obeyed once per consumer,
#: per version, forever. Stated as a different contract identifier it is
#: obeyed **zero** times: the check every consumer already has, refusing a
#: contract it does not recognise, does the work.
#:
#: Handling surrogate records therefore becomes an explicit opt-in, which is
#: the right shape: knowing they exist is the whole of what makes them safe to
#: read.
CONTRACT_WITH_SURROGATES = "mamori.protection-scope/1+surrogate"

#: The return half. A protection record says what was replaced; this says
#: what came back and what became of it. Joined on ``scope``, the two are the
#: lineage of one round trip -- original, protected, answer, restored -- and
#: neither carries a value.
#:
#: Separate rather than one record with more fields, for a reason the
#: surrogate contract already demonstrates: the two halves are written at
#: different moments, and a protection that never got an answer must not look
#: like one whose answer was clean. An absent restoration record is a visible
#: absence; a protection record with empty restoration fields is not.
RESTORATION_CONTRACT = "mamori.restoration-scope/1"

_SCHEMA_FILE = "protection-scope-1.json"
_RESTORATION_SCHEMA_FILE = "restoration-scope-1.json"


def _load_schema(name: str = _SCHEMA_FILE) -> dict[str, Any]:
    from importlib import resources

    text = (resources.files("mamori.schemas") / name).read_text(encoding="utf-8")
    loaded: dict[str, Any] = json.loads(text)
    return loaded


#: The JSON Schema, so a consumer can validate without a network fetch or a
#: pinned copy that drifts.
SCHEMA: dict[str, Any] = _load_schema()

#: The same, for :func:`restoration_record`.
RESTORATION_SCHEMA: dict[str, Any] = _load_schema(_RESTORATION_SCHEMA_FILE)


def policy_hash(
    policy: PrivacyPolicy,
    *,
    surrogate_types: frozenset[str] = frozenset(),
    placeholder_style: str = "",
) -> str:
    """A fingerprint of the **settings**, and of nothing else.

    Over the policy alone. A hash mixing in anything from the document turns
    the record into an oracle for guessing at content: hand somebody a hash
    that depends on the text and they can confirm a guess about it.

    ``surrogate_types`` and ``placeholder_style`` are included because they
    change what a record *means*, not because they say anything about a
    document.
    """
    payload = {
        "rules": {name: action.value for name, action in sorted(policy.rules.items())},
        "category_defaults": {
            category.value: action.value
            for category, action in sorted(
                policy.category_defaults.items(), key=lambda pair: pair[0].value
            )
        },
        "default_action": policy.default_action.value,
        "mask_token": policy.mask_token,
        "min_confidence": policy.min_confidence,
        "uncertain": policy.uncertain.value,
        "surrogate_types": sorted(surrogate_types),
        "placeholder_style": placeholder_style,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def protection_record(
    result: ProtectionResult,
    *,
    session: PrivacySession | None = None,
    by: str = "",
    recall: str | None = None,
    policy_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Build a ``mamori.protection-scope/1`` record for one protected text.

    Args:
        result: What :meth:`~mamori.PrivacySession.protect` returned.
        session: The session that produced it, if the caller has it. Only
            used to fingerprint its policy. This module reads the session;
            the session does not know this module exists, which is the same
            arrangement :mod:`mamori.report` has with configuration -- a
            description that the thing described cannot reach.
        by: Producer, as ``name/version``. Defaults to this mamori.
        recall: The stance the detectors ran under, when the caller knows it.
            A session does not hold it -- the configuration that built the
            detectors does -- so mamori does not invent one. Omitted when
            ``None``, and a record without it says nothing about recall rather
            than claiming a default.
        policy_fingerprint: From :func:`policy_hash`. Omitted when ``None``.

    Returns:
        A JSON-serialisable dict. Every value in it is derivable from
        ``result.protected_text`` by somebody holding that text.

    The contract identifier differs when any surrogate is present, so a
    consumer pinned to :data:`CONTRACT` refuses such a record through the check
    it already has instead of through a rule it has to remember.

    The mode is a **summary, not a switch.** Implementing this found that
    surrogates are enabled per entity type, so one document routinely carries
    both -- a surrogated ``PERSON`` beside a tokenised ``EMAIL``, and even a
    tokenised ``PERSON`` in a locale with no surrogate pool. ``placeholders``
    and ``protected`` are therefore both always present and disjoint by
    construction: a token goes in one, a surrogate is counted in the other,
    and no surrogate string appears anywhere.
    """
    if not by:
        from . import __version__

        by = f"mamori/{__version__}"

    if policy_fingerprint is None and session is not None:
        policy_fingerprint = policy_hash(
            session.policy,
            surrogate_types=session.surrogate_types,
            placeholder_style=session.placeholder_style.name,
        )

    placeholders: list[dict[str, str]] = []
    surrogated: Counter[str] = Counter()
    masked: Counter[str] = Counter()

    for entity in result.entities:
        if entity.action is Action.MASK:
            masked[entity.entity_type] += 1
        elif entity.action is Action.ANONYMIZE:
            if entity.surrogate:
                surrogated[entity.entity_type] += 1
            elif entity.placeholder:
                placeholders.append({"token": entity.placeholder, "kind": entity.entity_type})

    if surrogated and placeholders:
        mode = "mixed"
    elif surrogated:
        mode = "surrogate"
    else:
        mode = "placeholder"

    record: dict[str, Any] = {
        "contract": CONTRACT_WITH_SURROGATES if surrogated else CONTRACT,
        "by": by,
        "scope": result.scope,
        "reversible": result.reversible,
        "mode": mode,
        "placeholders": placeholders,
        "protected": _counted(surrogated),
        "masked": _counted(masked),
    }
    if recall is not None:
        record["recall"] = recall
    if policy_fingerprint is not None:
        record["policy_hash"] = policy_fingerprint
    return record


def restoration_record(
    result: RestorationResult,
    *,
    scope: str,
    by: str = "",
) -> dict[str, Any]:
    """Build a ``mamori.restoration-scope/1`` record for one restored answer.

    Args:
        result: What :meth:`~mamori.PrivacySession.restore` returned.
        scope: The scope the placeholders were allocated in -- the same value
            the protection record carries, and the only thing joining the two.
            Passed rather than read off the result because a
            :class:`~mamori.RestorationResult` does not hold one: restoration
            is given a scope, it does not discover one.
        by: Producer, as ``name/version``. Defaults to this mamori.

    Returns:
        A JSON-serialisable dict carrying **no restored value**, by the same
        test :func:`protection_record` passes: everything in it is derivable
        from the protected text by somebody who already holds it. Tokens yes;
        the values behind them, the answer's wording, and the surface forms a
        model typed, no.

    The last of those is the one worth stating. ``result.unknown`` holds the
    surface as the answer wrote it -- what a person reading a warning needs --
    and this record carries the **canonical identity** instead. A surface is
    whatever a model produced; an identity is ``(TYPE, index)`` and is bounded
    by the placeholder grammar. An audit line is somewhere model output should
    not arrive verbatim.
    """
    if not by:
        from . import __version__

        by = f"mamori/{__version__}"

    return {
        "contract": RESTORATION_CONTRACT,
        "by": by,
        "scope": scope,
        "clean": result.is_clean,
        "restored": _tokens(occurrence.placeholder for occurrence in result.restored),
        "tampered": _tokens(occurrence.placeholder for occurrence in result.tampered),
        "unknown": _tokens(result.unknown_identities),
        "unused": _tokens(result.missing),
    }


def _tokens(placeholders: Iterable[Placeholder]) -> list[dict[str, str]]:
    """Canonical token and kind, deduplicated, in a fixed order.

    Sorted and deduplicated so that two records of the same answer compare
    equal: a token mentioned three times is one fact about the answer, and a
    count of mentions would be a shape of the answer's wording.
    """
    seen = {
        placeholder.token: {
            "token": placeholder.token,
            "kind": placeholder.entity_type_name,
        }
        for placeholder in placeholders
    }
    return [seen[token] for token in sorted(seen)]


def _counted(counts: Counter[str]) -> list[dict[str, Any]]:
    """Kind and count, in a fixed order. Never a string that was substituted."""
    return [{"kind": kind, "count": count} for kind, count in sorted(counts.items())]


class ProtectionLedger:
    """Builds a record for each protection and hands it to a sink.

    The pairing that makes the audit trail possible without moving anything
    inward. :class:`~mamori.PrivacySession` cannot do this itself and should
    not learn how: `provenance` reads the application, so a session that
    recorded its own protections would invert that, and *stating what
    happened* would become part of *doing it* -- the arrangement ADR 0032 set
    up specifically to prevent.

    So the caller wires it up, and the session stays unaware:

        >>> from mamori import PrivacySession
        >>> from mamori.infrastructure.audit import JsonlAuditSink
        >>> session = PrivacySession()                     # doctest: +SKIP
        >>> ledger = ProtectionLedger(                     # doctest: +SKIP
        ...     JsonlAuditSink("audit.jsonl"), by="billing-import/2.1"
        ... )
        >>> result = session.protect(text)                 # doctest: +SKIP
        >>> ledger.record(result, session=session)         # doctest: +SKIP

    ``by``, ``recall`` and ``policy_fingerprint`` are held here rather than
    passed to every call, because they describe the deployment and not the
    document, and a value repeated at every call site is a value that will
    disagree with itself at one of them.
    """

    def __init__(
        self,
        sink: AuditSink,
        *,
        by: str = "",
        recall: str | None = None,
        policy_fingerprint: str | None = None,
        strict: bool = True,
    ) -> None:
        """
        Args:
            sink: Where records go.
            by: Producer, as ``name/version``. Defaults to this mamori.
            recall: The stance the detectors ran under, when the caller knows
                it. Omitted from every record when ``None``, because a record
                that guesses is worse than one that is silent.
            policy_fingerprint: From :func:`policy_hash`. When ``None`` and a
                session is passed to :meth:`record`, it is computed from that
                session.
            strict: Whether a sink that fails should stop the caller.

                **On by default, which is the unusual choice, so here is the
                reasoning.** The instinct is that auditing is bookkeeping and
                bookkeeping must never break the work. The trouble is what
                that produces: a misconfigured path, a full disk or a
                read-only mount then yields a privacy layer that runs
                perfectly and an audit file that is empty, and nothing
                anywhere says which protections are missing from it. An audit
                trail is worth having because it is complete; one that fails
                open is a file that reads like evidence and is not.

                ``strict=False`` is there for the deployment that has weighed
                this and prefers protection to survive a broken disk. It
                counts what it dropped -- see :attr:`dropped` -- so the gap is
                at least visible from inside the process.
        """
        self._sink = sink
        self._by = by
        self._recall = recall
        self._policy_fingerprint = policy_fingerprint
        self._strict = strict
        self._written = 0
        self._dropped = 0

    @property
    def written(self) -> int:
        """Records the sink accepted."""
        return self._written

    @property
    def dropped(self) -> int:
        """Records lost to a sink failure. Always ``0`` when ``strict``."""
        return self._dropped

    def record(
        self,
        result: ProtectionResult,
        *,
        session: PrivacySession | None = None,
    ) -> dict[str, Any]:
        """Record one protection. Returns the record, whether or not it landed.

        Returning it regardless is deliberate: with ``strict=False`` the
        caller still gets the document and can do something else with it, and
        the return value never becomes a way to ask whether the write
        succeeded -- :attr:`dropped` is that, and it does not look like
        anything else.

        Raises:
            Whatever the sink raises, when ``strict``. Usually
            :class:`~mamori.errors.StorageError`.
        """
        document = protection_record(
            result,
            session=session,
            by=self._by,
            recall=self._recall,
            policy_fingerprint=self._policy_fingerprint,
        )
        return self._emit(document)

    def record_restoration(
        self,
        result: RestorationResult,
        *,
        scope: str,
    ) -> dict[str, Any]:
        """Record the return half. Returns the record, whether or not it landed.

        The same sink, the same strictness, the same counters. Joined to the
        protection record by ``scope``, which is why that argument is required
        and not defaulted: a restoration record nobody can join is a row that
        says a round trip happened somewhere.

        `recall` and `policy_fingerprint` are deliberately not on it. They
        describe how detection ran, which is a fact about the outbound half
        and is already recorded there; repeating them here would let the two
        halves of one round trip disagree about the run that produced them.
        """
        return self._emit(restoration_record(result, scope=scope, by=self._by))

    def _emit(self, document: dict[str, Any]) -> dict[str, Any]:
        try:
            self._sink.record(document)
        except Exception:
            self._dropped += 1
            if self._strict:
                raise
            return document
        self._written += 1
        return document
