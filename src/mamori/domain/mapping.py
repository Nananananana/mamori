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
    #: What was actually substituted into the text, when that is not the
    #: placeholder token. Empty for every mapping mamori has ever made by
    #: default; non-empty means a surrogate was used, and restoration has to
    #: look for a plain string rather than for a token shape.
    #:
    #: Excluded from ``repr`` like the original value. A surrogate is not
    #: sensitive, but the pair (surrogate, mapping) is exactly the lookup table
    #: this library exists to keep off other people's machines.
    surface: str = field(repr=False, default="")

    @property
    def token(self) -> str:
        return self.placeholder.token

    @property
    def substituted(self) -> str:
        """What the model sees in place of the original."""
        return self.surface or self.placeholder.token

    @property
    def is_surrogate(self) -> bool:
        return bool(self.surface)
