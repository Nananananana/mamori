"""In-memory mapping store.

The default. Mappings never touch the disk, so there is no file to leak, no
file to encrypt and no file to forget to delete. A persistent store is a
deliberate choice a user should have to make, not the default they inherit.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence

from ...domain.mapping import Mapping
from ...domain.placeholder import Placeholder
from ...domain.retention import Retention

__all__ = ["InMemoryMappingStore"]


class InMemoryMappingStore:
    """Thread-safe, process-local implementation of ``MappingStore``."""

    def __init__(
        self,
        retention: Retention | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Args:
        retention: How long to keep a mapping. Forever by default, which
            is what this store did before `0.29`: expiring by surprise
            would be a worse change than not expiring at all.
        clock: Monotonic, so a clock adjustment cannot resurrect an
            expired mapping or retire a live one. Injected because a test
            that waited a real half hour would not be run.
        """
        self._clock = clock
        self._lock = threading.RLock()
        self._by_identity: dict[tuple[str, str], Mapping] = {}
        self._by_placeholder: dict[tuple[str, Placeholder], Mapping] = {}
        self._counters: dict[tuple[str, str], int] = {}
        self._written: dict[tuple[str, Placeholder], float] = {}
        self._retention = retention if retention is not None else Retention.forever()

    @property
    def retention(self) -> Retention:
        """How long this store keeps what it keeps. Read by `mamori privacy`."""
        return self._retention

    def find_by_identity(self, scope: str, identity_key: str) -> Mapping | None:
        with self._lock:
            self._drop_expired()
            return self._by_identity.get((scope, identity_key))

    def find_by_placeholder(self, scope: str, placeholder: Placeholder) -> Mapping | None:
        with self._lock:
            self._drop_expired()
            return self._by_placeholder.get((scope, placeholder))

    def put(self, mapping: Mapping) -> None:
        with self._lock:
            self._drop_expired()
            key = (mapping.scope, mapping.placeholder)
            self._by_placeholder[key] = mapping
            self._written[key] = self._clock()
            if mapping.identity_key:
                self._by_identity[(mapping.scope, mapping.identity_key)] = mapping

    def _drop_expired(self) -> None:
        """Forget what the retention rule says is past its time.

        Called from every read and write rather than from a timer. A sweeper
        thread would delete at moments the caller cannot predict or observe,
        and would make this store's contents depend on how long the process
        had been running -- which is what proposal 0002 meant by *a stated
        rule rather than a background process*.

        The caller must hold the lock.
        """
        if self._retention.is_forever:
            return
        now = self._clock()
        stale = [key for key, at in self._written.items() if self._retention.expired(at, now)]
        for key in stale:
            mapping = self._by_placeholder.pop(key, None)
            self._written.pop(key, None)
            if mapping is not None and mapping.identity_key:
                self._by_identity.pop((mapping.scope, mapping.identity_key), None)

    def next_index(self, scope: str, entity_type_name: str) -> int:
        with self._lock:
            key = (scope, entity_type_name)
            index = self._counters.get(key, 0) + 1
            self._counters[key] = index
            return index

    def list_scope(self, scope: str) -> Sequence[Mapping]:
        with self._lock:
            self._drop_expired()
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
            self._written = {key: value for key, value in self._written.items() if key[0] != scope}
