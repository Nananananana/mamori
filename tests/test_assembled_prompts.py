"""Prompts nobody typed.

A prompt increasingly arrives *assembled*: a retrieval layer selects passages
out of local notes, wraps each in a header naming the file it came from, states
what it left out, and renders the lot as named sections. Three kinds of thing
end up in one document and only the first is prose.

1. **Passages.** Ordinary text, full of names. This is what every other test
   file here is about.
2. **Headers.** ``[1a78a34e8a99] /home/p.doe/notes/customers.md (Meeting)[120:193]``
   -- a file path identifies a person as surely as a signature block does, and
   no rule looked at one before 0.17.
3. **Structure.** Item ids, content hashes, character offsets, budgets. These
   must survive untouched: a redacted hash is a package whose id no longer
   verifies, and the consumer cannot tell that from a package that was tampered
   with.

The tests below are grouped that way. The sibling project ``tsumugi`` is the
concrete producer this was measured against, and nothing here imports it: the
shapes are what matters and a dependency between the two would be worse than
the duplication.
"""

from __future__ import annotations

import pytest

from mamori import MamoriConfig, PrivacySession

from .helpers import types_in, values_of


class TestAHomeDirectoryNamesItsOwner:
    @pytest.mark.parametrize(
        ("path", "user"),
        [
            ("/home/p.doe/notes/x.md", "p.doe"),
            ("/Users/sato.hanako/notes/x.md", "sato.hanako"),
            ("C:/Users/t.mercer/memo/a.md", "t.mercer"),
            (r"C:\Users\t.mercer\memo\a.md", "t.mercer"),
            ("D:/users/yamada98/2026/x.md", "yamada98"),
            ("/export/home/liwei/docs/note.md", "liwei"),
        ],
    )
    def test_the_segment_after_the_root(self, path: str, user: str) -> None:
        assert user in values_of(path, "PERSON", "en")

    def test_only_that_segment(self) -> None:
        """The rest of the path is provenance and somebody may be checking it."""
        with PrivacySession() as session:
            protected = session.protect("[1a78a34e8a99] /home/p.doe/notes/customers.md")
        assert protected.protected_text.startswith("[1a78a34e8a99] /home/<PERSON_001>")
        assert protected.protected_text.endswith("/notes/customers.md")

    @pytest.mark.parametrize(
        "path",
        [
            "/home/runner/work/repo/build.log",
            "/home/ubuntu/agent/run.sh",
            "C:/Users/Public/Documents/x.md",
            "/Users/Shared/notes.md",
            "/home/root/.bashrc",
            "/home/www-data/site",
        ],
    )
    def test_a_system_account_is_not_a_person(self, path: str) -> None:
        """A closed set, which is what makes the list defensible.

        Nobody coins a new value for the Windows public profile, and a build
        agent that shows up in every CI log is not somebody's name.
        """
        assert "PERSON" not in types_in(path, "en")

    @pytest.mark.parametrize(
        "path", ["/srv/shared/notes/x.md", "//fileserver/team/2026/x.md", "/mnt/corpus/a.md"]
    )
    def test_shared_storage_names_nobody(self, path: str) -> None:
        assert "PERSON" not in types_in(path, "en")

    def test_it_survives_the_round_trip(self) -> None:
        text = "The note is at /home/p.doe/notes/customers.md, line 40."
        with PrivacySession() as session:
            protected = session.protect(text)
            assert "p.doe" not in protected.protected_text
            assert session.restore(protected.protected_text).text == text


class TestStructureIsNotAValue:
    """The negative set. Anything replaced here is a bug with a number on it."""

    @pytest.mark.parametrize(
        "structure",
        [
            "[1a78a34e8a99]",
            "[5b469054284c]",
            "[92485203fd8a]",
            "sha256:9f2b1c0e4d5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c",
            "(Meeting)[464:562]",
            "20 items, 398/400 tokens via heuristic/cjk-aware@1",
        ],
    )
    def test_it_is_left_alone(self, structure: str) -> None:
        with PrivacySession() as session:
            assert session.protect(structure).protected_text == structure

    def test_a_digit_run_inside_a_hash_is_part_of_the_hash(self) -> None:
        """`5b469054284c` contains nine digits. It is not a number anybody was
        issued, and redacting it breaks a checksum to protect nothing."""
        assert types_in("[5b469054284c] /srv/shared/x.md", "en") == set()

    def test_a_path_is_not_a_credential(self) -> None:
        """The wide secret rule's `mixed case and digits` requirement was
        written `(?=[^A-Z]*[A-Z])`, which any capital later in the document
        satisfies -- so every long path in a document qualified."""
        text = "[fb5c0de1a6b4] //fileserver/team/2026/meeting-log.md (Background)[0:88]\nA Note."
        assert "API_KEY" not in types_in(text, "en")

    def test_a_real_key_shaped_run_still_fires(self) -> None:
        """The guard above must not have turned the rule off.

        The wide tier, because that is where a run with no keyword in front of
        it is judged on shape alone.
        """
        from mamori.domain.stance import Stance

        found = types_in("aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bD1fH3j", "en", Stance.RECALL_FIRST)
        assert "API_KEY" in found


