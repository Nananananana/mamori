"""The operator's last word.

Corrections are the only thing in mamori that can *reduce* what is protected,
which makes this the file where the safety rules matter most. Everything else
in the library could only ever add; `NEVER` breaks that deliberately, and the
tests here are what keep the exception narrow.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mamori import MamoriConfig, PrivacySession
from mamori.domain.corrections import (
    PROTECTED_CATEGORIES,
    Correction,
    CorrectionLog,
    Verdict,
)
from mamori.errors import ConfigurationError, PolicyViolationError
from mamori.infrastructure.storage.corrections import (
    append_correction,
    dump_corrections,
    load_corrections,
)
from mamori.interfaces.cli.main import main
from mamori.report import build_report

from .credentials import FAKE_AWS_KEY

NEVER_MONDAY = Correction("Monday", Verdict.NEVER, note="a weekday, not a name")
ALWAYS_ACME = Correction("Acme", Verdict.ALWAYS, entity_type="COMPANY_NAME")


class TestTheLogIsAppendOnly:
    """Undo is another append. Nothing is deleted, so the history survives."""

    def test_the_latest_word_about_a_value_wins(self) -> None:
        log = CorrectionLog.of([NEVER_MONDAY, Correction("Monday", Verdict.ALWAYS, "PERSON")])
        assert [c.value for c in log.added()] == ["Monday"]
        assert log.excluded() == ()

    def test_undoing_is_another_entry_not_a_deletion(self) -> None:
        log = CorrectionLog.of(
            [NEVER_MONDAY, Correction("Monday", Verdict.ALWAYS, "PERSON"), NEVER_MONDAY]
        )
        assert len(log) == 3
        assert [c.value for c in log.excluded()] == ["Monday"]

    def test_appending_returns_a_new_log(self) -> None:
        first = CorrectionLog()
        second = first.appended(NEVER_MONDAY)
        assert len(first) == 0
        assert len(second) == 1

    def test_an_empty_log_is_falsey(self) -> None:
        assert not CorrectionLog()
        assert CorrectionLog.of([NEVER_MONDAY])


class TestWhatMakesAValidCorrection:
    def test_an_always_correction_must_name_a_type(self) -> None:
        with pytest.raises(ValueError, match="which type"):
            Correction("Acme", Verdict.ALWAYS)

    def test_an_always_correction_must_name_a_type_that_exists(self) -> None:
        with pytest.raises(ValueError, match="unknown entity type"):
            Correction("Acme", Verdict.ALWAYS, entity_type="VIBES")

    def test_a_never_correction_needs_no_type(self) -> None:
        assert Correction("Monday", Verdict.NEVER).entity_type == ""

    def test_a_one_character_value_is_refused(self) -> None:
        """It would match most of a CJK document."""
        with pytest.raises(ValueError, match="too short"):
            Correction("x", Verdict.NEVER)

    def test_an_empty_value_is_refused(self) -> None:
        with pytest.raises(ValueError):
            Correction("", Verdict.NEVER)


class TestACredentialCannotBeCorrectedAway:
    """The one rule that is not the operator's to overrule.

    Enforced in three places because one is not enough: the domain refuses an
    exclusion naming a credential type, `excludes` refuses to apply one at read
    time whatever a hand-edited file says, and `mamori correct` checks the value
    before writing -- because appending first would leave the credential in a
    file, which is the outcome this library exists to avoid.
    """

    def test_an_exclusion_naming_a_credential_type_is_refused(self) -> None:
        with pytest.raises(ValueError, match="credential"):
            CorrectionLog().appended(
                Correction("hunter2spring", Verdict.NEVER, entity_type="PASSWORD")
            )

    def test_a_hand_written_log_cannot_allow_list_a_credential(self) -> None:
        """The check that holds when the others were bypassed."""
        log = CorrectionLog(entries=(Correction(FAKE_AWS_KEY, Verdict.NEVER),))
        with PrivacySession(corrections=log) as session, pytest.raises(PolicyViolationError):
            session.protect(f"the key is {FAKE_AWS_KEY}")

    def test_the_cli_refuses_before_writing_anything(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log = tmp_path / "corrections.json"
        assert main(["correct", FAKE_AWS_KEY, "--never", "--log", str(log)]) == 1
        assert not log.exists(), "the credential must not reach the disk"
        assert "credential" in capsys.readouterr().err

    def test_the_refusal_says_what_to_do_instead(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["correct", FAKE_AWS_KEY, "--never", "--log", str(tmp_path / "c.json")])
        assert "Rotate it" in capsys.readouterr().err

    def test_an_ordinary_value_is_still_allowed(self, tmp_path: Path) -> None:
        log = tmp_path / "corrections.json"
        assert main(["correct", "Monday", "--never", "--log", str(log)]) == 0
        assert log.exists()

    def test_the_protected_categories_are_what_we_think(self) -> None:
        from mamori.domain.entity_types import Category

        assert Category.SECRET in PROTECTED_CATEGORIES


class TestCorrectionsChangeWhatIsProtected:
    @staticmethod
    def _session(*corrections: Correction) -> PrivacySession:
        return PrivacySession(corrections=CorrectionLog.of(corrections))

    def test_a_never_correction_stops_a_false_positive(self) -> None:
        """The English pack really does read a weekday as a name here.

        A salutation is a strong anchor, and 'Dear <word>' is the shape it
        looks for. It is right far more often than it is wrong, which is
        exactly why the operator needs a way to say so when it is wrong.
        """
        text = "Dear Monday, the report is attached."
        with PrivacySession() as plain:
            assert "Monday" not in plain.protect(text).protected_text, (
                "the fixture must actually be a false positive, or this proves nothing"
            )
        with self._session(NEVER_MONDAY) as corrected:
            assert "Monday" in corrected.protect(text).protected_text

    def test_it_only_affects_the_value_named(self) -> None:
        with self._session(NEVER_MONDAY) as session:
            protected = session.protect("Monday met 田中太郎.").protected_text
        assert "Monday" in protected
        assert "田中太郎" not in protected

    def test_an_always_correction_finds_what_no_rule_can(self) -> None:
        """`Acme` is a trading name with no legal suffix: a documented gap."""
        config = MamoriConfig(corrections=[ALWAYS_ACME.as_mapping()])
        with config.session() as session:
            protected = session.protect("The contract is with Acme until March.").protected_text
        assert "Acme" not in protected
        assert "COMPANY_NAME" in protected

    def test_an_always_correction_covers_every_occurrence(self) -> None:
        config = MamoriConfig(corrections=[ALWAYS_ACME.as_mapping()])
        with config.session() as session:
            protected = session.protect("Acme signed. Acme paid. Acme left.").protected_text
        assert "Acme" not in protected

    def test_the_value_still_restores(self) -> None:
        config = MamoriConfig(corrections=[ALWAYS_ACME.as_mapping()])
        text = "The contract is with Acme."
        with config.session() as session:
            protected = session.protect(text).protected_text
            assert session.restore(protected).text == text

    def test_a_correction_does_not_relabel_what_a_rule_already_found(self) -> None:
        """Corrections add evidence; they do not argue with a rule that fired."""
        config = MamoriConfig(
            corrections=[Correction("田中太郎", Verdict.ALWAYS, "PROJECT_NAME").as_mapping()]
        )
        with config.session() as session:
            result = session.protect("田中太郎さんへ")
        assert [e.entity_type for e in result.entities] == ["PERSON"]

    def test_no_corrections_means_no_change_at_all(self) -> None:
        text = "Dear Monday, the contract is with Acme."
        with PrivacySession() as plain, MamoriConfig().session() as configured:
            assert plain.protect(text).protected_text == configured.protect(text).protected_text


class TestTheLogOnDisk:
    def test_a_missing_file_is_an_empty_log(self, tmp_path: Path) -> None:
        """The common case: a configuration naming a log not yet written to."""
        assert load_corrections(tmp_path / "nothing.json") == CorrectionLog()

    def test_it_survives_a_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        dump_corrections(CorrectionLog.of([NEVER_MONDAY, ALWAYS_ACME]), path)
        loaded = load_corrections(path)
        assert [c.value for c in loaded] == ["Monday", "Acme"]
        assert loaded.verdict_for("Monday") is not None

    def test_appending_keeps_what_was_there(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        append_correction(path, NEVER_MONDAY)
        log = append_correction(path, ALWAYS_ACME)
        assert len(log) == 2
        assert len(load_corrections(path)) == 2

    def test_the_file_says_what_it_is(self, tmp_path: Path) -> None:
        """Somebody will find this in a repository and need to know."""
        path = tmp_path / "c.json"
        dump_corrections(CorrectionLog.of([ALWAYS_ACME]), path)
        assert "sensitive" in json.loads(path.read_text(encoding="utf-8"))["_note"]

    def test_a_malformed_entry_is_refused_not_skipped(self, tmp_path: Path) -> None:
        """An operator whose ruling was ignored would not find out."""
        path = tmp_path / "c.json"
        path.write_text(
            json.dumps({"corrections": [{"value": "x", "verdict": "maybe"}]}), encoding="utf-8"
        )
        with pytest.raises(ConfigurationError, match="never"):
            load_corrections(path)

    def test_unreadable_json_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ConfigurationError):
            load_corrections(path)


class TestConfiguration:
    def test_a_path_is_accepted(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        dump_corrections(CorrectionLog.of([NEVER_MONDAY]), path)
        config = MamoriConfig.from_mapping({"corrections": str(path)})
        assert len(config.correction_log()) == 1

    def test_entries_are_accepted_inline(self) -> None:
        config = MamoriConfig.from_mapping({"corrections": [NEVER_MONDAY.as_mapping()]})
        assert len(config.correction_log()) == 1

    def test_nonsense_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="corrections"):
            MamoriConfig.from_mapping({"corrections": 42})

    def test_the_default_is_no_corrections(self) -> None:
        assert MamoriConfig().correction_log() == CorrectionLog()


class TestItIsVisible:
    """An exclusion reduces protection, so it may not be quiet."""

    def test_the_privacy_report_names_what_was_excluded(self) -> None:
        config = MamoriConfig(corrections=[NEVER_MONDAY.as_mapping()])
        report = build_report(config)
        assert report.detection["corrections"]["excluded"] == ["Monday"]

    def test_an_exclusion_is_a_warning(self) -> None:
        config = MamoriConfig(corrections=[NEVER_MONDAY.as_mapping()])
        assert any("no longer protected" in w for w in build_report(config).warnings)

    def test_an_addition_is_not_a_warning(self) -> None:
        """Adding protection needs no warning. Removing it does."""
        config = MamoriConfig(corrections=[ALWAYS_ACME.as_mapping()])
        assert build_report(config).warnings == ()

    def test_the_command_lists_both_sides(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "c.json"
        dump_corrections(CorrectionLog.of([NEVER_MONDAY, ALWAYS_ACME]), path)
        settings = tmp_path / "mamori.json"
        settings.write_text(json.dumps({"corrections": str(path)}), encoding="utf-8")
        assert main(["corrections", "--config", str(settings)]) == 0
        out = capsys.readouterr().out
        assert "Monday" in out
        assert "Acme" in out
        assert "reduces coverage" in out

    def test_an_empty_log_explains_how_to_use_it(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["corrections"]) == 0
        assert "mamori correct" in capsys.readouterr().out

    def test_correcting_without_a_log_says_so(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["correct", "Monday", "--never"]) == 1
        assert "--log" in capsys.readouterr().err
