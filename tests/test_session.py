"""End-to-end behaviour of a session: protect, restore, and the round trip."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from mamori import PrivacySession
from mamori.domain import entity_types as t
from mamori.domain.confidence import CERTAIN
from mamori.domain.policy import Action, PrivacyPolicy
from mamori.domain.sensitive_entity import SensitiveEntity
from mamori.domain.span import Span
from mamori.errors import DetectionError, PolicyViolationError
from mamori.infrastructure.storage import InMemoryMappingStore

from .credentials import FAKE_AWS_KEY


class StubDetector:
    """Reports a fixed literal wherever it appears."""

    def __init__(self, literal: str, entity_type: object = t.PERSON) -> None:
        self._literal = literal
        self._type = entity_type
        self.name = "stub"

    def detect(self, text: str) -> Sequence[SensitiveEntity]:
        found = []
        start = text.find(self._literal)
        while start != -1:
            found.append(
                SensitiveEntity(
                    entity_type=self._type,  # type: ignore[arg-type]
                    span=Span(start, start + len(self._literal)),
                    value=self._literal,
                    confidence=CERTAIN,
                    source="stub",
                )
            )
            start = text.find(self._literal, start + 1)
        return found


class ExplodingDetector:
    name = "exploding"

    def detect(self, text: str) -> Sequence[SensitiveEntity]:
        raise RuntimeError("model unavailable")


class TestProtect:
    def test_the_original_value_is_gone_from_the_protected_text(self) -> None:
        with PrivacySession() as session:
            result = session.protect("連絡先は tanaka@example.com です")
            assert "tanaka@example.com" not in result.protected_text
            assert "<EMAIL_001>" in result.protected_text

    def test_untouched_text_is_preserved_exactly(self) -> None:
        with PrivacySession() as session:
            result = session.protect("連絡先は tanaka@example.com です")
            assert result.protected_text.startswith("連絡先は ")
            assert result.protected_text.endswith(" です")

    def test_empty_input(self) -> None:
        with PrivacySession() as session:
            result = session.protect("")
            assert result.protected_text == ""
            assert result.entities == ()

    def test_text_with_nothing_sensitive_is_returned_unchanged(self) -> None:
        text = "The quick brown fox jumps over the lazy dog."
        with PrivacySession() as session:
            assert session.protect(text).protected_text == text

    def test_the_same_value_twice_gets_one_placeholder(self) -> None:
        with PrivacySession() as session:
            result = session.protect("田中太郎さんと田中太郎さん")
            assert result.protected_text.count("<PERSON_001>") == 2

    def test_the_same_value_keeps_its_placeholder_across_calls(self) -> None:
        """A conversation must stay coherent from one turn to the next."""
        with PrivacySession() as session:
            first = session.protect("tanaka@example.com に送って")
            second = session.protect("やはり tanaka@example.com は不要")
            assert "<EMAIL_001>" in first.protected_text
            assert "<EMAIL_001>" in second.protected_text

    def test_spacing_variants_of_a_name_share_a_placeholder(self) -> None:
        with PrivacySession(detectors=[StubDetector("田中 太郎")]) as session:
            first = session.protect("田中 太郎さん")
            with_wide_space = session.protect("田中　太郎さん")
        assert "<PERSON_001>" in first.protected_text
        assert "<PERSON_001>" in with_wide_space.protected_text

    def test_different_values_get_different_placeholders(self) -> None:
        with PrivacySession() as session:
            result = session.protect("a@example.com と b@example.com")
            assert "<EMAIL_001>" in result.protected_text
            assert "<EMAIL_002>" in result.protected_text

    def test_two_sessions_do_not_share_placeholders(self) -> None:
        store = InMemoryMappingStore()
        with PrivacySession(store=store) as first, PrivacySession(store=store) as second:
            first.protect("a@example.com")
            result = second.protect("b@example.com")
            assert "<EMAIL_001>" in result.protected_text

    def test_each_report_names_a_type_and_a_placeholder(self) -> None:
        with PrivacySession() as session:
            result = session.protect("tanaka@example.com")
            (report,) = [e for e in result.entities if e.entity_type == "EMAIL"]
            assert report.placeholder == "<EMAIL_001>"
            assert report.action is Action.ANONYMIZE

    def test_counts_by_type(self) -> None:
        with PrivacySession() as session:
            result = session.protect("a@example.com と b@example.com")
            assert result.counts_by_type()["EMAIL"] == 2
            assert result.anonymized_count == 2


class TestFailClosed:
    def test_a_failing_detector_produces_no_protected_text(self) -> None:
        session = PrivacySession(detectors=[ExplodingDetector()])
        with pytest.raises(DetectionError) as caught:
            session.protect("田中太郎さん")
        assert caught.value.detector == "exploding"

    def test_a_credential_stops_the_request(self) -> None:
        session = PrivacySession()
        with pytest.raises(PolicyViolationError):
            session.protect(f"APIキーは {FAKE_AWS_KEY} です")

    def test_a_blocked_request_names_the_type_but_not_the_value(self) -> None:
        session = PrivacySession()
        with pytest.raises(PolicyViolationError) as caught:
            session.protect(f"key {FAKE_AWS_KEY}")
        assert "API_KEY" in str(caught.value)
        assert FAKE_AWS_KEY not in str(caught.value)

    def test_an_unrecognised_type_is_blocked_by_default(self) -> None:
        from mamori.domain.entity_types import EntityType

        unknown = EntityType("SOMETHING_NEW")
        session = PrivacySession(detectors=[StubDetector("secret-ish", unknown)])
        with pytest.raises(PolicyViolationError):
            session.protect("this is secret-ish text")

    def test_nothing_is_stored_when_the_policy_blocks(self) -> None:
        store = InMemoryMappingStore()
        session = PrivacySession(store=store)
        with pytest.raises(PolicyViolationError):
            session.protect(f"tanaka@example.com key {FAKE_AWS_KEY}")
        assert store.list_scope(session.scope) == ()


class TestActions:
    def test_allow_leaves_the_value_in_place(self) -> None:
        policy = PrivacyPolicy.permissive().with_rule("EMAIL", Action.ALLOW)
        with PrivacySession(policy=policy) as session:
            result = session.protect("mail tanaka@example.com")
            assert "tanaka@example.com" in result.protected_text

    def test_mask_replaces_without_a_mapping(self) -> None:
        policy = PrivacyPolicy.permissive().with_rule("EMAIL", Action.MASK)
        with PrivacySession(policy=policy) as session:
            result = session.protect("mail tanaka@example.com")
            assert "[REDACTED]" in result.protected_text
            assert session.restore(result.protected_text).restored == ()


class TestRestore:
    def test_round_trip(self) -> None:
        text = "田中太郎さんへ tanaka@example.com からメールが届きました。"
        with PrivacySession() as session:
            protected = session.protect(text)
            assert session.restore(protected.protected_text).text == text

    def test_a_reply_that_only_mentions_some_placeholders(self) -> None:
        with PrivacySession() as session:
            session.protect("田中太郎さんと tanaka@example.com")
            restored = session.restore("<PERSON_001>さんに連絡します")
            assert restored.text == "田中太郎さんに連絡します"
            assert len(restored.missing) == 1

    def test_a_reply_with_no_placeholders_comes_back_unchanged(self) -> None:
        with PrivacySession() as session:
            session.protect("tanaka@example.com")
            assert session.restore("承知しました。").text == "承知しました。"

    def test_altered_placeholders_are_recovered_and_reported(self) -> None:
        with PrivacySession() as session:
            session.protect("田中太郎さんへ tanaka@example.com")
            restored = session.restore("PERSON_1 and <EMAIL_1>")
            assert restored.text == "田中太郎 and tanaka@example.com"
            assert len(restored.tampered) == 2

    def test_a_placeholder_the_model_invented_is_not_resolved(self) -> None:
        with PrivacySession() as session:
            session.protect("田中太郎さん")
            restored = session.restore("<PERSON_001> と <PERSON_042> です")
            assert "田中太郎" in restored.text
            assert "<PERSON_042>" in restored.text
            assert restored.unknown == ("<PERSON_042>",)
            assert restored.is_clean is False

    def test_a_response_cannot_read_another_scope(self) -> None:
        store = InMemoryMappingStore()
        with PrivacySession(store=store) as owner, PrivacySession(store=store) as other:
            owner.protect("tanaka@example.com")
            restored = other.restore("<EMAIL_001>")
            assert "tanaka@example.com" not in restored.text
            assert restored.unknown == ("<EMAIL_001>",)

    def test_empty_response(self) -> None:
        with PrivacySession() as session:
            session.protect("tanaka@example.com")
            assert session.restore("").text == ""


class TestNormalizationRoundTrip:
    """What goes back must be what was taken out, not its normalized form."""

    def test_a_full_width_email_is_restored_exactly_as_written(self) -> None:
        text = "連絡先は ｔａｎａｋａ＠ｅｘａｍｐｌｅ．ｃｏｍ です"
        with PrivacySession() as session:
            protected = session.protect(text)
            assert "<EMAIL_001>" in protected.protected_text
            assert session.restore(protected.protected_text).text == text

    def test_a_ligature_inside_a_match_is_restored_unchanged(self) -> None:
        """NFKC expands Ĳ to IJ, so the normalized value is one char longer."""
        text = "mail 0@a.example.comĲ now"
        with PrivacySession() as session:
            protected = session.protect(text)
            assert session.restore(protected.protected_text).text == text

    def test_a_company_written_with_the_ligature_character(self) -> None:
        text = "取引先は㍿さくら商事です"
        with PrivacySession() as session:
            protected = session.protect(text)
            assert session.restore(protected.protected_text).text == text

    def test_a_full_width_and_half_width_email_share_one_placeholder(self) -> None:
        with PrivacySession() as session:
            first = session.protect("ｔａｎａｋａ＠ｅｘａｍｐｌｅ．ｃｏｍ")
            second = session.protect("tanaka@example.com")
        assert "<EMAIL_001>" in first.protected_text
        assert "<EMAIL_001>" in second.protected_text


class TestPlaceholderCollision:
    """Input that already looks like a placeholder must not confuse restoration."""

    def test_a_placeholder_shaped_input_is_itself_replaced(self) -> None:
        with PrivacySession() as session:
            protected = session.protect("The token <PERSON_001> is literal.")
            assert "<PERSON_001>" not in protected.protected_text
            assert "<TEXT_001>" in protected.protected_text

    def test_a_literal_placeholder_survives_the_round_trip(self) -> None:
        text = "The token <PERSON_001> is literal."
        with PrivacySession() as session:
            protected = session.protect(text)
            assert session.restore(protected.protected_text).text == text

    def test_a_literal_placeholder_cannot_borrow_a_real_value(self) -> None:
        """Without escaping, this input would restore to 田中太郎."""
        with PrivacySession() as session:
            session.protect("田中太郎さんへ")
            protected = session.protect("Quote this exactly: <PERSON_001>")
            restored = session.restore(protected.protected_text)
            assert restored.text == "Quote this exactly: <PERSON_001>"


class TestSessionLifecycle:
    def test_close_discards_the_mappings(self) -> None:
        store = InMemoryMappingStore()
        session = PrivacySession(store=store)
        session.protect("tanaka@example.com")
        session.close()
        assert store.list_scope(session.scope) == ()

    def test_leaving_the_context_discards_the_mappings(self) -> None:
        store = InMemoryMappingStore()
        with PrivacySession(store=store) as session:
            session.protect("tanaka@example.com")
            scope = session.scope
        assert store.list_scope(scope) == ()

    def test_sessions_get_distinct_scopes(self) -> None:
        assert PrivacySession().scope != PrivacySession().scope

    def test_an_explicit_scope_is_honoured(self) -> None:
        assert PrivacySession(scope="conversation-7").scope == "conversation-7"
