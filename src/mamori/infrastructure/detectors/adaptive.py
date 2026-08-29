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

**The evidence is local, and until 0.18 it was applied globally.** One kana
character anywhere in a text stood the Chinese pack down for all of it, which is
right for a paragraph and wrong for a document: a JSON payload whose subject
line is Japanese and whose body is Chinese had the body sent in the clear, and
so did any bilingual thread, ticket or context package. A pack that a script
would suppress now runs anyway and its detections are kept **outside** the
regions where that script actually appears. Rules still see the whole text, so
nothing loses the context it needs -- only the answers are filtered.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...domain.script import covered_by, script_regions, scripts_in
from ...domain.sensitive_entity import SensitiveEntity
from ...domain.stance import Stance
from ...ports.detector import Detector
from .locales import LocalePack
from .patterns import rules_for
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
        stance: Stance = Stance.RECALL_FIRST,
    ) -> None:
        """
        Args:
            packs: Language packs to choose between.
            name: Detector name, used only in error messages.
            always: Detectors that run whatever the text looks like, for rules
                that do not depend on language.
            stance: Which rule tiers to run.
        """
        self._name = name
        self._always = tuple(always)
        self._packs = tuple(packs)
        self._stance = stance
        self._detectors = {
            pack.code: RegexDetector(pack.code, rules_for(pack.rules, stance))
            for pack in self._packs
        }

    @property
    def name(self) -> str:
        return self._name

    @property
    def stance(self) -> Stance:
        return self._stance

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

        scripts = scripts_in(text)
        for pack in self._packs:
            if pack.triggers and not (pack.triggers & scripts):
                continue
            suppressing = pack.suppressed_by & scripts
            if not suppressing:
                found.extend(self._detectors[pack.code].detect(text))
                continue
            # The pack is suppressed *somewhere*. Run it and keep what falls
            # outside the reach of the evidence against it.
            regions = script_regions(text, suppressing)
            if _reaches_everywhere(regions, len(text)):
                continue
            found.extend(
                entity
                for entity in self._detectors[pack.code].detect(text)
                if not covered_by(regions, entity.span.start, entity.span.end)
            )
        return found


def _reaches_everywhere(regions: tuple[tuple[int, int], ...], length: int) -> bool:
    """Whether every sentence in the text carries the evidence.

    The common case, and worth taking: a Japanese document is kana in every
    sentence, so the Chinese pack is skipped outright rather than run and
    filtered. Gaps of a few characters between regions are the boundaries
    themselves -- punctuation belongs to no sentence -- and a name cannot sit
    inside one, so they do not count as uncovered.
    """
    if not regions:
        return False
    covered = sum(end - start for start, end in regions)
    return covered >= length - 2 * len(regions)
