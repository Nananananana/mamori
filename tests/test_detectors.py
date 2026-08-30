"""Universal and Japanese detection rules.

These tests double as the specification of what each rule is meant to catch and
what it is knowingly allowed to miss. English and Chinese live in their own
modules; cross-language behaviour lives in ``test_locales.py``.
"""

from __future__ import annotations

import pytest

from mamori.domain.normalization import NormalizedText
from mamori.infrastructure.detectors import (
    JAPANESE,
    UNIVERSAL_RULES,
    CompositeDetector,
    RegexDetector,
    luhn_valid,
)
from mamori.infrastructure.detectors.locales.ja import my_number_valid

from .credentials import CREDENTIAL_FIXTURES, FAKE_AWS_KEY
from .helpers import detector_for, types_in, values_of

LOCALE = "ja"


def ja_types(text: str) -> set[str]:
    return types_in(text, LOCALE)


def ja_values(text: str, type_name: str) -> set[str]:
    return values_of(text, type_name, LOCALE)


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
        assert ja_values("連絡は tanaka@example.com まで", "EMAIL") == {"tanaka@example.com"}

    def test_email_written_full_width(self) -> None:
        assert "EMAIL" in ja_types("ｔａｎａｋａ＠ｅｘａｍｐｌｅ．ｃｏｍ")

    def test_email_with_a_subdomain_and_plus_tag(self) -> None:
        assert ja_values("a.b+tag@mail.corp.example.co.jp", "EMAIL") == {
            "a.b+tag@mail.corp.example.co.jp"
        }

    @pytest.mark.parametrize(
        "phone", ["090-1234-5678", "03-1234-5678", "+81-90-1234-5678", "08012345678"]
    )
    def test_phone_numbers(self, phone: str) -> None:
        assert "PHONE" in ja_types(f"電話は{phone}です")

    def test_a_bare_digit_run_is_not_a_phone_number(self) -> None:
        """Deliberate: an unseparated ten-digit run is usually an order number."""
        assert "PHONE" not in ja_types("注文番号は0312345678です")

    def test_postal_code_needs_its_marker(self) -> None:
        assert ja_values("〒100-0001 東京都", "POSTAL_CODE") == {"100-0001"}
        assert "POSTAL_CODE" not in ja_types("品番 100-0001")

    def test_address(self) -> None:
        assert "ADDRESS" in ja_types("東京都千代田区千代田1-1")

    def test_date_of_birth_needs_its_label(self) -> None:
        assert ja_values("生年月日: 1985-04-01", "DATE_OF_BIRTH") == {"1985-04-01"}
        assert "DATE_OF_BIRTH" not in ja_types("納期は 1985-04-01 です")


class TestCredentials:
    @pytest.mark.parametrize("secret", CREDENTIAL_FIXTURES)
    def test_vendor_prefixed_keys(self, secret: str) -> None:
        assert ja_types(f"key = {secret}") & {"API_KEY", "ACCESS_TOKEN"}

    def test_private_key_block(self) -> None:
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----"
        assert "PRIVATE_KEY" in ja_types(pem)

    def test_database_url(self) -> None:
        assert "DATABASE_URL" in ja_types("postgres://user:pw@db.example.com:5432/app")

    def test_password_assignment_redacts_the_value_not_the_keyword(self) -> None:
        assert ja_values("password: hunter2xyz", "PASSWORD") == {"hunter2xyz"}

    def test_password_assignment_in_japanese(self) -> None:
        assert ja_values("パスワード: hunter2xyz", "PASSWORD") == {"hunter2xyz"}

    def test_secrets_are_found_next_to_japanese_text(self) -> None:
        """Word boundaries do not exist in Japanese, so the rules use lookarounds."""
        assert "API_KEY" in ja_types(f"鍵は{FAKE_AWS_KEY}です")


class TestInternalInfrastructure:
    def test_internal_url(self) -> None:
        assert "INTERNAL_URL" in ja_types("https://wiki.corp.local/page")

    def test_a_public_url_is_not_flagged_as_internal(self) -> None:
        assert "INTERNAL_URL" not in ja_types("https://example.com/page")

    def test_private_ip(self) -> None:
        assert "INTERNAL_IP" in ja_types("host 192.168.1.10")

    def test_public_ip_is_left_alone(self) -> None:
        assert "INTERNAL_IP" not in ja_types("host 8.8.8.8")

    def test_a_version_string_is_not_an_ip(self) -> None:
        assert "INTERNAL_IP" not in ja_types("version 1.2.3")


class TestOrganisations:
    @pytest.mark.parametrize(
        "company", ["株式会社さくら商事", "さくら商事株式会社", "有限会社みどり"]
    )
    def test_japanese_company_forms(self, company: str) -> None:
        assert company in ja_values(f"取引先は{company}です", "COMPANY_NAME")

    def test_a_company_name_stops_at_a_particle(self) -> None:
        """Greedy kana would otherwise swallow the rest of the sentence."""
        assert ja_values("株式会社さくら商事の田中さん", "COMPANY_NAME") == {"株式会社さくら商事"}

    def test_employee_id_needs_its_label(self) -> None:
        assert ja_values("社員番号: A-12345", "EMPLOYEE_ID") == {"A-12345"}