class TestACodenameIsANoun:
    """The project rules took the sentence after the name as well.

    Two costs, and the second is the worse one. The sentence disappears, and
    the same project in two sentences gets two different placeholders, so the
    model cannot tell they are the same and a quotation restores to a different
    string than the passage it came from.
    """

    @pytest.mark.parametrize(
        ("text", "name"),
        [
            ("プロジェクト鶴の残作業は?", "鶴"),
            ("プロジェクトあおぞらの進捗を確認した。", "あおぞら"),
            ("プロジェクトあおぞらは順調です", "あおぞら"),
            ("项目子午的进度：完成83%", "子午"),
            ("项目子午还剩什么?", "子午"),
        ],
    )
    def test_the_name_stops_where_the_grammar_starts(self, text: str, name: str) -> None:
        locale = "ja" if text.startswith("プロジェクト") else "zh"
        assert values_of(text, "PROJECT_NAME", locale) == {name}

    def test_the_same_project_gets_the_same_placeholder(self) -> None:
        with PrivacySession() as session:
            protected = session.protect(
                "プロジェクトあおぞらの進捗。\nプロジェクトあおぞらは順調です。"
            )
        assert protected.protected_text.count("<PROJECT_NAME_001>") == 2


class TestJapaneseNamesInHiragana:
    """さくら, ゆき, あおい are ordinary given names.

    Every rule wanted Han or katakana, so 西村さくら様 was invisible while
    西村花子様 was found. A corpus whose given names are all Han cannot show
    that, which is the argument for generating one that is not.
    """

    @pytest.mark.parametrize(
        "text", ["西村さくら様", "山田ゆきさん", "石川あおい様", "氏名: 山田さくら"]
    )
    def test_it_is_found(self, text: str) -> None:
        assert "PERSON" in types_in(text, "ja")

    def test_the_honorific_is_not_part_of_the_name(self) -> None:
        assert values_of("西村さくら様", "PERSON", "ja") == {"西村さくら"}

    def test_a_bare_surname_and_a_particle_are_not_a_name(self) -> None:
        """Which is why the hiragana tail needs an honorific in front of it."""
        with PrivacySession(locales=("ja",)) as session:
            protected = session.protect("会議はさんかいです")
        assert protected.protected_text == "会議はさんかいです"


class TestALabelDoesNotSitAgainstItsValue:
    """社員番号は入社時にA-44881を付与予定です. Same shape as the Chinese fix in 0.15."""

    def test_japanese(self) -> None:
        assert values_of("社員番号は入社時にA-44881を付与予定です。", "EMPLOYEE_ID", "ja") == {
            "A-44881"
        }

    def test_it_does_not_cross_a_clause(self) -> None:
        assert "EMPLOYEE_ID" not in types_in("社員番号は未定、電話は03-1234-5678です。", "ja")

    def test_english_born(self) -> None:
        assert values_of("Priya Raman, born 1988-10-14.", "DATE_OF_BIRTH", "en") == {"1988-10-14"}

    def test_born_somewhere_is_not_a_date(self) -> None:
        assert "DATE_OF_BIRTH" not in types_in("He was born in Ashford.", "en")


class TestWhatTheConsumerHasToBeTold:
    """`reversible` is not visible in the text: <PERSON_001> and [REDACTED]
    look equally replaced, and only one of them can be undone."""

    def test_anonymized_is_reversible(self) -> None:
        with PrivacySession() as session:
            result = session.protect("Dear Jane Doe, call 415-555-0198.")
        assert result.reversible is True
        assert result.masked_types == ()

    def test_masked_is_not(self) -> None:
        config = MamoriConfig.from_mapping({"rules": {"PHONE": "mask"}})
        with config.session() as session:
            result = session.protect("Dear Jane Doe, call 415-555-0198.")
        assert result.reversible is False
        assert result.masked_types == ("PHONE",)

    def test_it_names_types_and_not_values(self) -> None:
        config = MamoriConfig.from_mapping({"rules": {"PHONE": "mask"}})
        with config.session() as session:
            result = session.protect("Dear Jane Doe, call 415-555-0198.")
        assert "415" not in " ".join(result.masked_types)


class TestAQuotationSurvivesExactly:
    """The property the composition rests on.

    A retrieval layer verifies the model's answer by matching the quotation
    against the passage it sent. Restore before you verify, and the restored
    quotation has to equal the original **exactly** -- one character of drift
    is a false accusation of fabrication.
    """

    PACKAGE = """# SYSTEM
Answer the question using only the context provided below.
- Quote the exact text you rely on.

# TASK
What happened with the Northwind Ltd quote?

# CONTEXT

[fbd4c2a631fd] /home/p.doe/notes/meeting-log.md (Meeting)[464:562]
Met with Priya Raman from Northwind Ltd on Tuesday.
They asked for the quote to be reissued; Michael Chen is handling it.

# NOT INCLUDED
2 relevant-looking passages were considered and left out of this context."""

    QUOTE = "Met with Priya Raman from Northwind Ltd on Tuesday."

    def test_the_quotation_comes_back_character_for_character(self) -> None:
        with PrivacySession() as session:
            protected = session.protect(self.PACKAGE)
            # What the model was given, and therefore what it can quote.
            start = protected.protected_text.index("Met with")
            quoted = protected.protected_text[start : start + len(self.QUOTE) + 40].split("\n")[0]
            answer = f"The context says this:\n\n> {quoted}\n\nOn that basis, it needs reissuing."
            restored = session.restore(answer).text
        assert self.QUOTE in restored

    def test_the_model_never_saw_the_values_it_quoted(self) -> None:
        with PrivacySession() as session:
            protected = session.protect(self.PACKAGE)
        for value in ("Priya Raman", "Michael Chen", "p.doe"):
            assert value not in protected.protected_text
