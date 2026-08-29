"""Placeholder tokens.

A placeholder is what the external LLM sees in place of a sensitive value. The
format is deliberately readable -- ``<PERSON_001>`` rather than a random
string -- so the model keeps enough structure to write a sensible answer, and
so that a human reviewing the outbound payload can tell what was removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["STRICT_PLACEHOLDER_RE", "Placeholder"]

#: Exactly the form this library emits.
STRICT_PLACEHOLDER_RE = re.compile(r"<([A-Z][A-Z0-9_]{0,62})_(\d{1,6})>")


@dataclass(frozen=True, slots=True, order=True)
class Placeholder:
    """``<TYPE_NNN>`` -- a stable stand-in for one entity within a scope."""

    entity_type_name: str
    index: int

    def __post_init__(self) -> None:
        if self.index < 1:
            raise ValueError(f"placeholder index must be >= 1, got {self.index}")

    @property
    def token(self) -> str:
        """The canonical text form, e.g. ``<PERSON_001>``."""
        return f"<{self.entity_type_name}_{self.index:03d}>"

    @classmethod
    def parse(cls, token: str) -> Placeholder | None:
        """Parse a canonical token. Returns ``None`` if it is not one."""
        match = STRICT_PLACEHOLDER_RE.fullmatch(token)
        if match is None:
            return None
        return cls(match.group(1), int(match.group(2)))

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.token
