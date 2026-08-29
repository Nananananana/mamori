"""Configuring a model, on this machine or on the company's.

The same code has to serve a laptop pointing at Ollama and a server pointing at
a GPU box two racks over. What differs is a config file, and this pins down what
that file may say -- including the two things it may never say: a key, and a
public endpoint.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mamori import MamoriConfig, load_config_file
from mamori.domain.trust import TrustBoundary
from mamori.errors import ConfigurationError
from mamori.llm_settings import LLMSettings

LOCAL = "http://localhost:11434/v1/"
IN_HOUSE = "http://llm01.corp:8000/v1/"
PUBLIC = "https://api.openai.com/v1/"


class TestDefaults:
    def test_the_default_points_at_this_machine(self) -> None:
        assert "localhost" in LLMSettings().base_url

    def test_the_default_boundary_covers_the_company_network(self) -> None:
        assert LLMSettings().trust is TrustBoundary.PRIVATE_NETWORK

    def test_the_model_is_the_only_thing_with_no_sensible_default(self) -> None:
        assert LLMSettings().model == ""

    def test_the_model_is_not_required_by_default(self) -> None:
        """Rules are the guarantee; a model is the improvement."""
        assert LLMSettings().require_model is False

    def test_a_config_has_no_model_unless_asked(self) -> None:
        assert MamoriConfig().llm is None
        assert MamoriConfig().llm_passes() == ()


class TestValidation:
    def test_a_non_positive_timeout_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="timeout"):
            LLMSettings(timeout=0)

    def test_negative_retries_are_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="retries"):
            LLMSettings(retries=-1)

    def test_a_zero_input_limit_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            LLMSettings(max_input_characters=0)


class TestFromMapping:
    def test_the_in_house_server_case(self) -> None:
        settings = LLMSettings.from_mapping({"model": "qwen2.5:7b", "base_url": IN_HOUSE})
        assert settings.endpoint().is_remote
        assert settings.endpoint().policy.admits(IN_HOUSE)

    def test_the_same_machine_case(self) -> None:
        settings = LLMSettings.from_mapping({"model": "qwen2.5:7b"})
        assert not settings.endpoint().is_remote

    def test_a_named_key_variable(self) -> None:
        assert LLMSettings.from_mapping({"api_key_env": "MY_KEY"}).api_key_env == "MY_KEY"

    def test_a_literal_key_is_refused(self) -> None:
        """A config file that gets committed must not carry a credential."""
        with pytest.raises(ConfigurationError, match="environment variable"):
            LLMSettings.from_mapping({"model": "m", "api_key": "sk-secret"})

    def test_the_trust_boundary(self) -> None:
        assert LLMSettings.from_mapping({"trust": "same_host"}).trust is TrustBoundary.SAME_HOST

    def test_an_unknown_boundary_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="unknown boundary"):
            LLMSettings.from_mapping({"trust": "vibes"})

    def test_trusted_hosts(self) -> None:
        settings = LLMSettings.from_mapping({"trusted_hosts": ["llm.example.com"]})
        assert settings.trusted_hosts == ("llm.example.com",)

    def test_numbers_as_strings(self) -> None:
        settings = LLMSettings.from_mapping({"timeout": "30", "retries": "1"})
        assert settings.timeout == 30.0
        assert settings.retries == 1

    def test_an_unknown_key_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="unknown llm key"):
            LLMSettings.from_mapping({"base_urls": LOCAL})

    def test_a_non_numeric_timeout_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="must be a number"):
            LLMSettings.from_mapping({"timeout": "soon"})

    def test_a_non_whole_retry_count_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="whole number"):
            LLMSettings.from_mapping({"retries": "many"})

    def test_a_non_list_trusted_hosts_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="must be a list"):
            LLMSettings.from_mapping({"trusted_hosts": "llm.example.com"})

    def test_locales_can_be_null(self) -> None:
        assert LLMSettings.from_mapping({"locales": None}).locales is None

    def test_locales_narrow_the_prompt(self) -> None:
        assert LLMSettings.from_mapping({"locales": ["ja"]}).locales == ("ja",)

    def test_options_pass_through(self) -> None:
        settings = LLMSettings.from_mapping({"options": {"num_ctx": 8192}})
        assert settings.endpoint().options == {"num_ctx": 8192}

    def test_a_non_mapping_options_block_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="options must be a mapping"):
            LLMSettings.from_mapping({"options": ["num_ctx"]})


class TestDescription:
    def test_it_round_trips(self) -> None:
        original = LLMSettings(model="m", base_url=IN_HOUSE, trust=TrustBoundary.SAME_HOST)
        assert LLMSettings.from_mapping(original.as_mapping()) == original

    def test_the_description_never_contains_a_key(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("MY_KEY", "super-secret")
        described = json.dumps(LLMSettings(model="m", api_key_env="MY_KEY").as_mapping())
        assert "super-secret" not in described
        assert "MY_KEY" in described


class TestBuildingThePass:
    def test_the_in_house_server_builds_a_pass(self) -> None:
        settings = MamoriConfig.from_mapping({"llm": {"model": "qwen2.5:7b", "base_url": IN_HOUSE}})
        assert len(settings.llm_passes()) == 1

    def test_the_same_machine_builds_a_pass(self) -> None:
        settings = MamoriConfig.from_mapping({"llm": {"model": "qwen2.5:7b"}})
        assert len(settings.llm_passes()) == 1

    def test_a_public_endpoint_is_refused_at_startup(self) -> None:
        """Not on the first document, by which time it is too late to matter."""
        settings = MamoriConfig.from_mapping({"llm": {"model": "gpt", "base_url": PUBLIC}})
        with pytest.raises(ConfigurationError, match="outside the private_network"):
            settings.llm_passes()

    def test_a_public_endpoint_can_be_declared_trusted(self) -> None:
        settings = MamoriConfig.from_mapping(
            {
                "llm": {
                    "model": "m",
                    "base_url": "https://llm.example.com/v1/",
                    "trusted_hosts": ["llm.example.com"],
                }
            }
        )
        assert len(settings.llm_passes()) == 1

    def test_no_model_name_means_no_pass(self) -> None:
        """A half-filled config does not silently start talking to Ollama."""
        assert MamoriConfig.from_mapping({"llm": {"base_url": IN_HOUSE}}).llm_passes() == ()

    def test_an_unknown_provider_is_refused(self) -> None:
        settings = MamoriConfig.from_mapping({"llm": {"provider": "nope", "model": "m"}})
        with pytest.raises(ConfigurationError, match="unknown LLM provider"):
            settings.llm_passes()

    def test_the_pass_reaches_the_pipeline(self) -> None:
        settings = MamoriConfig.from_mapping({"llm": {"model": "qwen2.5:7b"}})
        pipeline = settings.detectors()[0]
        assert [p.name for p in pipeline.passes] == ["rules", "co-occurrence", "llm"]

    def test_the_prompt_overlay_reaches_the_pass(self) -> None:
        settings = MamoriConfig.from_mapping(
            {
                "llm": {"model": "m"},
                "prompts": {"detection": {"add": [{"id": "acme.case", "text": "ACME-12345."}]}},
            }
        )
        assert "ACME-12345" in settings.llm_passes()[0].rendered_prompt()

    def test_the_input_limit_reaches_the_pass(self) -> None:
        settings = MamoriConfig.from_mapping({"llm": {"model": "m", "max_input_characters": 500}})
        assert settings.llm_passes()[0]._max_input == 500


class TestConfigIntegration:
    def test_llm_can_be_null(self) -> None:
        assert MamoriConfig.from_mapping({"llm": None}).llm is None

    def test_a_non_mapping_llm_block_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="must be a mapping"):
            MamoriConfig.from_mapping({"llm": "qwen"})

    def test_a_full_deployment_from_a_file(self, tmp_path: Path) -> None:
        """The shape a team on a shared server would actually check in."""
        path = tmp_path / "mamori.json"
        path.write_text(
            json.dumps(
                {
                    "locales": ["ja", "en"],
                    "stance": "recall_first",
                    "llm": {
                        "provider": "openai_compatible",
                        "model": "qwen2.5:7b",
                        "base_url": IN_HOUSE,
                        "api_key_env": "LLM_API_KEY",
                        "timeout": 45,
                        "retries": 3,
                        "trust": "private_network",
                        "locales": ["ja"],
                    },
                    "prompts": {"detection": {"disable": ["zh.person.shape"]}},
                }
            ),
            encoding="utf-8",
        )
        settings = load_config_file(path)
        assert settings.llm is not None
        assert settings.llm.endpoint().is_remote
        pipeline = settings.detectors()[0]
        assert [p.name for p in pipeline.passes] == ["rules", "co-occurrence", "llm"]

    def test_a_session_can_be_built_from_it(self, tmp_path: Path) -> None:
        settings = MamoriConfig.from_mapping({"llm": {"model": "qwen2.5:7b"}})
        with settings.session() as session:
            protected = session.protect("田中太郎さんへ")
        # The model is unreachable in a test, so the pass degrades and the
        # rules carry the document, which is the designed behaviour.
        assert "<PERSON_001>" in protected.protected_text