class TestJapaneseNames:
    def test_honorific_anchored_name(self) -> None:
        assert "田中" in ja_values("田中さんに連絡", "PERSON")

    def test_the_honorific_itself_is_not_part_of_the_value(self) -> None:
        assert all("さん" not in value for value in ja_values("田中さんに連絡", "PERSON"))

    def test_honorific_works_for_a_surname_outside_the_dictionary(self) -> None:
        assert "凪沢" in ja_values("凪沢さんに連絡", "PERSON")

    def test_title_as_honorific(self) -> None:
        assert "佐藤" in ja_values("佐藤部長にご確認ください", "PERSON")

    def test_dictionary_anchored_full_name(self) -> None:
        assert "田中太郎" in ja_values("担当は田中太郎、よろしく", "PERSON")

    def test_a_company_is_not_read_as_a_person(self) -> None:
        assert "PERSON" not in ja_types("田中商事に発注しました")

    def test_a_place_is_not_read_as_a_person(self) -> None:
        assert "PERSON" not in ja_types("山口県に行きます")

    def test_polite_address_is_not_a_person(self) -> None:
        assert "PERSON" not in ja_types("お客様各位")

    def test_katakana_full_name(self) -> None:
        assert "ジョン・スミス" in ja_values("ジョン・スミスさん", "PERSON")


DETECTOR = detector_for(LOCALE)


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
        detector = RegexDetector("universal", UNIVERSAL_RULES)
        assert len(detector.rules) == len(UNIVERSAL_RULES)
        assert len(JAPANESE.rules) >= 8


class TestAnAddressHeldApart:
    """`jane.doe @ example.com`, which 0.25 found as the last leak class in
    English: 22 of 300 adversarially written documents."""

    def test_it_is_found(self) -> None:
        assert "EMAIL" in types_in("Sent to jane.doe @ example.co.jp this morning.")

    @pytest.mark.parametrize(
        "text",
        [
            "write to us @ the office tomorrow",
            "meet @ 3pm at the cafe",
            "follow @example on the site",
        ],
    )
    def test_an_at_sign_alone_is_not_an_address(self, text: str) -> None:
        assert "EMAIL" not in types_in(text)

    def test_it_does_not_reach_across_a_line(self) -> None:
        assert "EMAIL" not in types_in("ends here jane\n@ example.com")


class TestAOneCharacterSurnameOnItsOwn:
    """林, 森, 原, 岡 are surnames. They are also a wood, a forest, a cause and
    a hill, and with no given name the noun is commoner than the person.

    0.25 made a given name required for those four. What a name still has, when
    it is one, is an honorific, a label, or a given name of its own -- and
    27 spurious detections in three hundred adversarial documents went away.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "林の手入れは来月です",
            "森の手前で道が細くなります",
            "岡の上に建てる予定です",
        ],
    )
    def test_a_bare_one_character_surname_is_not_a_person(self, text: str) -> None:
        assert "PERSON" not in ja_types(text)

    @pytest.mark.parametrize(
        ("text", "name"),
        [
            ("森さんに確認します", "森"),
            ("担当: 森", "森"),
            ("森健太が対応します", "森健太"),
            ("林部長にご相談ください", "林"),
        ],
    )
    def test_an_anchor_or_a_given_name_still_finds_it(self, text: str, name: str) -> None:
        assert name in ja_values(text, "PERSON")

    def test_a_two_character_surname_still_stands_alone(self) -> None:
        """田中の資料 is about a person, and 田中 is unambiguous in a way that
        森 is not."""
        assert "田中" in ja_values("田中の資料を見ました", "PERSON")


class TestATradingNameWithNoLegalForm:
    """田中商事, さくら製作所 -- how a Japanese company is written in a sentence.

    A documented gap since 0.9, and hidden until 0.25 by an accident: the wide
    tier read 田中商事 as a person, the span overlapped the COMPANY_NAME label,
    and the evaluation counted the company as covered. An over-detection can
    stand in front of a miss.
    """

    @pytest.mark.parametrize(
        ("text", "company"),
        [
            ("田中商事への発注は完了しています。", "田中商事"),
            ("さくら製作所と契約しました", "さくら製作所"),
            ("あおい技研の担当者に確認します", "あおい技研"),
        ],
    )
    def test_it_is_found(self, text: str, company: str) -> None:
        assert company in ja_values(text, "COMPANY_NAME")

    @pytest.mark.parametrize("text", ["商事部門の予算", "製作所の見学に行きます"])
    def test_the_suffix_alone_is_not_a_company(self, text: str) -> None:
        assert "COMPANY_NAME" not in ja_types(text)

    def test_it_is_not_also_a_person(self) -> None:
        """The whole point: the person reading was the bug."""
        assert "PERSON" not in ja_types("田中商事への発注は完了しています。")
