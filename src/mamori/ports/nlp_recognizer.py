"""Named-entity recognition, as something this library asks rather than does.

The pattern rules find what has a shape. A personal name does not have one --
`SECURITY.md` calls an unanchored English name *"the largest single gap in the
library"* -- and the only things that close it are a dictionary, an anchor
word, or a model that reads the sentence. The first two are what this library
already has, and their limits are measured and published.

A statistical recogniser is the third, and it is what every comparable tool
reaches for. Measured on the same sentences the English rules are measured on:

    balanced stance        found 0 of 4 real names, 0 of 4 false positives
    recall-first stance    found 4 of 4 real names, and pays for it elsewhere
    spaCy en_core_web_sm   found 3 of 4 real names, 0 of 4 false positives

So this is a port rather than an import: mamori asks a recogniser what it can
see, and a recogniser is a name in a configuration. Which model, and whether
one runs at all, stays the deployment's decision -- the same shape the LLM
pass, the language packs and the secrets algorithm already have.

**Nothing here reaches the domain.** A recogniser returns labels and offsets;
mapping a label onto an entity type, deciding what the policy does with it and
resolving it against everything else are unchanged and stay in code with no
model in it. A model is not the security mechanism, and this port is where
that rule is enforced rather than restated.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..domain.span import Span

__all__ = ["NlpRecognizer", "RecognizedEntity"]


@dataclass(frozen=True, slots=True)
class RecognizedEntity:
    """One thing a recogniser saw, in its own vocabulary.

    Security note:
        There is no ``value`` field. A recogniser reports *where*, and the
        application reads the characters itself -- so a recogniser cannot
        report a span and a value that disagree, which is the failure that puts
        the wrong characters back into a document.
    """

    #: The recogniser's own label -- ``PERSON``, ``ORG``, ``PER``, ``B-LOC``.
    #: Not mamori's vocabulary: translating is the adapter's job, and a port
    #: that demanded mamori's names would push that translation into every
    #: implementation.
    label: str
    span: Span
    #: How sure it is, in ``[0, 1]``. Models that do not score their output say
    #: ``1.0``, and the pass that uses this decides what a model's certainty is
    #: worth -- which is not the same question.
    score: float = 1.0


@runtime_checkable
class NlpRecognizer(Protocol):
    """Finds entities in text by reading it rather than by matching a shape.

    Implementations receive **normalized** text and return spans in the
    coordinates of the string they were given, exactly as a ``Detector`` does.

    A recogniser that cannot do its job must raise. Returning nothing to signal
    failure is the fail-open bug this library exists to avoid: the caller
    cannot tell *"no names here"* from *"the model did not load"*.
    """

    @property
    def name(self) -> str:
        """Stable identifier, recorded on every entity this produces."""
        ...

    def entities(self, text: str) -> Sequence[RecognizedEntity]:
        """Return what this recogniser sees in ``text``."""
        ...
