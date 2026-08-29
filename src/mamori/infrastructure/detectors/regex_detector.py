"""Regex-backed detector."""

from __future__ import annotations

from collections.abc import Sequence

from ...domain.sensitive_entity import SensitiveEntity
from ...domain.span import Span
from .patterns import PatternRule

__all__ = ["RegexDetector"]


class RegexDetector:
    """Applies a set of :class:`PatternRule` to a text.

    Overlaps between rules are *not* resolved here. Every rule reports what it
    sees and the application resolves conflicts once, in one place, with one
    documented rule -- see :mod:`mamori.domain.resolution`.
    """

    def __init__(self, name: str, rules: Sequence[PatternRule]) -> None:
        self._name = name
        self._rules = tuple(rules)

    @property
    def name(self) -> str:
        return self._name

    @property
    def rules(self) -> tuple[PatternRule, ...]:
        return self._rules

    def detect(self, text: str) -> Sequence[SensitiveEntity]:
        found: list[SensitiveEntity] = []
        for rule in self._rules:
            for match in rule.pattern.finditer(text):
                start, end = match.span(rule.group)
                if start < 0 or end <= start:
                    continue
                value = match.group(rule.group)
                if rule.validator is not None and not rule.validator(value):
                    continue
                found.append(
                    SensitiveEntity(
                        entity_type=rule.entity_type,
                        span=Span(start, end),
                        value=value,
                        confidence=rule.confidence,
                        source=self._name,
                    )
                )
        return found
