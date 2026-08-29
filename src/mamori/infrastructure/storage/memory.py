"""In-memory mapping store.

The default. Mappings never touch the disk, so there is no file to leak, no
file to encrypt and no file to forget to delete. A persistent store is a
deliberate choice a user should have to make, not the default they inherit.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence

from ...domain.mapping import Mapping
from ...domain.placeholder import Placeholder

__all__ = ["InMemoryMappingStore"]


class InMemoryMappingStore:
    """Thread-safe, process-local implementation of ``MappingStore``."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_identity: dict[tuple[str, str], Mapping] = {}
        self._by_placeholder: dict[tuple[str, Placeholder], Mapping] = {}
        self._counters: dict[tuple[str, str], int] = {}

    def find_by_identity(self, scope: str, identity_key: str) -> Mapping | None:
        with self._lock:
            return self._by_identity.get((scope, identity_key))

    def find_by_placeholder(self, scope: str, placeholder: Placeholder) -> Mapping | None:
        with self._lock:
            return self._by_placeholder.get((scope, placeholder))

    def put(self, mapping: Mapping) -> None:
        with self._lock:
            self._by_placeholder[(mapping.scope, mapping.placeholder)] = mapping
            if mapping.identity_key:
                self._by_identity[(mapping.scope, mapping.identity_key)] = mapping

    def next_index(self, scope: str, entity_type_name: str) -> int:
        with self._lock:
            key = (scope, entity_type_name)
            index = self._counters.get(key, 0) + 1
            self._counters[key] = index
            return index

    def list_scope(self, scope: str) -> Sequence[Mapping]:
        with self._lock:
            return tuple(
                mapping
                for (mapping_scope, _), mapping in self._by_placeholder.items()
                if mapping_scope == scope
            )

    def purge(self, scope: str) -> None:
        """Drop every mapping in ``scope``.

        Python cannot guarantee the string objects are erased from memory, so
        this is not a secure wipe -- see ``docs/threat-model.md``. It does
        remove the references, which is what a process-local store can offer.
        """
        with self._lock:
            self._by_identity = {
                key: value for key, value in self._by_identity.items() if key[0] != scope
            }
            self._by_placeholder = {
                key: value for key, value in self._by_placeholder.items() if key[0] != scope
            }
            self._counters = {
                key: value for key, value in self._counters.items() if key[0] != scope
            }
