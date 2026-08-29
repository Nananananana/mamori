"""Run the language packs that the text gives a reason to run.

Running every pack against every text would be simplest, and for most pairs of
languages it would also be fine -- English rules find nothing in Chinese prose,
because they are anchored on Latin words.

Chinese and Japanese are the exception. They share Han characters, so the two
surname lists fire on each other's text constantly, and the result is a document
full of placeholders standing in for ordinary words.

This detector settles that with the one piece of evidence that is decisive: kana
appear in Japanese and never in Chinese. Text containing kana is Japanese, so
the Chinese pack stands down. Text in Han alone could be either, so both run and
over-detect -- the safe direction, since a spurious placeholder costs answer
quality while a missed name costs the thing the library exists to prevent.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...domain.script import scripts_in
from ...domain.sensitive_entity import SensitiveEntity
from ...ports.detector import Detector
from .locales import LocalePack
from .regex_detector import RegexDetector

__all__ = ["AdaptiveLocaleDetector"]


class AdaptiveLocaleDetector:
    """Selects language packs per text, by the scripts the text uses."""

    def __init__(
        self,
        packs: Sequence[LocalePack],
        *,
        name: str = "locale",
        always: Sequence[Detector] = (),
    ) -> None:
        """
        Args:
            packs: Language packs to choose between.
            name: Detector name, used only in error messages.
            always: Detectors that run whatever the text looks like, for rules
                that do not depend on language.
        """
        self._name = name
        self._always = tuple(always)
        self._packs = tuple(packs)
        self._detectors = {pack.code: RegexDetector(pack.code, pack.rules) for pack in self._packs}

    @property
    def name(self) -> str:
        return self._name

    @property
    def packs(self) -> tuple[LocalePack, ...]:
        return self._packs

    def packs_for(self, text: str) -> tuple[LocalePack, ...]:
        """Which packs would run against ``text``. Exposed for ``mamori inspect``."""
        scripts = scripts_in(text)
        return tuple(pack for pack in self._packs if pack.applies_to(scripts))

    def detect(self, text: str) -> Sequence[SensitiveEntity]:
        found: list[SensitiveEntity] = []
        for detector in self._always:
            found.extend(detector.detect(text))
        for pack in self.packs_for(text):
            found.extend(self._detectors[pack.code].detect(text))
        return found
