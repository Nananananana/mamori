"""Mapping store port.

A mapping store holds placeholder <-> original-value pairs. It is the highest
value target in the system; implementations that persist to disk must encrypt
and must support deletion.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ..domain.mapping import Mapping
from ..domain.placeholder import Placeholder

__all__ = ["MappingStore"]


@runtime_checkable
class MappingStore(Protocol):
    """Scope-partitioned storage for mappings."""

    def find_by_identity(self, scope: str, identity_key: str) -> Mapping | None:
        """Return the mapping for an entity identity, if one was allocated."""
        ...

    def find_by_placeholder(self, scope: str, placeholder: Placeholder) -> Mapping | None:
        """Return the mapping for a placeholder, if it was allocated."""
        ...

    def put(self, mapping: Mapping) -> None:
        """Store a mapping. Must be idempotent for an identical mapping."""
        ...

    def next_index(self, scope: str, entity_type_name: str) -> int:
        """Reserve and return the next 1-based index for a type within a scope."""
        ...

    def list_scope(self, scope: str) -> Sequence[Mapping]:
        """Return every mapping in a scope."""
        ...

    def purge(self, scope: str) -> None:
        """Delete every mapping in a scope."""
        ...
