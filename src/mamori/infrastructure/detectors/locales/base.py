"""What a language pack is.

Some things look the same in every language -- an email address, a card number,
an AWS key. Those live in :mod:`..patterns`. Everything else does not: a phone
number, a postal code, a company suffix and, above all, a personal name are
written differently in every language, and a rule that works for one is usually
noise in another.

A pack groups the rules for one language, plus the evidence for deciding
whether they are worth running at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ....domain.script import Script
from ..patterns import PatternRule

__all__ = ["LocalePack"]


@dataclass(frozen=True, slots=True)
class LocalePack:
    """The detection rules for one language.

    Args:
        code: Short identifier, e.g. ``"ja"``. Used to select packs and as the
            detector name recorded on every entity the pack produces.
        name: Human-readable name, for ``mamori locales``.
        rules: The rules themselves.
        triggers: Scripts whose presence in a text means this pack is worth
            running. Empty means always run.
        suppressed_by: Scripts whose presence means this pack is *not* worth
            running, whatever the triggers say. This exists for one specific
            case: kana appear in Japanese and never in Chinese, so kana in the
            text is proof the Chinese rules would only add noise.
    """

    code: str
    name: str
    rules: tuple[PatternRule, ...]
    triggers: frozenset[Script] = field(default_factory=frozenset)
    suppressed_by: frozenset[Script] = field(default_factory=frozenset)

    def applies_to(self, scripts: frozenset[Script]) -> bool:
        """Whether this pack should run against a text using ``scripts``."""
        if self.suppressed_by & scripts:
            return False
        if not self.triggers:
            return True
        return bool(self.triggers & scripts)
