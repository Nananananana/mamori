"""The secrets that look like nothing, found by how evenly they are spread.

The credential rules match a vendor prefix, a PEM header, a database scheme or
a keyword. A key with none of those -- a bare 40-character hex token, a random
session id, a base32 recovery code -- has been the documented gap since 0.1,
and the wide-tier rule that reaches for it only sees a *mixed-case* run of
32 or more. Hex has no case to mix.

This pass measures instead of matching. :mod:`mamori.domain.entropy` decides
whether one token looks generated; this module decides **which runs of the
text are tokens**, which of those are already spoken for, and what sits beside
them. That last part is the difference between this and a naive entropy scan:

    api_key = a3f9c2e14b7d8e0f6a1c5b9d2e8f4a7c3b6d9e1f     keyword nearby -> MEDIUM
    commit  = a3f9c2e14b7d8e0f6a1c5b9d2e8f4a7c3b6d9e1f     keyword nearby -> LOW,
                                                            and named as a hash
    see a3f9c2e14b7d8e0f6a1c5b9d2e8f4a7c3b6d9e1f above      nothing nearby -> LOW

`gitleaks` and `detect-secrets` do the same, and for the same reason: entropy
alone cannot tell a key from a checksum, but the word before it usually can.

**Off by default, selected by `MamoriConfig(secrets="entropy")`.** What it adds
is reported as ``API_KEY``, which the default policy **blocks** -- there is no
legitimate reason to send a credential to a third party, and a placeholder
still tells the recipient one exists. So a false positive here does not cost a
stray placeholder; it stops the request. That is the right behaviour for a key
and the wrong one for a content hash, and the measure cannot tell them apart.
A deployment turning this on has decided that blocking a hash is cheaper than
sending a key. ``min_confidence`` is the dial for the rest: at ``LOW``
confidence, a threshold of ``0.6`` drops everything without a keyword.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ...domain import entity_types as t
from ...domain.confidence import LOW, MEDIUM, Confidence
from ...domain.entropy import (
    BASE64_THRESHOLD,
    HEX_THRESHOLD,
    MIN_LENGTH,
    Alphabet,
    judge,
)
from ...domain.sensitive_entity import SensitiveEntity
from ...domain.span import Span
from ...ports.detection_pass import DetectionContext

__all__ = ["EntropyPass"]

#: A run of characters a key could be made of. Bounded on both sides by
#: something that is not one of them, so ``...key=abc...`` yields ``abc`` and
#: not ``key=abc``. Dots and slashes are deliberately *not* in the class: a
#: path, a URL and a version string are long runs of exactly these characters
#: plus separators, and cutting at the separator is what keeps
#: ``github.com/owner/repo/blob/main/x`` from arriving here as one token.
_RUN = re.compile(r"(?<![A-Za-z0-9+/=_\-])[A-Za-z0-9+/=_\-]{16,}(?![A-Za-z0-9+/=_\-])")

#: What a secret is usually next to. Multilingual on purpose, like the
#: password rules: a Japanese or Chinese team's config still says ``token=``
#: and their prose says 鍵 or 密钥. Matched case-insensitively within
#: :data:`_WINDOW` characters before the token.
_KEYWORDS = re.compile(
    r"(?i)(?:secret|key|token|password|passwd|pwd|credential|auth|bearer|"
    r"api|private|signature|sig|"
    r"鍵|キー|トークン|パスワード|秘密|認証|"
    r"密钥|密鑰|令牌|密码|密碼|凭证|憑證|签名|簽名)"
)

#: What a *hash* is usually next to. A keyword from this set beside a token
#: says the number is a checksum, and the pass says so rather than staying
#: quiet -- the documented false positive, made visible instead of avoided.
_HASH_WORDS = re.compile(r"(?i)(?:sha|md5|hash|digest|checksum|commit|etag|ハッシュ|哈希|摘要)")

#: How far back to look for a keyword. Sixty characters is a short line: it
#: reaches ``Authorization: Bearer`` and ``"api_key": "`` and not the previous
#: paragraph.
_WINDOW = 60


def _has_a_mix(token: str) -> bool:
    """Upper, lower and a digit, for a base64-class token.

    The same requirement the wide-tier secret rule makes, for the same reason:
    a long lowercase run is a word, and a pangram clears the base64 threshold
    at 4.54 without one. Hex is exempt -- it has no case to mix, which is
    exactly why it needed a measure rather than a pattern.
    """
    return (
        any(c.islower() for c in token)
        and any(c.isupper() for c in token)
        and any(c.isdigit() for c in token)
    )


class EntropyPass:
    """Report long, evenly-spread runs of key-shaped characters as ``API_KEY``.

    Args:
        hex_threshold: Bits per character for a hex-only run.
        base64_threshold: The same for a run from the base64 alphabet.
        min_length: Shortest run judged. Below twenty the number is noise.
        window: Characters before a run searched for a keyword.
        name: Recorded on every entity, so ``mamori trace`` says a detection
            came from a measurement and not a pattern.
    """

    def __init__(
        self,
        *,
        hex_threshold: float = HEX_THRESHOLD,
        base64_threshold: float = BASE64_THRESHOLD,
        min_length: int = MIN_LENGTH,
        window: int = _WINDOW,
        name: str = "entropy",
    ) -> None:
        if min_length < 8:
            raise ValueError(f"min_length must be >= 8, got {min_length}")
        if window < 0:
            raise ValueError(f"window must be >= 0, got {window}")
        self._hex_threshold = hex_threshold
        self._base64_threshold = base64_threshold
        self._min_length = min_length
        self._window = window
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def run(self, context: DetectionContext) -> Sequence[SensitiveEntity]:
        text = context.text
        covered = context.covered()
        found: list[SensitiveEntity] = []

        for match in _RUN.finditer(text):
            start, end = match.span()
            if any(index in covered for index in range(start, end)):
                # A vendor-prefixed key, an email, a URL: something with an
                # anchor already claimed it, and an anchor beats a measurement.
                continue

            token = match.group()
            verdict = judge(
                token,
                hex_threshold=self._hex_threshold,
                base64_threshold=self._base64_threshold,
                min_length=self._min_length,
            )
            if not verdict.generated:
                continue
            if verdict.alphabet is Alphabet.BASE64 and not _has_a_mix(token):
                continue

            found.append(
                SensitiveEntity(
                    entity_type=t.API_KEY,
                    span=Span(start, end),
                    value=token,
                    confidence=self._confidence(text, start),
                    source=self._name,
                )
            )
        return found

    def _confidence(self, text: str, start: int) -> Confidence:
        """MEDIUM beside a secret word, LOW beside a hash word or nothing.

        A hash word and a secret word together -- ``token digest`` -- is LOW:
        the safer reading of an ambiguous label is the one that does not stop
        the request, and ``min_confidence`` can still catch it.
        """
        before = text[max(0, start - self._window) : start]
        if _HASH_WORDS.search(before):
            return LOW
        if _KEYWORDS.search(before):
            return MEDIUM
        return LOW
