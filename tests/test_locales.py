"""Script detection and which language packs it selects.

The case that matters is Chinese and Japanese. They share Han characters, so
without a rule the two surname lists fire on each other's text and every
document comes back full of placeholders standing in for ordinary words.
"""

from __future__ import annotations

import itertools

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
        """13812345678 is a Chinese mobile number and nothing in Japanese.

        The framing carries no label on purpose. It used to say 受付番号は,
        which stopped being neutral in 0.14 when that became an identifier
        label -- and the number then *was* detected, correctly, as a reference
        number rather than as a phone. A probe for one behaviour has to avoid
        triggering another.
        """
        with MamoriConfig(stance=Stance.BALANCED).session() as session:
            protected = session.protect("メモに13812345678と書いてありました。")
        assert protected.protected_text == "メモに13812345678と書いてありました。"

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


class TestEvidenceIsLocal:
    """One kana character speaks for its sentence, and not for the document.

    Until 0.18 it spoke for all of it: a payload whose subject line was
    Japanese and whose body was Chinese had the Chinese sent in the clear,
    because the Chinese pack stood down for the whole text. So did any
    bilingual thread, ticket or context package.
    """

    JAPANESE_THEN_CHINESE = (
        '{"subject": "契約更新のご連絡", "body": "关于朱强的事，我会和新程工业集团确认后回复。"}'
    )

    def test_a_chinese_sentence_beside_a_japanese_one(self) -> None:
        with PrivacySession() as session:
            protected = session.protect(self.JAPANESE_THEN_CHINESE).protected_text
        assert "朱强" not in protected
        assert "新程工业集团" not in protected

    def test_the_japanese_sentence_keeps_its_own_rules(self) -> None:
        """And is not reported as Chinese, which is what the suppression was for."""
        with PrivacySession() as session:
            protected = session.protect(self.JAPANESE_THEN_CHINESE).protected_text
        assert "契約更新のご連絡" in protected

    def test_a_sentence_boundary_is_what_separates_them(self) -> None:
        text = "契約更新のご連絡。关于朱强的事。"
        with PrivacySession() as session:
            assert "朱强" not in session.protect(text).protected_text

    def test_a_comma_is_not_a_boundary(self) -> None:
        """本日、会議資料を送付します is one sentence, and the kana at the end
        of it are evidence about the kanji at the start."""
        with MamoriConfig(stance=Stance.BALANCED).session() as session:
            protected = session.protect("本日、会議資料を送付します。").protected_text
        assert protected == "本日、会議資料を送付します。"

    def test_japanese_prose_is_still_free_of_chinese_rules(self) -> None:
        text = "メモに13812345678と書いてありました。"
        with MamoriConfig(stance=Stance.BALANCED).session() as session:
            assert session.protect(text).protected_text == text

    def test_the_regions_are_ordered_and_do_not_overlap(self) -> None:
        from mamori.domain.script import Script, script_regions

        regions = script_regions("あ。x。い。y。う", frozenset({Script.KANA}))
        assert list(regions) == sorted(regions)
        for earlier, later in itertools.pairwise(regions):
            assert earlier[1] <= later[0]

    def test_no_evidence_means_no_regions(self) -> None:
        from mamori.domain.script import Script, script_regions

        assert script_regions("张伟先生", frozenset({Script.KANA})) == ()


class TestAKeyIsALabel:
    """`{"employee_id": "B-12778"}` says what the value is as plainly as a
    sentence does. In four hundred generated agent turns this was the largest
    leak, and it is not a language problem: an API is written in English keys
    whatever language its values are in."""

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            ('{"employee_id": "B-12778"}', "EMPLOYEE_ID"),
            ('{"employeeId": "B-12778"}', "EMPLOYEE_ID"),
            ('{"employee-id": "B-12778"}', "EMPLOYEE_ID"),
            ('{"postal_code": "36099"}', "POSTAL_CODE"),
            ('{"customer": "Jane Doe"}', "PERSON"),
            ('{"attendee": "Jane Doe"}', "PERSON"),
            ('{"company": "Northwind Ltd"}', "COMPANY_NAME"),
            ('{"dob": "1988-10-14"}', "DATE_OF_BIRTH"),
            ('{"社員番号": "A-99"}', "EMPLOYEE_ID"),
            ('{"住所": "東京都港区1-2"}', "ADDRESS"),
            ('{"工号": "B-12778"}', "EMPLOYEE_ID"),
        ],
    )
    def test_the_key_names_the_type(self, payload: str, expected: str) -> None:
        assert expected in types_in(payload)

    def test_a_bare_name_key_is_not_a_person(self) -> None:
        """In JSON it is a tool name, a model name or a field name far more
        often than a person, and redacting the name of the function an agent is
        calling breaks the call."""
        with PrivacySession() as session:
            protected = session.protect('{"name": "send_email", "type": "function"}')
        assert protected.protected_text == '{"name": "send_email", "type": "function"}'

    def test_a_schema_is_not_a_payload(self) -> None:
        schema = '{"type": "object", "properties": {"customer": {"type": "string"}}}'
        with PrivacySession() as session:
            assert session.protect(schema).protected_text == schema

    def test_the_value_keeps_its_quotes(self) -> None:
        """An application parses this. A span that crossed a quote would turn a
        payload into a parse error in somebody else's process."""
        import json

        with PrivacySession() as session:
            protected = session.protect('{"customer": "Jane Doe", "priority": "high"}')
        assert json.loads(protected.protected_text)["priority"] == "high"


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
