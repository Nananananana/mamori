"""The values must not escape through a side channel.

A library that removes a name from the prompt and then writes it to a log file
has moved the leak, not fixed it. These tests grep the actual output of logging,
reprs, exceptions and result objects for the raw values.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Sequence

import pytest

from mamori import PrivacySession
from mamori.application.results import mask_preview
from mamori.domain import entity_types as t
from mamori.domain.confidence import CERTAIN
from mamori.domain.mapping import Mapping
from mamori.domain.placeholder import Placeholder
from mamori.domain.sensitive_entity import SensitiveEntity
from mamori.domain.span import Span
from mamori.errors import PolicyViolationError
from mamori.infrastructure.storage import InMemoryMappingStore

from .credentials import FAKE_AWS_KEY

SECRET_EMAIL = "leaky-canary@example.com"
SECRET_NAME = "田中太郎"
SECRET_KEY = FAKE_AWS_KEY
SAMPLE = f"{SECRET_NAME}さんへ {SECRET_EMAIL} から連絡がありました。"


class TestReprDoesNotLeak:
    def test_sensitive_entity_repr_hides_the_value(self) -> None:
        entity = SensitiveEntity(
            entity_type=t.EMAIL,
            span=Span(0, len(SECRET_EMAIL)),
            value=SECRET_EMAIL,
            confidence=CERTAIN,
            source="test",
        )
        assert SECRET_EMAIL not in repr(entity)
        assert SECRET_EMAIL not in str(entity)
        assert "EMAIL" in repr(entity)

    def test_mapping_repr_hides_the_value(self) -> None:
        mapping = Mapping(
            scope="s",
            placeholder=Placeholder("EMAIL", 1),
            entity_type_name="EMAIL",
            original_value=SECRET_EMAIL,
            identity_key=f"EMAIL:{SECRET_EMAIL}",
        )
        assert SECRET_EMAIL not in repr(mapping)

    def test_entity_report_carries_only_a_masked_preview(self) -> None:
        with PrivacySession() as session:
            result = session.protect(SAMPLE)
        assert result.entities, "nothing was detected, so this checked no report"
        for report in result.entities:
            assert SECRET_EMAIL not in repr(report)
            assert SECRET_NAME not in repr(report)

    def test_protection_result_repr_holds_no_original_values(self) -> None:
        with PrivacySession() as session:
            result = session.protect(SAMPLE)
        assert SECRET_EMAIL not in repr(result)
        assert SECRET_NAME not in repr(result)

    def test_session_repr_holds_no_values(self) -> None:
        with PrivacySession() as session:
            session.protect(SAMPLE)
            assert SECRET_EMAIL not in repr(session)


class TestLoggingDoesNotLeak:
    def test_nothing_is_logged_during_a_round_trip(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG):
            with PrivacySession() as session:
                protected = session.protect(SAMPLE)
                session.restore(protected.protected_text)
        recorded = "\n".join(record.getMessage() for record in caplog.records)
        assert SECRET_EMAIL not in recorded
        assert SECRET_NAME not in recorded

    def test_a_blocked_request_logs_nothing_sensitive(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG), pytest.raises(PolicyViolationError):
            PrivacySession().protect(f"key {SECRET_KEY}")
        assert SECRET_KEY not in "\n".join(r.getMessage() for r in caplog.records)


class TestExceptionsDoNotLeak:
    def test_policy_violation_message_names_types_not_values(self) -> None:
        with pytest.raises(PolicyViolationError) as caught:
            PrivacySession().protect(f"key {SECRET_KEY} for {SECRET_EMAIL}")
        message = str(caught.value)
        assert SECRET_KEY not in message
        assert SECRET_EMAIL not in message
        assert "API_KEY" in message

    def test_a_traceback_through_the_pipeline_holds_no_values(self) -> None:
        class Exploding:
            name = "exploding"

            def detect(self, text: str) -> Sequence[SensitiveEntity]:
                raise RuntimeError("boom")

        session = PrivacySession(detectors=[Exploding()])
        try:
            session.protect(SAMPLE)
        except Exception:
            rendered = traceback.format_exc()
        else:  # pragma: no cover - the detector always raises
            pytest.fail("expected a DetectionError")
        assert SECRET_EMAIL not in rendered
        assert SECRET_NAME not in rendered


class TestOutboundPayload:
    def test_the_protected_text_holds_no_original_value(self) -> None:
        with PrivacySession() as session:
            protected = session.protect(SAMPLE)
        assert SECRET_EMAIL not in protected.protected_text
        assert SECRET_NAME not in protected.protected_text

    def test_the_protected_text_holds_no_part_of_the_mapping(self) -> None:
        """The recipient sees the placeholder, never the pair."""
        store = InMemoryMappingStore()
        with PrivacySession(store=store) as session:
            protected = session.protect(SAMPLE)
            mappings = store.list_scope(session.scope)
            assert mappings, "nothing was allocated, so this checked no mapping"
            for mapping in mappings:
                assert mapping.original_value not in protected.protected_text

    def test_a_detector_failure_yields_no_payload_at_all(self) -> None:
        class Exploding:
            name = "exploding"

            def detect(self, text: str) -> Sequence[SensitiveEntity]:
                raise RuntimeError("boom")

        session = PrivacySession(detectors=[Exploding()])
        with pytest.raises(Exception, match="exploding"):
            session.protect(SAMPLE)


class TestMaskPreview:
    def test_keeps_only_the_first_character(self) -> None:
        assert mask_preview("tanaka@example.com") == "t" + "*" * 17

    def test_short_values_are_fully_masked(self) -> None:
        assert mask_preview("a") == "*"

    def test_empty(self) -> None:
        assert mask_preview("") == ""

    def test_the_preview_never_contains_the_tail_of_the_value(self) -> None:
        preview = mask_preview(SECRET_EMAIL)
        assert "example.com" not in preview


class TestStoreIsolation:
    def test_purge_removes_every_trace_from_the_store(self) -> None:
        store = InMemoryMappingStore()
        session = PrivacySession(store=store)
        protected = session.protect(SAMPLE)
        placeholders = [
            Placeholder.parse(report.placeholder)
            for report in protected.entities
            if report.placeholder
        ]
        assert placeholders

        session.close()

        assert store.list_scope(session.scope) == ()
        for placeholder in placeholders:
            assert placeholder is not None
            assert store.find_by_placeholder(session.scope, placeholder) is None
        assert store.find_by_identity(session.scope, f"EMAIL:{SECRET_EMAIL}") is None

    def test_purging_one_scope_leaves_another_alone(self) -> None:
        store = InMemoryMappingStore()
        keeper = PrivacySession(store=store)
        keeper.protect(SAMPLE)
        doomed = PrivacySession(store=store)
        doomed.protect(SAMPLE)

        doomed.close()

        assert store.list_scope(doomed.scope) == ()
        assert store.list_scope(keeper.scope) != ()
