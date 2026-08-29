"""Export and import a mapping scope as JSON.

This exists so the CLI can protect in one process and restore in another. It is
**not** a recommended way to run the library.

A file written by :func:`dump_scope` contains every value that was removed from
the prompt, in the clear. It is exactly the material the library exists to keep
off other machines, concentrated into one artefact that is easy to copy, easy
to back up by accident, and easy to forget. Use it for a scripted round trip
you control, delete it afterwards, and keep it out of version control.

A future release will add an encrypted store; until then this module refuses to
pretend the plaintext form is safe.
"""

from __future__ import annotations

import json
from pathlib import Path

from ...domain.mapping import Mapping
from ...domain.placeholder import Placeholder
from ...errors import StorageError
from ...ports.mapping_store import MappingStore

__all__ = ["PLAINTEXT_WARNING", "dump_scope", "load_scope"]

PLAINTEXT_WARNING = (
    "This file contains the original values in plain text. "
    "Delete it when you are done and never commit it."
)

_FORMAT_VERSION = 1


def dump_scope(store: MappingStore, scope: str, path: Path) -> int:
    """Write every mapping in ``scope`` to ``path``. Returns the count."""
    records = [
        {
            "placeholder": mapping.placeholder.token,
            "entity_type": mapping.entity_type_name,
            "original_value": mapping.original_value,
            "identity_key": mapping.identity_key,
        }
        for mapping in sorted(store.list_scope(scope), key=lambda m: m.placeholder)
    ]
    payload = {
        "format_version": _FORMAT_VERSION,
        "warning": PLAINTEXT_WARNING,
        "scope": scope,
        "mappings": records,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(records)


def load_scope(store: MappingStore, path: Path, scope: str | None = None) -> str:
    """Load mappings from ``path`` into ``store``. Returns the scope used."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StorageError(f"could not read mapping file: {path}") from exc

    if not isinstance(payload, dict) or payload.get("format_version") != _FORMAT_VERSION:
        raise StorageError(f"unsupported mapping file format: {path}")

    target_scope = scope or str(payload.get("scope") or "")
    if not target_scope:
        raise StorageError("mapping file has no scope and none was given")

    for record in payload.get("mappings", []):
        placeholder = Placeholder.parse(str(record.get("placeholder", "")))
        if placeholder is None:
            raise StorageError("mapping file contains a malformed placeholder")
        store.put(
            Mapping(
                scope=target_scope,
                placeholder=placeholder,
                entity_type_name=str(record.get("entity_type", placeholder.entity_type_name)),
                original_value=str(record.get("original_value", "")),
                identity_key=str(record.get("identity_key", "")),
            )
        )
    return target_scope
