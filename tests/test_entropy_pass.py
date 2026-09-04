"""The entropy pass, and the switch that selects it.

Three questions, kept apart because they fail differently: does the pass find
a bare key and leave a word alone; does the switch actually change what a
session does; and does *not* switching it on leave every published number
exactly where it was.
"""

from __future__ import annotations

import pytest

from mamori import MamoriConfig, PrivacySession
from mamori.domain.confidence import LOW, MEDIUM
from mamori.domain.sensitive_entity import SensitiveEntity
from mamori.errors import ConfigurationError, PolicyViolationError
from mamori.infrastructure.detectors import EntropyPass
from mamori.infrastructure.detectors.secrets import (
    DEFAULT_SECRET_ALGORITHM,
    available_secret_algorithms,
    register_secret_algorithm,
    secret_passes,
)
from mamori.ports.detection_pass import DetectionContext, DetectionPass

from .contracts import DetectionPassContract

HEX_KEY = "a3f9c2e14b7d8e0f6a1c5b9d2e8f4a7c3b6d9e1f"
B64_KEY = "Kx7pQz2mNv8Ld4Rt9Wy3Bc6Hj1Fs5Gk0Zn"


def found_by(text: str, **kwargs: object) -> list[SensitiveEntity]:
    return list(EntropyPass(**kwargs).run(DetectionContext(text=text)))  # type: ignore[arg-type]


class TestItSatisfiesTheContract(DetectionPassContract):
    def make_pass(self) -> DetectionPass:
        return EntropyPass()

    def sample(self) -> str:
        """The contract's default text holds no run long enough to judge, so
        the coverage check over it would pass while checking nothing."""
        return f"Authorization: Bearer {HEX_KEY}"


class TestWhatItFinds:
    """Phrasings measured against the default rules first, at both stances,
    and missed by every one of them. `api_key = X` and `token: X` are *not*
    here: the keyword-assignment rule already blocks those as PASSWORD, and
    this pass defers to it. What is here is what nothing had an anchor for."""

    def test_a_bearer_token_in_a_header(self) -> None:
        """No vendor prefix, no `=`, no case to mix. Missed since 0.1."""
        (entity,) = found_by(f"Authorization: Bearer {HEX_KEY}")
        assert entity.entity_type.name == "API_KEY"
        assert entity.value == HEX_KEY
        assert entity.confidence == MEDIUM

    def test_a_key_named_in_prose(self) -> None:
        (entity,) = found_by(f"the new staging key is {HEX_KEY}")
        assert entity.confidence == MEDIUM

    def test_a_base64_token_named_in_prose(self) -> None:
        (entity,) = found_by(f"rotate the token {B64_KEY} tomorrow")
        assert entity.value == B64_KEY
        assert entity.confidence == MEDIUM

    def test_a_key_with_nothing_beside_it_is_low(self) -> None:
        """Found, but at LOW, so `min_confidence=0.6` drops exactly these."""
        (entity,) = found_by(f"see {HEX_KEY} above")
        assert entity.confidence == LOW

    def test_a_japanese_keyword_counts(self) -> None:
        (entity,) = found_by(f"鍵は {HEX_KEY} です")
        assert entity.confidence == MEDIUM

    def test_a_chinese_keyword_counts(self) -> None:
        (entity,) = found_by(f"密钥：{HEX_KEY}")
        assert entity.confidence == MEDIUM

    def test_the_span_is_the_token_and_not_the_keyword(self) -> None:
        text = f"Bearer {HEX_KEY}"
        (entity,) = found_by(text)
        assert text[entity.span.start : entity.span.end] == HEX_KEY

    def test_the_source_says_it_was_measured(self) -> None:
        (entity,) = found_by(f"key {HEX_KEY}")
        assert entity.source == "entropy"


