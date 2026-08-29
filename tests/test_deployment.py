"""Deploying it: what a team needs before this is allowed near production.

Three things, and none of them is a detection rule.

**A placeholder that is not mistaken for a tag.** ``<PERSON_001>`` inside an
HTML document is an unknown element. A browser drops it, a parser may drop the
text around it, and a model asked to edit the document is being shown a tag
rather than a token.

**A way to be stopped rather than guessed at.** The default resolves doubt in
favour of sending: a detection below the confidence threshold is discarded and
the text goes out. Some deployments would rather send nothing.

**A way to find out before it is committed.** The values that reach a model
through a repository never pass through this library at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mamori import MamoriConfig, PrivacySession
from mamori.domain.placeholder import Placeholder, PlaceholderStyle
from mamori.errors import ConfigurationError, PolicyViolationError
from mamori.interfaces.cli import main
from mamori.interfaces.cli.linting import lint_paths, scan_file

HTML = "<p>Contact <b>Jane Doe</b> at jane.doe@example.com.</p>"


class TestAPlaceholderThatIsNotATag:
    @pytest.mark.parametrize(
        ("style", "expected"),
        [("angle", "<PERSON_001>"), ("square", "[PERSON_001]"), ("curly", "{PERSON_001}")],
    )
    def test_the_brackets_are_a_setting(self, style: str, expected: str) -> None:
        with MamoriConfig(placeholder_style=style).session() as session:
            assert expected in session.protect(HTML).protected_text

    @pytest.mark.parametrize("style", ["angle", "square", "curly"])
    def test_every_style_round_trips(self, style: str) -> None:
        with MamoriConfig(placeholder_style=style).session() as session:
            protected = session.protect(HTML)
            assert "Jane Doe" not in protected.protected_text
            assert session.restore(protected.protected_text).text == HTML

    def test_a_document_protected_in_one_style_restores_from_another(self) -> None:
        """Identity is the (type, index) pair. The brackets are surface, and
        restoration has always been permissive about surface."""
        with MamoriConfig(placeholder_style="square").session() as session:
            protected = session.protect(HTML).protected_text
            as_angle = protected.replace("[", "<").replace("]", ">")
            assert session.restore(as_angle).text == HTML

    def test_the_canonical_token_does_not_change(self) -> None:
        """It is what a mapping is keyed by and what a trace prints."""
        placeholder = Placeholder("PERSON", 1)
        assert placeholder.token == "<PERSON_001>"
        assert placeholder.rendered(PlaceholderStyle.SQUARE) == "[PERSON_001]"

    def test_the_default_is_unchanged(self) -> None:
        with PrivacySession() as session:
            assert "<PERSON_001>" in session.protect(HTML).protected_text

    def test_a_typo_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="placeholder_style"):
            MamoriConfig(placeholder_style="round").session()

    def test_it_survives_a_round_trip_through_html(self) -> None:
        """The point of the setting: the token is a word, not an element."""
        with MamoriConfig(placeholder_style="square").session() as session:
            protected = session.protect(HTML).protected_text
        assert protected.count("<") == HTML.count("<"), "no new tags were introduced"


class TestBeingStoppedRatherThanGuessedAt:
    TEXT = "Please ask Riverton about the Foundry Row site."

    def test_the_default_discards_and_sends(self) -> None:
        with MamoriConfig(min_confidence=0.85).session() as session:
            assert session.protect(self.TEXT).protected_text == self.TEXT

    def test_refusing_stops_instead(self) -> None:
        config = MamoriConfig(min_confidence=0.85, uncertain="refuse")
        with config.session() as session:
            with pytest.raises(PolicyViolationError) as raised:
                session.protect(self.TEXT)
        assert "below the confidence threshold" in str(raised.value)

    def test_the_refusal_names_types_and_never_values(self) -> None:
        config = MamoriConfig(min_confidence=0.85, uncertain="refuse")
        with config.session() as session:
            with pytest.raises(PolicyViolationError) as raised:
                session.protect(self.TEXT)
        message = str(raised.value)
        assert "PERSON" in message
        assert "Riverton" not in message
        assert "Foundry Row" not in message

    def test_it_does_nothing_at_the_default_threshold(self) -> None:
        """Nothing is below zero, so this is one dial and not two."""
        with MamoriConfig(uncertain="refuse").session() as session:
            assert "<PERSON_001>" in session.protect(self.TEXT).protected_text

    def test_a_confident_document_still_goes_out(self) -> None:
        config = MamoriConfig(min_confidence=0.85, uncertain="refuse")
        with config.session() as session:
            protected = session.protect("Email tanaka@example.com about it.")
        assert "<EMAIL_001>" in protected.protected_text

    def test_nothing_is_produced_when_it_refuses(self) -> None:
        """Checked before resolution, so there is no partial text to leak."""
        config = MamoriConfig(min_confidence=0.85, uncertain="refuse")
        with config.session() as session:
            with pytest.raises(PolicyViolationError):
                session.protect(self.TEXT)
            # The store holds nothing: no placeholder was allocated.
            assert session.restore("<PERSON_001>").text == "<PERSON_001>"

    def test_a_typo_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="uncertain"):
            MamoriConfig(uncertain="maybe").session()


class TestANameSplitAcrossKeys:
    """Each half is a word. There is no prose to reach it with, because the
    structure is carrying the meaning a salutation would carry in a sentence."""

    @pytest.mark.parametrize(
        "payload",
        [
            '{"first_name": "Jane", "last_name": "Doe"}',
            '{"given_name": "太郎", "family_name": "田中"}',
            '{"surname": "Doe", "forename": "Jane"}',
        ],
    )
    def test_both_halves_are_found(self, payload: str) -> None:
        with PrivacySession() as session:
            protected = session.protect(payload).protected_text
        assert protected.count("<PERSON_") == 2

    def test_they_stay_two_values(self) -> None:
        """Reassembling them would put a full name where the application
        expects a given name."""
        payload = '{"first_name": "Jane", "last_name": "Doe"}'
        with PrivacySession() as session:
            protected = session.protect(payload)
            assert session.restore(protected.protected_text).text == payload


class TestTheLinter:
    def fixture(self, tmp_path: Path) -> Path:
        (tmp_path / "prompt.md").write_text(
            "Dear Jane Doe,\n\nCall 415-555-0198 about the renewal.\n", encoding="utf-8"
        )
        (tmp_path / "clean.md").write_text("Nothing sensitive here.\n", encoding="utf-8")
        (tmp_path / "keys.env").write_text(
            'TOKEN = "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bD1fH3j"\n', encoding="utf-8"
        )
        return tmp_path

    def test_it_finds_a_value_and_says_which_line(self, tmp_path: Path) -> None:
        findings, _ = lint_paths(MamoriConfig(), [self.fixture(tmp_path)])
        phones = [f for f in findings if f.entity_type == "PHONE"]
        assert len(phones) == 1
        assert phones[0].line == 3

    def test_it_never_prints_the_value(self, tmp_path: Path) -> None:
        """These land in CI logs, which are archived and widely readable."""
        findings, _ = lint_paths(MamoriConfig(), [self.fixture(tmp_path)])
        rendered = "\n".join(f.describe() for f in findings)
        assert "415-555-0198" not in rendered
        assert "Jane Doe" not in rendered
        assert "4***********" in rendered

    def test_a_clean_file_yields_nothing(self, tmp_path: Path) -> None:
        findings, _ = lint_paths(MamoriConfig(), [self.fixture(tmp_path) / "clean.md"])
        assert findings == []

    def test_binary_is_not_scanned(self, tmp_path: Path) -> None:
        (tmp_path / "blob.dat").write_bytes(b"\x00\x01Dear Jane Doe, 415-555-0198")
        findings = scan_file(tmp_path / "blob.dat", list(MamoriConfig().detectors()))
        assert findings == []

    def test_a_known_binary_suffix_is_skipped_before_reading(self, tmp_path: Path) -> None:
        (tmp_path / "photo.png").write_text("Dear Jane Doe,", encoding="utf-8")
        findings, skipped = lint_paths(MamoriConfig(), [tmp_path])
        assert findings == []
        assert any(path.name == "photo.png" for path, _ in skipped)

    def test_a_large_file_is_skipped_and_says_so(self, tmp_path: Path) -> None:
        (tmp_path / "big.txt").write_text("x" * 500, encoding="utf-8")
        _, skipped = lint_paths(MamoriConfig(), [tmp_path], max_bytes=100)
        assert any("over the" in reason for _, reason in skipped)

    def test_exclusions(self, tmp_path: Path) -> None:
        findings, skipped = lint_paths(MamoriConfig(), [self.fixture(tmp_path)], exclude=["*.md"])
        assert all(f.path.suffix != ".md" for f in findings)
        assert skipped

    def test_one_finding_per_value(self, tmp_path: Path) -> None:
        """Several rules matching one address is normal; reporting it three
        times makes a clean file look like an incident."""
        (tmp_path / "a.txt").write_text("mail tanaka@example.com\n", encoding="utf-8")
        findings = scan_file(tmp_path / "a.txt", list(MamoriConfig().detectors()))
        assert len({(f.line, f.entity_type, f.preview) for f in findings}) == len(findings)

    def test_type_filtering(self, tmp_path: Path) -> None:
        findings, _ = lint_paths(MamoriConfig(), [self.fixture(tmp_path)], types=["phone"])
        assert {f.entity_type for f in findings} == {"PHONE"}


class TestTheLinterAsACommand:
    def fixture(self, tmp_path: Path) -> Path:
        (tmp_path / "prompt.md").write_text("Dear Jane Doe,\n", encoding="utf-8")
        return tmp_path

    def test_pii_alone_does_not_fail_the_build(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A name in a fixture is a decision somebody should make on purpose,
        and a linter that fails on it teaches people to skip the hook."""
        assert main(["lint", str(self.fixture(tmp_path))]) == 0
        assert "PERSON" in capsys.readouterr().out

    def test_a_credential_does(self, tmp_path: Path) -> None:
        (tmp_path / "config.env").write_text("password: hunter2spring\n", encoding="utf-8")
        assert main(["lint", str(tmp_path)]) == 2

    def test_fail_on_any(self, tmp_path: Path) -> None:
        assert main(["lint", str(self.fixture(tmp_path)), "--fail-on", "any"]) == 2

    def test_fail_on_never(self, tmp_path: Path) -> None:
        (tmp_path / "config.env").write_text("password: hunter2spring\n", encoding="utf-8")
        assert main(["lint", str(tmp_path), "--fail-on", "never"]) == 0

    def test_json(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        main(["lint", str(self.fixture(tmp_path)), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["findings"][0]["type"] == "PERSON"
        assert "Jane" not in json.dumps(payload)

    def test_a_missing_path_is_an_error_not_a_pass(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A linter that reports success for a path it could not find is worse
        than one that is not installed."""
        assert main(["lint", str(tmp_path / "nowhere")]) == 1
        assert "no such path" in capsys.readouterr().err

    def test_a_clean_tree_says_so(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (tmp_path / "readme.md").write_text("Nothing here.\n", encoding="utf-8")
        assert main(["lint", str(tmp_path)]) == 0
        assert "nothing found" in capsys.readouterr().out


class TestTheReportDescribesTheseSettings:
    """`mamori privacy` says what a configuration does with your data.

    A setting it does not mention is a setting somebody has to read the source
    to discover, which is the opposite of the point. Four releases added
    settings before this test existed, and two of them changed behaviour.
    """

    def report(self, **settings: object) -> object:
        from mamori.report import build_report

        return build_report(MamoriConfig(**settings))  # type: ignore[arg-type]

    def test_it_names_what_happens_below_the_threshold(self) -> None:
        report = self.report(min_confidence=0.8, uncertain="refuse")
        assert report.detection["uncertain"] == "refuse"  # type: ignore[attr-defined]
        assert "stops the text" in report.detection["uncertain_note"]  # type: ignore[attr-defined]

    def test_a_refusal_that_can_never_fire_is_a_warning(self) -> None:
        """`uncertain="refuse"` at the default threshold does nothing at all,
        and a privacy setting that silently does nothing is the worst kind."""
        report = self.report(uncertain="refuse")
        assert any("does nothing at min_confidence" in w for w in report.warnings)  # type: ignore[attr-defined]

    def test_no_warning_when_it_can_fire(self) -> None:
        report = self.report(uncertain="refuse", min_confidence=0.8)
        assert not any("does nothing" in w for w in report.warnings)  # type: ignore[attr-defined]

    def test_it_names_the_placeholder_style(self) -> None:
        report = self.report(placeholder_style="square")
        assert report.detection["placeholder_style"] == "square"  # type: ignore[attr-defined]

    def test_the_command_prints_both(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["privacy"]) == 0
        out = capsys.readouterr().out
        assert "below that" in out
        assert "placeholders" in out
