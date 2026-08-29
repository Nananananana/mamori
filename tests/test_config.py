"""Configuration: one object holding every switch, and the layers over it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mamori import MamoriConfig, PrivacySession, load_config_file
from mamori.domain.entity_types import Category
from mamori.domain.policy import Action
from mamori.domain.stance import Stance
from mamori.errors import ConfigurationError


class TestDefaults:
    def test_the_default_config_matches_the_default_session(self) -> None:
        assert MamoriConfig().policy().default_action is Action.BLOCK

    def test_coverage_is_not_reduced_by_default(self) -> None:
        """The confidence floor must stay at zero unless somebody asks."""
        assert MamoriConfig().min_confidence == 0.0

    def test_co_occurrence_is_on_by_default(self) -> None:
        assert MamoriConfig().co_occurrence is True

    def test_all_locales_by_default(self) -> None:
        assert MamoriConfig().locales is None

    def test_it_is_immutable(self) -> None:
        settings = MamoriConfig()
        with pytest.raises(AttributeError):
            settings.min_confidence = 0.5  # type: ignore[misc]


class TestValidation:
    @pytest.mark.parametrize("value", [-0.1, 1.5])
    def test_an_out_of_range_confidence_is_refused(self, value: float) -> None:
        with pytest.raises(ConfigurationError):
            MamoriConfig(min_confidence=value)

    @pytest.mark.parametrize("value", [-0.1, 1.5])
    def test_an_out_of_range_seed_confidence_is_refused(self, value: float) -> None:
        with pytest.raises(ConfigurationError):
            MamoriConfig(co_occurrence_min_confidence=value)


class TestFromMapping:
    def test_locales_as_a_list(self) -> None:
        assert MamoriConfig.from_mapping({"locales": ["ja", "en"]}).locales == ("ja", "en")

    def test_locales_as_a_comma_separated_string(self) -> None:
        assert MamoriConfig.from_mapping({"locales": "ja, en"}).locales == ("ja", "en")

    def test_locales_null_means_all(self) -> None:
        assert MamoriConfig.from_mapping({"locales": None}).locales is None

    def test_rules(self) -> None:
        settings = MamoriConfig.from_mapping({"rules": {"EMAIL": "allow"}})
        assert settings.rules == {"EMAIL": Action.ALLOW}

    def test_category_defaults(self) -> None:
        settings = MamoriConfig.from_mapping({"category_defaults": {"pii": "mask"}})
        assert settings.category_defaults == {Category.PII: Action.MASK}

    def test_default_action(self) -> None:
        assert MamoriConfig.from_mapping({"default_action": "ANONYMIZE"}).default_action is (
            Action.ANONYMIZE
        )

    @pytest.mark.parametrize(("raw", "expected"), [("on", True), ("off", False), (False, False)])
    def test_booleans(self, raw: object, expected: bool) -> None:
        assert MamoriConfig.from_mapping({"co_occurrence": raw}).co_occurrence is expected

    def test_numbers_as_strings(self) -> None:
        assert MamoriConfig.from_mapping({"min_confidence": "0.7"}).min_confidence == 0.7

    def test_an_unknown_key_is_refused(self) -> None:
        """A typo in a privacy setting that silently does nothing is the worst case."""
        with pytest.raises(ConfigurationError, match="unknown configuration key"):
            MamoriConfig.from_mapping({"min_confidance": 0.7})

    def test_the_error_lists_the_known_keys(self) -> None:
        with pytest.raises(ConfigurationError, match="min_confidence"):
            MamoriConfig.from_mapping({"nope": 1})

    def test_an_unknown_action_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="unknown action"):
            MamoriConfig.from_mapping({"default_action": "shred"})

    def test_an_unknown_category_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="unknown category"):
            MamoriConfig.from_mapping({"category_defaults": {"vibes": "allow"}})

    def test_a_non_mapping_rules_block_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="rules must be a mapping"):
            MamoriConfig.from_mapping({"rules": ["EMAIL"]})

    def test_a_non_numeric_confidence_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="must be a number"):
            MamoriConfig.from_mapping({"min_confidence": "soon"})

    def test_a_non_boolean_toggle_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="must be true or false"):
            MamoriConfig.from_mapping({"co_occurrence": "maybe"})

    def test_an_empty_mapping_gives_the_defaults(self) -> None:
        assert MamoriConfig.from_mapping({}) == MamoriConfig()

    def test_the_seed_confidence(self) -> None:
        settings = MamoriConfig.from_mapping({"co_occurrence_min_confidence": 0.5})
        assert settings.co_occurrence_min_confidence == 0.5

    def test_the_mask_token(self) -> None:
        assert MamoriConfig.from_mapping({"mask_token": "[GONE]"}).mask_token == "[GONE]"

    def test_a_locales_value_of_the_wrong_shape_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="locales must be"):
            MamoriConfig.from_mapping({"locales": 7})

    def test_a_non_mapping_category_block_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="category_defaults must be a mapping"):
            MamoriConfig.from_mapping({"category_defaults": ["pii"]})


class TestFromEnv:
    def test_locales(self) -> None:
        settings = MamoriConfig.from_env({"MAMORI_LOCALES": "ja,en"})
        assert settings.locales == ("ja", "en")

    def test_min_confidence(self) -> None:
        assert MamoriConfig.from_env({"MAMORI_MIN_CONFIDENCE": "0.7"}).min_confidence == 0.7

    def test_a_toggle(self) -> None:
        assert MamoriConfig.from_env({"MAMORI_CO_OCCURRENCE": "off"}).co_occurrence is False

    def test_unrelated_variables_are_ignored(self) -> None:
        assert MamoriConfig.from_env({"PATH": "/usr/bin", "HOME": "/root"}) == MamoriConfig()

    def test_an_unknown_mamori_variable_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            MamoriConfig.from_env({"MAMORI_MIN_CONFIDANCE": "0.7"})

    def test_an_empty_environment(self) -> None:
        assert MamoriConfig.from_env({}) == MamoriConfig()


class TestLoadConfigFile:
    def test_json(self, tmp_path: Path) -> None:
        path = tmp_path / "mamori.json"
        path.write_text(json.dumps({"locales": ["ja"], "min_confidence": 0.6}), encoding="utf-8")
        settings = load_config_file(path)
        assert settings.locales == ("ja",)
        assert settings.min_confidence == 0.6

    def test_a_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="could not read"):
            load_config_file(tmp_path / "nope.json")

    def test_malformed_json_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "mamori.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="malformed"):
            load_config_file(path)

    def test_a_non_mapping_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "mamori.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="must be a mapping"):
            load_config_file(path)

    def test_toml(self, tmp_path: Path) -> None:
        pytest.importorskip("tomllib")
        path = tmp_path / "mamori.toml"
        path.write_text('locales = ["ja", "en"]\nmin_confidence = 0.6\n', encoding="utf-8")
        settings = load_config_file(path)
        assert settings.locales == ("ja", "en")


class TestMerging:
    def test_a_later_layer_wins(self) -> None:
        base = MamoriConfig(locales=("ja",), min_confidence=0.5)
        overlay = MamoriConfig(min_confidence=0.8)
        assert base.merged_with(overlay).min_confidence == 0.8

    def test_an_untouched_field_survives(self) -> None:
        base = MamoriConfig(locales=("ja",), min_confidence=0.5)
        assert base.merged_with(MamoriConfig(min_confidence=0.8)).locales == ("ja",)

    def test_merging_defaults_changes_nothing(self) -> None:
        base = MamoriConfig(locales=("ja",), co_occurrence=False)
        assert base.merged_with(MamoriConfig()) == base

    def test_replace(self) -> None:
        assert MamoriConfig().replace(min_confidence=0.4).min_confidence == 0.4


class TestBuildingBlocks:
    def test_the_policy_carries_the_confidence_floor(self) -> None:
        assert MamoriConfig(min_confidence=0.7).policy().min_confidence == 0.7

    def test_the_policy_keeps_the_fail_closed_default(self) -> None:
        from mamori.domain.entity_types import EntityType

        policy = MamoriConfig().policy()
        assert policy.action_for(EntityType("SOMETHING_NEW")) is Action.BLOCK

    def test_a_rule_overrides_the_built_in_one(self) -> None:
        from mamori.domain import entity_types as t

        settings = MamoriConfig(rules={"EMAIL": Action.ALLOW})
        assert settings.policy().action_for(t.EMAIL) is Action.ALLOW

    def test_the_detectors_honour_the_locale_choice(self) -> None:
        pipeline = MamoriConfig(locales=("ja",), stance=Stance.BALANCED).detectors()[0]
        assert "PHONE" not in {e.entity_type.name for e in pipeline.detect("请拨打 13812345678")}

    def test_the_detectors_honour_the_co_occurrence_toggle(self) -> None:
        assert len(MamoriConfig(co_occurrence=False).detectors()[0].passes) == 1
        assert len(MamoriConfig(co_occurrence=True).detectors()[0].passes) == 2

    def test_an_unknown_locale_is_refused_when_the_detectors_are_built(self) -> None:
        with pytest.raises(ConfigurationError, match="unknown locale"):
            MamoriConfig(locales=("kl",)).detectors()


class TestSessionIntegration:
    def test_a_session_takes_a_config(self) -> None:
        settings = MamoriConfig(locales=("en",), min_confidence=0.6)
        with PrivacySession(config=settings) as session:
            assert session.config is settings
            assert session.policy.min_confidence == 0.6

    def test_an_explicit_argument_beats_the_config(self) -> None:
        from mamori.domain.policy import PrivacyPolicy

        settings = MamoriConfig(min_confidence=0.6)
        policy = PrivacyPolicy.permissive()
        with PrivacySession(config=settings, policy=policy) as session:
            assert session.policy is policy

    def test_the_confidence_floor_reaches_detection(self) -> None:
        text = "张伟先生您好。项目名称: 夜莺。"
        with PrivacySession(config=MamoriConfig(min_confidence=0.6)) as session:
            types = {e.entity_type for e in session.protect(text).entities}
        assert "PROJECT_NAME" not in types
        assert "PERSON" in types

    def test_the_locale_choice_reaches_detection(self) -> None:
        settings = MamoriConfig(locales=("ja",), stance=Stance.BALANCED)
        with PrivacySession(config=settings) as session:
            protected = session.protect("请拨打 13812345678")
        assert "13812345678" in protected.protected_text

    def test_a_session_with_no_config_behaves_as_before(self) -> None:
        with PrivacySession() as session:
            protected = session.protect("田中太郎さんへ tanaka@example.com")
        assert "<PERSON_001>" in protected.protected_text
        assert "<EMAIL_001>" in protected.protected_text
