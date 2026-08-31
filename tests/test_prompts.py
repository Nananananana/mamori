"""Prompts: composition, overlays, and reading a model's answer.

Two things are being pinned down here. That a prompt can be changed by an
organisation without forking it -- which is the whole reason it is a document
with parts rather than a string. And that nothing a model says is trusted: a
hallucinated span is dropped, a refusal degrades, and neither can move a
security decision.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from mamori import MamoriConfig, PrivacySession
from mamori.domain.stance import Stance
from mamori.errors import ConfigurationError, DetectionError
from mamori.infrastructure.detectors import CoOccurrencePass, build_pipeline
from mamori.infrastructure.detectors.llm_pass import LLMDetectionPass
from mamori.infrastructure.llm import FailingProvider, ScriptedProvider
from mamori.ports.detection_pass import DetectionContext
from mamori.prompts import (
    BUILTIN_GUIDANCE,
    DETECTION_PROMPT_ID,
    EXTERNAL_PROMPT_ID,
    GuidanceKind,
    GuidanceRule,
    GuidanceSet,
    PromptDefinition,
    PromptLibrary,
    PromptOverlay,
    PromptSection,
    default_library,
    parse_detection_response,
)


def rule(rule_id: str, text: str = "x", **kwargs: object) -> GuidanceRule:
    return GuidanceRule(id=rule_id, text=text, **kwargs)  # type: ignore[arg-type]


def answer(*entities: Mapping[str, object]) -> str:
    return json.dumps({"entities": list(entities)})


class TestGuidanceSet:
    def test_ids(self) -> None:
        assert GuidanceSet((rule("a"), rule("b"))).ids() == ("a", "b")

    def test_get(self) -> None:
        assert GuidanceSet((rule("a"),)).get("a") is not None
        assert GuidanceSet((rule("a"),)).get("z") is None

    def test_without_drops_by_id(self) -> None:
        assert GuidanceSet((rule("a"), rule("b"))).without(["a"]).ids() == ("b",)

    def test_with_rules_appends(self) -> None:
        assert GuidanceSet((rule("a"),)).with_rules([rule("b")]).ids() == ("a", "b")

    def test_with_rules_replaces_in_place(self) -> None:
        """A replacement keeps its position, so the reading order is stable."""
        base = GuidanceSet((rule("a"), rule("b"), rule("c")))
        updated = base.with_rules([rule("b", "new")])
        assert updated.ids() == ("a", "b", "c")
        assert updated.get("b").text == "new"  # type: ignore[union-attr]

    def test_of_kind(self) -> None:
        mixed = GuidanceSet((rule("a"), rule("b", kind=GuidanceKind.IGNORE)))
        assert mixed.of_kind(GuidanceKind.IGNORE).ids() == ("b",)

    def test_for_locales_keeps_language_neutral_rules(self) -> None:
        mixed = GuidanceSet((rule("any"), rule("ja.x", locales=("ja",))))
        assert mixed.for_locales(["en"]).ids() == ("any",)

    def test_for_locales_keeps_matching_rules(self) -> None:
        mixed = GuidanceSet((rule("any"), rule("ja.x", locales=("ja",))))
        assert mixed.for_locales(["ja"]).ids() == ("any", "ja.x")

    def test_none_keeps_everything(self) -> None:
        mixed = GuidanceSet((rule("any"), rule("ja.x", locales=("ja",))))
        assert len(mixed.for_locales(None)) == 2

    def test_operations_do_not_mutate(self) -> None:
        base = GuidanceSet((rule("a"),))
        base.without(["a"])
        base.with_rules([rule("b")])
        assert base.ids() == ("a",)


class TestBuiltinGuidance:
    def test_it_covers_all_three_languages(self) -> None:
        locales = {loc for r in BUILTIN_GUIDANCE for loc in r.locales}
        assert {"ja", "en", "zh"} <= locales

    def test_ids_are_unique(self) -> None:
        ids = BUILTIN_GUIDANCE.ids()
        assert len(ids) == len(set(ids))

    def test_every_rule_is_addressable_and_named_by_scope(self) -> None:
        for guidance in BUILTIN_GUIDANCE:
            assert guidance.id
            assert guidance.id.split(".")[0] in {"any", "ja", "en", "zh"}

    def test_it_carries_the_negative_knowledge(self) -> None:
        """What looks sensitive and is not -- the expensive half."""
        assert len(BUILTIN_GUIDANCE.of_kind(GuidanceKind.IGNORE)) >= 4

    def test_the_uncertainty_rule_leans_towards_reporting(self) -> None:
        uncertain = BUILTIN_GUIDANCE.get("any.uncertain")
        assert uncertain is not None
        assert "report it" in uncertain.text


class TestRendering:
    def test_sections_appear_in_order(self) -> None:
        prompt = PromptDefinition(
            id="p",
            sections=(PromptSection("one", "first"), PromptSection("two", "second")),
        )
        text = prompt.render().text
        assert text.index("first") < text.index("second")

    def test_guidance_lands_where_it_is_asked_to(self) -> None:
        prompt = PromptDefinition(
            id="p",
            sections=(PromptSection("a", "AAA"), PromptSection("b", "BBB")),
            guidance=GuidanceSet((rule("g", "GGG"),)),
            guidance_after="a",
        )
        text = prompt.render().text
        assert text.index("AAA") < text.index("GGG") < text.index("BBB")

    def test_guidance_goes_last_by_default(self) -> None:
        prompt = PromptDefinition(
            id="p",
            sections=(PromptSection("a", "AAA"),),
            guidance=GuidanceSet((rule("g", "GGG"),)),
        )
        text = prompt.render().text
        assert text.index("AAA") < text.index("GGG")

    def test_kinds_get_their_own_headings(self) -> None:
        prompt = PromptDefinition(
            id="p",
            guidance=GuidanceSet((rule("a", "FIND"), rule("b", "SKIP", kind=GuidanceKind.IGNORE))),
        )
        text = prompt.render().text
        assert "What counts as sensitive" in text
        assert "What looks sensitive and is not" in text

    def test_examples_are_included(self) -> None:
        prompt = PromptDefinition(
            id="p", guidance=GuidanceSet((rule("a", "text", examples=("X -> Y",)),))
        )
        assert "X -> Y" in prompt.render().text

    def test_rendering_is_deterministic(self) -> None:
        library = default_library()
        assert library.render("detection").text == library.render("detection").text

    def test_the_fingerprint_changes_with_the_text(self) -> None:
        library = default_library()
        base = library.render(DETECTION_PROMPT_ID)
        narrowed = library.render(DETECTION_PROMPT_ID, ["ja"])
        assert base.fingerprint != narrowed.fingerprint

    def test_narrowing_the_locale_shortens_the_prompt(self) -> None:
        """It matters: a small local model has a short context."""
        library = default_library()
        assert len(library.render(DETECTION_PROMPT_ID, ["ja"])) < len(
            library.render(DETECTION_PROMPT_ID)
        )

    def test_the_rendered_prompt_records_what_went_into_it(self) -> None:
        rendered = default_library().render(DETECTION_PROMPT_ID)
        assert rendered.prompt_id == "detection"
        assert rendered.version
        assert rendered.guidance_ids


class TestExternalPrompt:
    def test_it_tells_the_model_to_copy_placeholders_verbatim(self) -> None:
        text = default_library().render(EXTERNAL_PROMPT_ID).text
        assert "exactly as written" in text
        assert "<PERSON_001>" in text

    def test_it_names_the_mutations_restoration_has_to_recover_from(self) -> None:
        text = default_library().render(EXTERNAL_PROMPT_ID).text
        for mangled in ("<PERSON_1>", "PERSON_001", "＜PERSON_001＞"):
            assert mangled in text

    def test_it_forbids_inventing_placeholders(self) -> None:
        assert "Do not invent" in default_library().render(EXTERNAL_PROMPT_ID).text

    def test_a_session_hands_it_out(self) -> None:
        with PrivacySession() as session:
            assert "placeholder" in session.external_system_prompt()

    def test_it_is_short_enough_to_prepend(self) -> None:
        assert len(default_library().render(EXTERNAL_PROMPT_ID)) < 2000


class TestOverlay:
    def test_adding_a_rule(self) -> None:
        overlay = PromptOverlay(add=(rule("acme.case", "Case numbers look like ACME-12345."),))
        prompt = overlay.apply(default_library().get(DETECTION_PROMPT_ID))
        assert "acme.case" in prompt.guidance.ids()
        assert "ACME-12345" in prompt.render().text

    def test_disabling_a_rule(self) -> None:
        overlay = PromptOverlay(disable=("en.person.unanchored",))
        prompt = overlay.apply(default_library().get(DETECTION_PROMPT_ID))
        assert "en.person.unanchored" not in prompt.guidance.ids()

    def test_replacing_a_rule_by_id(self) -> None:
        overlay = PromptOverlay(add=(rule("any.uncertain", "Report nothing you are unsure of."),))
        prompt = overlay.apply(default_library().get(DETECTION_PROMPT_ID))
        assert "Report nothing" in prompt.render().text

    def test_replacing_a_section(self) -> None:
        overlay = PromptOverlay(sections={"role": "You are an internal compliance scanner."})
        prompt = overlay.apply(default_library().get(DETECTION_PROMPT_ID))
        assert "internal compliance scanner" in prompt.render().text

    def test_disabling_something_that_does_not_exist_is_refused(self) -> None:
        """A typo that silently does nothing is how a team believes they changed
        something and did not."""
        overlay = PromptOverlay(disable=("en.person.unanchord",))
        with pytest.raises(ConfigurationError, match="cannot disable unknown guidance"):
            overlay.apply(default_library().get(DETECTION_PROMPT_ID))

    def test_replacing_an_unknown_section_is_refused(self) -> None:
        overlay = PromptOverlay(sections={"rle": "..."})
        with pytest.raises(ConfigurationError, match="unknown section"):
            overlay.apply(default_library().get(DETECTION_PROMPT_ID))

    def test_lenient_mode_exists_for_when_it_is_wanted(self) -> None:
        overlay = PromptOverlay(disable=("nope",), strict=False)
        assert overlay.apply(default_library().get(DETECTION_PROMPT_ID)) is not None

    def test_overlays_stack(self) -> None:
        first = PromptOverlay(disable=("en.person.unanchored",))
        second = PromptOverlay(add=(rule("acme.case"),))
        merged = first.merged_with(second)
        assert merged.disable == ("en.person.unanchored",)
        assert merged.add[0].id == "acme.case"

    def test_an_added_rule_is_marked_as_local(self) -> None:
        """So 'mamori prompt --guidance' can show what is house policy."""
        overlay = PromptOverlay.from_mapping(
            {"add": [{"id": "acme.case", "text": "..."}]}, origin="overlay:detection"
        )
        assert overlay.add[0].origin == "overlay:detection"


class TestOverlayFromMapping:
    def test_a_full_overlay(self) -> None:
        overlay = PromptOverlay.from_mapping(
            {
                "disable": ["en.person.unanchored"],
                "add": [
                    {
                        "id": "acme.case",
                        "text": "Case numbers look like ACME-12345.",
                        "kind": "find",
                        "entity_types": ["IDENTIFIER"],
                        "locales": ["en"],
                        "examples": ["ACME-12345"],
                    }
                ],
                "sections": {"role": "custom"},
            }
        )
        assert overlay.disable == ("en.person.unanchored",)
        assert overlay.add[0].entity_types == ("IDENTIFIER",)

    def test_an_unknown_key_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="unknown prompt overlay key"):
            PromptOverlay.from_mapping({"disabled": []})

    def test_an_unknown_guidance_key_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="unknown guidance key"):
            PromptOverlay.from_mapping({"add": [{"id": "a", "text": "b", "colour": "red"}]})

    def test_a_rule_without_an_id_is_refused(self) -> None:
        """Without one it could never be disabled again."""
        with pytest.raises(ConfigurationError, match="needs an id"):
            PromptOverlay.from_mapping({"add": [{"text": "b"}]})

    def test_a_rule_without_text_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="has no text"):
            PromptOverlay.from_mapping({"add": [{"id": "a"}]})

    def test_an_unknown_kind_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="unknown kind"):
            PromptOverlay.from_mapping({"add": [{"id": "a", "text": "b", "kind": "vibes"}]})

    def test_a_non_list_disable_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="must be a list"):
            PromptOverlay.from_mapping({"disable": "en.person.unanchored"})


class TestPromptLibrary:
    def test_the_bundled_ids(self) -> None:
        assert default_library().ids() == ("detection", "external")

    def test_an_unknown_prompt_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="unknown prompt"):
            default_library().get("nope")

    def test_an_overlay_applies_on_the_way_out(self) -> None:
        library = default_library().with_overlay(
            DETECTION_PROMPT_ID, PromptOverlay(disable=("any.uncertain",))
        )
        assert "any.uncertain" not in library.get(DETECTION_PROMPT_ID).guidance.ids()

    def test_an_overlay_on_one_prompt_leaves_the_other_alone(self) -> None:
        library = default_library().with_overlay(
            DETECTION_PROMPT_ID, PromptOverlay(sections={"role": "changed"})
        )
        assert "changed" not in library.render(EXTERNAL_PROMPT_ID).text

    def test_a_custom_prompt_can_be_added(self) -> None:
        library = default_library().with_prompt(PromptDefinition(id="mine"))
        assert "mine" in library.ids()

    def test_from_mapping(self) -> None:
        library = PromptLibrary.from_mapping(
            {"detection": {"add": [{"id": "acme.case", "text": "..."}]}}
        )
        assert "acme.case" in library.get(DETECTION_PROMPT_ID).guidance.ids()

    def test_an_overlay_for_an_unknown_prompt_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="unknown prompt"):
            PromptLibrary.from_mapping({"detektion": {}})


class TestConfigIntegration:
    def test_prompt_overlays_come_from_the_config(self) -> None:
        settings = MamoriConfig.from_mapping(
            {"prompts": {"detection": {"disable": ["en.person.unanchored"]}}}
        )
        ids = settings.prompt_library().get(DETECTION_PROMPT_ID).guidance.ids()
        assert "en.person.unanchored" not in ids

    def test_a_broken_overlay_is_refused_when_the_config_is_built(self) -> None:
        """Not when a model is finally wired up, months later."""
        with pytest.raises(ConfigurationError):
            MamoriConfig.from_mapping({"prompts": {"detection": {"disable": ["nope"]}}})

    def test_the_default_config_has_the_bundled_prompts(self) -> None:
        assert MamoriConfig().prompt_library().ids() == ("detection", "external")


class TestParsingAModelAnswer:
    TEXT = "Please ask Kenji about the Tsubaki rollout."

    def entity(self, value: str, entity_type: str = "PERSON") -> dict[str, object]:
        start = self.TEXT.index(value)
        return {"type": entity_type, "start": start, "end": start + len(value), "text": value}

    def test_a_clean_answer(self) -> None:
        outcome = parse_detection_response(answer(self.entity("Kenji")), self.TEXT)
        assert len(outcome.entities) == 1
        assert outcome.is_clean

    def test_an_empty_answer(self) -> None:
        outcome = parse_detection_response('{"entities": []}', self.TEXT)
        assert outcome.entities == ()
        assert outcome.is_clean

    def test_json_in_a_code_fence(self) -> None:
        raw = "Here you go:\n```json\n" + answer(self.entity("Kenji")) + "\n```"
        assert len(parse_detection_response(raw, self.TEXT).entities) == 1

    def test_json_after_a_sentence(self) -> None:
        raw = "I found one entity. " + answer(self.entity("Kenji"))
        assert len(parse_detection_response(raw, self.TEXT).entities) == 1

    def test_prose_with_no_json(self) -> None:
        outcome = parse_detection_response("I cannot help with that.", self.TEXT)
        assert outcome.unparsable
        assert outcome.entities == ()

    def test_a_value_that_is_not_in_the_text_is_dropped(self) -> None:
        """The check that stops the wrong characters being spliced out.

        A model can infer a name from an email address and report it as
        though it were written down. Protecting a value the document does not
        contain would mean cutting characters that are not there.
        """
        bad = {"type": "PERSON", "text": "Yamada"}
        outcome = parse_detection_response(answer(bad), self.TEXT)
        assert outcome.entities == ()
        assert "does not appear in the text" in outcome.rejected[0]

    def test_the_rejection_does_not_quote_the_value_back(self) -> None:
        """Rejections end up in diagnostics; they show a shape, not a value."""
        bad = {"type": "PERSON", "text": "Yamada"}
        outcome = parse_detection_response(answer(bad), self.TEXT)
        assert "Yamada" not in outcome.rejected[0]

    def test_wrong_offsets_no_longer_throw_the_answer_away(self) -> None:
        """Measured: a local 8B model got 0 of 52 offsets right, and 51 of
        those 52 values were really in the document. Asking a model to count
        characters and discarding it for failing was throwing away the tier."""
        bad = {"type": "PERSON", "start": 0, "end": 5, "text": "Kenji"}
        outcome = parse_detection_response(answer(bad), self.TEXT)
        assert [e.value for e in outcome.entities] == ["Kenji"]
        assert self.TEXT[outcome.entities[0].span.start : outcome.entities[0].span.end] == "Kenji"

    def test_offsets_outside_the_text_are_ignored_not_fatal(self) -> None:
        bad = {"type": "PERSON", "start": 900, "end": 950, "text": "Kenji"}
        outcome = parse_detection_response(answer(bad), self.TEXT)
        assert [e.value for e in outcome.entities] == ["Kenji"]

    def test_correct_offsets_are_still_honoured(self) -> None:
        """A model that can count keeps its exact span, including the case the
        search cannot resolve: the same value twice, only one of them meant."""
        text = "Kenji spoke to Kenji."
        item = {"type": "PERSON", "start": 15, "end": 20, "text": "Kenji"}
        outcome = parse_detection_response(answer(item), text)
        assert [(e.span.start, e.span.end) for e in outcome.entities] == [(15, 20)]

    def test_a_value_appearing_twice_is_reported_twice(self) -> None:
        """Protecting one mention and leaving the other is not protecting it."""
        text = "Kenji spoke to Kenji."
        outcome = parse_detection_response(answer({"type": "PERSON", "text": "Kenji"}), text)
        assert [(e.span.start, e.span.end) for e in outcome.entities] == [(0, 5), (15, 20)]

    def test_offsets_are_optional(self) -> None:
        outcome = parse_detection_response(answer({"type": "PERSON", "text": "Kenji"}), self.TEXT)
        assert len(outcome.entities) == 1

    def test_a_one_character_value_is_refused(self) -> None:
        """It would match most of a CJK document."""
        outcome = parse_detection_response(answer({"type": "PERSON", "text": "K"}), self.TEXT)
        assert outcome.entities == ()

    def test_a_latin_value_respects_word_boundaries(self) -> None:
        """Ann is a name; Announcement is not an occurrence of it."""
        text = "Dear Ann, the announcement goes out Monday."
        outcome = parse_detection_response(answer({"type": "PERSON", "text": "Ann"}), text)
        assert [(e.span.start, e.span.end) for e in outcome.entities] == [(5, 8)]

    def test_an_unknown_type_is_dropped(self) -> None:
        bad = dict(self.entity("Kenji"), type="VIBES")
        outcome = parse_detection_response(answer(bad), self.TEXT)
        assert outcome.entities == ()
        assert "unknown type" in outcome.rejected[0]

    def test_a_near_miss_type_name_is_accepted(self) -> None:
        """A model that says ORG means COMPANY_NAME.

        Strictness about type names is right -- a model that invents a type has
        told nobody anything. But in one measured run a 14B model reported 38
        entities and 11 were rejected for spelling: ORG, EMAIL_ADDRESS,
        PHONE_NUMBER. That is 29% of a model's work discarded over a synonym.
        """
        item = dict(self.entity("Kenji"), type="PERSON_NAME")
        outcome = parse_detection_response(answer(item), self.TEXT)
        assert outcome.entities[0].entity_type.name == "PERSON"
        assert outcome.rejected == ()

    @pytest.mark.parametrize(
        ("said", "meant"),
        [
            ("ORG", "COMPANY_NAME"),
            ("ORGANIZATION", "COMPANY_NAME"),
            ("EMAIL_ADDRESS", "EMAIL"),
            ("PHONE_NUMBER", "PHONE"),
            ("CARD_NUMBER", "CREDIT_CARD"),
            ("ZIP_CODE", "POSTAL_CODE"),
            ("DOB", "DATE_OF_BIRTH"),
            # From the Chinese and Japanese runs, where the tail of near
            # misses is different: 工号 comes back as WORK_NUMBER, and a
            # reference of any kind comes back named after what it references.
            ("WORK_NUMBER", "EMPLOYEE_ID"),
            ("CUSTOMER_NUMBER", "IDENTIFIER"),
            ("CASE_NUMBER", "IDENTIFIER"),
        ],
    )
    def test_the_synonyms_that_are_unambiguous(self, said: str, meant: str) -> None:
        item = dict(self.entity("Kenji"), type=said)
        outcome = parse_detection_response(answer(item), self.TEXT)
        assert outcome.entities[0].entity_type.name == meant

    @pytest.mark.parametrize(
        "said",
        ["IP_ADDRESS", "LOCATION", "CREDENTIAL", "PII", "HOSTNAME", "IDENTITY_NUMBER"],
    )
    def test_the_ones_that_stay_refused(self, said: str) -> None:
        """Each for its own reason, all of them recorded in `_ALIASES`.

        `IP_ADDRESS` would map onto INTERNAL_IP and redact 8.8.8.8, when the
        point of that type is that a public address is not sensitive.
        `LOCATION` could be a country or a street. `CREDENTIAL` would map onto
        PASSWORD, whose action is BLOCK, and a fuzzy label should not be able to
        stop somebody's request. `HOSTNAME` has no type to map to -- a URL and
        an address are not a name. `IDENTITY_NUMBER` is a 身份证号 in a Chinese
        document and something else with some other shape everywhere else, and
        RESIDENT_ID carries a checksum this pass cannot verify.
        """
        item = dict(self.entity("Kenji"), type=said)
        outcome = parse_detection_response(answer(item), self.TEXT)
        assert outcome.entities == ()
        assert "unknown type" in outcome.rejected[0]

    def test_other_sensitive_is_accepted(self) -> None:
        """A model saying 'this matters and I cannot name it' is worth keeping."""
        item = dict(self.entity("Kenji"), type="OTHER_SENSITIVE")
        outcome = parse_detection_response(answer(item), self.TEXT)
        assert outcome.entities[0].entity_type.name == "OTHER_SENSITIVE"

    def test_one_bad_candidate_does_not_cost_the_good_ones(self) -> None:
        good = self.entity("Kenji")
        bad = {"type": "PERSON", "start": 0, "end": 5, "text": "wrong"}
        outcome = parse_detection_response(answer(good, bad), self.TEXT)
        assert len(outcome.entities) == 1
        assert len(outcome.rejected) == 1

    def test_missing_fields_are_dropped(self) -> None:
        outcome = parse_detection_response(answer({"type": "PERSON"}), self.TEXT)
        assert outcome.entities == ()

    def test_a_non_object_entry_is_dropped(self) -> None:
        raw = json.dumps({"entities": ["Kenji"]})
        assert parse_detection_response(raw, self.TEXT).entities == ()


class TestLLMDetectionPass:
    TEXT = "Please ask Kenji about the Tsubaki rollout."

    def proposal(self, value: str, entity_type: str = "PERSON") -> str:
        start = self.TEXT.index(value)
        return answer(
            {"type": entity_type, "start": start, "end": start + len(value), "text": value}
        )

    def test_a_proposal_becomes_a_detection(self) -> None:
        pass_ = LLMDetectionPass(ScriptedProvider(self.proposal("Kenji")))
        found = pass_.run(DetectionContext(text=self.TEXT))
        assert [e.value for e in found] == ["Kenji"]

    def test_it_does_not_repeat_what_the_rules_already_found(self) -> None:
        from mamori.domain import entity_types as t
        from mamori.domain.confidence import HIGH
        from mamori.domain.sensitive_entity import SensitiveEntity
        from mamori.domain.span import Span

        start = self.TEXT.index("Kenji")
        already = SensitiveEntity(
            entity_type=t.PERSON,
            span=Span(start, start + 5),
            value="Kenji",
            confidence=HIGH,
            source="rules",
        )
        pass_ = LLMDetectionPass(ScriptedProvider(self.proposal("Kenji")))
        assert pass_.run(DetectionContext(text=self.TEXT, found=(already,))) == []

    def test_a_broken_provider_degrades_rather_than_stopping(self) -> None:
        """A missing model is a weaker detector, not a failed request."""
        pass_ = LLMDetectionPass(FailingProvider())
        assert pass_.run(DetectionContext(text=self.TEXT)) == []
        assert pass_.last_outcome is not None
        assert pass_.last_outcome.unparsable

    def test_require_model_turns_that_into_a_failure(self) -> None:
        pass_ = LLMDetectionPass(FailingProvider(), require_model=True)
        with pytest.raises(DetectionError):
            pass_.run(DetectionContext(text=self.TEXT))

    def test_an_unparsable_answer_degrades(self) -> None:
        pass_ = LLMDetectionPass(ScriptedProvider("I cannot help with that."))
        assert pass_.run(DetectionContext(text=self.TEXT)) == []

    def test_require_model_refuses_an_unparsable_answer(self) -> None:
        pass_ = LLMDetectionPass(ScriptedProvider("nope"), require_model=True)
        with pytest.raises(DetectionError):
            pass_.run(DetectionContext(text=self.TEXT))

    def test_empty_text_is_not_sent(self) -> None:
        provider = ScriptedProvider(self.proposal("Kenji"))
        LLMDetectionPass(provider).run(DetectionContext(text="   "))
        assert provider.requests == []

    def test_a_long_document_is_scanned_in_windows(self) -> None:
        """Not truncated, and no longer skipped.

        Truncating reports success on a document it never read. Skipping is
        honest but means the model tier quietly stops applying at the length
        where documents get interesting -- which is a recall hole with a
        length threshold on it.
        """
        provider = ScriptedProvider("{}")
        pass_ = LLMDetectionPass(provider, max_input_characters=100)
        pass_.run(DetectionContext(text="x" * 1000))
        assert len(provider.requests) > 1
        covered = "".join(r.user.split(chr(10), 1)[1] for r in provider.requests)
        assert len(covered) >= 1000, "the windows must between them cover the document"

    def test_a_short_document_is_still_one_request(self) -> None:
        """Windowing must cost nothing in the common case."""
        provider = ScriptedProvider("{}")
        LLMDetectionPass(provider, max_input_characters=8000).run(DetectionContext(text=self.TEXT))
        assert len(provider.requests) == 1

    def test_a_detection_in_a_later_window_lands_in_document_coordinates(self) -> None:
        """The arithmetic that would corrupt the document if it were wrong.

        A model answering about window three reports offsets inside window
        three. Replacement happens in the document, so anything that forgets to
        add the offset cuts characters out of the wrong sentence.
        """
        from mamori.domain.windowing import windows

        text = "x" * 300 + chr(10) + "Contact Kenji tomorrow."
        pieces = windows(text, 310)
        assert len(pieces) > 1, "the fixture must actually be split"

        index, window = next((i, w) for i, w in enumerate(pieces) if "Kenji" in w.text and i > 0)
        local = window.text.index("Kenji")
        answers = ["{}"] * index
        answers.append(
            answer(
                {
                    "type": "PERSON",
                    "start": local,
                    "end": local + len("Kenji"),
                    "text": "Kenji",
                }
            )
        )
        found = LLMDetectionPass(ScriptedProvider(answers), max_input_characters=310).run(
            DetectionContext(text=text)
        )

        assert [e.value for e in found] == ["Kenji"]
        span = found[0].span
        assert text[span.start : span.end] == "Kenji"
        assert span.start == text.index("Kenji")

    def test_the_same_entity_seen_in_two_windows_is_reported_once(self) -> None:
        """Overlap is the library's business, not something the caller counts."""
        text = "x" * 200 + " Contact Kenji now. " + "y" * 200
        start = text.index("Kenji")
        both = answer({"type": "PERSON", "start": 0, "end": 0, "text": ""})
        provider = ScriptedProvider(both)
        pass_ = LLMDetectionPass(provider, max_input_characters=250)
        found = pass_.run(DetectionContext(text=text))
        assert len({(e.span.start, e.span.end) for e in found}) == len(found)
        assert start > 0

    def test_the_prompt_it_sends_is_inspectable(self) -> None:
        pass_ = LLMDetectionPass(ScriptedProvider("{}"))
        assert "What counts as sensitive" in pass_.rendered_prompt()

    def test_the_text_is_sent_behind_a_marker(self) -> None:
        provider = ScriptedProvider("{}")
        LLMDetectionPass(provider).run(DetectionContext(text=self.TEXT))
        assert provider.requests[0].user.startswith("---TEXT---")

    def test_an_overlay_reaches_the_prompt(self) -> None:
        library = default_library().with_overlay(
            DETECTION_PROMPT_ID, PromptOverlay(add=(rule("acme.case", "ACME-12345 is a case."),))
        )
        pass_ = LLMDetectionPass(ScriptedProvider("{}"), library=library)
        assert "ACME-12345" in pass_.rendered_prompt()

    def test_narrowing_the_locale_shortens_what_is_sent(self) -> None:
        wide = LLMDetectionPass(ScriptedProvider("{}"))
        narrow = LLMDetectionPass(ScriptedProvider("{}"), locales=["ja"])
        assert len(narrow.rendered_prompt()) < len(wide.rendered_prompt())


