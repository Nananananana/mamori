"""The recall/precision dial, and the wide rules it turns on.

The wide tier is where the library accepts false positives on purpose. Each
test here names both halves of the trade: what the rule now finds, and what it
now also flags.
"""

from __future__ import annotations

import pytest

from mamori import MamoriConfig, PrivacySession
from mamori.domain.stance import RuleTier, Stance
from mamori.infrastructure.detectors import UNIVERSAL_RULES, rules_for
from mamori.infrastructure.detectors.locales import CHINESE, ENGLISH, JAPANESE

from .helpers import types_in, values_of

WIDE = Stance.RECALL_FIRST
CORE = Stance.BALANCED


def wide_types(text: str, locale: str | None = None) -> set[str]:
    return types_in(text, locale, WIDE)


def wide_values(text: str, type_name: str, locale: str | None = None) -> set[str]:
    return values_of(text, type_name, locale, WIDE)


class TestStance:
    def test_balanced_runs_core_only(self) -> None:
        assert CORE.includes(RuleTier.CORE)
        assert not CORE.includes(RuleTier.WIDE)

    def test_recall_first_runs_everything(self) -> None:
        assert WIDE.includes(RuleTier.CORE)
        assert WIDE.includes(RuleTier.WIDE)

    def test_filtering_keeps_the_core_rules(self) -> None:
        core = rules_for(UNIVERSAL_RULES, CORE)
        assert all(rule.tier is RuleTier.CORE for rule in core)
        assert len(core) < len(UNIVERSAL_RULES)

    def test_filtering_at_recall_first_keeps_everything(self) -> None:
        assert len(rules_for(UNIVERSAL_RULES, WIDE)) == len(UNIVERSAL_RULES)

    @pytest.mark.parametrize("pack", [JAPANESE, ENGLISH, CHINESE])
    def test_every_pack_has_both_tiers(self, pack: object) -> None:
        tiers = {rule.tier for rule in pack.rules}  # type: ignore[attr-defined]
        assert tiers == {RuleTier.CORE, RuleTier.WIDE}

    def test_the_shipping_default_is_recall_first(self) -> None:
        assert MamoriConfig().stance is WIDE


class TestWideUniversalRules:
    def test_a_long_random_looking_token_is_flagged(self) -> None:
        """The documented gap: a credential with no vendor prefix."""
        secret = "Kx7pQz2mNv8Ld4Rt9Wy3Bc6Hj1Fs5Gk0Zn"
        assert "API_KEY" in wide_types(f"key = {secret}")
        assert "API_KEY" not in types_in(f"key = {secret}")

    def test_a_base64_payload_is_also_flagged(self) -> None:
        """The cost of the rule above, stated rather than hidden."""
        assert "API_KEY" in wide_types("data = Kx7pQz2mNv8Ld4Rt9Wy3Bc6Hj1Fs5Gk0Zn")

    def test_lowercase_prose_is_not_a_secret(self) -> None:
        assert "API_KEY" not in wide_types("thequickbrownfoxjumpsoverthelazydogandruns")

    def test_a_long_digit_run_becomes_an_identifier(self) -> None:
        assert "IDENTIFIER" in wide_types("reference 900123456789")
        assert "IDENTIFIER" not in types_in("reference 900123456789")

    def test_a_short_digit_run_is_left_alone(self) -> None:
        assert "IDENTIFIER" not in wide_types("item 4021")


class TestWideEnglishRules:
    def test_an_unanchored_name_is_now_found(self) -> None:
        """The largest documented gap in the library."""
        assert "PERSON" in wide_types("I spoke to Jane Doe yesterday", "en")
        assert "PERSON" not in types_in("I spoke to Jane Doe yesterday", "en")

    def test_a_heading_is_not_a_person(self) -> None:
        assert "PERSON" not in wide_types("The Quarterly Business Review is Monday", "en")

    def test_a_labelled_phrase_is_not_a_person(self) -> None:
        assert "PERSON" not in wide_types("Social Security Number is required", "en")

    def test_bare_ten_digits_become_a_phone_number(self) -> None:
        assert "PHONE" in wide_types("call 4155550198", "en")

    def test_bare_nine_digits_become_an_ssn(self) -> None:
        assert "SSN" in wide_types("id 123456789", "en")

    def test_a_state_and_zip_are_found(self) -> None:
        assert wide_values("Springfield, IL 62704", "POSTAL_CODE", "en") == {"62704"}


