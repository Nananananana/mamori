"""Script detection and which language packs it selects.

The case that matters is Chinese and Japanese. They share Han characters, so
without a rule the two surname lists fire on each other's text and every
document comes back full of placeholders standing in for ordinary words.
"""

from __future__ import annotations

import pytest

from mamori import ConfigurationError, MamoriConfig, PrivacySession
from mamori.domain.script import Script, scripts_in
from mamori.domain.stance import Stance
from mamori.infrastructure.detectors import (
    CHINESE,
    ENGLISH,
    JAPANESE,
    AdaptiveLocaleDetector,
    LocalePack,
    available_locales,
    get_locale,
    register_locale,
    resolve_locales,
)

from .helpers import types_in, values_of


class TestScriptDetection:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("hello world", {Script.LATIN}),
            ("こんにちは", {Script.KANA}),
            ("カタカナ", {Script.KANA}),
            ("ﾊﾝｶｸ", {Script.KANA}),
            ("北京云图", {Script.HAN}),
            ("田中さん", {Script.KANA, Script.HAN}),
            ("Contact 田中", {Script.LATIN, Script.HAN}),
            ("안녕하세요", {Script.HANGUL}),
            ("Привет", {Script.CYRILLIC}),
        ],
    )
    def test_scripts_found(self, text: str, expected: set[Script]) -> None:
        assert scripts_in(text) == frozenset(expected)

    def test_digits_and_punctuation_carry_no_signal(self) -> None:
        assert scripts_in("123 456-7890 !?,.") == frozenset()

    def test_empty_text(self) -> None:
        assert scripts_in("") == frozenset()

    def test_full_width_latin_counts_as_latin(self) -> None:
        assert Script.LATIN in scripts_in("ＡＢＣ")

    def test_the_sample_limit_stops_the_scan(self) -> None:
        text = "a" * 100 + "日本語"
        assert scripts_in(text, sample_limit=10) == frozenset({Script.LATIN})


class TestPackSelection:
    def test_kana_stands_the_chinese_pack_down(self) -> None:
        assert not CHINESE.applies_to(frozenset({Script.HAN, Script.KANA}))

    def test_han_alone_runs_both_cjk_packs(self) -> None:
        scripts = frozenset({Script.HAN})
        assert CHINESE.applies_to(scripts)
        assert JAPANESE.applies_to(scripts)

    def test_english_runs_on_latin(self) -> None:
        assert ENGLISH.applies_to(frozenset({Script.LATIN}))

    def test_english_runs_inside_a_japanese_document(self) -> None:
        """Where an English name is most likely to be the thing nobody redacted."""
        assert ENGLISH.applies_to(frozenset({Script.LATIN, Script.KANA, Script.HAN}))

    def test_a_pack_with_no_triggers_always_runs(self) -> None:
        pack = LocalePack(code="x", name="X", rules=())
        assert pack.applies_to(frozenset())

    def test_the_detector_reports_which_packs_it_would_use(self) -> None:
        detector = AdaptiveLocaleDetector([JAPANESE, ENGLISH, CHINESE])
        assert [p.code for p in detector.packs_for("田中さんへ")] == ["ja"]
        assert [p.code for p in detector.packs_for("田中さん / John")] == ["ja", "en"]
        assert [p.code for p in detector.packs_for("北京云图科技")] == ["ja", "zh"]
        assert [p.code for p in detector.packs_for("Hello there")] == ["en"]


class TestCrossLanguageBehaviour:
    def test_japanese_text_is_not_scanned_with_chinese_rules(self) -> None:
        """13812345678 is a Chinese mobile number and nothing in Japanese."""
        with PrivacySession(config=MamoriConfig(stance=Stance.BALANCED)) as session:
            protected = session.protect("受付番号は13812345678です。")
        assert protected.protected_text == "受付番号は13812345678です。"

    def test_a_japanese_document_still_protects_an_english_name(self) -> None:
        with PrivacySession() as session:
            protected = session.protect("担当は Mr. John Smith です。")
        assert "John Smith" not in protected.protected_text

    def test_a_chinese_document_still_protects_an_email(self) -> None:
        with PrivacySession() as session:
            protected = session.protect("邮箱是 zhang@example.com")
        assert "zhang@example.com" not in protected.protected_text

    def test_han_only_text_is_covered_by_both_cjk_packs(self) -> None:
        """No kana to settle it, so both run. Over-detecting is the safe side."""
        assert "PERSON" in types_in("北京云图科技有限公司张伟")

    def test_each_language_round_trips(self) -> None:
        texts = [
            "田中太郎さんへ tanaka@example.com からご連絡がありました。",
            "Dear Jane Doe,\n\nPlease call 415-555-0198.\n\nRegards,\nJohn Smith",
            "张伟先生您好，请拨打 13812345678。",
        ]
        for text in texts:
            with PrivacySession() as session:
                protected = session.protect(text)
                assert session.restore(protected.protected_text).text == text

    def test_one_session_can_hold_three_languages(self) -> None:
        text = "田中太郎さん / Jane Doe / 张伟先生"
        with PrivacySession() as session:
            protected = session.protect(text)
            assert protected.protected_text.count("<PERSON_") >= 2
            assert session.restore(protected.protected_text).text == text


class TestLocaleSelection:
    def test_narrowing_to_one_locale_skips_the_others(self) -> None:
        assert "PHONE" not in types_in("请拨打 13812345678", "ja")
        assert "PHONE" in types_in("请拨打 13812345678", "zh")

    def test_universal_rules_run_whatever_the_locale(self) -> None:
        for locale in ("ja", "en", "zh"):
            assert values_of("mail a@example.com", "EMAIL", locale) == {"a@example.com"}

    def test_a_session_accepts_a_locale_list(self) -> None:
        with PrivacySession(locales=["ja"]) as session:
            protected = session.protect("请拨打 13812345678")
        assert "PHONE" not in {e.entity_type for e in protected.entities}

    def test_a_session_accepts_a_single_locale_string(self) -> None:
        with PrivacySession(locales="en") as session:
            assert session.protect("Dear Jane Doe,").entity_count == 1

    def test_an_unknown_locale_is_refused(self) -> None:
        """Silently ignoring it would leave a language unprotected."""
        with pytest.raises(ConfigurationError, match="unknown locale"):
            PrivacySession(locales=["kl"])

    def test_the_error_lists_what_is_available(self) -> None:
        with pytest.raises(ConfigurationError, match="ja"):
            resolve_locales(["nope"])

    def test_none_means_every_pack(self) -> None:
        assert set(resolve_locales(None)) == set(available_locales())


class TestRegistry:
    def test_builtin_packs_are_registered(self) -> None:
        assert {p.code for p in available_locales()} >= {"ja", "en", "zh"}

    def test_lookup_by_code(self) -> None:
        assert get_locale("ja") is JAPANESE

    def test_unknown_code_returns_none(self) -> None:
        assert get_locale("kl") is None

    def test_a_custom_pack_can_be_registered(self) -> None:
        from mamori.domain import entity_types as t
        from mamori.infrastructure.detectors import compile_rule

        pack = LocalePack(
            code="test-lang",
            name="Test",
            rules=(compile_rule(t.PROJECT_NAME, r"CODENAME-[A-Z]{3}"),),
        )
        register_locale(pack)
        try:
            assert get_locale("test-lang") is pack
            assert "PROJECT_NAME" in types_in("see CODENAME-ABC", "test-lang")
        finally:
            from mamori.infrastructure.detectors import locales

            locales._REGISTRY.pop("test-lang", None)
