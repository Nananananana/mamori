"""Plausible values instead of tokens.

The most dangerous option in the library, and the tests are shaped by that. An
unrestored placeholder is obvious; an unrestored surrogate is a readable
sentence about the wrong person. Most of this file is about the ways that can
happen and what mamori does to narrow them.
"""

from __future__ import annotations

import pytest

from mamori import MamoriConfig, PrivacySession
from mamori.domain.surrogate import (
    SURROGATE_POOLS,
    pool_for,
    supported_types,
    surrogate_for,
)
from mamori.errors import ConfigurationError, PolicyViolationError
from mamori.report import build_report

from .credentials import FAKE_AWS_KEY

JA = "田中太郎さんへ。tanaka@example.com か 090-1234-5678 までご返信ください。"
EN = "Dear Jane Doe, reach me at jane.doe@example.com or 415-555-0198."


def surrogate_config(*types: str) -> MamoriConfig:
    return MamoriConfig(surrogates=list(types) if types else True)


class TestOffByDefault:
    """Nothing changes for anybody who does not ask."""

    def test_the_default_is_tokens(self) -> None:
        with MamoriConfig().session() as session:
            assert "<PERSON_001>" in session.protect(EN).protected_text

    def test_the_default_config_lists_no_types(self) -> None:
        assert MamoriConfig().surrogate_types() == frozenset()

    def test_a_mapping_has_no_surface_by_default(self) -> None:
        from mamori.domain.mapping import Mapping
        from mamori.domain.placeholder import Placeholder

        mapping = Mapping("s", Placeholder("PERSON", 1), "PERSON", "x")
        assert mapping.surface == ""
        assert mapping.substituted == "<PERSON_001>"
        assert not mapping.is_surrogate


class TestSubstitution:
    def test_a_name_becomes_a_name(self) -> None:
        with surrogate_config("PERSON").session() as session:
            protected = session.protect(EN).protected_text
        assert "Jane Doe" not in protected
        assert "<PERSON" not in protected, "a token would defeat the point"

    def test_the_language_of_the_text_decides_the_pool(self) -> None:
        with surrogate_config("PERSON").session() as session:
            protected = session.protect(JA).protected_text
        assert "田中太郎" not in protected
        japanese = pool_for("PERSON", "ja")
        assert japanese is not None
        assert any(name in protected for name in japanese.values)

    def test_only_the_types_asked_for_are_substituted(self) -> None:
        with surrogate_config("PERSON").session() as session:
            protected = session.protect(EN).protected_text
        assert "<EMAIL_001>" in protected, "EMAIL was not asked for"

    def test_a_type_with_no_pool_stays_a_token(self) -> None:
        with surrogate_config().session() as session:
            protected = session.protect("マイナンバーは123456789018です").protected_text
        assert "MY_NUMBER" in protected

    def test_the_same_value_keeps_the_same_surrogate(self) -> None:
        """Otherwise a model cannot tell two mentions are one person."""
        text = "Dear Jane Doe, please tell Jane Doe that Jane Doe is expected."
        with surrogate_config("PERSON").session() as session:
            protected = session.protect(text).protected_text
        names = {
            word
            for word in protected.split()
            if word.rstrip(",.") not in {"Dear", "please", "tell", "that", "is", "expected"}
        }
        assert "Jane" not in protected
        assert protected.count(protected.split()[1].rstrip(",")) >= 2
        del names

    def test_two_people_get_two_surrogates(self) -> None:
        with surrogate_config("PERSON").session() as session:
            protected = session.protect("Dear Jane Doe, Mr. John Smith called.").protected_text
        pool = pool_for("PERSON", "en")
        assert pool is not None
        assert len([v for v in pool.values if v in protected]) == 2


class TestRoundTrip:
    @pytest.mark.parametrize("text", [EN, JA])
    def test_the_original_comes_back(self, text: str) -> None:
        with surrogate_config().session() as session:
            protected = session.protect(text).protected_text
            assert session.restore(protected).text == text

    def test_it_survives_the_model_rewriting_around_it(self) -> None:
        with surrogate_config().session() as session:
            protected = session.protect(JA).protected_text
            reply = protected.replace("さんへ", "様へ")
            assert "田中太郎様へ" in session.restore(reply).text

    def test_a_rewritten_surrogate_is_reported_as_missing(self) -> None:
        """The failure this feature cannot avoid, made detectable.

        A placeholder is recognised by shape, so a mangled one still restores.
        A surrogate is a name: it matches or it does not. What mamori can do is
        say so, and `missing` is where it says it.
        """
        with surrogate_config("PERSON").session() as session:
            result = session.protect(EN)
            surrogate = next(
                v
                for v in getattr(pool_for("PERSON", "en"), "values", ())
                if v in result.protected_text
            )
            mangled = result.protected_text.replace(surrogate, surrogate.split()[0])
            answer = session.restore(mangled)
        assert answer.missing, "an unrestored surrogate must not be silent"
        assert answer.missing[0].entity_type_name == "PERSON"

    def test_a_clean_round_trip_reports_nothing_missing(self) -> None:
        with surrogate_config().session() as session:
            protected = session.protect(EN).protected_text
            assert session.restore(protected).missing == ()


