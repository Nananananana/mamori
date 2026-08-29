"""Detector port."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ..domain.sensitive_entity import SensitiveEntity

__all__ = ["Detector"]


@runtime_checkable
class Detector(Protocol):
    """Finds sensitive values in text.

    Implementations receive **normalized** text and must return spans in the
    coordinates of the string they were given. The application maps those spans
    back onto the original text.

    A detector that cannot do its job must raise. Returning an empty result to
    signal failure would be a fail-open bug: the caller cannot tell "nothing
    sensitive here" from "I gave up".
    """

    @property
    def name(self) -> str:
        """Stable identifier, recorded on every entity this detector produces."""
        ...

    def detect(self, text: str) -> Sequence[SensitiveEntity]:
        """Return detections found in ``text``."""
        ...