class TestWhatItLeavesAlone:
    def test_a_long_word(self) -> None:
        assert found_by("Donaudampfschifffahrtsgesellschaftskapitaen") == []

    def test_a_pangram_is_not_believed_without_a_mix(self) -> None:
        """Clears the entropy line at 4.54 and has no upper case or digit.
        The domain measure flags it; the pass does not."""
        assert found_by("key thequickbrownfoxjumpsoverthelazydog") == []

    def test_a_digit_run(self) -> None:
        """An order number is an identifier, and the wide rules own it."""
        assert found_by("order 98765432109876543210") == []

    def test_a_uuid(self) -> None:
        assert found_by("request_id 3f2504e0-4f89-41d3-9a0c-0305e82c3301") == []

    def test_a_path(self) -> None:
        """Slashes cut the run. The wide-tier rule learned this from an
        assembled-prompt corpus; here it is a property of the tokeniser."""
        assert found_by("see /srv/shared/notes/customer-notes-2026-final-draft") == []

    def test_a_url(self) -> None:
        assert found_by("https://github.com/owner/repo/blob/main/src/very/long/path/name.py") == []

    def test_a_short_run(self) -> None:
        assert found_by(f"key {HEX_KEY[:19]}") == []

    def test_something_already_covered(self) -> None:
        """A span something with an anchor already claimed is left alone. An
        anchor beats a measurement, and reporting it twice is noise.

        The first version used the AWS fixture as the covered span, and the
        class-mix guard rejects that token on its own -- all upper case -- so
        the test passed with coverage ignored entirely. Measured by removing
        the coverage check and watching nothing go red. The covered span is
        now one the pass *would* flag, so the only reason it is not is that
        it was told not to.
        """
        text = f"see {HEX_KEY} above"
        assert found_by(text), "the sample must be one the pass flags when uncovered"
        (would_flag,) = found_by(text)
        prior = SensitiveEntity(
            entity_type=would_flag.entity_type,
            span=would_flag.span,
            value=HEX_KEY,
            source="rules",
        )
        context = DetectionContext(text=text, found=(prior,))
        assert list(EntropyPass().run(context)) == []


class TestTheHashWords:
    """The documented false positive, made visible rather than avoided."""

    def test_a_commit_id_next_to_the_word_commit_is_low(self) -> None:
        (entity,) = found_by(f"commit {HEX_KEY}")
        assert entity.confidence == LOW

    def test_a_hash_word_beats_a_secret_word(self) -> None:
        """`token digest` is ambiguous; the reading that does not stop the
        request wins, and `min_confidence` can still catch it."""
        (entity,) = found_by(f"token digest: {HEX_KEY}")
        assert entity.confidence == LOW


class TestTheDials:
    def test_the_thresholds_are_the_domains(self) -> None:
        assert found_by(f"key {HEX_KEY}", hex_threshold=4.1) == []

    def test_the_window(self) -> None:
        far = "x" * 80
        (entity,) = found_by(f"api_key {far} {HEX_KEY}", window=10)
        assert entity.confidence == LOW

    def test_a_nonsense_length_is_refused(self) -> None:
        with pytest.raises(ValueError, match="min_length"):
            EntropyPass(min_length=4)

    def test_a_nonsense_window_is_refused(self) -> None:
        with pytest.raises(ValueError, match="window"):
            EntropyPass(window=-1)


