"""Detection as an ordered sequence of passes.

The pipeline is itself a ``Detector``, so nothing upstream of it changes: the
protection service still asks one object what it can see. What changed is that
the object is now assembled from parts that can be reordered, replaced or left
out, and each part gets to see what the previous ones found.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...domain.sensitive_entity import SensitiveEntity
from ...ports.detection_pass import DetectionContext, DetectionPass
from ...ports.detector import Detector

__all__ = ["DetectionPipeline", "DetectorPass"]


class DetectorPass:
    """Adapts a plain ``Detector`` into a pass.

    The adapter exists so that the narrow contract stays the default. A rule
    set should not be handed the other rule sets' findings just because the
    pipeline could: most detection is better off not knowing.
    """

    def __init__(self, detector: Detector, name: str | None = None) -> None:
        self._detector = detector
        self._name = name or detector.name

    @property
    def name(self) -> str:
        return self._name

    @property
    def detector(self) -> Detector:
        return self._detector

    def run(self, context: DetectionContext) -> Sequence[SensitiveEntity]:
        return self._detector.detect(context.text)


class DetectionPipeline:
    """Runs passes in order, accumulating what each one adds.

    Order matters: a pass reasoning over prior findings has to come after
    whatever produces them. Nothing is deduplicated or resolved here -- passes
    are free to report the same span twice, and
    :mod:`mamori.domain.resolution` settles it once, in one place, later.
    """

    def __init__(self, passes: Sequence[DetectionPass], name: str = "pipeline") -> None:
        self._passes = tuple(passes)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def passes(self) -> tuple[DetectionPass, ...]:
        return self._passes

    def detect(self, text: str) -> Sequence[SensitiveEntity]:
        context = DetectionContext(text=text)
        found: list[SensitiveEntity] = []
        for stage in self._passes:
            added = stage.run(context)
            found.extend(added)
            context = context.with_more(added)
        return found
