"""English detection rules.

The negative tests matter more here than anywhere else. An English name is two
capitalised words, and so is every product, city and department, so each name
rule is anchored on something that only precedes a name. These tests pin down
both what that buys and what it costs.
"""

from __future__ import annotations

import pytest

from mamori.domain.stance import Stance
from mamori.infrastructure.detectors.locales.en import ssn_valid

from .helpers import types_in, values_of

LOCALE = "en"


def en_types(text: str) -> set[str]:
    return types_in(text, LOCALE)


def en_values(text: str, type_name: str) -> set[str]:
    return values_of(text, type_name, LOCALE)


class TestSsnValidation:
    def test_accepts_a_structurally_valid_number(self) -> None:
        assert ssn_valid("123-45-6789")

    @pytest.mark.parametrize(
        "number",
        ["000-45-6789", "666-45-6789", "900-45-6789", "123-00-6789", "123-45-0000"],
    )
    def test_rejects_ranges_that_are_never_issued(self, number: str) -> None:
        assert not ssn_valid(number)

    @pytest.mark.parametrize("value", ["12345678", "1234567890", "abc-de-fghi"])
    def test_rejects_wrong_shapes(self, value: str) -> None:
        assert not ssn_valid(value)


class TestContactDetails:
    @pytest.mark.parametrize(
        "phone", ["(415) 555-0198", "415-555-0198", "415.555.0198", "415 555 0198"]
    )
    def test_north_american_formats(self, phone: str) -> None:
        assert "PHONE" in en_types(f"Call {phone} tomorrow")

    def test_international_form_is_caught_by_the_universal_rule(self) -> None:
        assert "PHONE" in en_types("Call +1 415 555 0198")

    def test_a_bare_digit_run_is_not_a_phone_number(self) -> None:
        assert "PHONE" not in en_types("Order 4155550198 shipped")

    def test_ssn_in_hyphenated_form(self) -> None:
        assert en_values("SSN 123-45-6789 on file", "SSN") == {"123-45-6789"}

    def test_ssn_behind_a_label_without_hyphens(self) -> None:
        assert en_values("Social Security Number: 123456789", "SSN") == {"123456789"}

    def test_a_date_is_not_read_as_an_ssn(self) -> None:
        assert "SSN" not in en_types("Released 666-45-6789")

    def test_zip_plus_four(self) -> None:
        assert "POSTAL_CODE" in en_types("Springfield, IL 62704-1234")

    def test_a_bare_five_digit_zip_needs_a_label(self) -> None:
        assert en_values("ZIP code: 62704", "POSTAL_CODE") == {"62704"}
        assert "POSTAL_CODE" not in en_types("Part 62704 is in stock")

    def test_uk_postcode(self) -> None:
        assert "POSTAL_CODE" in en_types("Our office is at SW1A 1AA")

    def test_date_of_birth_needs_its_label(self) -> None:
        assert en_values("Date of birth: March 4, 1985", "DATE_OF_BIRTH") == {"March 4, 1985"}
        assert "DATE_OF_BIRTH" not in en_types("Shipped on 1985-04-01")

    def test_street_address(self) -> None:
        assert "1600 Pennsylvania Avenue" in en_values(
            "Send it to 1600 Pennsylvania Avenue, Washington", "ADDRESS"
        )

    def test_a_number_followed_by_ordinary_words_is_not_an_address(self) -> None:
        assert "ADDRESS" not in en_types("We shipped 1600 Widgets Today")


class TestOrganisations:
    @pytest.mark.parametrize(
        "company", ["Acme Inc.", "Globex Corporation", "Initech LLC", "Umbrella Ltd"]
    )
    def test_legal_suffixes(self, company: str) -> None:
        assert "COMPANY_NAME" in en_types(f"The contract is with {company} today")

    def test_a_trading_name_with_no_suffix_is_missed(self) -> None:
        """Documented gap: nothing marks Acme as a company in running text."""
        assert "COMPANY_NAME" not in en_types("The contract is with Acme")

    def test_employee_id_needs_its_label(self) -> None:
        assert en_values("Employee ID: A-12345", "EMPLOYEE_ID") == {"A-12345"}

    def test_project_code_needs_its_label(self) -> None:
        assert en_values("Project: Nightingale", "PROJECT_NAME") == {"Nightingale"}


