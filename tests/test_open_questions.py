"""`docs/open-questions.md` keeps the rule it states about itself.

The file's own opening says: *every entry names what would settle it*, because
a concern with no settling condition is a worry and a file of worries stops
being read. Nothing enforced that, and nothing checked the file was even
well-formed.

Both mattered on the same day. Removing an entry that had been answered cut
from its heading to the next `---`, and the entry contained a markdown table
whose separator row is also `---`, so the deletion stopped early and left
twenty-three orphaned lines: a table with no header, a paragraph with no
heading, and a settling condition for a question that was no longer there.

It survived a commit. The link checker passed, the test suite passed, and the
document read as though a section had simply lost its title.
"""

from __future__ import annotations

import pathlib
import re

DOC = pathlib.Path(__file__).resolve().parent.parent / "docs" / "open-questions.md"
SEPARATOR = "\n---\n"


def sections() -> list[str]:
    """Everything after the preamble, split on the horizontal rules."""
    return [block.strip() for block in DOC.read_text(encoding="utf-8").split(SEPARATOR)[1:]]


def test_the_file_is_not_empty_of_entries() -> None:
    """A regex that matched nothing would make every check below vacuous."""
    assert sections(), "no sections parsed -- has the file changed shape?"


def test_every_section_starts_with_a_heading() -> None:
    """The shape a botched deletion leaves: prose and a table with no title.

    Reads as a section that lost its heading rather than as damage, which is
    why it went unnoticed through a commit.
    """
    orphans = [block.splitlines()[0][:60] for block in sections() if not block.startswith("## ")]
    assert not orphans, f"text after a rule that is not a section: {orphans}"


def test_every_entry_says_what_would_settle_it() -> None:
    """The rule the file states in its own opening paragraph.

    An entry that cannot say what would close it belongs in a commit message
    or nowhere -- which is the difference between this file and a graveyard.
    """
    missing = [
        block.splitlines()[0].removeprefix("## ")
        for block in sections()
        if "**Settled by**" not in block
    ]
    assert not missing, f"entries with no settling condition: {missing}"


def test_the_headings_are_questions_or_statements_of_a_gap() -> None:
    """Not a style rule. A heading that names a solution has already decided,
    and belongs in an ADR instead."""
    for block in sections():
        heading = block.splitlines()[0].removeprefix("## ")
        assert not re.match(r"^(Add|Implement|Fix|Write) ", heading), (
            f"'{heading}' reads as a task, not an open question. "
            "A decision that has been made belongs in docs/adr/."
        )
