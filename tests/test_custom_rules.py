"""Rules an organisation writes, and the one thing they must not be allowed to do.

Everything this library detected was something it shipped. A company whose
case references look like `CS/2026/0041` had to write a locale pack in Python,
rule on each value with `mamori correct`, or accept the miss.

The half of this worth testing is not that a pattern in a file finds a match.
It is that **a regular expression in a configuration file is a performance
decision somebody made without meaning to** -- 0.33 spent a release removing
two quadratics from this library's own rules, and holding that door open for
everybody else would have been a poor joke. Every pattern is timed against
adversarial input before it is accepted.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from mamori import MamoriConfig
from mamori.domain.entity_types import get_type
from mamori.domain.stance import Stance
from mamori.errors import ConfigurationError
from mamori.infrastructure.detectors.custom import compile_custom_rules, time_pattern

ACME = {"type": "EMPLOYEE_ID", "pattern": r"ACME-\d{6}", "confidence": 0.95}
CASE = {"type": "CASE_REFERENCE", "category": "PII", "pattern": r"CS/\d{4}/\d{4}"}
TEXT = "Case CS/2026/0041 belongs to ACME-004512."


class TestARuleInAFileIsARule:
    def test_it_finds_what_nothing_shipped_would(self) -> None:
        assert "EMPLOYEE_ID" not in MamoriConfig().session().inspect(TEXT)
        found = MamoriConfig(patterns=[ACME, CASE]).session().inspect(TEXT)
        assert set(found) >= {"EMPLOYEE_ID", "CASE_REFERENCE"}

    def test_the_value_is_replaced_and_comes_back(self) -> None:
        with MamoriConfig(patterns=[ACME, CASE]).session() as session:
            protected = session.protect(TEXT)
            assert "ACME-004512" not in protected.protected_text
            assert "CS/2026/0041" not in protected.protected_text
            assert session.restore(protected.protected_text).text == TEXT

    def test_a_new_type_becomes_a_placeholder_of_its_own(self) -> None:
        with MamoriConfig(patterns=[CASE]).session() as session:
            assert "<CASE_REFERENCE_001>" in session.protect(TEXT).protected_text

    def test_it_is_arbitrated_like_every_other_rule(self) -> None:
        """Beside the built-ins, not after them.

        A later pass would lose every overlap to a shipped rule, which is
        backwards for somebody who wrote one *because* the shipped rules were
        not enough. Here a custom rule at 0.95 takes a span the wide-tier
        `IDENTIFIER` rule would otherwise have claimed at 0.50.
        """
        found = MamoriConfig(patterns=[ACME]).session().inspect("ref ACME-004512 attached")
        assert "EMPLOYEE_ID" in found
        assert "IDENTIFIER" not in found

    def test_the_report_says_which_rule(self) -> None:
        """`mamori trace` and the audit both name the source, and "custom" is
        what an operator needs to see when a rule they wrote fires."""
        with MamoriConfig(patterns=[ACME]).session() as session:
            result = session.protect(TEXT)
        sources = {report.source for report in result.entities}
        assert "custom" in sources, sources


class TestAPatternThatWouldSlowEverythingDownIsRefused:
    """The reason this feature is safe to have at all."""

    #: The shape that broke this library's own email rules: an unbounded run
    #: of the characters a local part is made of, followed by something that
    #: is usually absent. `finditer` restarts at every position of a long run
    #: and reads to the end of it each time.
    QUADRATIC = r"[A-Za-z0-9._%+-]+@corp\.local"

    def test_it_is_refused_at_configuration_time(self) -> None:
        with pytest.raises(ConfigurationError) as raised:
            MamoriConfig(patterns=[{"type": "EMAIL", "pattern": self.QUADRATIC}])
        assert "four times the input" in str(raised.value)

    def test_the_message_names_the_shape_and_the_fix(self) -> None:
        """An operator who cannot see what to do next will disable the check
        rather than fix the pattern, and there is no way to disable it."""
        with pytest.raises(ConfigurationError) as raised:
            compile_custom_rules([{"type": "EMAIL", "pattern": self.QUADRATIC}])
        message = str(raised.value)
        assert "patterns[0]" in message
        assert "{1,64}" in message
        assert "(?<![A-Za-z0-9])" in message

    def test_the_bounded_version_of_the_same_rule_is_accepted(self) -> None:
        """The fix the message describes, checked to actually work.

        A guard that refused the bad pattern and also the good one would be a
        guard nobody could satisfy.
        """
        bounded = r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,64}@corp\.local"
        rules = compile_custom_rules([{"type": "EMAIL", "pattern": bounded}])
        assert len(rules) == 1
        session = MamoriConfig(patterns=[{"type": "EMAIL", "pattern": bounded}]).session()
        assert "EMAIL" in session.inspect("write to jane@corp.local today")

    @pytest.mark.parametrize(
        "pattern",
        [
            r"ACME-\d{6}",
            r"CS/\d{4}/\d{4}",
            r"(?i)case\s*ref[:#]?\s*([A-Z0-9-]{4,20})",
            r"[A-Z]{2,4}-[0-9]{3,8}",
            r"社員番号\s*[:：]?\s*\d{4,8}",
            r"\b(?:INT|EXT)-[0-9]{4}\b",
        ],
    )
    def test_an_ordinary_rule_passes(self, pattern: str) -> None:
        """The false-positive side. A check that refused reasonable patterns
        would make the feature unusable, which is worse than not having it."""
        assert time_pattern(re.compile(pattern)) is None, pattern


class TestItRefusesWhatItCannotRead:
    @pytest.mark.parametrize(
        ("entry", "expected"),
        [
            ({"pattern": "x"}, "'type' is required"),
            ({"type": "EMAIL"}, "'pattern' is required"),
            ({"type": "NOPE", "pattern": "x"}, "'category' is required"),
            ({"type": "EMAIL", "pattern": "([unclosed"}, "not a valid regular expression"),
            ({"type": "EMAIL", "pattern": "x", "tier": "huge"}, "unknown tier"),
            ({"type": "EMAIL", "pattern": "x", "group": 3}, "the pattern has 0"),
            ({"type": "NOPE", "category": "NOSUCH", "pattern": "x"}, "unknown category"),
            ({"type": "EMAIL", "pattern": "x", "colour": "red"}, "unknown key"),
            ({"type": "EMAIL", "pattern": "x", "confidence": "high"}, "must be a number"),
        ],
        ids=[
            "no type",
            "no pattern",
            "new type, no category",
            "not a regex",
            "unknown tier",
            "group out of range",
            "unknown category",
            "unknown key",
            "confidence is not a number",
        ],
    )
    def test_the_message_says_what_is_wrong(self, entry: dict[str, Any], expected: str) -> None:
        with pytest.raises(ConfigurationError, match=expected):
            compile_custom_rules([entry])

    def test_a_bad_rule_is_refused_when_the_file_is_read(self) -> None:
        """Not on the first document. A deployment with a broken rule should
        fail at startup, where somebody is watching."""
        with pytest.raises(ConfigurationError):
            MamoriConfig.from_mapping({"patterns": [{"type": "EMAIL", "pattern": "("}]})

    def test_patterns_must_be_a_list(self) -> None:
        with pytest.raises(ConfigurationError, match="list of rule mappings"):
            MamoriConfig.from_mapping({"patterns": "ACME-[0-9]{6}"})


class TestReadingAFileLeavesNothingBehind:
    """Registering a type is what building a session does, not what reading a
    configuration does.

    The first version registered during validation. So a configuration
    refused at `patterns[1]` had already registered `patterns[0]`'s type, and
    a second configuration in the same process that disagreed about a
    category was refused because the first had won for good -- from a file
    that was never used.
    """

    def test_a_refused_configuration_registers_nothing(self) -> None:
        assert get_type("NEVER_USED_TYPE") is None
        with pytest.raises(ConfigurationError):
            MamoriConfig(
                patterns=[
                    {"type": "NEVER_USED_TYPE", "category": "PII", "pattern": "x"},
                    {"type": "BROKEN", "pattern": "("},
                ]
            )
        assert get_type("NEVER_USED_TYPE") is None, "reading a refused file registered a type"

    def test_an_accepted_configuration_registers_nothing_until_a_session_is_built(
        self,
    ) -> None:
        assert get_type("LATE_TYPE") is None
        config = MamoriConfig(
            patterns=[{"type": "LATE_TYPE", "category": "PII", "pattern": r"LT-\d{4}"}]
        )
        assert get_type("LATE_TYPE") is None, "validation registered a type"
        config.session()
        registered = get_type("LATE_TYPE")
        assert registered is not None and registered.category.value == "PII"

    def test_a_file_that_disagrees_with_the_process_is_refused_when_read(self) -> None:
        """Said at read time, whether or not this read would register: a file
        that means something different by a name the process already uses is
        wrong now, not later."""
        MamoriConfig(patterns=[{"type": "FIXED_TYPE", "category": "PII", "pattern": "x"}]).session()
        with pytest.raises(ConfigurationError, match="different settings"):
            MamoriConfig(patterns=[{"type": "FIXED_TYPE", "category": "SECRET", "pattern": "y"}])


class TestTheTierIsHonoured:
    def test_a_wide_rule_does_not_run_under_the_balanced_stance(self) -> None:
        """The same dial the shipped wide rules use. A rule that matches on
        shape alone belongs behind it, and a deployment that writes one should
        get the stance behaviour it already understands."""
        wide = {"type": "IDENTIFIER", "pattern": r"[A-Z]{2}[0-9]{5}", "tier": "wide"}
        text = "reference AB12345 attached"
        narrow = MamoriConfig(patterns=[wide], stance=Stance.BALANCED)
        widened = MamoriConfig(patterns=[wide], stance=Stance.RECALL_FIRST)
        assert "IDENTIFIER" not in narrow.session().inspect(text)
        assert "IDENTIFIER" in widened.session().inspect(text)


class TestFromAFileOnDisk:
    def test_a_json_file_carries_them(self, tmp_path: Path) -> None:
        """JSON first, because it is the format that works on every version
        this library supports. `tomllib` arrived in 3.11 and mamori runs on
        3.10, which is why `load_config_file` says *use a .json config
        instead* -- and why the TOML test below skips rather than fails."""
        import json as _json

        from mamori.config import load_config_file

        path = tmp_path / "mamori.json"
        path.write_text(
            _json.dumps({"stance": "balanced", "patterns": [ACME, CASE]}), encoding="utf-8"
        )
        config = load_config_file(path)
        assert len(config.patterns) == 2
        assert set(config.session().inspect(TEXT)) == {"EMPLOYEE_ID", "CASE_REFERENCE"}

    def test_a_toml_file_carries_them(self, tmp_path: Path) -> None:
        """The shape an operator actually writes, single-quoted so TOML does
        not eat the backslashes before this ever sees them."""
        pytest.importorskip("tomllib")
        from mamori.config import load_config_file

        path = tmp_path / "mamori.toml"
        path.write_text(
            "stance = 'balanced'\n\n"
            "[[patterns]]\n"
            "type = 'EMPLOYEE_ID'\n"
            "pattern = 'ACME-\\d{6}'\n"
            "confidence = 0.95\n\n"
            "[[patterns]]\n"
            "type = 'CASE_REFERENCE'\n"
            "category = 'PII'\n"
            "pattern = 'CS/\\d{4}/\\d{4}'\n",
            encoding="utf-8",
        )
        config = load_config_file(path)
        assert len(config.patterns) == 2
        assert set(config.session().inspect(TEXT)) == {"EMPLOYEE_ID", "CASE_REFERENCE"}

    def test_a_registered_type_survives_into_the_registry(self) -> None:
        """A custom type has to be looked up by name during restoration, so
        registering it is not decoration."""
        MamoriConfig(patterns=[CASE])
        registered = get_type("CASE_REFERENCE")
        assert registered is not None
        assert registered.category.value == "PII"