class TestTheSwitch:
    """`MamoriConfig(secrets=...)`. The algorithm is a name, and the name has
    to change what a session does, or it is a comment."""

    def test_the_default_is_patterns_only(self) -> None:
        assert MamoriConfig().secrets == DEFAULT_SECRET_ALGORITHM == "patterns"

    def test_patterns_adds_no_pass(self) -> None:
        assert secret_passes("patterns") == ()

    def test_entropy_adds_the_pass(self) -> None:
        (only,) = secret_passes("entropy")
        assert isinstance(only, EntropyPass)

    #: Missed by the default rules at both stances -- measured, not assumed.
    BARE = f"Authorization: Bearer {HEX_KEY}"

    def test_the_default_session_does_not_find_a_bare_key(self) -> None:
        """The property every published figure rests on. If this ever starts
        finding one, the tables in SECURITY.md are describing a different
        detector than the one that ships."""
        with PrivacySession() as session:
            result = session.protect(self.BARE)
        assert HEX_KEY in result.protected_text

    def test_an_anchored_key_was_never_this_pass_s_business(self) -> None:
        """`api_key = X` is the keyword-assignment rule's finding, blocked as
        PASSWORD whatever this switch says. The first version of these tests
        used it as the "bare" sample and learned that from the failure."""
        with pytest.raises(PolicyViolationError, match="PASSWORD"):
            PrivacySession().protect(f"api_key = {HEX_KEY}")

    def test_the_switched_session_blocks_it(self) -> None:
        """Found, and *blocked*: it is a credential, and the default policy
        refuses to send one. A deployment turning this on has chosen that."""
        config = MamoriConfig.from_mapping({"secrets": "entropy"})
        with pytest.raises(PolicyViolationError, match="API_KEY"):
            config.session().protect(self.BARE)

    def test_the_switched_session_pseudonymises_it_when_permitted(self) -> None:
        config = MamoriConfig.from_mapping(
            {"secrets": "entropy", "rules": {"API_KEY": "anonymize"}}
        )
        result = config.session().protect(self.BARE)
        assert HEX_KEY not in result.protected_text
        assert "<API_KEY_001>" in result.protected_text

    def test_it_reaches_japanese_and_chinese_prose(self) -> None:
        config = MamoriConfig.from_mapping(
            {"secrets": "entropy", "rules": {"API_KEY": "anonymize"}}
        )
        for text in (f"鍵は {HEX_KEY} です", f"密钥：{HEX_KEY}"):
            assert HEX_KEY not in config.session().protect(text).protected_text

    def test_min_confidence_drops_the_unanchored_ones(self) -> None:
        """LOW without a keyword. The dial that turns this from "block every
        hash" into "block every hash that something called a key"."""
        config = MamoriConfig.from_mapping(
            {"secrets": "entropy", "min_confidence": 0.6, "rules": {"API_KEY": "anonymize"}}
        )
        kept = config.session().protect(f"see {HEX_KEY} above").protected_text
        assert HEX_KEY in kept
        gone = config.session().protect(self.BARE).protected_text
        assert HEX_KEY not in gone

    def test_from_the_environment(self) -> None:
        assert MamoriConfig.from_env({"MAMORI_SECRETS": "entropy"}).secrets == "entropy"

    def test_a_misspelling_is_refused_when_the_file_is_read(self) -> None:
        """Not silently patterns. A config that says it is looking for bare
        keys and a scanner that is not is the worst outcome available."""
        with pytest.raises(ConfigurationError, match="unknown secrets algorithm"):
            MamoriConfig.from_mapping({"secrets": "entrpy"})

    def test_the_error_names_what_is_available(self) -> None:
        with pytest.raises(ConfigurationError, match="patterns, entropy"):
            secret_passes("nope")

    def test_the_trace_names_the_measurement(self) -> None:
        config = MamoriConfig.from_mapping(
            {"secrets": "entropy", "rules": {"API_KEY": "anonymize"}}
        )
        result = config.session(trace=True).protect(self.BARE)
        assert any(e.source == "entropy" for e in result.entities)


class TestTheRegistry:
    """A fourth algorithm is a call and a config value, not an edit."""

    def test_registration_makes_a_name_selectable(self) -> None:
        class Nothing:
            name = "nothing"

            def run(self, context: DetectionContext) -> list[SensitiveEntity]:
                return []

        register_secret_algorithm("nothing", lambda: (Nothing(),))
        try:
            assert "nothing" in available_secret_algorithms()
            (only,) = secret_passes("nothing")
            assert only.name == "nothing"
            assert MamoriConfig.from_mapping({"secrets": "nothing"}).secrets == "nothing"
        finally:
            from mamori.infrastructure.detectors import secrets as module

            del module._REGISTRY["nothing"]

    def test_the_default_is_listed_first(self) -> None:
        assert available_secret_algorithms()[0] == DEFAULT_SECRET_ALGORITHM

    def test_a_name_with_a_space_is_refused(self) -> None:
        with pytest.raises(ValueError):
            register_secret_algorithm("two words", lambda: ())