class TestWhatAModelDoesToAName:
    """A surrogate has no shape, so restoration finds it by looking for it.

    Two liberties are taken with *how* it looks, both for the same reason: a
    surrogate that is not put back is a plausible sentence about a person who
    does not exist, and nobody notices. A corpus of 1200 surrogate replies puts
    the two at 17% and 11% of the losses.
    """

    def stand_in(self) -> str:
        pool = pool_for("PERSON", "en")
        assert pool is not None
        return pool.values[0]

    def restored(self, written: str) -> str:
        """Protect a name, then restore a reply that wrote the stand-in thus."""
        with surrogate_config("PERSON").session() as session:
            result = session.protect("Dear Jane Doe, hello.")
            assert self.stand_in() in result.protected_text
            return session.restore(f"I met {written} today.").text

    def test_it_is_put_back_when_quoted_exactly(self) -> None:
        assert "Jane Doe" in self.restored(self.stand_in())

    def test_case_is_folded(self) -> None:
        """`alex rivera` is the same stand-in, written carelessly."""
        assert "Jane Doe" in self.restored(self.stand_in().lower())
        assert "Jane Doe" in self.restored(self.stand_in().upper())

    def test_a_name_wrapped_across_a_line_is_put_back(self) -> None:
        assert "Jane Doe" in self.restored(self.stand_in().replace(" ", "\n", 1))

    def test_it_does_not_reach_across_a_blank_line(self) -> None:
        """One line break, not a paragraph. Otherwise two unrelated words at
        the end and the start of adjacent paragraphs become somebody's name."""
        assert "Jane Doe" not in self.restored(self.stand_in().replace(" ", "\n\n", 1))

    def test_half_a_name_restores_nothing_and_is_reported(self) -> None:
        """The cost of the option, and the whole of the mitigation: the caller
        is told which placeholder did not come back."""
        half = self.stand_in().split()[0]
        with surrogate_config("PERSON").session() as session:
            session.protect("Dear Jane Doe, hello.")
            answer = session.restore(f"I met {half} today.")
        assert "Jane Doe" not in answer.text
        assert [p.token for p in answer.missing] == ["<PERSON_001>"]

    def test_an_honorific_or_a_possessive_does_not_stop_it(self) -> None:
        assert "Jane Doe" in self.restored(self.stand_in() + "'s report")
        assert "Jane Doe" in self.restored("Mr " + self.stand_in())


class TestTheHazards:
    def test_a_surrogate_never_collides_with_text_already_there(self) -> None:
        """Restoring the wrong occurrence would corrupt the caller's words."""
        pool = pool_for("PERSON", "en")
        assert pool is not None
        text = f"Dear Jane Doe, and {pool.values[0]} is copied."
        with surrogate_config("PERSON").session() as session:
            result = session.protect(text)
            assert session.restore(result.protected_text).text == text

    def test_choosing_avoids_what_is_already_taken(self) -> None:
        pool = pool_for("PERSON", "en")
        assert pool is not None
        assert surrogate_for("PERSON", 1, locale="en", avoid=[pool.values[0]]) != pool.values[0]

    def test_an_exhausted_pool_falls_back_to_tokens(self) -> None:
        """A token is always safe, so running out is not a failure."""
        pool = pool_for("PERSON", "en")
        assert pool is not None
        names = [
            "Jane Doe",
            "John Smith",
            "Mary Jones",
            "Alan Turing",
            "Priya Raman",
            "Michael Chen",
            "Robert Lang",
            "Yuki Tanaka",
            "Sarah Klein",
            "Tom Baker",
            "Ann Mercer",
            "Paul Vance",
            "Rosa Delgado",
            "Ivan Petrov",
            "Nina Kovac",
        ]
        assert len(names) > len(pool.values), "the fixture must exhaust the pool"
        text = chr(10).join(f"Dear {name}, hello." for name in names)
        with surrogate_config("PERSON").session() as session:
            result = session.protect(text)
            assert "<PERSON_" in result.protected_text, "the overflow must become tokens"
            assert session.restore(result.protected_text).text == text

    def test_a_credential_is_still_blocked(self) -> None:
        with surrogate_config().session() as session, pytest.raises(PolicyViolationError):
            session.protect(f"the key is {FAKE_AWS_KEY}")

    def test_the_surrogate_does_not_depend_on_the_value_it_replaces(self) -> None:
        """The property that stops a surrogate carrying information.

        Deriving it from the original would give the same person the same fake
        name in every document, so somebody holding two protected documents
        could tell they are about the same individual.
        """
        first = "Dear Jane Doe, hello."
        second = "Dear Alan Turing, hello. Also Jane Doe."
        with surrogate_config("PERSON").session() as a:
            one = a.protect(first).protected_text
        with surrogate_config("PERSON").session() as b:
            two = b.protect(second).protected_text
        pool = pool_for("PERSON", "en")
        assert pool is not None
        assert pool.values[0] in one
        assert pool.values[1] in two, "Jane Doe is second here, so she gets the second name"


