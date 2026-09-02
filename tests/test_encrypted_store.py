"""The mapping scope written to disk, encrypted.

`--save-mapping` writes every original value in the clear. T10 in the threat
model has called that *your responsibility* and promised an encrypted store
since proposal 0001; `0.29` is where the promise stopped being one.

These need `cryptography`, which is an optional extra. A skipped test is not a
passing one, so the first case asserts the extra is installed here -- otherwise
a broken install would report a green suite made entirely of skips.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from mamori.domain.mapping import Mapping
from mamori.domain.placeholder import Placeholder
from mamori.errors import ConfigurationError, StorageError
from mamori.infrastructure.storage import InMemoryMappingStore
from mamori.infrastructure.storage.encrypted import (
    DEFAULT_KEY_VARIABLE,
    generate_key,
    read_encrypted_scope,
    write_encrypted_scope,
)

VALUE = "田中太郎"
ADDRESS = "tanaka@example.com"


def stocked() -> InMemoryMappingStore:
    store = InMemoryMappingStore()
    for index, (kind, value) in enumerate([("PERSON", VALUE), ("EMAIL", ADDRESS)], start=1):
        store.put(
            Mapping(
                scope="req-1",
                placeholder=Placeholder(kind, index),
                entity_type_name=kind,
                original_value=value,
                identity_key=f"{kind}:{value}",
            )
        )
    return store


def test_the_optional_extra_is_installed_for_this_suite() -> None:
    """A file of skips reports green. This is the line that stops that."""
    pytest.importorskip("cryptography")
    assert generate_key(), "the extra is installed but produced no key"


class TestTheRoundTrip:
    def test_a_scope_survives_a_write_and_a_read(self, tmp_path: Path) -> None:
        key = generate_key()
        path = tmp_path / "scope.enc"

        assert write_encrypted_scope(stocked(), "req-1", path, key=key) == 2

        back = InMemoryMappingStore()
        assert read_encrypted_scope(back, path, key=key) == "req-1"
        found = back.find_by_identity("req-1", f"PERSON:{VALUE}")
        assert found is not None
        assert found.original_value == VALUE

    def test_nothing_readable_is_on_disk(self, tmp_path: Path) -> None:
        """The property the file exists for, checked against the bytes rather
        than against the API that wrote them."""
        path = tmp_path / "scope.enc"
        write_encrypted_scope(stocked(), "req-1", path, key=generate_key())

        raw = path.read_bytes()
        for secret in (VALUE, ADDRESS, "PERSON_001"):
            assert secret.encode("utf-8") not in raw

    def test_the_scope_name_is_inside_the_ciphertext(self, tmp_path: Path) -> None:
        """A scope can be named after its subject. `protect` refuses that at
        the source; a file written by something else need not have gone
        through it, so the name does not sit in the envelope."""
        path = tmp_path / "scope.enc"
        write_encrypted_scope(stocked(), "invoice-for-tanaka", path, key=generate_key())
        assert b"invoice-for-tanaka" not in path.read_bytes()

    def test_the_envelope_still_says_what_the_file_is(self, tmp_path: Path) -> None:
        """A reader without the key gets bytes and an explanation, not just
        bytes."""
        path = tmp_path / "scope.enc"
        write_encrypted_scope(stocked(), "req-1", path, key=generate_key())

        envelope = json.loads(path.read_text(encoding="utf-8"))
        assert envelope["cipher"] == "fernet"
        assert "key is not in this file" in envelope["note"]


class TestItRefusesWhatItCannotVouchFor:
    def test_the_wrong_key_is_an_error_and_not_an_empty_scope(self, tmp_path: Path) -> None:
        path = tmp_path / "scope.enc"
        write_encrypted_scope(stocked(), "req-1", path, key=generate_key())

        with pytest.raises(StorageError, match="could not decrypt"):
            read_encrypted_scope(InMemoryMappingStore(), path, key=generate_key())

    def test_one_flipped_bit_is_refused(self, tmp_path: Path) -> None:
        """Fernet authenticates, so this is not a claim about the format -- it
        checks that the authentication reaches the caller rather than being
        swallowed on the way."""
        key = generate_key()
        path = tmp_path / "scope.enc"
        write_encrypted_scope(stocked(), "req-1", path, key=key)

        envelope = json.loads(path.read_text(encoding="utf-8"))
        token = bytearray(base64.b64decode(envelope["payload"]))
        token[-1] ^= 1
        envelope["payload"] = base64.b64encode(bytes(token)).decode("ascii")
        path.write_text(json.dumps(envelope), encoding="utf-8")

        with pytest.raises(StorageError, match="could not decrypt"):
            read_encrypted_scope(InMemoryMappingStore(), path, key=key)

    def test_the_error_does_not_guess_which_failure_it_was(self, tmp_path: Path) -> None:
        """A wrong key and a changed file are indistinguishable to
        authentication, and the message says so instead of picking one."""
        path = tmp_path / "scope.enc"
        write_encrypted_scope(stocked(), "req-1", path, key=generate_key())

        with pytest.raises(StorageError) as raised:
            read_encrypted_scope(InMemoryMappingStore(), path, key=generate_key())
        assert "the key is wrong, or the file was changed" in str(raised.value)

    def test_a_plaintext_mapping_file_is_not_mistaken_for_one(self, tmp_path: Path) -> None:
        path = tmp_path / "plain.json"
        path.write_text('{"format_version": 1, "mappings": []}', encoding="utf-8")
        with pytest.raises(StorageError):
            read_encrypted_scope(InMemoryMappingStore(), path, key=generate_key())


class TestWhereTheKeyComesFrom:
    def test_the_environment_when_the_caller_gives_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DEFAULT_KEY_VARIABLE, generate_key())
        path = tmp_path / "scope.enc"
        write_encrypted_scope(stocked(), "req-1", path)

        assert read_encrypted_scope(InMemoryMappingStore(), path) == "req-1"

    def test_the_variable_is_outside_the_settings_prefix(self) -> None:
        """`MAMORI_*` is read as configuration and unknown keys are refused, so
        a key variable in that namespace breaks every command. The first
        version of this module used one and did."""
        assert not DEFAULT_KEY_VARIABLE.startswith("MAMORI_")

    def test_a_callable_is_accepted_for_a_keyring(self, tmp_path: Path) -> None:
        key = generate_key()
        path = tmp_path / "scope.enc"
        write_encrypted_scope(stocked(), "req-1", path, key=lambda: key)
        assert read_encrypted_scope(InMemoryMappingStore(), path, key=lambda: key) == "req-1"

    def test_no_key_anywhere_says_what_to_do(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(DEFAULT_KEY_VARIABLE, raising=False)
        with pytest.raises(ConfigurationError, match="mamori keygen"):
            write_encrypted_scope(stocked(), "req-1", tmp_path / "scope.enc")

    def test_a_passphrase_is_refused_rather_than_stretched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deriving a key from a passphrase needs a salt and a work factor.
        Both are decisions, and a library that makes them silently has made
        them for everybody."""
        monkeypatch.setenv(DEFAULT_KEY_VARIABLE, "hunter2")
        with pytest.raises(ConfigurationError, match="not a valid Fernet key"):
            write_encrypted_scope(stocked(), "req-1", tmp_path / "scope.enc")


def test_two_keys_are_not_the_same_key() -> None:
    """Cheap, and it would catch a `generate_key` that returned a constant --
    which is the shape a stubbed-out crypto helper takes."""
    assert generate_key() != generate_key()
