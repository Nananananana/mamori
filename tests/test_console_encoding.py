"""The CLI prints on a console that cannot represent everything it prints.

`cp932` is what a Japanese Windows user gets with no configuration, and this
project's primary languages are Japanese and English. A command that raises
`UnicodeEncodeError` on a name it has just detected is broken for the people it
was written for.

Two separate things keep that from happening, and they fail differently:

**`_force_utf8` reconfigures the stream**, which is what lets a Chinese
document survive on a Japanese console. Nothing checked it. CI runners are
UTF-8, so deleting the call leaves every other test green and only a user on
`cp932` sees the traceback -- the environment hiding the failure rather than
the code causing it. A sibling project found the same defect in three commands
at once.

**mamori's own output does not stay inside `cp932`**, and cannot. `mamori
prompt detection` prints the guidance a local model is given, which explains
Chinese honorifics and company suffixes in simplified characters -- eleven of
them outside `cp932`. This file first asserted the opposite, measured it, and
was wrong: the reconfigure is not insurance, it is load-bearing, and removing
it breaks a command a Japanese user has every reason to run.

The first is exercised by Chinese text, not Japanese: `cp932` covers Japanese.
A test that fed this `田中太郎` would pass with the reconfigure removed, which
is what the first version of this file did.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import ClassVar

import pytest

from mamori.interfaces.cli.main import _force_utf8, main

#: Simplified forms `cp932` has no room for. The Chinese rules are full of
#: them, and a Chinese document read on a Japanese desktop is not exotic.
OUTSIDE_CP932 = "连络"


def outside_cp932(text: str) -> set[str]:
    """Every character in ``text`` a cp932 console would refuse."""
    refused = set()
    for character in text:
        try:
            character.encode("cp932")
        except UnicodeEncodeError:
            refused.add(character)
    return refused


class _Cp932Stream:
    """A stream that refuses what a cp932 console refuses.

    Standing in for the console rather than asserting `reconfigure` was
    called: that assertion would pass on a stream reconfigured to something
    else entirely.
    """

    def __init__(self) -> None:
        self.encoding = "cp932"
        self.errors = "strict"
        self.written: list[str] = []

    def write(self, text: str) -> int:
        text.encode(self.encoding)  # raises exactly as the console would
        self.written.append(text)
        return len(text)

    def reconfigure(self, *, encoding: str | None = None, **_: object) -> None:
        if encoding:
            self.encoding = encoding

    def isatty(self) -> bool:
        return False

    def flush(self) -> None:
        pass


def test_the_stand_in_refuses_what_cp932_refuses() -> None:
    """Otherwise everything below passes against a stream that accepts anything."""
    stream = _Cp932Stream()
    with pytest.raises(UnicodeEncodeError):
        stream.write(OUTSIDE_CP932)
    assert outside_cp932(OUTSIDE_CP932) == set(OUTSIDE_CP932)
    assert not outside_cp932("田中太郎"), "Japanese is inside cp932; it tests nothing here"


def test_force_utf8_reconfigures_the_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _Cp932Stream()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", _Cp932Stream())

    _force_utf8()

    assert stream.encoding == "utf-8"
    stream.write(OUTSIDE_CP932)  # would raise without the call


def test_a_chinese_document_survives_a_japanese_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case the reconfigure exists for.

    `protect` echoes the document back with the values replaced, so the
    untouched half of a Chinese sentence reaches a console that cannot encode
    it. This is the one command in the suite whose output leaves `cp932`, and
    it leaves it because of the user's text rather than mamori's.
    """
    monkeypatch.setattr(sys, "stdout", _Cp932Stream())
    monkeypatch.setattr(sys, "stderr", _Cp932Stream())
    assert main(["protect", f"张伟さんに{OUTSIDE_CP932}"]) == 0


COMMANDS = [
    pytest.param(["locales"], id="locales"),
    pytest.param(["policy"], id="policy"),
    pytest.param(["privacy"], id="privacy"),
    pytest.param(["prompt"], id="prompt"),
    pytest.param(["prompt", "detection"], id="prompt detection"),
    pytest.param(["prompt", "detection", "--guidance"], id="prompt guidance"),
    pytest.param(["prompt", "external"], id="prompt external"),
    # Chinese, not Japanese. These carry the **user's** text into the output,
    # which is the widest path in the library -- mamori reads a document, hides
    # part of it and prints the rest back. `inspect` was written with
    # `田中太郎`, which cp932 encodes, so it passed with the reconfigure removed
    # and tested nothing. The docstring at the top of this file warns about
    # exactly that mistake and the file was making it two lines below.
    pytest.param(["inspect", f"张伟さんに{OUTSIDE_CP932}"], id="inspect"),
    pytest.param(["protect", f"张伟さんに{OUTSIDE_CP932}"], id="protect"),
    # `trace` is here for coverage of the command and **not** as a test of the
    # reconfigure -- see `test_trace_cannot_reach_the_console_with_a_value`,
    # which is the reason it cannot be one.
    pytest.param(["trace", "张伟"], id="trace"),
    pytest.param(["demo"], id="demo"),
]


