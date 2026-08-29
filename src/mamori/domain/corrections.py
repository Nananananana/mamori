"""What the operator has ruled on, and mamori has to accept.

Everything else in this library decides for itself. Rules fire, a model
proposes, the resolver picks a winner, the policy acts. The operator watching
"Monday" become a `PERSON` has had no way to disagree except by editing rules
or forking the prompt library, and neither is available to somebody who simply
wants their own document to come out right.

A correction is one appended record: a value, a verdict, and a note saying why.
The log is append-only and the latest word about a value wins, so undoing a
correction is another correction and nothing is ever lost. Applied at read
time, as a filter over what was detected -- rules are not rewritten, prompts
are not edited, and turning the log off restores exactly the previous
behaviour.

This is the sibling `kiseki` project's ADR-0044 shape. Two things are different
here, and both come from what this library is for.

**A correction can remove protection, and that is new.** Every pass, every
tier, every model proposal in mamori so far could only ever *add*. That
one-way property is what makes it safe to let a model near a document at all.
``NEVER`` breaks it deliberately, because the alternative -- an operator who
cannot fix a false positive -- ends with the whole library switched off. So the
exception is narrow, explicit, logged, reversible, and visible in
``mamori privacy``.

**A credential can never be excluded.** This is the one rule that is not the
operator's to overrule: a password ruled "not sensitive" is a password in
somebody's prompt, and no note explains that away.

It is enforced in three places, because one is not enough. This module refuses
an exclusion that *names* a credential type. :meth:`CorrectionLog.excludes`
refuses to apply one at read time whatever the log says, so a hand-edited file
changes nothing. And ``mamori correct`` runs the value through the detectors
before writing, because a ``never`` ruling names no type at all and the check
here would have nothing to look at -- and because appending first would leave
the credential sitting in a file, which is the outcome this library exists to
avoid.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum

from .entity_types import Category, EntityType, get_type
from .sensitive_entity import SensitiveEntity

__all__ = [
    "PROTECTED_CATEGORIES",
    "Correction",
    "CorrectionLog",
    "Verdict",
]

#: Categories no correction may exclude. A credential ruled "not sensitive" is
#: a credential in somebody's prompt.
PROTECTED_CATEGORIES: frozenset[Category] = frozenset({Category.SECRET})

#: Shorter than this and a correction would match too much of a document. Same
#: floor as :mod:`mamori.domain.occurrences`, for the same reason.
MIN_CORRECTION_LENGTH = 2


class Verdict(str, Enum):
    """What the operator said about a value."""

    #: Not sensitive here. Detections of it are dropped.
    NEVER = "never"
    #: Sensitive here, whatever the rules think. Added wherever it appears.
    ALWAYS = "always"


@dataclass(frozen=True, slots=True)
class Correction:
    """One ruling about one value."""

    value: str
    verdict: Verdict
    #: Which type an ``ALWAYS`` value is. Ignored for ``NEVER``, which is about
    #: the value rather than about any particular reading of it.
    entity_type: str = ""
    #: Why. Optional, and the first thing anybody reviewing the log wants.
    note: str = ""
    #: When, as the caller chose to record it. A string rather than a
    #: timestamp: the domain layer does not read a clock, and an operator
    #: pasting a ticket reference here is doing something reasonable.
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("a correction needs a value")
        if len(self.value) < MIN_CORRECTION_LENGTH:
            raise ValueError(
                f"{self.value!r} is too short to correct: it would match most of a document"
            )
        if self.verdict is Verdict.ALWAYS and not self.entity_type:
            raise ValueError("an 'always' correction must say which type the value is")
        if self.verdict is Verdict.ALWAYS:
            resolved = get_type(self.entity_type)
            if resolved is None:
                raise ValueError(f"unknown entity type {self.entity_type!r}")

    def resolved_type(self) -> EntityType | None:
        return get_type(self.entity_type) if self.entity_type else None

    def as_mapping(self) -> dict[str, str]:
        return {
            "value": self.value,
            "verdict": self.verdict.value,
            "entity_type": self.entity_type,
            "note": self.note,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class CorrectionLog:
    """Every ruling, in the order they were made.

    Append-only. The latest entry about a value is the one that applies, so an
    operator who changes their mind appends the opposite rather than deleting
    anything, and the history of what was decided survives.
    """

    entries: tuple[Correction, ...] = field(default_factory=tuple)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[Correction]:
        return iter(self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)

    @classmethod
    def of(cls, corrections: Iterable[Correction]) -> CorrectionLog:
        log = cls()
        for correction in corrections:
            log = log.appended(correction)
        return log

    def appended(self, correction: Correction) -> CorrectionLog:
        """Return a log with one more ruling on the end.

        Raises:
            ValueError: The correction would allow-list a credential. Refused
                here as well as at read time, so a log cannot be *written*
                containing one either.
        """
        _refuse_protected(correction)
        return CorrectionLog(entries=(*self.entries, correction))

    def current(self) -> dict[str, Correction]:
        """The ruling that applies to each value: the last one made."""
        latest: dict[str, Correction] = {}
        for correction in self.entries:
            latest[correction.value] = correction
        return latest

    def verdict_for(self, value: str) -> Correction | None:
        return self.current().get(value)

    def excluded(self) -> tuple[Correction, ...]:
        """Values currently ruled not sensitive. What protection was given up."""
        return tuple(c for c in self.current().values() if c.verdict is Verdict.NEVER)

    def added(self) -> tuple[Correction, ...]:
        """Values currently ruled sensitive whatever the rules think."""
        return tuple(c for c in self.current().values() if c.verdict is Verdict.ALWAYS)

    def excludes(self, entity: SensitiveEntity) -> bool:
        """Whether this detection has been ruled away.

        A protected category is never excluded, however the log was written.
        The check at append time can be bypassed by editing a file; this one
        cannot be bypassed at all.
        """
        if entity.entity_type.category in PROTECTED_CATEGORIES:
            return False
        correction = self.current().get(entity.value)
        return correction is not None and correction.verdict is Verdict.NEVER

    def as_mapping(self) -> dict[str, object]:
        return {"entries": [c.as_mapping() for c in self.entries]}


def _refuse_protected(correction: Correction) -> None:
    """Refuse an exclusion that names a credential type.

    Limited on purpose: a ``never`` ruling usually names no type, so this sees
    nothing and :meth:`CorrectionLog.excludes` is what actually holds. The
    caller is expected to check the value itself before writing -- see
    ``mamori correct``.
    """
    if correction.verdict is not Verdict.NEVER:
        return
    entity_type = correction.resolved_type()
    if entity_type is not None and entity_type.category in PROTECTED_CATEGORIES:
        raise ValueError(
            f"{entity_type.name} is a credential and cannot be ruled 'never'. "
            "A password ruled not sensitive is a password in somebody's prompt."
        )
