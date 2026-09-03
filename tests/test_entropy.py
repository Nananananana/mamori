"""The entropy measure: what it calls generated, and what it knowingly cannot.

These pin the algorithm rather than the detector that uses it. Every claim in
the module docstring -- the ceilings, the two thresholds, the digit exemption,
the minimum length -- is a sentence that could quietly stop being true, so
each one is a test.
"""

from __future__ import annotations

import math

import pytest

from mamori.domain.entropy import (
    BASE64_THRESHOLD,
    HEX_THRESHOLD,
    MIN_LENGTH,
    Alphabet,
    alphabet_of,
    judge,
    shannon_entropy,
)

#: Invented, and shaped like the things this exists to find.
HEX_KEY = "a3f9c2e14b7d8e0f6a1c5b9d2e8f4a7c3b6d9e1f"  # 40 hex, SHA-1 shaped
BASE64_KEY = "Kx7pQz2mNv8Ld4Rt9Wy3Bc6Hj1Fs5Gk0Zn"
UUID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


class TestShannonEntropy:
    def test_the_empty_string_has_none(self) -> None:
        assert shannon_entropy("") == 0.0

    def test_one_repeated_character_has_none(self) -> None:
        assert shannon_entropy("aaaaaaaaaa") == 0.0

    def test_two_characters_evenly_is_one_bit(self) -> None:
        assert shannon_entropy("abababab") == pytest.approx(1.0)

    def test_sixteen_distinct_hex_digits_is_four_bits(self) -> None:
        """The hex ceiling, reached exactly when every digit appears once."""
        assert shannon_entropy("0123456789abcdef") == pytest.approx(4.0)

    def test_it_never_exceeds_the_log_of_the_alphabet(self) -> None:
        for token in (HEX_KEY, BASE64_KEY, "hello world", "田中太郎"):
            assert shannon_entropy(token) <= math.log2(len(set(token))) + 1e-9


class TestAlphabetOf:
    @pytest.mark.parametrize(
        ("token", "expected"),
        [
            ("", Alphabet.OTHER),
            ("0123456789", Alphabet.DIGITS),
            ("deadbeef00", Alphabet.HEX),
            ("DEADBEEF", Alphabet.HEX),
            (BASE64_KEY, Alphabet.BASE64),
            ("abc+/=_-", Alphabet.BASE64),
            ("hello world", Alphabet.OTHER),
            ("田中", Alphabet.OTHER),
            (UUID, Alphabet.BASE64),  # the hyphens take it out of hex
        ],
    )
    def test_the_narrowest_fit(self, token: str, expected: Alphabet) -> None:
        assert alphabet_of(token) is expected

    def test_hex_is_narrower_than_base64(self) -> None:
        """A hex string is base64-legal too. Judged against 4.5 it could never
        be flagged, so it must be classed as hex first."""
        assert alphabet_of(HEX_KEY) is Alphabet.HEX


