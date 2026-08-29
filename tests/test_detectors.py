"""Detection rules.

These tests double as the specification of what each rule is meant to catch and
what it is knowingly allowed to miss.
"""

from __future__ import annotations

import pytest

from mamori.domain.normalization import NormalizedText
from mamori.infrastructure.detectors import (
    DEFAULT_RULES,
    NAME_RULES,
    CompositeDetector,
    RegexDetector,
    default_detectors,
    luhn_valid,
    my_number_valid,
)

from .credentials import CREDENTIAL_FIXTURES, FAKE_AWS_KEY

DETECTOR = CompositeDetector("all", list(default_detectors()))


def types_in(text: str) -> set[str]:
    normalized = NormalizedText.of(text)
    return {e.entity_type.name for e in DETECTOR.detect(normalized.text)}


def values_of(text: str, type_name: str) -> set[str]:
    normalized = NormalizedText.of(text)
    return {e.value for e in DETECTOR.detect(normalized.text) if e.entity_type.name == type_name}


class TestChecksums:
    @pytest.mark.parametrize("number", ["4111111111111111", "5500005555555559"])
    def test_luhn_accepts_valid_test_numbers(self, number: str) -> None:
        assert luhn_valid(number)

    @pytest.mark.parametrize("number", ["4111111111111112", "1234567812345678"])
    def test_luhn_rejects_invalid(self, number: str) -> None:
        assert not luhn_valid(number)

    def test_luhn_tolerates_separators(self) -> None:
        assert luhn_valid("4111-1111-1111-1111")

    def test_my_number_check_digit(self) -> None:
        """Generated from the published weighting, then verified by the rule."""
        body = "12345678901"
        total = sum(
            int(body[11 - position]) * (position + 1 if position <= 6 else position - 5)
            for position in range(1, 12)
        )
        remainder = total % 11
        check = 0 if remainder <= 1 else 11 - remainder
        assert my_number_valid(body + str(check))

    def test_my_number_rejects_a_wrong_check_digit(self) -> None:
        assert not my_number_valid("123456789010") or not my_number_valid("123456789011")

    @pytest.mark.parametrize("value", ["12345678901", "1234567890123", "abcdefghijkl"])
    def test_my_number_rejects_wrong_shapes(self, value: str) -> None:
        assert not my_number_valid(value)


class TestContactDetails:
    def test_email(self) -> None:
        assert values_of("連絡は tanaka@example.com まで", "EMAIL") == {"tanaka@example.com"}

    def test_email_written_full_width(self) -> None:
        assert "EMAIL" in types_in("ｔａｎａｋａ＠ｅｘａｍｐｌｅ．ｃｏｍ")

    def test_email_with_a_subdomain_and_plus_tag(self) -> None:
        assert values_of("a.b+tag@mail.corp.example.co.jp", "EMAIL") == {
            "a.b+tag@mail.corp.example.co.jp"
        }

    @pytest.mark.parametrize(
        "phone", ["090-1234-5678", "03-1234-5678", "+81-90-1234-5678", "08012345678"]
    )
    def test_phone_numbers(self, phone: str) -> None:
        assert "PHONE" in types_in(f"電話は{phone}です")

    def test_a_bare_digit_run_is_not_a_phone_number(self) -> None:
        """Deliberate: an unseparated ten-digit run is usually an order number."""
        assert "PHONE" not in types_in("注文番号は0312345678です")

    def test_postal_code_needs_its_marker(self) -> None:
        assert values_of("〒100-0001 東京都", "POSTAL_CODE") == {"100-0001"}
        assert "POSTAL_CODE" not in types_in("品番 100-0001")

    def test_address(self) -> None:
        assert "ADDRESS" in types_in("東京都千代田区千代田1-1")

    def test_date_of_birth_needs_its_label(self) -> None:
        assert values_of("生年月日: 1985-04-01", "DATE_OF_BIRTH") == {"1985-04-01"}
        assert "DATE_OF_BIRTH" not in types_in("納期は 1985-04-01 です")


class TestCredentials:
    @pytest.mark.parametrize("secret", CREDENTIAL_FIXTURES)
    def test_vendor_prefixed_keys(self, secret: str) -> None:
        assert types_in(f"key = {secret}") & {"API_KEY", "ACCESS_TOKEN"}

    def test_private_key_block(self) -> None:
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----"
        assert "PRIVATE_KEY" in types_in(pem)

    def test_database_url(self) -> None:
        assert "DATABASE_URL" in types_in("postgres://user:pw@db.example.com:5432/app")

    def test_password_assignment_redacts_the_value_not_the_keyword(self) -> None:
        assert values_of("password: hunter2xyz", "PASSWORD") == {"hunter2xyz"}

    def test_password_assignment_in_japanese(self) -> None:
        assert values_of("パスワード: hunter2xyz", "PASSWORD") == {"hunter2xyz"}

    def test_secrets_are_found_next_to_japanese_text(self) -> None:
        """Word boundaries do not exist in Japanese, so the rules use lookarounds."""
        assert "API_KEY" in types_in(f"鍵は{FAKE_AWS_KEY}です")


