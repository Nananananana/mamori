"""Configuration: one object holding every switch, and the layers over it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from mamori import MamoriConfig, PrivacySession, load_config_file
from mamori.domain.entity_types import Category
from mamori.domain.placeholder import PlaceholderStyle
from mamori.domain.policy import Action, Uncertain
from mamori.domain.stance import Stance
from mamori.errors import ConfigurationError, PolicyViolationError


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
    def test_settings_build_a_session(self) -> None:
        settings = MamoriConfig(locales=("en",), min_confidence=0.6)
        with settings.session() as session:
            assert session.policy.min_confidence == 0.6

    def test_a_session_can_still_be_built_by_hand(self) -> None:
        """Settings assemble a session; they are not the only way to get one."""
        from mamori.domain.policy import PrivacyPolicy

        policy = PrivacyPolicy.permissive()
        with PrivacySession(policy=policy) as session:
            assert session.policy is policy

    def test_the_confidence_floor_reaches_detection(self) -> None:
        text = "张伟先生您好。项目名称: 夜莺。"
        with MamoriConfig(min_confidence=0.6).session() as session:
            types = {e.entity_type for e in session.protect(text).entities}
        assert "PROJECT_NAME" not in types
        assert "PERSON" in types

    def test_the_locale_choice_reaches_detection(self) -> None:
        settings = MamoriConfig(locales=("ja",), stance=Stance.BALANCED)
        with settings.session() as session:
            protected = session.protect("请拨打 13812345678")
        assert "13812345678" in protected.protected_text

    def test_a_session_with_no_config_behaves_as_before(self) -> None:
        with PrivacySession() as session:
            protected = session.protect("田中太郎さんへ tanaka@example.com")
        assert "<PERSON_001>" in protected.protected_text
        assert "<EMAIL_001>" in protected.protected_text


class TestTheEnvironmentPrefixIsReserved:
    """``MAMORI_*`` names settings and nothing else.

    Refusing an unknown one is what catches a misspelled privacy variable, but
    it also means the obvious name for an API key variable is a trap. The error
    has to say which, or the reader concludes mamori is broken.
    """

    def test_an_unknown_variable_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            MamoriConfig.from_env({"MAMORI_LLM_KEY": "secret"})

    def test_the_error_names_the_variable_and_the_rule(self) -> None:
        with pytest.raises(ConfigurationError) as caught:
            MamoriConfig.from_env({"MAMORI_LLM_KEY": "secret"})
        message = str(caught.value)
        assert "MAMORI_LLM_KEY" in message
        assert "reserved" in message

    def test_the_value_is_not_echoed(self) -> None:
        """It is probably a secret. That is the whole reason it is here."""
        with pytest.raises(ConfigurationError) as caught:
            MamoriConfig.from_env({"MAMORI_LLM_KEY": "super-secret-value"})
        assert "super-secret-value" not in str(caught.value)

    def test_a_key_variable_outside_the_prefix_is_left_alone(self) -> None:
        config = MamoriConfig.from_env({"LLM_API_KEY": "secret", "MAMORI_LOCALES": "ja"})
        assert config.locales == ("ja",)


def _built(**settings: Any) -> MamoriConfig:
    """`MamoriConfig(**one_setting)`, through a signature a checker can read.

    The tests below build a config from a name chosen at run time, which is
    a `dict[str, object]` and matches no single field's type. The point of
    them is precisely that the constructor takes what a config file holds, so
    the `Any` is the subject rather than a way around it.
    """
    return MamoriConfig(**settings)


class TestEveryFieldSurvivesTheMapping:
    """A field `from_mapping` accepts as known and then drops is worse than an
    unknown key.

    An unknown key is refused, loudly, because *a typo in a privacy setting
    that silently does nothing is the worst possible outcome*. Two fields
    managed the same outcome from the other side: `uncertain` and
    `placeholder_style` were dataclass fields since 0.19 and 0.20, the known-key
    check accepted them, and nothing read them. `{"uncertain": "refuse"}` in a
    file, or `MAMORI_UNCERTAIN=refuse` in the environment, gave `discard` --
    the safety setting the deployment believed it had turned on, and had not.

    So this makes a field without a parser a failure. Every dataclass field
    needs an entry below giving a value that differs from the default, and the
    round trip has to produce that value. Adding a field without adding a line
    here fails at the `KeyError`, which is the whole point: the decision
    cannot be skipped.
    """

    #: A non-default value for every field, in the shape a config file gives.
    SAMPLES: ClassVar[dict[str, object]] = {
        "locales": ["ja"],
        "stance": "balanced",
        "rules": {"EMAIL": "allow"},
        "category_defaults": {"pii": "mask"},
        "default_action": "anonymize",
        "min_confidence": 0.5,
        "co_occurrence": False,
        "co_occurrence_min_confidence": 0.5,
        "mask_token": "[GONE]",
        "prompts": {"detection": {"disable": ["any.width"]}},
        "llm": {"model": "qwen2.5:7b"},
        "corrections": [{"value": "Acme", "verdict": "never", "type": "COMPANY_NAME"}],
        "surrogates": ["PERSON"],
        "placeholder_style": "square",
        "uncertain": "refuse",
        "patterns": [{"type": "EMPLOYEE_ID", "pattern": "ACME-[0-9]{6}"}],
        "secrets": "entropy",
        "nlp": "spacy",
        "phone": "phonenumbers",
    }

    def test_the_table_covers_every_field(self) -> None:
        # Private fields are excluded because they are not settings: `_named`
        # records which keys a loader saw, is refused as a config key, and is
        # left out of equality and every report. Excluding it is a decision
        # this line makes deliberately -- the check caught it on the commit
        # that added it, which is what the check is for.
        fields = {name for name in MamoriConfig.__dataclass_fields__ if not name.startswith("_")}
        assert set(self.SAMPLES) == fields, (
            f"not in the table: {sorted(fields - set(self.SAMPLES))}; "
            f"not a field any more: {sorted(set(self.SAMPLES) - fields)}. A field "
            "that is not in this table has no proof that from_mapping reads it."
        )

    @pytest.mark.parametrize("name", sorted(SAMPLES))
    def test_a_field_set_through_the_mapping_is_not_the_default(self, name: str) -> None:
        default = getattr(MamoriConfig(), name)
        loaded = getattr(MamoriConfig.from_mapping({name: self.SAMPLES[name]}), name)
        assert loaded != default, (
            f"{name}: from_mapping accepted {self.SAMPLES[name]!r} as a known key and "
            f"produced the default {default!r}. The key is read as valid and does "
            "nothing, which is the failure this class exists for."
        )

    @pytest.mark.parametrize("name", sorted(SAMPLES))
    def test_the_constructor_and_the_mapping_agree(self, name: str) -> None:
        """The same value, written the same way, gives the same config.

        The table above is *"the shape a config file gives"*, and until 0.33
        only `from_mapping` could read that shape. `MamoriConfig(stance=...)`
        stored whatever it was handed. Measured across these settings when it
        was found: five diverged, and `min_confidence="0.7"` raised a bare
        `TypeError` from the range check. `MamoriConfig(stance="balanced")`
        was accepted in silence and died later at

            AttributeError: 'str' object has no attribute 'includes'

        which names neither the setting nor the file it came from.

        Every README example passes enums, so the documented path worked and
        the obvious one did not -- and no test compared them, because each
        path was tested against itself.
        """
        written = self.SAMPLES[name]
        assert _built(**{name: written}) == MamoriConfig.from_mapping({name: written}), (
            f"{name}: MamoriConfig({name}={written!r}) and "
            f"from_mapping({{{name!r}: {written!r}}}) are different objects. One of "
            "the two paths is not coercing, and the caller cannot tell which."
        )

    @pytest.mark.parametrize("name", sorted(SAMPLES))
    def test_a_value_neither_path_can_read_is_refused_by_both(self, name: str) -> None:
        """And refused *here*, with a message naming the setting.

        `ConfigurationError` specifically: a bare `TypeError` or `ValueError`
        from somewhere inside is what this replaced, and it tells the operator
        nothing about which setting they got wrong.
        """
        if name == "mask_token":
            pytest.skip("any string is a mask token; there is nothing to refuse")
        nonsense = {"llm": 7, "prompts": 7, "corrections": 7, "surrogates": 7}.get(
            name, "no-such-value"
        )
        with pytest.raises(ConfigurationError):
            _built(**{name: nonsense})
        with pytest.raises(ConfigurationError):
            MamoriConfig.from_mapping({name: nonsense})


class TestALayerCanRestoreADefault:
    """The layering could not express *"set this back to the safe value"*.

    `merged_with` decided what to overlay by comparing against the defaults,
    so a layer that named a setting whose value happened to *be* the default
    was indistinguishable from a layer that said nothing. The worst case is
    the fail-closed one: a config file saying `default_action = "allow"` could
    not be overridden by `MAMORI_DEFAULT_ACTION=block`, because `block` is the
    default. An operator tightening protection was ignored in silence.

    Same family as the two fields above -- a setting accepted and discarded --
    reached from the other direction, by a correct key with a correct value.
    """

    def layered(self, file: dict[str, object], env: dict[str, str]) -> MamoriConfig:
        """Exactly what the command line does: defaults, file, environment."""
        settings = MamoriConfig()
        settings = settings.merged_with(MamoriConfig.from_mapping(file))
        return settings.merged_with(MamoriConfig.from_env(env))

    def test_the_environment_can_restore_the_fail_closed_default(self) -> None:
        merged = self.layered({"default_action": "allow"}, {"MAMORI_DEFAULT_ACTION": "block"})
        assert merged.default_action is Action.BLOCK

    def test_the_environment_can_restore_the_safer_stance(self) -> None:
        merged = self.layered({"stance": "balanced"}, {"MAMORI_STANCE": "recall_first"})
        assert merged.stance is Stance.RECALL_FIRST

    def test_the_environment_can_restore_full_coverage(self) -> None:
        merged = self.layered({"min_confidence": 0.9}, {"MAMORI_MIN_CONFIDENCE": "0.0"})
        assert merged.min_confidence == 0.0

    def test_the_environment_can_turn_co_occurrence_back_on(self) -> None:
        merged = self.layered({"co_occurrence": False}, {"MAMORI_CO_OCCURRENCE": "on"})
        assert merged.co_occurrence is True

    def test_a_layer_that_says_nothing_still_changes_nothing(self) -> None:
        """The property the old heuristic got right, kept."""
        merged = self.layered({"stance": "balanced"}, {})
        assert merged.stance is Stance.BALANCED

    def test_an_unrelated_key_does_not_drag_the_others_along(self) -> None:
        merged = self.layered(
            {"stance": "balanced", "min_confidence": 0.9}, {"MAMORI_LOCALES": "ja"}
        )
        assert merged.locales == ("ja",)
        assert merged.stance is Stance.BALANCED
        assert merged.min_confidence == 0.9

    def test_a_hand_built_config_keeps_the_old_behaviour(self) -> None:
        """A config assembled in Python names every field by construction, so
        it cannot say which were meant. Documented, and unchanged -- a caller
        in Python can build the final object instead of layering."""
        assert MamoriConfig(stance=Stance.BALANCED).merged_with(MamoriConfig()).stance is (
            Stance.BALANCED
        )

    def test_the_marker_is_not_a_configuration_key(self) -> None:
        with pytest.raises(ConfigurationError, match="unknown configuration key"):
            MamoriConfig.from_mapping({"_named": ["stance"]})

    def test_the_marker_is_not_offered_as_a_known_key(self) -> None:
        with pytest.raises(ConfigurationError) as raised:
            MamoriConfig.from_mapping({"nope": 1})
        assert "_named" not in str(raised.value)

    def test_the_marker_does_not_affect_equality(self) -> None:
        assert MamoriConfig.from_mapping({"stance": "recall_first"}) == MamoriConfig()


class TestTheTwoFieldsThatWereDropped:
    def test_uncertain_from_a_mapping(self) -> None:
        assert MamoriConfig.from_mapping({"uncertain": "refuse"}).uncertain == "refuse"

    def test_uncertain_from_the_environment(self) -> None:
        """The deployment that wants to be stopped sets this in an environment
        variable, and until 0.31 it was ignored there."""
        assert MamoriConfig.from_env({"MAMORI_UNCERTAIN": "refuse"}).uncertainty() is (
            Uncertain.REFUSE
        )

    def test_placeholder_style_from_a_mapping(self) -> None:
        assert MamoriConfig.from_mapping({"placeholder_style": "square"}).style() is (
            PlaceholderStyle.SQUARE
        )

    def test_placeholder_style_from_the_environment(self) -> None:
        assert MamoriConfig.from_env({"MAMORI_PLACEHOLDER_STYLE": "curly"}).style() is (
            PlaceholderStyle.CURLY
        )

    def test_a_refusal_reaches_the_session_it_configures(self) -> None:
        """The setting is only real if the session built from it refuses."""
        config = MamoriConfig.from_mapping({"min_confidence": 0.95, "uncertain": "refuse"})
        with pytest.raises(PolicyViolationError, match="refuses"):
            config.session().protect("I spoke to Jane Doe yesterday about 090-1234-5678")

    @pytest.mark.parametrize("key", ["uncertain", "placeholder_style"])
    def test_a_bad_name_is_refused_when_the_file_is_read(self, key: str) -> None:
        """Not on the first document. `style()` and `uncertainty()` already
        refuse at use time; a config file should fail when it is loaded."""
        with pytest.raises(ConfigurationError, match=f"unknown {key}"):
            MamoriConfig.from_mapping({key: "sideways"})

    def test_the_names_are_case_insensitive_like_every_other_choice(self) -> None:
        assert MamoriConfig.from_mapping({"uncertain": "REFUSE"}).uncertain == "refuse"