class TestJudge:
    def test_a_hex_key_is_generated(self) -> None:
        verdict = judge(HEX_KEY)
        assert verdict.generated
        assert verdict.alphabet is Alphabet.HEX
        assert verdict.threshold == HEX_THRESHOLD

    def test_a_base64_key_is_generated(self) -> None:
        verdict = judge(BASE64_KEY)
        assert verdict.generated
        assert verdict.threshold == BASE64_THRESHOLD

    @pytest.mark.parametrize(
        "word",
        [
            "Donaudampfschifffahrtsgesellschaftskapitaen",
            "internationalizationconfiguration",
        ],
    )
    def test_a_long_word_is_not(self, word: str) -> None:
        """Prose repeats letters; a key does not. Measured at 3.96 and 3.32
        bits against a 4.5 threshold."""
        assert not judge(word).generated

    def test_a_pangram_is_the_known_exception(self) -> None:
        """`thequickbrownfoxjumpsoverthelazydog` spreads 26 letters almost
        evenly and clears 4.5 at 4.54. It is the worst case prose can
        produce and it is not representative -- but it is why the *detector*
        asks for a mix of character classes before believing this number, and
        why this function alone is not the detector. Pinned so the exception
        stays known rather than rediscovered."""
        assert judge("thequickbrownfoxjumpsoverthelazydog").generated

    def test_a_repeated_pattern_is_not(self) -> None:
        assert not judge("abcabcabcabcabcabcabcabc").generated

    def test_a_digit_run_is_never_generated(self) -> None:
        """A long digit run is an identifier and the wide rules own it. A
        second detector claiming it as a *credential* would block the request
        over an order number."""
        verdict = judge("9876543210987654321098765432")
        assert not verdict.generated
        assert verdict.alphabet is Alphabet.DIGITS

    def test_below_the_minimum_length_is_never_generated(self) -> None:
        short = HEX_KEY[: MIN_LENGTH - 1]
        assert judge(short).entropy >= HEX_THRESHOLD, "the sample is too tame to test this"
        assert not judge(short).generated

    def test_at_the_minimum_length_it_can_be(self) -> None:
        assert judge(HEX_KEY[:MIN_LENGTH]).generated

    def test_a_sentence_is_not_a_token(self) -> None:
        """This function does not tokenise. Handed prose it measures prose,
        and the alphabet says it is not a token at all."""
        verdict = judge("the password is hunter2 and the key is abc")
        assert not verdict.generated
        assert verdict.alphabet is Alphabet.OTHER
        assert verdict.threshold == math.inf

    def test_the_thresholds_are_dials(self) -> None:
        assert not judge(HEX_KEY, hex_threshold=4.1).generated
        assert judge("thequickbrownfoxjumpsoverthelazydog", base64_threshold=1.0).generated

    def test_the_verdict_carries_its_numbers(self) -> None:
        """So a flagged hash can be reviewed: 3.7 bits against 3.0 is a tool
        doing what it was set to do, and the sentence has to be printable."""
        text = judge(HEX_KEY).describe()
        assert "hex" in text and "bits/char" in text and "3.0" in text


class TestTheDocumentedFalsePositives:
    """The trade the module docstring names. Each one is stated as a test so
    that a change which happens to remove it is noticed and celebrated rather
    than a change which reintroduces it being missed."""

    def test_a_commit_id_is_flagged(self) -> None:
        assert judge("e3b0c44298fc1c149afbf4c8996fb92427ae41e4").generated

    def test_a_base64_payload_is_flagged(self) -> None:
        """Encoded prose. 4.98 bits: base64 spreads even a sentence across
        most of its alphabet, which is exactly what makes it indistinguishable
        from a key by this measure."""
        encoded = "TG9yZW0gaXBzdW0gZG9sb3Igc2l0IGFtZXQsIGNvbnNlY3RldHVyIGFkaXBpc2NpbmcgZWxpdA=="
        assert judge(encoded).generated

    def test_a_short_base64_payload_can_sit_just_under(self) -> None:
        """The first version of this file asserted this one was flagged. It
        measures 4.48, two hundredths under the line. The threshold is a line
        through a distribution, not a fact about base64."""
        assert not judge("SGVsbG8sIFdvcmxkISBUaGlzIGlzIGJhc2U2NC4=").generated

    def test_a_uuid_is_not_flagged_and_cannot_be(self) -> None:
        """The hyphens put a UUID in the base64 class, and sixteen hex digits
        plus a hyphen is seventeen symbols: the ceiling is log2(17), about
        4.09, below the 4.5 threshold however the digits fall. The first
        version of this file claimed the opposite and measurement said 3.62.

        A miss, stated: a UUID-shaped API key is not found by this. It is also
        the property that keeps every request id, trace id and record id in an
        agent payload from becoming a blocked request, so it is kept."""
        verdict = judge(UUID)
        assert not verdict.generated
        assert verdict.entropy < 4.5