@pytest.mark.parametrize("argv", COMMANDS)
def test_every_command_prints_on_a_cp932_console(
    argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole surface, because the failure is per-command.

    A sibling project had it in `explain`, `audit` and `eval` at once, and
    fixing one would have left two. Here the reconfigure covers all of them,
    which is precisely why a regression in it would be invisible from any
    single command.
    """
    monkeypatch.setattr(sys, "stdout", _Cp932Stream())
    monkeypatch.setattr(sys, "stderr", _Cp932Stream())
    assert main(argv) == 0


def test_trace_cannot_reach_the_console_with_a_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`trace` gets an exemption the other commands do not, and it is worth
    naming rather than leaving as a coincidence.

    It prints where a value was, which rules fired and what won -- and never
    the value. So its output stays inside cp932 whatever the document was, and
    a cp932 test through `trace` proves nothing about the reconfigure. Measured
    rather than assumed: a `trace` case was in the list above pretending to
    carry Chinese text, and it passed with `_force_utf8` deleted.

    The property that makes the exemption real is the one asserted here. If
    `trace` ever starts echoing a matched span, this fails, and the exemption
    ends in the same change.
    """
    stream = _Cp932Stream()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", _Cp932Stream())
    assert main(["trace", f"张伟さんに{OUTSIDE_CP932}"]) == 0

    printed = "".join(stream.written)
    assert not outside_cp932(printed), (
        "trace put a character outside cp932 on the console, which means it is "
        "now echoing the document rather than describing it"
    )
    assert "张伟" not in printed


def test_the_guidance_is_why_this_is_not_optional() -> None:
    """Named, because "it happens to work" and "it has to work" are different
    facts and only the second justifies a test.

    The Chinese guidance is mamori's own text, not a user's, so no choice of
    input avoids it.
    """
    from mamori.prompts import default_library

    rendered = default_library().render("detection")
    refused = outside_cp932(getattr(rendered, "text", None) or str(rendered))
    assert refused, (
        "the detection prompt no longer contains anything outside cp932. If "
        "the Chinese guidance was removed, that is a bigger change than this "
        "test; if it was rewritten in characters cp932 has, this test should "
        "be rewritten to say so."
    )


class TestWhatGoesIntoARedirectedFile:
    """`mamori ... > file` is a different encoding decision from the console.

    Python picks the **locale** encoding for a redirected stream, and a sibling
    project found out the hard way: its JSON report was written in `cp932`,
    was not valid JSON, and the hash it published was over bytes that were not
    in the file. It read deliberately and wrote by accident.

    mamori's `_force_utf8` reconfigures `sys.stdout`, and a redirect *is*
    `sys.stdout`, so the same call should cover this. Should is the word these
    tests are here to remove -- nothing measured it, and a fix that happens to
    cover a second case is one refactor away from covering only the first.

    Run as a real subprocess, because the redirect is what is being tested and
    `capsys` is not one.
    """

    #: `-X utf8=0` turns off UTF-8 mode so the locale decides, and `LC_ALL=C`
    #: gives POSIX a locale that cannot encode this text -- which is what
    #: `cp932` is on the Windows desktop this project is written for. One lever
    #: for two platforms, standing for the same property: the locale is not
    #: enough and the program has to say so.
    ENV: ClassVar[dict[str, str]] = {
        "PYTHONUTF8": "0",
        "PYTHONIOENCODING": "",
        "LC_ALL": "C",
        "LANG": "C",
    }

    def run(self, argv: list[str], out: Path) -> bytes:
        import os
        import subprocess

        environment = {**os.environ, **self.ENV}
        environment.pop("PYTHONIOENCODING", None)
        with out.open("wb") as handle:
            completed = subprocess.run(  # noqa: S603
                [sys.executable, "-X", "utf8=0", "-m", "mamori.interfaces.cli.main", *argv],
                stdout=handle,
                stderr=subprocess.PIPE,
                env=environment,
                check=False,
            )
        assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
        return out.read_bytes()

    def test_the_locale_here_would_not_have_been_enough(self) -> None:
        """Otherwise the two tests below prove nothing: on a UTF-8 locale a
        redirect is already UTF-8 and the reconfigure could be deleted."""
        import locale

        assert locale.getpreferredencoding(False).lower().replace("-", "") not in {
            "utf8",
            "cp65001",
        }, "this machine's locale is already UTF-8; force it with LC_ALL=C"

    def test_a_redirected_command_writes_utf8(self, tmp_path: Path) -> None:
        raw = self.run(["prompt", "detection"], tmp_path / "out.txt")
        text = raw.decode("utf-8")  # raises if the locale won
        assert outside_cp932(text), "this command's output no longer leaves cp932"

    def test_no_character_was_replaced_on_the_way_out(self, tmp_path: Path) -> None:
        """The quieter failure. A stream configured with `errors="replace"`
        writes valid UTF-8 and loses characters to `?` while doing it -- and
        for a document, as opposed to prose, a lost character is corruption
        rather than a blemish."""
        raw = self.run(["protect", f"张伟さんに{OUTSIDE_CP932}"], tmp_path / "out.txt")
        assert "?" not in raw.decode("utf-8")

    def test_a_redirected_json_document_parses(self, tmp_path: Path) -> None:
        """The failure the sibling project actually shipped: a report nobody
        could read back, including the tool that wrote it."""
        import json

        raw = self.run(["inspect", "--json", f"张伟さんに{OUTSIDE_CP932}"], tmp_path / "out.json")
        json.loads(raw.decode("utf-8"))


class TestTheFilesTheCommandsWrite:
    """A mapping file is read by a program, and a lost character is corruption.

    The rule a sibling project arrived at is the right one: a `?` in prose is
    one character and a surviving audit; a `?` in a document is a broken
    document. Everything mamori writes to a path is the second kind, and the
    mapping file is the worst of them -- lose a character in a name and the
    value never comes back, which is the one failure this library exists to
    prevent.

    The three things these check, learned from three siblings on the same day:

    1. **A real subprocess.** Replacing `sys.stdout` in-process tests the
       console path and only the console path.
    2. **The redirected path separately.** The defect that shipped elsewhere
       was on that side.
    3. **The bytes, not the exit code.** A command that writes an unparseable
       file and exits 0 looks like a survivor to anything watching for a
       crash. That is the failure that goes quiet, and it is the one worth
       catching.
    """

    ENV = TestWhatGoesIntoARedirectedFile.ENV

    def run(self, argv: list[str]) -> None:
        import os
        import subprocess

        environment = {**os.environ, **self.ENV}
        environment.pop("PYTHONIOENCODING", None)
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-X", "utf8=0", "-m", "mamori.interfaces.cli.main", *argv],
            capture_output=True,
            env=environment,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")

    def test_a_saved_mapping_is_utf8_and_parses(self, tmp_path: Path) -> None:
        import json

        path = tmp_path / "mapping.json"
        self.run(["protect", f"张伟さんに{OUTSIDE_CP932}", "--save-mapping", str(path)])

        raw = path.read_bytes()
        saved = json.loads(raw.decode("utf-8"))
        assert saved["mappings"], "nothing was saved, so nothing was checked"

    def test_the_value_in_it_is_the_value_that_went_in(self, tmp_path: Path) -> None:
        """The assertion that matters. A file can be valid UTF-8, valid JSON,
        and hold `张?` -- and the exit code is 0 either way."""
        import json

        path = tmp_path / "mapping.json"
        self.run(["protect", f"张伟さんに{OUTSIDE_CP932}", "--save-mapping", str(path)])

        saved = json.loads(path.read_text(encoding="utf-8"))
        values = [mapping["original_value"] for mapping in saved["mappings"]]
        assert "张伟" in values, f"the name did not survive being written: {values}"
        assert not any("?" in value for value in values), values

    def test_a_document_restores_from_a_mapping_written_on_that_locale(
        self, tmp_path: Path
    ) -> None:
        """End to end through two processes, both on a locale that cannot
        encode the text. Restoration is the only thing the mapping file is
        for, so it is the only real check that the file is intact."""
        import json
        import os
        import subprocess

        path = tmp_path / "mapping.json"
        document = f"张伟さんに{OUTSIDE_CP932}してください"
        self.run(["protect", document, "--save-mapping", str(path)])

        saved = json.loads(path.read_text(encoding="utf-8"))
        token = saved["mappings"][0]["placeholder"]

        environment = {**os.environ, **self.ENV}
        environment.pop("PYTHONIOENCODING", None)
        restored = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-X",
                "utf8=0",
                "-m",
                "mamori.interfaces.cli.main",
                "restore",
                f"{token}さんに连络",
                "--mapping",
                str(path),
            ],
            capture_output=True,
            env=environment,
            check=False,
        )
        assert restored.returncode == 0, restored.stderr.decode("utf-8", "replace")
        assert "张伟" in restored.stdout.decode("utf-8")

    def test_an_encrypted_mapping_decrypts_to_the_same_value(self, tmp_path: Path) -> None:
        """Ciphertext is base64 inside JSON, so the envelope cannot lose a
        character -- but the plaintext is encoded before it is encrypted, and
        that step is on the same locale as everything else here."""
        pytest.importorskip("cryptography")
        import os

        from mamori.infrastructure.storage import InMemoryMappingStore
        from mamori.infrastructure.storage.encrypted import (
            DEFAULT_KEY_VARIABLE,
            generate_key,
            read_encrypted_scope,
        )

        key = generate_key()
        path = tmp_path / "mapping.enc"
        saved = os.environ.get(DEFAULT_KEY_VARIABLE)
        os.environ[DEFAULT_KEY_VARIABLE] = key
        try:
            self.run(["protect", f"张伟さんに{OUTSIDE_CP932}", "--encrypt-mapping", str(path)])
        finally:
            if saved is None:
                del os.environ[DEFAULT_KEY_VARIABLE]
            else:
                os.environ[DEFAULT_KEY_VARIABLE] = saved

        store = InMemoryMappingStore()
        scope = read_encrypted_scope(store, path, key=key)
        values = [m.original_value for m in store.list_scope(scope)]
        assert values, "the encrypted file held no mappings, so nothing was checked"
        assert "张伟" in values, values
