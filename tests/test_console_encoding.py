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
    pytest.param(["inspect", "田中太郎さんに連絡"], id="inspect"),
    pytest.param(["trace", "田中太郎"], id="trace"),
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
