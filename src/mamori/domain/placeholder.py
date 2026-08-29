"""Placeholder tokens.

A placeholder is what the external LLM sees in place of a sensitive value. The
format is deliberately readable -- ``<PERSON_001>`` rather than a random
string -- so the model keeps enough structure to write a sensible answer, and
so that a human reviewing the outbound payload can tell what was removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

__all__ = ["STRICT_PLACEHOLDER_RE", "Placeholder", "PlaceholderStyle"]

#: Exactly the form this library emits.
STRICT_PLACEHOLDER_RE = re.compile(r"<([A-Z][A-Z0-9_]{0,62})_(\d{1,6})>")


class PlaceholderStyle(Enum):
    """Which brackets a placeholder is written with.

    The identity of a placeholder is its ``(type, index)`` pair and nothing
    else; the brackets are surface. Restoration has always accepted all three
    forms -- it is permissive about surface and strict about identity -- so
    this only decides what goes *out*.

    It exists because of one payload shape. ``<PERSON_001>`` inside an HTML or
    XML document is an unknown element: a browser drops it, a parser may drop
    the text around it, and a model asked to edit the document is being shown a
    tag rather than a token. ``[PERSON_001]`` is a word there.

    ANGLE stays the default. It is the form every example and every test in
    this project uses, and a project that changes what it emits by default
    breaks the restoration of anything that stored the old form.
    """

    #: ``<PERSON_001>`` -- the default.
    ANGLE = "angle"
    #: ``[PERSON_001]`` -- for HTML, XML and anything else that reads ``<`` as
    #: the start of a tag.
    SQUARE = "square"
    #: ``{PERSON_001}`` -- for text that is about to be passed through a
    #: template engine that would eat square brackets.
    CURLY = "curly"

    @property
    def brackets(self) -> tuple[str, str]:
        return _BRACKETS[self]


_BRACKETS = {
    PlaceholderStyle.ANGLE: ("<", ">"),
    PlaceholderStyle.SQUARE: ("[", "]"),
    PlaceholderStyle.CURLY: ("{", "}"),
}


@dataclass(frozen=True, slots=True, order=True)
class Placeholder:
    """``<TYPE_NNN>`` -- a stable stand-in for one entity within a scope."""

    entity_type_name: str
    index: int

    def __post_init__(self) -> None:
        if self.index < 1:
            raise ValueError(f"placeholder index must be >= 1, got {self.index}")

    @property
    def token(self) -> str:
        """The canonical text form, e.g. ``<PERSON_001>``.

        This is the identity form: what a mapping is keyed by, what a trace
        prints, what a test asserts on. :meth:`rendered` is what goes into a
        protected text, and the two differ only when a caller asked for
        different brackets.
        """
        return f"<{self.entity_type_name}_{self.index:03d}>"

    def rendered(self, style: PlaceholderStyle = PlaceholderStyle.ANGLE) -> str:
        """The text form to substitute, in ``style``."""
        opening, closing = style.brackets
        return f"{opening}{self.entity_type_name}_{self.index:03d}{closing}"

    @classmethod
    def parse(cls, token: str) -> Placeholder | None:
        """Parse a canonical token. Returns ``None`` if it is not one."""
        match = STRICT_PLACEHOLDER_RE.fullmatch(token)
        if match is None:
            return None
        return cls(match.group(1), int(match.group(2)))

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.token
