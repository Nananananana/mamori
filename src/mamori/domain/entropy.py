"""Whether a run of characters looks generated rather than written.

A secret with no vendor prefix and no keyword beside it has been the documented
gap in credential detection since the first release. The pattern rules cannot
close it: a 40-character hex API key, a base32 recovery code and a random
session token have no anchor at all. What they do have is a property no word
in any language has -- **their characters are spread evenly**. English prose
runs at about 4 bits of Shannon entropy per character over a large alphabet
and far less over a short window; a token drawn uniformly from sixteen hex
digits runs at 4.0 flat, and one drawn from sixty-four base64 characters at up
to 6.0.

This is the algorithm `detect-secrets`, `gitleaks` and `trufflehog` share, and
it is here for the same reason it is in those: it is the only detector for the
secrets that look like nothing. It is also **why it is not on by default**. A
content hash, a commit id, a base64 payload and a signed URL segment are all
generated too, and the measure cannot tell them from a key. The threat model
has said so since 0.1 and this module does not change that; it makes the trade
available to a deployment that would rather block a hash than send a key.

Two thresholds rather than one, because the ceiling depends on the alphabet. A
hex string cannot exceed 4.0 bits per character however random it is, so the
base64 threshold would never fire on one and the hex threshold would fire on
every base64 payload. The numbers are `detect-secrets`' defaults -- 3.0 for hex,
4.5 for base64 -- chosen there by measurement on real repositories and kept
here so a reader coming from that tool finds the same dial.

Two things this measure knowingly cannot see, both measured rather than
assumed. **A UUID is never flagged**: its hyphens put it in the base64 class,
and sixteen hex digits plus a hyphen is seventeen symbols, whose ceiling is
log2(17) -- about 4.09, under the 4.5 line however the digits fall. That is a
miss for a UUID-shaped key and it is also what keeps every request id in an
agent payload from becoming a blocked request. **A pangram is flagged**:
`thequickbrownfoxjumpsoverthelazydog` spreads 26 letters almost evenly and
clears 4.5 at 4.54. Nobody types one into a prompt, but it is why the detector
asks for a mix of character classes before believing this number.

Pure: no I/O, no regular expressions on the caller's text, nothing but
arithmetic on one token. Where a token comes from, and what sits beside it, are
the detector's concern.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "BASE64_THRESHOLD",
    "HEX_THRESHOLD",
    "MIN_LENGTH",
    "Alphabet",
    "EntropyVerdict",
    "alphabet_of",
    "judge",
    "shannon_entropy",
]

#: Bits per character above which a hex-only token is taken as generated. Hex
#: tops out at 4.0; 3.0 is what `detect-secrets` ships and what a 40-character
#: SHA-1 clears easily, which is the false positive this dial is known for.
HEX_THRESHOLD = 3.0

#: The same for a token drawn from the base64 alphabet, which tops out at 6.0.
#: 4.5 is again `detect-secrets`' default. Words, even long ones, sit well
#: below it; `Kx7pQz2mNv8Ld4Rt9Wy3Bc6Hj1Fs5Gk0Zn` sits above.
BASE64_THRESHOLD = 4.5

#: Shorter than this and the estimate is noise. Entropy of a five-character
#: string says nothing: every character can be distinct and the number is
#: maximal whatever the characters were. Twenty is where the two thresholds
#: above start to separate keys from words on the corpora this was checked on.
MIN_LENGTH = 20

_HEX = frozenset("0123456789abcdefABCDEF")
_BASE64 = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=_-")
_DIGITS = frozenset("0123456789")


class Alphabet(Enum):
    """Which character set a token is drawn from, which fixes its ceiling."""

    #: Digits only. Never judged here: a long digit run is an identifier, a
    #: phone number or an order number, and the wide rules already own it.
    DIGITS = "digits"
    #: `[0-9a-fA-F]` only. Ceiling 4.0 bits per character.
    HEX = "hex"
    #: The base64 alphabet, URL-safe variants included. Ceiling 6.0.
    BASE64 = "base64"
    #: Anything else -- a space, a CJK character, punctuation. Not a token.
    OTHER = "other"


def alphabet_of(token: str) -> Alphabet:
    """The narrowest alphabet ``token`` fits in.

    Narrowest, so that a hex string is judged against the hex ceiling and not
    the base64 one it also happens to fit: ``deadbeef...`` is base64-legal, and
    against a 4.5 threshold it could never be flagged at all.
    """
    if not token:
        return Alphabet.OTHER
    characters = set(token)
    if characters <= _DIGITS:
        return Alphabet.DIGITS
    if characters <= _HEX:
        return Alphabet.HEX
    if characters <= _BASE64:
        return Alphabet.BASE64
    return Alphabet.OTHER


def shannon_entropy(token: str) -> float:
    """Bits per character. ``0.0`` for the empty string and for one repeated
    character, which is the same as saying nothing was drawn at random."""
    if not token:
        return 0.0
    length = len(token)
    return -sum((count / length) * math.log2(count / length) for count in Counter(token).values())


@dataclass(frozen=True, slots=True)
class EntropyVerdict:
    """What :func:`judge` decided, and the numbers it decided on.

    The numbers come back with the answer because the answer alone is not
    reviewable. ``mamori trace`` prints them, so that somebody looking at a
    flagged hash can see *3.7 bits against a 3.0 threshold* and understand
    that the tool did exactly what it was set to do.
    """

    generated: bool
    alphabet: Alphabet
    entropy: float
    threshold: float

    def describe(self) -> str:
        return f"{self.alphabet.value} {self.entropy:.2f} bits/char vs {self.threshold:.1f}"


def judge(
    token: str,
    *,
    hex_threshold: float = HEX_THRESHOLD,
    base64_threshold: float = BASE64_THRESHOLD,
    min_length: int = MIN_LENGTH,
) -> EntropyVerdict:
    """Decide whether ``token`` looks generated.

    Args:
        token: One run of characters, already cut out of the text. This
            function does not tokenise; handing it a sentence measures the
            sentence.
        hex_threshold: Bits per character for a hex-only token.
        base64_threshold: The same for a base64-alphabet token.
        min_length: Below this the verdict is always ``False``.

    A digit-only run is never generated here, whatever its entropy. The wide
    rules already report a long digit run as an identifier, and a second
    detector claiming the same span as a credential -- which blocks rather than
    pseudonymises -- would turn every order number into a refused request.
    """
    alphabet = alphabet_of(token)
    entropy = shannon_entropy(token)

    if alphabet is Alphabet.HEX:
        threshold = hex_threshold
    elif alphabet is Alphabet.BASE64:
        threshold = base64_threshold
    else:
        return EntropyVerdict(False, alphabet, entropy, math.inf)

    generated = len(token) >= min_length and entropy >= threshold
    return EntropyVerdict(generated, alphabet, entropy, threshold)