class TestInternalInfrastructure:
    def test_internal_url(self) -> None:
        assert "INTERNAL_URL" in types_in("https://wiki.corp.local/page")

    def test_a_public_url_is_not_flagged_as_internal(self) -> None:
        assert "INTERNAL_URL" not in types_in("https://example.com/page")

    def test_private_ip(self) -> None:
        assert "INTERNAL_IP" in types_in("host 192.168.1.10")

    def test_public_ip_is_left_alone(self) -> None:
        assert "INTERNAL_IP" not in types_in("host 8.8.8.8")

    def test_a_version_string_is_not_an_ip(self) -> None:
        assert "INTERNAL_IP" not in types_in("version 1.2.3")


class TestOrganisations:
    @pytest.mark.parametrize(
        "company", ["株式会社さくら商事", "さくら商事株式会社", "有限会社みどり"]
    )
    def test_japanese_company_forms(self, company: str) -> None:
        assert company in values_of(f"取引先は{company}です", "COMPANY_NAME")

    def test_a_company_name_stops_at_a_particle(self) -> None:
        """Greedy kana would otherwise swallow the rest of the sentence."""
        assert values_of("株式会社さくら商事の田中さん", "COMPANY_NAME") == {"株式会社さくら商事"}

    def test_employee_id_needs_its_label(self) -> None:
        assert values_of("社員番号: A-12345", "EMPLOYEE_ID") == {"A-12345"}


class TestJapaneseNames:
    def test_honorific_anchored_name(self) -> None:
        assert "田中" in values_of("田中さんに連絡", "PERSON")

    def test_the_honorific_itself_is_not_part_of_the_value(self) -> None:
        assert all("さん" not in value for value in values_of("田中さんに連絡", "PERSON"))

    def test_honorific_works_for_a_surname_outside_the_dictionary(self) -> None:
        assert "凪沢" in values_of("凪沢さんに連絡", "PERSON")

    def test_title_as_honorific(self) -> None:
        assert "佐藤" in values_of("佐藤部長にご確認ください", "PERSON")

    def test_dictionary_anchored_full_name(self) -> None:
        assert "田中太郎" in values_of("担当は田中太郎、よろしく", "PERSON")

    def test_a_company_is_not_read_as_a_person(self) -> None:
        assert "PERSON" not in types_in("田中商事に発注しました")

    def test_a_place_is_not_read_as_a_person(self) -> None:
        assert "PERSON" not in types_in("山口県に行きます")

    def test_polite_address_is_not_a_person(self) -> None:
        assert "PERSON" not in types_in("お客様各位")

    def test_katakana_full_name(self) -> None:
        assert "ジョン・スミス" in values_of("ジョン・スミスさん", "PERSON")

    def test_latin_name_after_a_title(self) -> None:
        assert "John Smith" in values_of("Mr. John Smith will attend", "PERSON")


class TestDetectorContract:
    def test_spans_delimit_the_reported_value(self) -> None:
        text = "田中太郎さんへ tanaka@example.com"
        normalized = NormalizedText.of(text)
        for found in DETECTOR.detect(normalized.text):
            assert normalized.text[found.span.start : found.span.end] == found.value

    def test_every_detection_records_its_source(self) -> None:
        normalized = NormalizedText.of("tanaka@example.com")
        assert all(e.source for e in DETECTOR.detect(normalized.text))

    def test_empty_text_yields_nothing(self) -> None:
        assert DETECTOR.detect("") == []

    def test_text_with_nothing_sensitive_yields_nothing(self) -> None:
        assert DETECTOR.detect("The quick brown fox jumps over the lazy dog.") == []

    def test_a_failing_child_detector_propagates(self) -> None:
        class Broken:
            name = "broken"

            def detect(self, text: str) -> list[object]:
                raise RuntimeError("model unavailable")

        composite = CompositeDetector("mixed", [Broken()])  # type: ignore[list-item]
        with pytest.raises(RuntimeError):
            composite.detect("anything")

    def test_rules_are_exposed_for_inspection(self) -> None:
        detector = RegexDetector("regex", DEFAULT_RULES)
        assert len(detector.rules) == len(DEFAULT_RULES)
        assert len(NAME_RULES) >= 4
