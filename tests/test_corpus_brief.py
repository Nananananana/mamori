"""`docs/corpus-brief.md` names every type it would have to cover.

The brief is what somebody outside this project would be handed. Its coverage
floor is a list of entity types, and a list of entity types written by hand in
a document is a list that goes stale the first time one is added -- silently,
because a corpus is commissioned once and nobody re-reads the brief afterwards.
A type missing from it is a type the corpus would not have measured, and the
gap would surface as a confident figure rather than as an absence.

`TEXT` is the exception and is excluded deliberately: it is the catch-all a
custom rule lands in, so asking an outside writer for twenty instances of it
per language asks for nothing in particular.
"""

from __future__ import annotations

import re
from pathlib import Path

from mamori.domain.entity_types import BUILTIN_TYPES

BRIEF = Path(__file__).resolve().parent.parent / "docs" / "corpus-brief.md"

#: The catch-all. See the module docstring.
NOT_ASKED_FOR = frozenset({"TEXT"})


def named_in_the_brief() -> set[str]:
    """Every SCREAMING_CASE run in the file, which is how the lists are written."""
    return set(re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", BRIEF.read_text(encoding="utf-8")))


def test_the_brief_is_there_to_be_read() -> None:
    """A missing file would make every check below vacuously true."""
    assert BRIEF.is_file()
    assert len(BRIEF.read_text(encoding="utf-8")) > 2000


def test_every_type_the_policy_names_is_asked_for() -> None:
    missing = sorted((set(BUILTIN_TYPES) - NOT_ASKED_FOR) - named_in_the_brief())
    assert not missing, (
        f"{missing} would not be measured by a corpus commissioned from this "
        "brief. Add them to the coverage floor in docs/corpus-brief.md, or say "
        "there why they are excluded."
    )


def test_the_brief_does_not_ask_for_a_type_that_does_not_exist() -> None:
    """The other direction, which is how a renamed type reads.

    Filtered to names that look like entity types rather than prose acronyms:
    the file also says RFC, UTF, and the licence.
    """
    ignore = {"RFC", "UTF", "MIT", "TEXT"}
    asked = {n for n in named_in_the_brief() if "_" in n or n.isalpha()} - ignore
    invented = sorted(n for n in asked if n.isupper() and "_" in n)
    unknown = [n for n in invented if n not in BUILTIN_TYPES]
    assert not unknown, f"docs/corpus-brief.md asks for types that do not exist: {unknown}"
