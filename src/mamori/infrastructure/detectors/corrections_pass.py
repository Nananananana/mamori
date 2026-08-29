"""Finding what the operator said is sensitive, whatever the rules think.

The other half of a correction. :class:`~mamori.domain.corrections.Verdict`
``NEVER`` is a filter over what was detected and lives in the protection
service; ``ALWAYS`` has to *find* something, which makes it a detection pass
like any other.

It is deliberately the simplest pass in the package. It has no patterns and no
judgement: the operator named a value, so every occurrence of that value is a
detection. The work of locating it is
:func:`~mamori.domain.occurrences.find_occurrences`, which the co-occurrence
pass and the model parser already use for the same reason.

Confidence is ``CERTAIN``. A rule is a guess about a shape and a model is a
guess about a sentence; an operator typing a value into a correction log is
neither. It should beat both in overlap resolution, because it is the only
evidence in the system that came from somebody who actually knows.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...domain.confidence import CERTAIN
from ...domain.corrections import CorrectionLog
from ...domain.occurrences import find_occurrences
from ...domain.sensitive_entity import SensitiveEntity
from ...ports.detection_pass import DetectionContext

__all__ = ["CorrectionsPass"]


class CorrectionsPass:
    """Adds every value the operator ruled sensitive.

    Args:
        log: The rulings. An empty log makes this pass a no-op, which is what
            it is for every user who has never corrected anything.
        name: Recorded on every entity, so a report can say plainly that a
            detection came from a correction rather than from a rule.
    """

    def __init__(self, log: CorrectionLog, *, name: str = "correction") -> None:
        self._log = log
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def log(self) -> CorrectionLog:
        return self._log

    def run(self, context: DetectionContext) -> Sequence[SensitiveEntity]:
        added = self._log.added()
        if not added:
            return []

        text = context.text
        already = context.covered()
        found: list[SensitiveEntity] = []

        for correction in added:
            entity_type = correction.resolved_type()
            if entity_type is None:  # pragma: no cover - refused at construction
                continue
            for span in find_occurrences(text, correction.value):
                if any(index in already for index in range(span.start, span.end)):
                    # Something already covers it. A correction exists to add
                    # protection, not to relabel what is already protected.
                    continue
                found.append(
                    SensitiveEntity(
                        entity_type=entity_type,
                        span=span,
                        value=text[span.start : span.end],
                        confidence=CERTAIN,
                        source=self._name,
                    )
                )
        return found