class TestLLMPassInAPipeline:
    TEXT = "Please ask Kenji about the Tsubaki rollout."

    def pipeline(self, provider: object) -> object:
        return build_pipeline(
            co_occurrence=CoOccurrencePass(),
            stance=Stance.BALANCED,
            extra_passes=[LLMDetectionPass(provider)],  # type: ignore[arg-type]
        )

    def test_a_model_proposal_becomes_a_placeholder(self) -> None:
        start = self.TEXT.index("Tsubaki")
        proposal = answer(
            {"type": "PROJECT_NAME", "start": start, "end": start + 7, "text": "Tsubaki"}
        )
        settings = MamoriConfig(stance=Stance.BALANCED)
        with PrivacySession(
            detectors=[self.pipeline(ScriptedProvider(proposal))],  # type: ignore[list-item]
            policy=settings.policy(),
        ) as session:
            protected = session.protect(self.TEXT)
            assert "Tsubaki" not in protected.protected_text
            assert session.restore(protected.protected_text).text == self.TEXT

    def test_a_silenced_model_leaves_the_rules_untouched(self) -> None:
        """The property that makes a model safe to include: it only ever adds."""
        text = "Dear Jane Doe,\n\nmail jane@example.com."
        settings = MamoriConfig(stance=Stance.BALANCED)
        with PrivacySession(
            detectors=[self.pipeline(ScriptedProvider('{"entities": []}'))],  # type: ignore[list-item]
            policy=settings.policy(),
        ) as session:
            with_model = session.protect(text).protected_text
        with settings.session() as session:
            without_model = session.protect(text).protected_text
        assert with_model == without_model

    def test_a_failing_model_leaves_the_rules_untouched(self) -> None:
        text = "Dear Jane Doe,\n\nmail jane@example.com."
        settings = MamoriConfig(stance=Stance.BALANCED)
        with PrivacySession(
            detectors=[self.pipeline(FailingProvider())],  # type: ignore[list-item]
            policy=settings.policy(),
        ) as session:
            assert "jane@example.com" not in session.protect(text).protected_text