class TestKatakanaNeedsAnAnchor:
    """Removed from the wide tier in 0.9, after measuring what it cost.

    A bare run of katakana used to be a wide-tier PERSON, filtered by a
    stoplist of loanwords. Eight Japanese documents produced 37 false
    positives from it -- ホスト, プール, ゲートウェイ, ノード -- and no true
    positive the anchored rules did not already have. The list could not have
    been fixed by adding words: Japanese business writing coins loanwords
    faster than anybody maintains a list, so such a list encodes one author's
    vocabulary and is wrong for the next document.

    A bare katakana run is not weak evidence of a name. It is no evidence of
    one, and the wide tier is for weak evidence rather than for none.
    """

    def test_a_bare_katakana_run_is_not_a_person_at_any_stance(self) -> None:
        assert "PERSON" not in wide_types("スミスに確認してください", "ja")

    def test_a_loanword_is_certainly_not(self) -> None:
        assert "PERSON" not in wide_types("バージョンをアップデートしました", "ja")

    def test_technical_vocabulary_survives_a_whole_document(self) -> None:
        text = "ポッドはプールに接続し、ゲートウェイのタイムアウトを待つ。ノードは12台。"
        assert "PERSON" not in wide_types(text, "ja")

    def test_an_honorific_still_anchors_one(self) -> None:
        """What replaced it: evidence, not a word list."""
        from mamori import MamoriConfig
        from mamori.domain.stance import Stance

        with MamoriConfig(stance=Stance.BALANCED, locales=("ja",)).session() as session:
            protected = session.protect("ジョンさんに確認してください").protected_text
        assert "ジョン" not in protected

    def test_a_label_anchors_one(self) -> None:
        from mamori import MamoriConfig
        from mamori.domain.stance import Stance

        with MamoriConfig(stance=Stance.BALANCED, locales=("ja",)).session() as session:
            protected = session.protect("担当: マイケル").protected_text
        assert "マイケル" not in protected

    def test_a_middle_dot_anchors_one(self) -> None:
        from mamori import MamoriConfig
        from mamori.domain.stance import Stance

        with MamoriConfig(stance=Stance.BALANCED, locales=("ja",)).session() as session:
            protected = session.protect("ジョン・スミスさんが来社されます").protected_text
        assert "スミス" not in protected

    def test_an_unseparated_phone_number_is_now_found(self) -> None:
        assert "PHONE" in wide_types("電話は09012345678です", "ja")

    def test_a_postal_code_without_its_marker_is_now_found(self) -> None:
        assert "POSTAL_CODE" in wide_types("住所 100-0001 東京", "ja")

    def test_an_organisation_name_is_now_read_as_a_person_too(self) -> None:
        """The stated cost: the wide rule drops the organisation guard."""
        assert "PERSON" in wide_types("田中商事に発注しました", "ja")


class TestWideChineseRules:
    def test_the_stoplist_is_dropped(self) -> None:
        """高兴 is 'happy'. Under recall-first it is reported anyway."""
        assert "PERSON" in wide_types("收到消息我很高兴", "zh")
        assert "PERSON" not in types_in("收到消息我很高兴", "zh")

    def test_a_weekday_is_the_one_thing_it_still_refuses(self) -> None:
        """The exception to the rule above, and the only one.

        高兴 stays because somebody really could be called that. 周四 goes
        because 周 is a common surname, the weekdays are a closed set nobody
        extends, and no calendar day is anybody's name. Fifty-three spurious
        detections in a thousand generated documents came from this word class.
        """
        assert "PERSON" not in wide_types("时间: 周四 14:00", "zh")
        assert "PERSON" in wide_types("收到消息我很高兴", "zh")

    def test_bare_six_digits_become_a_postcode(self) -> None:
        assert "POSTAL_CODE" in wide_types("编号 100081", "zh")


class TestEndToEnd:
    def test_the_stance_reaches_a_session(self) -> None:
        text = "I spoke to Jane Doe yesterday."
        with MamoriConfig(stance=CORE).session() as session:
            assert "Jane Doe" in session.protect(text).protected_text
        with PrivacySession() as session:
            assert "Jane Doe" not in session.protect(text).protected_text

    def test_the_round_trip_still_holds_under_the_wide_stance(self) -> None:
        text = "I spoke to Jane Doe about 900123456789 and スミス."
        with PrivacySession() as session:
            protected = session.protect(text)
            assert session.restore(protected.protected_text).text == text

    def test_wide_detections_are_low_confidence(self) -> None:
        """So a confidence floor can switch them off without switching stance."""
        with PrivacySession() as session:
            entities = session.protect("I spoke to Jane Doe yesterday.").entities
        assert all(e.confidence <= 0.5 for e in entities if e.entity_type == "PERSON")

    def test_a_confidence_floor_can_undo_the_wide_tier(self) -> None:
        settings = MamoriConfig(min_confidence=0.6)
        with settings.session() as session:
            assert "Jane Doe" in session.protect("I spoke to Jane Doe yesterday.").protected_text
