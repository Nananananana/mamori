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
from typing import TYPE_CHECKING, Any

from .domain.policy import Action

if TYPE_CHECKING:  # pragma: no cover
    from .application.results import ProtectionResult
    from .application.session import PrivacySession
    from .domain.policy import PrivacyPolicy

__all__ = [
    "CONTRACT",
    "CONTRACT_WITH_SURROGATES",
    "SCHEMA",
    "policy_hash",
    "protection_record",
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

_SCHEMA_FILE = "protection-scope-1.json"


def _load_schema() -> dict[str, Any]:
    from importlib import resources

    text = (resources.files("mamori.schemas") / _SCHEMA_FILE).read_text(encoding="utf-8")
    loaded: dict[str, Any] = json.loads(text)
    return loaded


#: The JSON Schema, so a consumer can validate without a network fetch or a
#: pinned copy that drifts.
SCHEMA: dict[str, Any] = _load_schema()


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


def _counted(counts: Counter[str]) -> list[dict[str, Any]]:
    """Kind and count, in a fixed order. Never a string that was substituted."""
    return [{"kind": kind, "count": count} for kind, count in sorted(counts.items())]
