"""Whose hands are in a corpus, and what that lets a number mean.

The README says it in prose: *"Who wrote the documents these numbers come from
-- we did."* This module is the same sentence in a form the scorer can act on,
because a caveat that lives only in a README is a caveat that travels separately
from the number and arrives after it.

The distinction it draws is **not** synthetic-versus-real. Every dataset here
carries ``source: "synthetic"`` and always will -- these files ship inside the
package, so a real name committed here is published to everyone who installs
mamori. That field answers "is this invented", which is a safety question. It
says nothing about the question a reader of a leak rate needs answered, which is
**"was this written by the same hand that wrote the rules being scored"**.

Three findings shaped what is here, none of them ours:

**Independence is a relation, not a label** (mamori, 2026-08-30). A sibling
project borrowed this corpus, recorded honestly that it had not written it, and
still reported a miss rate its own unseen data did not support. The corpus was
not written by *them*, but it was written by someone who could see their rules,
and shared design discussion is the thing that leaks. So a dataset cannot
declare "I am independent". It can only declare **who touched it**, and
independence is computed against a named subject from there.

**Generation does not launder provenance** (mamori, 2026-08-30). The 900-document
adversarial corpus was produced by a script, and the script was written by the
people who wrote the rules. A generator is a hand. Three of that corpus's five
findings were resolved by deciding what the generator should have been able to
write, which is what it looks like when a corpus can only refute what its own
author already imagined.

**One corpus has more than one hand** (akashi, 2026-08-30). Their taxonomy is
theirs, their unit rules are theirs, and their sentence text can come from a
model. Recording a single origin for the file would average three different
answers into one wrong one. Here the two hands are the **text** and the
**labels**, and they come apart exactly where it matters: text drafted by
somebody else and labelled by us is the cheap way to stop measuring our own
imagination, and it is visible only if the two are recorded separately.

The default is undeclared, and undeclared refuses. That direction is deliberate
and matches the rest of this library: claiming independence you do not have is a
quiet failure that changes what a reader believes, and failing to claim
independence you do have only makes a number more modest than it needed to be.

Pointing the default the right way is not enough on its own, because a default
only governs the value nobody wrote. The strongest claim here -- that the
authors could see nobody's rules, which makes a corpus evidence about everybody
-- must therefore also be expensive to write, and ``[]`` is the cheapest string
in JSON to produce by accident. So it is spelled ``"none"`` and a literal empty
list is refused. See :data:`NOTHING_IN_VIEW`.

One asymmetry is deliberate and worth naming, because it puts friction on the
path this module exists to encourage. A corpus written by a hand inside the
family and not saying what it could see is assumed to have seen everything,
which is right -- we know what the people here can see. An *outside* corpus that
does not say is refused rather than assumed innocent, because nobody here knows
what its authors had read. The cost of that is one word in the file, and the
alternative is granting outsiders an independence nobody checked, which is the
same unearned claim in a more flattering direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import ConfigurationError

__all__ = ["NOTHING_IN_VIEW", "UNDECLARED", "Provenance", "ProvenanceError"]


class ProvenanceError(ConfigurationError):
    """A number was asked to mean more than its corpus can support.

    Raised by :meth:`~mamori.evaluation.scoring.EvaluationReport.as_evidence_for`
    rather than by scoring, because running a detector over home-ground data is
    a perfectly good thing to do -- it is how the regression floor in this
    project's CI works. What is not fine is calling the result evidence about
    documents nobody here has seen.

    Also raised by :meth:`Provenance.from_payload` for a declaration that does
    not parse, so that a caller catching this catches a corpus whose provenance
    is broken as well as one whose provenance disqualifies it. It subclasses
    :class:`~mamori.errors.ConfigurationError`, so anything already catching
    that keeps working.
    """


#: Every project whose rules the authors of this corpus can see. They are one
#: family, sharing design discussion and reviewing each other's decisions, so a
#: corpus written by any of them is home ground for all of them. A dataset that
#: names one of these as a hand is not independent evidence for any of the rest,
#: which is the specific mistake that produced a borrowed 1.0% miss rate.
FAMILY = frozenset({"akashi", "iriguchi", "kiseki", "mamori", "musubi", "tsumugi"})

#: What an unrecorded hand is called. Not ``""``: a reader skimming a data file
#: should see a word that says the field was never filled in, rather than an
#: absence they read as "nothing to declare".
UNDECLARED = "undeclared"

#: How a file says its authors could see nobody's rules -- ``"rules_in_view":
#: "none"`` rather than ``[]``.
#:
#: The empty set is the most permissive value in this module: it makes a corpus
#: independent evidence about everybody. It is also the cheapest value to
#: produce by accident. ``sorted(view or [])``, a generator's default argument,
#: a hand-edit that removed the last name from a list -- all of them yield
#: ``[]``, and in JSON ``[]`` sits one character from ``null`` while meaning its
#: opposite.
#:
#: So the strongest claim in the format is spelled as a word of a different
#: type, and a literal ``[]`` is refused with both alternatives named. None of
#: the ways a value slips produce a string.
NOTHING_IN_VIEW = "none"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Who wrote a corpus, and whose rules they could see while writing it.

    Args:
        text: Who wrote the documents. A project name (``"mamori"``), a model
            (``"model:llama3.1:8b"``), or an outside corpus
            (``"external:ragtruth"``). A generator script counts as whoever
            wrote the generator.
        labels: Who decided what should have been redacted. Often not the same
            hand as the text, and the interesting corpora are the ones where it
            is not.
        rules_in_view: Every project whose rules those hands could see. ``None``
            means nobody said, which is treated as "all of them" -- see the
            module docstring on which direction the default points. An empty
            set is the strongest claim this class can carry, so the file format
            makes it cost a word: see :data:`NOTHING_IN_VIEW`.
    """

    text: str = UNDECLARED
    labels: str = UNDECLARED
    rules_in_view: frozenset[str] | None = None

    @property
    def hands(self) -> tuple[str, ...]:
        """Every distinct hand in this corpus, in a stable order."""
        return tuple(sorted({self.text, self.labels}))

    @property
    def is_declared(self) -> bool:
        """True when every hand has been named."""
        return UNDECLARED not in (self.text, self.labels)

    def independent_of(self, subject: str) -> bool:
        """Can this corpus be evidence *about* ``subject``?

        True only when no hand in it is ``subject``, and no hand could see
        ``subject``'s rules while writing.
        """
        return self.why_not(subject) is None

    def why_not(self, subject: str) -> str | None:
        """The reason this corpus is not independent evidence, or ``None``.

        A sentence rather than a code, because it is printed next to the number
        it disqualifies, and a reader who has to look up an enum member will
        instead look up nothing.
        """
        if not self.is_declared:
            which = " and ".join(
                name
                for name, value in (("text", self.text), ("labels", self.labels))
                if value == UNDECLARED
            )
            return (
                f"nobody recorded who wrote the {which}. An unrecorded hand is "
                f"treated as ours, because that is the answer that costs least "
                f"when it is wrong."
            )
        if subject in self.hands:
            if self.text == self.labels:
                return f"the text and the labels here were both written by {subject}"
            which = "text" if self.text == subject else "labels"
            return f"the {which} here {'was' if which == 'text' else 'were'} written by {subject}"
        in_view = FAMILY if self.rules_in_view is None else self.rules_in_view
        if self.rules_in_view is None and not (set(self.hands) & FAMILY):
            # An outside hand that did not say what it could see. Outside hands
            # are the ones worth having, so do not silently assume the worst of
            # them -- but do not assume the best either.
            return (
                f"{self.text} did not record whose rules were in view when this "
                f"was written, so it cannot be claimed as evidence about {subject}"
            )
        if subject in in_view:
            hand = self.text if self.text in FAMILY else self.labels
            return (
                f"{hand} wrote this while able to see {subject}'s rules. "
                f"Not having written it is not the same as not having seen it."
            )
        return None

    def describe(self) -> str:
        """One line, for printing beside a number."""
        if not self.is_declared:
            return "not recorded"
        if self.text == self.labels:
            return f"text and labels by {self.text}"
        return f"text by {self.text}, labels by {self.labels}"

    @classmethod
    def from_payload(cls, payload: object, origin: str) -> Provenance:
        """Read the ``provenance`` block of a dataset file.

        Absent means undeclared, which refuses. Present but malformed is an
        error rather than a fallback to undeclared: a typo that silently
        removed a declaration would make a number quietly more modest, and the
        next person would spend an afternoon on why.
        """
        if payload is None:
            return cls()
        if not isinstance(payload, dict):
            raise ProvenanceError(f"provenance must be an object: {origin}")

        unknown = sorted(set(payload) - {"text", "labels", "rules_in_view"})
        if unknown:
            raise ProvenanceError(f"provenance has unknown keys {unknown}: {origin}")

        view = _view(payload.get("rules_in_view"), origin)

        return cls(
            text=_hand(payload.get("text"), "text", origin),
            labels=_hand(payload.get("labels"), "labels", origin),
            rules_in_view=view,
        )

    def as_mapping(self) -> dict[str, Any]:
        """The JSON form, for a report that has to travel."""
        return {
            "text": self.text,
            "labels": self.labels,
            "rules_in_view": (None if self.rules_in_view is None else sorted(self.rules_in_view)),
        }


def _view(raw: object, origin: str) -> frozenset[str] | None:
    """Read ``rules_in_view``, refusing the value that slips.

    Raises:
        ProvenanceError: The list is empty. That is the strongest claim the
            format can make and the easiest one to write by accident, so it has
            to be spelled as a word instead.
    """
    if raw is None:
        return None
    if raw == NOTHING_IN_VIEW:
        return frozenset()
    if isinstance(raw, list) and all(isinstance(name, str) and name for name in raw):
        if not raw:
            raise ProvenanceError(
                f"provenance.rules_in_view is an empty list: {origin}. An empty list "
                f"would make this corpus independent evidence about everybody, which "
                f"is the strongest thing this file can say, so it has to be said in "
                'words: use "none" if the authors could see no rules at all, or '
                "omit the key if nobody has checked."
            )
        return frozenset(raw)
    raise ProvenanceError(
        f'provenance.rules_in_view must be a list of project names or "none": {origin}'
    )


def _hand(value: object, field_name: str, origin: str) -> str:
    if value is None:
        return UNDECLARED
    if not isinstance(value, str) or not value.strip():
        raise ProvenanceError(f"provenance.{field_name} must be a name: {origin}")
    return value.strip()