class TestThePools:
    def test_every_pool_has_values_and_a_basis(self) -> None:
        for pool in SURROGATE_POOLS:
            assert pool.values, f"{pool.entity_type}/{pool.locale} is empty"
            assert pool.basis, f"{pool.entity_type}/{pool.locale} does not say why it is safe"

    def test_no_pool_value_repeats_within_a_pool(self) -> None:
        for pool in SURROGATE_POOLS:
            assert len(set(pool.values)) == len(pool.values)

    def test_structured_types_use_reserved_ranges(self) -> None:
        """A surrogate that escapes should mean nothing anywhere."""
        for entity_type in ("EMAIL", "INTERNAL_IP", "INTERNAL_URL"):
            for pool in SURROGATE_POOLS:
                if pool.entity_type == entity_type:
                    assert "reserved" in pool.basis or "RFC" in pool.basis

    def test_email_surrogates_use_the_reserved_domains(self) -> None:
        pool = pool_for("EMAIL", "*")
        assert pool is not None
        for value in pool.values:
            assert value.endswith(("@example.com", "@example.org", "@example.net"))

    def test_ip_surrogates_use_test_net(self) -> None:
        pool = pool_for("INTERNAL_IP", "*")
        assert pool is not None
        for value in pool.values:
            assert value.startswith(("192.0.2.", "198.51.100.", "203.0.113."))

    def test_names_admit_they_are_invented(self) -> None:
        """Nothing is reserved for personal names, and the pool says so."""
        pool = pool_for("PERSON", "en")
        assert pool is not None
        assert "invented" in pool.basis

    def test_no_pool_contains_a_credential_type(self) -> None:
        """There is no safe stand-in for a password."""
        assert not supported_types() & {"PASSWORD", "API_KEY", "ACCESS_TOKEN", "PRIVATE_KEY"}


class TestConfiguration:
    def test_true_enables_every_supported_type(self) -> None:
        assert MamoriConfig(surrogates=True).surrogate_types() == supported_types()

    def test_a_list_enables_those_types(self) -> None:
        assert MamoriConfig(surrogates=["PERSON"]).surrogate_types() == {"PERSON"}

    def test_it_reads_from_a_mapping(self) -> None:
        config = MamoriConfig.from_mapping({"surrogates": ["person", "email"]})
        assert config.surrogate_types() == {"PERSON", "EMAIL"}

    def test_a_type_with_no_pool_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="no surrogate pool"):
            MamoriConfig.from_mapping({"surrogates": ["MY_NUMBER"]})

    def test_nonsense_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            MamoriConfig.from_mapping({"surrogates": 7})


class TestItIsReported:
    """Severe failure mode, so it may not be quiet."""

    def test_the_privacy_report_names_the_types(self) -> None:
        report = build_report(MamoriConfig(surrogates=["PERSON"]))
        assert "PERSON" in report.detection["surrogates"]

    def test_it_warns(self) -> None:
        warnings = " ".join(build_report(MamoriConfig(surrogates=["PERSON"])).warnings)
        assert "surrogate" in warnings

    def test_it_says_which_ones_are_merely_invented(self) -> None:
        """Reserved and invented are very different promises."""
        warnings = " ".join(build_report(MamoriConfig(surrogates=["PERSON"])).warnings)
        assert "nothing is reserved" in warnings

    def test_a_reserved_only_configuration_still_warns_but_more_narrowly(self) -> None:
        warnings = " ".join(build_report(MamoriConfig(surrogates=["EMAIL"])).warnings)
        assert "surrogate" in warnings
        assert "nothing is reserved" not in warnings

    def test_the_default_reports_none_and_warns_about_nothing(self) -> None:
        report = build_report(MamoriConfig())
        assert report.detection["surrogates"] == {}
        assert report.warnings == ()


class TestTheStoreKeepsTheSurface:
    def test_a_surrogate_mapping_records_what_was_substituted(self) -> None:
        from mamori.infrastructure.storage import InMemoryMappingStore

        store = InMemoryMappingStore()
        config = surrogate_config("PERSON")
        with PrivacySession(
            detectors=list(config.detectors()),
            store=store,
            scope="s",
            surrogate_types=config.surrogate_types(),
        ) as session:
            session.protect(EN)
            # Inside the block: closing a session purges its scope, which is
            # the behaviour that stops a mapping outliving the request.
            mappings = [m for m in store.list_scope("s") if m.entity_type_name == "PERSON"]
            assert mappings and mappings[0].is_surrogate
            assert mappings[0].substituted == mappings[0].surface

    def test_the_surface_is_not_in_the_repr(self) -> None:
        """The pair (surrogate, original) is the lookup table this all avoids."""
        from mamori.domain.mapping import Mapping
        from mamori.domain.placeholder import Placeholder

        mapping = Mapping(
            "s", Placeholder("PERSON", 1), "PERSON", "Jane Doe", surface="Alex Rivera"
        )
        assert "Alex Rivera" not in repr(mapping)
        assert "Jane Doe" not in repr(mapping)
