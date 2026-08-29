"""Saying why something was replaced, and why something else was not.

The second question is the one that matters. A miss is the failure this
library exists to prevent, and "it found nothing" is not an explanation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

from mamori import MamoriConfig
from mamori.application.trace import Outcome
from mamori.domain.corrections import Correction, Verdict
from mamori.domain.resolution import resolve_overlaps, resolve_overlaps_traced
from mamori.interfaces.cli.explain import audit_rules
from mamori.interfaces.cli.main import main

MIXED = "Dear Monday, the contract is with Globex Corporation. Call 4155550198."


class TestTheTraceRecordsWhatHappened:
    def test_it_is_absent_unless_asked_for(self) -> None:
        """It costs a list of every candidate, and nothing normally reads it."""
        with MamoriConfig().session() as session:
            assert session.protect(MIXED).trace is None

    def test_every_kept_entity_appears(self) -> None:
        with MamoriConfig().session(trace=True) as session:
            result = session.protect(MIXED)
        assert result.trace is not None
        assert len(result.trace.kept) == result.entity_count

    def test_a_displaced_detection_says_what_beat_it(self) -> None:
        """The half that used to be dropped without a word."""
        with MamoriConfig().session(trace=True) as session:
            trace = session.protect(MIXED).trace
        assert trace is not None
        displaced = trace.with_outcome(Outcome.DISPLACED)
        assert displaced, "this fixture has an overlap"
        assert "lost to" in displaced[0].detail

    def test_a_correction_is_recorded_as_such(self) -> None:
        config = MamoriConfig(corrections=[Correction("Monday", Verdict.NEVER).as_mapping()])
        with config.session(trace=True) as session:
            trace = session.protect(MIXED).trace
        assert trace is not None
        corrected = trace.with_outcome(Outcome.CORRECTED_AWAY)
        assert corrected and corrected[0].entity_type == "PERSON"

    def test_a_low_confidence_drop_is_recorded_as_such(self) -> None:
        config = MamoriConfig(min_confidence=0.95)
        with config.session(trace=True) as session:
            trace = session.protect(MIXED).trace
        assert trace is not None
        assert trace.with_outcome(Outcome.BELOW_CONFIDENCE)

    def test_it_never_contains_a_value(self) -> None:
        """A trace is what somebody pastes into a bug report."""
        secret = "tanaka@example.com"
        with MamoriConfig().session(trace=True) as session:
            trace = session.protect(f"連絡先は{secret}です").trace
        assert trace is not None
        assert secret not in json.dumps(trace.as_mapping(), ensure_ascii=False)

    def test_it_names_which_rules_contributed(self) -> None:
        with MamoriConfig().session(trace=True) as session:
            trace = session.protect(MIXED).trace
        assert trace is not None
        assert set(trace.rules_that_fired()) & {"en", "universal"}


class TestTracedResolutionMatchesTheRealOne:
    """It is the same loop. If it drifts, the explanation stops being true."""

    TEXTS: ClassVar[list[str]] = [
        MIXED,
        "田中太郎さんへ tanaka@example.com から",
        "Where Umbrella Ltd discloses data to Globex Corporation",
        "",
    ]

    @pytest.mark.parametrize("text", TEXTS)
    def test_it_keeps_exactly_what_the_plain_one_keeps(self, text: str) -> None:
        detector = next(iter(MamoriConfig().detectors()))
        found = list(detector.detect(text)) if text else []
        plain = resolve_overlaps(found)
        traced, _ = resolve_overlaps_traced(found)
        assert [(e.entity_type.name, e.span) for e in plain] == [
            (e.entity_type.name, e.span) for e in traced
        ]

    def test_the_losers_and_the_winners_account_for_everything(self) -> None:
        detector = next(iter(MamoriConfig().detectors()))
        found = list(detector.detect(MIXED))
        kept, displaced = resolve_overlaps_traced(found)
        assert len(kept) + len(displaced) == len(found)

    def test_a_displacement_explains_itself(self) -> None:
        detector = next(iter(MamoriConfig().detectors()))
        _, displaced = resolve_overlaps_traced(list(detector.detect(MIXED)))
        assert displaced
        assert displaced[0].reason in {
            "wider span",
            "higher severity",
            "higher confidence",
            "earlier in the text",
            "tie broken by detector name",
        }


class TestTheCommand:
    def test_it_explains_a_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["trace", MIXED]) == 0
        out = capsys.readouterr().out
        assert "What was considered" in out
        assert "Why nothing else" in out

    def test_it_says_what_the_other_stance_would_have_found(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The question that was not answerable before."""
        assert main(["trace", "--stance", "balanced", "I spoke to Jane Doe."]) == 0
        out = capsys.readouterr().out
        assert "recall_first stance would additionally have found" in out
        assert "PERSON" in out

    def test_it_shows_a_shape_not_a_value(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["trace", "--stance", "balanced", "I spoke to Jane Doe."]) == 0
        out = capsys.readouterr().out
        assert "Jane Doe" not in out
        assert "shape" in out

    def test_it_points_somewhere_when_neither_stance_helps(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["trace", "The contract is with Acme."]) == 0
        out = capsys.readouterr().out
        assert "mamori correct" in out

    def test_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["trace", "--json", MIXED]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["trace"]["kept"] >= 1
        assert "other_stance" in payload

    def test_it_reads_a_file(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = tmp_path / "draft.txt"
        path.write_text(MIXED, encoding="utf-8")
        assert main(["trace", "-f", str(path)]) == 0
        assert "What was considered" in capsys.readouterr().out


class TestAudit:
    def test_it_counts_every_rule(self) -> None:
        usage = audit_rules(["Dear Jane Doe, call 415-555-0198."])
        assert len(usage) > 50
        assert any(u.matches for u in usage)

    def test_the_universal_rules_are_included(self) -> None:
        """They are the ones that matter most, and belong to no pack."""
        usage = audit_rules(["reach me at jane.doe@example.com"])
        universal = [u for u in usage if u.identifier.startswith("universal.")]
        assert universal
        assert any(u.matches and u.entity_type == "EMAIL" for u in universal)

    def test_a_rule_that_does_not_match_is_reported_dead(self) -> None:
        usage = audit_rules(["nothing sensitive at all here"])
        assert all(u.dead for u in usage)

    def test_rules_have_stable_identifiers(self) -> None:
        first = [u.identifier for u in audit_rules(["x"])]
        second = [u.identifier for u in audit_rules(["x"])]
        assert first == second
        assert len(set(first)) == len(first), "identifiers must be unique"

    def test_it_reports_dead_rules_over_the_corpus(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["audit", "--dead"]) == 0
        out = capsys.readouterr().out
        assert "Never fired" in out

    def test_the_only_dead_rules_are_the_credential_ones(self) -> None:
        """Which cannot have samples: a literal key in a shipped file trips
        every clone's secret scanner. If anything else appears here, either a
        rule is dead or the datasets have a hole."""
        from mamori.evaluation import bundled_datasets

        texts = [sample.text for dataset in bundled_datasets() for sample in dataset]
        allowed = {"API_KEY", "ACCESS_TOKEN", "PRIVATE_KEY"}
        dead = {u.entity_type for u in audit_rules(texts) if u.dead}
        assert dead <= allowed, f"unexplained dead rules for {sorted(dead - allowed)}"

    def test_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["audit", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["rules"] > 50
        assert "usage" in payload

    def test_it_audits_a_file(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = tmp_path / "mine.txt"
        path.write_text("Dear Jane Doe, call 415-555-0198.", encoding="utf-8")
        assert main(["audit", "-f", str(path)]) == 0
        assert "1 text(s)" in capsys.readouterr().out