class TestPersonNames:
    def test_title_anchored(self) -> None:
        assert "John Smith" in en_values("Mr. John Smith will attend", "PERSON")

    def test_the_title_is_not_part_of_the_value(self) -> None:
        assert all("Mr" not in value for value in en_values("Mr. John Smith", "PERSON"))

    def test_salutation_anchored(self) -> None:
        assert "Jane Doe" in en_values("Dear Jane Doe,\n\nThanks for writing.", "PERSON")

    def test_informal_salutation(self) -> None:
        assert "Jane" in en_values("Hi Jane,\nsee attached.", "PERSON")

    def test_sign_off_anchored(self) -> None:
        assert "Jane Doe" in en_values("Thanks for your help.\n\nRegards,\nJane Doe", "PERSON")

    def test_label_anchored(self) -> None:
        assert "Jane Doe" in en_values("Full name: Jane Doe", "PERSON")

    def test_hyphenated_surname(self) -> None:
        assert "Mary Smith-Jones" in en_values("Dr. Mary Smith-Jones called", "PERSON")

    def test_an_unanchored_name_is_missed(self) -> None:
        """The documented gap. Two capitalised words are not evidence of a name."""
        assert "PERSON" not in en_types("I spoke to Jane Doe about it")

    def test_a_capitalised_phrase_is_not_a_name(self) -> None:
        assert "PERSON" not in en_types("The Quarterly Business Review is on Monday")

    def test_a_sentence_opener_is_not_a_name(self) -> None:
        assert "PERSON" not in en_types("Monday works for me. Tuesday does not.")


class TestUniversalRulesStillApply:
    def test_email(self) -> None:
        assert en_values("write to jane@example.com", "EMAIL") == {"jane@example.com"}

    def test_internal_url(self) -> None:
        assert "INTERNAL_URL" in en_types("see https://wiki.corp.local/page")


class TestASalutationMustNotHideTheName:
    """`Jane Doe.` was detected and `Dear Jane Doe.` was not.

    Two decisions collided. The salutation-anchored rule requires a trailing
    comma or newline, so it does not fire on `Dear Jane Doe.` -- and `Dear` is
    in the wide rule's stoplist, so the wide rule matched the three-word run
    `Dear Jane Doe`, the validator rejected it for containing `Dear`, and
    `finditer` resumed *after* the rejected span. The name inside it was never
    reconsidered.

    **Adding the salutation made the name invisible**, which is backwards: an
    anchor is supposed to raise confidence, and this one removed the detection
    that would have happened without it. `Dear Jane Doe.` is the most ordinary
    opening line English business mail has, and `Dear Jane Doe.` is the exact
    string in this project's own README.

    The fix is in the pattern rather than the validator, because a validator
    cannot un-consume. A leading negative lookahead means the match never
    starts on a stop word, so the scan advances one character and finds the
    name. Measured on all four English corpora at both stances: every
    published figure unchanged.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "Dear Jane Doe.",
            "Dear Jane Doe",
            "Dear Jane Doe!",
            "Dear Jane Doe?",
            "Hi Jane Doe.",
            "Hello Jane Doe.",
            "Hey Jane Doe.",
            "Thanks Jane Doe.",
            "Dear Jane Doe. Thanks for the update.",
        ],
        ids=lambda t: t[:24],
    )
    def test_a_name_after_a_stoplist_word_is_still_found(self, text: str) -> None:
        assert "PERSON" in types_in(text, "en", Stance.RECALL_FIRST)

    def test_the_comma_form_still_works(self) -> None:
        """It went through the anchored rule and still does."""
        assert "PERSON" in types_in("Dear Jane Doe, thanks.", "en")

    def test_the_name_itself_is_what_is_reported(self) -> None:
        """Not `Dear Jane Doe` -- the salutation is context, and replacing it
        would put `<PERSON_001>` where the word `Dear` was."""
        assert values_of("Dear Jane Doe.", "PERSON", "en", Stance.RECALL_FIRST) == {"Jane Doe"}

    @pytest.mark.parametrize(
        "text",
        [
            "The Quarterly Business Review is Monday",
            "Social Security Number is required",
            "Meeting Notes Draft",
            "Next Steps Agenda",
        ],
        ids=lambda t: t[:24],
    )
    def test_the_stoplist_still_costs_the_false_positives_it_bought(self, text: str) -> None:
        """The lookahead stops a match *beginning* on a stop word. The
        validator still rejects one that contains a stop word later, which is
        what these rely on."""
        assert "PERSON" not in types_in(text, "en", Stance.RECALL_FIRST)

    def test_a_legal_suffix_is_still_a_company_not_a_person(self) -> None:
        found = types_in("Please contact Umbrella Ltd", "en", Stance.RECALL_FIRST)
        assert "COMPANY_NAME" in found
        assert "PERSON" not in found
