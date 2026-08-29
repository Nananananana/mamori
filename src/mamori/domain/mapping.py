"""The link between a placeholder and the value it replaced.

This is the most sensitive object in the system: a mapping table is a
collection of exactly the values the user was trying to protect. Treat it as a
secret in its own right -- see ``docs/threat-model.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .placeholder import Placeholder

__all__ = ["Mapping"]


@dataclass(frozen=True, slots=True)
class Mapping:
    """One placeholder <-> original value pair, valid within one scope."""

    scope: str
    placeholder: Placeholder
    entity_type_name: str
    original_value: str = field(repr=False)
    identity_key: str = field(repr=False, default="")

    @property
    def token(self) -> str:
        return self.placeholder.token
