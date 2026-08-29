"""A detected piece of sensitive information."""

from __future__ import annotations

from dataclasses import dataclass, field

from .confidence import Confidence
from .entity_types import EntityType
from .normalization import normalize_value
from .span import Span

__all__ = ["SensitiveEntity"]


@dataclass(frozen=True, slots=True)
class SensitiveEntity:
    """One detection.

    Security note:
        ``value`` is excluded from ``repr``. The default dataclass ``repr``
        would otherwise put raw PII into every traceback and log line that
        happens to format this object.
    """

    entity_type: EntityType
    span: Span
    value: str = field(repr=False)
    confidence: Confidence = field(default_factory=lambda: Confidence(0.9))
    source: str = "unknown"

    @property
    def identity_key(self) -> str:
        """Key deciding whether two detections denote the same entity.

        Normalized so that ``田中太郎`` and ``田中 太郎`` map to one placeholder.
        """
        return f"{self.entity_type.name}:{normalize_value(self.value)}"

    def relocated(self, span: Span, value: str) -> SensitiveEntity:
        """Return a copy carrying an original-text span and the text it covers.

        Detectors work on normalized text, so their ``value`` is the normalized
        form. What has to be put back later is the substring that was actually
        removed from the original, which is not always the same string: NFKC
        turns ``Ĳ`` into ``IJ`` and ``㍿`` into ``株式会社``.
        """
        return SensitiveEntity(
            entity_type=self.entity_type,
            span=span,
            value=value,
            confidence=self.confidence,
            source=self.source,
        )
