"""Presidio's analyzer, plugged in as a mamori recogniser.

The other direction from :mod:`mamori.interop.presidio`, and the reason it is
worth having: Presidio ships a large recogniser set and its own NLP engines,
and reimplementing those would be a worse use of anybody's time than calling
them. Registered as an algorithm, it becomes ``MamoriConfig(nlp="presidio")``.

An adapter, so it lives here. What mamori keeps doing is everything after the
finding -- resolution, policy, placeholder identity and restoration. A
recogniser proposes; this library still decides, which is the rule that does
not move whichever recogniser is running.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from ...domain.span import Span
from ...errors import ConfigurationError
from ...ports.nlp_recognizer import RecognizedEntity

__all__ = ["PresidioRecognizer", "as_recognized"]


def as_recognized(results: Iterable[Any]) -> list[RecognizedEntity]:
    """Presidio findings as things a mamori recogniser could have said.

    Accepts real ``presidio_analyzer.RecognizerResult`` objects, mamori's
    lookalike, or plain mappings -- anything carrying ``entity_type``,
    ``start`` and ``end``. Duck-typed on purpose: a fixture loaded from JSON is
    the commonest thing somebody has, and requiring the class would mean
    requiring the install.
    """
    found: list[RecognizedEntity] = []
    for item in results:
        if isinstance(item, dict):
            label, start, end = item["entity_type"], item["start"], item["end"]
            score = float(item.get("score", 1.0))
        else:
            label, start, end = item.entity_type, item.start, item.end
            score = float(getattr(item, "score", 1.0))
        found.append(
            RecognizedEntity(label=str(label), span=Span(int(start), int(end)), score=score)
        )
    return found


class PresidioRecognizer:
    """Ask Presidio, in mamori's vocabulary."""

    def __init__(self, engine: Any = None, *, language: str = "en", name: str = "") -> None:
        self._language = language
        self._name = name or f"presidio/{language}"
        self._engine = engine if engine is not None else self._load()

    @staticmethod
    def _load() -> Any:
        try:
            from presidio_analyzer import AnalyzerEngine
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on install
            raise ConfigurationError(
                "the Presidio recogniser needs `presidio-analyzer`: "
                'pip install "mamori[presidio]". It is optional because mamori '
                "detects without it, and because Presidio brings its own model "
                "stack -- which is both why somebody would want this and why it "
                "cannot be a default."
            ) from exc
        return AnalyzerEngine()

    @property
    def name(self) -> str:
        return self._name

    def entities(self, text: str) -> Sequence[RecognizedEntity]:
        return as_recognized(self._engine.analyze(text=text, language=self._language))
