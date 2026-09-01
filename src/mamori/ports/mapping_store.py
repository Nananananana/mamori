"""Mapping store port.

A mapping store holds placeholder <-> original-value pairs. It is the highest
value target in the system; implementations that persist to disk must encrypt
and must support deletion.

Every store also states its retention: how long it keeps what it keeps. The
default is forever, which is what every store did before `0.29` and remains the
default, because expiring by surprise would be a worse change than not expiring
at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ..domain.mapping import Mapping
from ..domain.placeholder import Placeholder
from ..domain.retention import Retention

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

    @property
    def retention(self) -> Retention:
        """How long this store keeps what it keeps.

        A property rather than a method because it is a statement about the
        store, not a question to ask it -- `mamori privacy` prints it so that
        somebody deciding whether to trust this with a document can read the
        answer instead of inferring it.

        Expiry happens when the store is used. Nothing here starts a thread:
        a sweeper deletes at moments the caller cannot predict or observe, and
        makes a store's contents depend on how long the process has been
        running.
        """
        ...
