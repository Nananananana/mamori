"""A mapping scope written to disk, encrypted, for the two-process case.

`--save-mapping` writes every original value in the clear. That is T10 in the
threat model, and it has said "an encrypted store is on the roadmap" since
proposal 0001. This is that store.

**What it protects against.** Somebody who obtains the file and not the key.
A backup that got copied somewhere it should not be, a directory that turned
out to be synced, a laptop that was lost. The file is a single artefact holding
every value removed from a document, which is what makes it worth encrypting at
all.

**What it does not protect against**, and this matters more than the feature:

- **A compromised machine.** Out of scope in the threat model since the first
  release, and still out of scope. If something is reading the process, the key
  is in the process.
- **A key beside the file.** `MAMORI_MAPPING_KEY=...` in the same directory,
  the same repository, or the same backup is a file with a decorative lock on
  it. Nothing here can tell whether the key travelled with the ciphertext.
- **Erasure.** Deleting the file does not overwrite the disk, and dropping the
  key does not overwrite memory. See `Retention`.

The key never comes from a configuration file. That is the same rule
`api_key_env` follows, for the same reason: a value in a settings file is a
value in version control, eventually.

Encryption itself is **not implemented here**. `cryptography` provides Fernet
-- AES-128-CBC with an HMAC-SHA256 authentication tag, a version byte and a
timestamp -- and this module composes it. Writing a cipher, or a mode, or a
padding scheme by hand would be the single worst thing this file could do, and
a reviewer who found one would be right to stop reading.

It is an optional dependency, so the package's promise of zero runtime
dependencies is unchanged for anybody who does not ask for this:

    pip install "mamori[encrypted]"
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from ...domain.mapping import Mapping
from ...domain.placeholder import Placeholder
from ...errors import ConfigurationError, StorageError
from ...ports.mapping_store import MappingStore

if TYPE_CHECKING:  # pragma: no cover
    from cryptography.fernet import Fernet

__all__ = [
    "DEFAULT_KEY_VARIABLE",
    "KeySource",
    "generate_key",
    "read_encrypted_scope",
    "write_encrypted_scope",
]

#: Where the key is read from when the caller does not supply one.
#:
#: **Outside the `MAMORI_` prefix on purpose.** That prefix is reserved for
#: settings: the loader reads every `MAMORI_*` variable as a configuration key
#: and refuses the ones it does not recognise. The first version of this module
#: used `MAMORI_MAPPING_KEY` and every command died with *"unknown
#: configuration key(s): mapping_key"* -- and the error went on to say that a
#: key variable needs a name outside the prefix, which this project had already
#: written down and this module had not read.
DEFAULT_KEY_VARIABLE = "MAPPING_ENCRYPTION_KEY"

_FORMAT_VERSION = 1
_MAGIC = "mamori.encrypted-mapping/1"

#: A key, or something that produces one. A callable is the escape hatch for a
#: keyring, a secrets manager, or a prompt -- anything that is not an
#: environment variable and is still not a configuration file.
KeySource = str | bytes | Callable[[], str | bytes]


def _fernet_class() -> type[Fernet]:
    """Import Fernet, or explain what to install.

    Deferred so that importing `mamori` costs nothing for the majority who
    never write a mapping to disk, and so the error names the extra rather than
    surfacing as a bare `ModuleNotFoundError` from three frames down.
    """
    try:
        from cryptography.fernet import Fernet
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on install
        raise ConfigurationError(
            "the encrypted mapping store needs the `cryptography` package: "
            'pip install "mamori[encrypted]". It is optional because the '
            "default store writes nothing to disk and needs no cipher."
        ) from exc
    return Fernet


def generate_key() -> str:
    """A new key, as text safe to put in an environment variable.

    Printed by `mamori keygen`. Generating one here rather than asking the
    caller to invent a password: a passphrase would need a KDF, a salt and a
    decision about work factor, and every one of those is somewhere else to get
    it wrong.
    """
    return _fernet_class().generate_key().decode("ascii")


def _resolve_key(key: KeySource | None) -> bytes:
    """Get the key, from the caller or the environment, and never from settings."""
    if callable(key):
        key = key()
    if key is None:
        from_env = os.environ.get(DEFAULT_KEY_VARIABLE)
        if not from_env:
            raise ConfigurationError(
                f"no key for the encrypted mapping store. Set {DEFAULT_KEY_VARIABLE}, "
                "or pass one. `mamori keygen` prints a new one. The key is never "
                "read from a configuration file, because a settings file ends up "
                "in version control."
            )
        key = from_env
    material = key.encode("ascii") if isinstance(key, str) else key
    try:
        _fernet_class()(material)
    except (ValueError, TypeError) as exc:
        raise ConfigurationError(
            "the mapping key is not a valid Fernet key. `mamori keygen` prints one; "
            "a passphrase will not work, because deriving a key from one needs "
            "choices this library declines to make on your behalf."
        ) from exc
    return material


def write_encrypted_scope(
    store: MappingStore,
    scope: str,
    path: Path,
    *,
    key: KeySource | None = None,
) -> int:
    """Write every mapping in ``scope`` to ``path``, encrypted. Returns the count.

    The scope name is inside the ciphertext rather than beside it. A filename
    and a header are the two places a scope would otherwise leak, and a scope
    can be named after its subject -- which `protect` refuses at the source,
    but a file written by something else need not have gone through that.
    """
    mappings = sorted(store.list_scope(scope), key=lambda m: m.placeholder)
    payload = json.dumps(
        {
            "magic": _MAGIC,
            "scope": scope,
            "mappings": [
                {
                    "placeholder": mapping.placeholder.token,
                    "entity_type": mapping.entity_type_name,
                    "original_value": mapping.original_value,
                    "identity_key": mapping.identity_key,
                    "surface": mapping.surface,
                }
                for mapping in mappings
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")

    token = _fernet_class()(_resolve_key(key)).encrypt(payload)
    envelope = json.dumps(
        {
            "format_version": _FORMAT_VERSION,
            # Outside the ciphertext on purpose: a reader with the wrong key,
            # or no key, still learns what this file is and what to do about
            # it. Neither line says anything about the document.
            "cipher": "fernet",
            "note": (
                "Encrypted mapping scope. The key is not in this file and is "
                "not in any mamori settings file. Without it this is bytes."
            ),
            "payload": base64.b64encode(token).decode("ascii"),
        },
        indent=2,
    )
    _write_privately(path, envelope)
    return len(mappings)


def _write_privately(path: Path, text: str) -> None:
    """Write, and on POSIX take the group and world bits off first.

    A file created with the default umask is often readable by the group. This
    closes the window between creating it and anybody noticing, which is the
    kind of gap that is invisible in a test on the machine that wrote it.

    Windows ignores the mode and gets the directory's ACL, so this is an
    improvement where it applies and not a claim where it does not.
    """
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)


def read_encrypted_scope(
    store: MappingStore,
    path: Path,
    *,
    key: KeySource | None = None,
    scope: str | None = None,
) -> str:
    """Load an encrypted scope into ``store``. Returns the scope used.

    Raises:
        StorageError: the file is unreadable, not one of ours, or does not
            authenticate. **A wrong key and a tampered file are the same
            error**, because Fernet cannot tell them apart and neither can
            this: both mean the bytes are not what was written.
    """
    fernet = _fernet_class()
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StorageError(f"could not read encrypted mapping file: {path}") from exc

    if not isinstance(envelope, dict) or envelope.get("format_version") != _FORMAT_VERSION:
        raise StorageError(f"not an encrypted mapping file this version can read: {path}")

    try:
        token = base64.b64decode(str(envelope.get("payload", "")), validate=True)
    except (ValueError, TypeError) as exc:
        raise StorageError(f"malformed encrypted mapping file: {path}") from exc

    try:
        payload = json.loads(fernet(_resolve_key(key)).decrypt(token))
    except ConfigurationError:
        raise
    except Exception as exc:
        raise StorageError(
            f"could not decrypt {path}: the key is wrong, or the file was changed "
            "since it was written. These are the same failure -- authentication "
            "does not say which."
        ) from exc

    if payload.get("magic") != _MAGIC:
        raise StorageError(f"decrypted, but not a mamori mapping scope: {path}")

    target = scope or str(payload.get("scope") or "")
    if not target:
        raise StorageError("encrypted mapping file has no scope and none was given")

    for record in payload.get("mappings", []):
        placeholder = Placeholder.parse(str(record.get("placeholder", "")))
        if placeholder is None:
            raise StorageError("encrypted mapping file contains a malformed placeholder")
        store.put(
            Mapping(
                scope=target,
                placeholder=placeholder,
                entity_type_name=str(record.get("entity_type", placeholder.entity_type_name)),
                original_value=str(record.get("original_value", "")),
                identity_key=str(record.get("identity_key", "")),
                surface=str(record.get("surface", "")),
            )
        )
    return target
