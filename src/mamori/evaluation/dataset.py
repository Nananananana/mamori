"""Labelled evaluation data.

Samples are authored with inline markup rather than character offsets::

    [[PERSON:田中太郎]]さんへ [[EMAIL:tanaka@example.com]] から連絡がありました。

The loader strips the markup and computes the spans. Hand-written offsets are
wrong often enough that a corpus annotated that way ends up measuring the
annotator rather than the detector, and a contributor adding a case should not
have to count characters.

**Every sample must be invented.** These files ship inside the package, so a
real name or a real key committed here is published to everyone who installs
mamori. See ``CONTRIBUTING.md``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..domain.span import Span
from ..errors import ConfigurationError

__all__ = ["Annotation", "Dataset", "Sample", "bundled_datasets", "parse_annotated"]

#: ``[[TYPE:value]]``. The value may not contain ``]]``, which keeps the parse
#: unambiguous without an escaping scheme nobody would remember.
_MARKUP_RE = re.compile(r"\[\[([A-Z][A-Z0-9_]{0,62}):((?:(?!\]\]).)+)\]\]", re.DOTALL)

_FORMAT_VERSION = 1
_DATA_DIR = Path(__file__).parent / "data"


@dataclass(frozen=True, slots=True)
class Annotation:
    """One labelled entity: what it is, and where it sits in the plain text."""

    entity_type: str
    span: Span

    @property
    def length(self) -> int:
        return self.span.length


@dataclass(frozen=True, slots=True)
class Sample:
    """One labelled text."""

    id: str
    text: str
    annotations: tuple[Annotation, ...] = ()
    #: Why this case is here. Shown when it fails, which is when it matters.
    note: str = ""

    @property
    def sensitive_characters(self) -> frozenset[int]:
        """Indices covered by an annotation."""
        return frozenset(
            index
            for annotation in self.annotations
            for index in range(annotation.span.start, annotation.span.end)
        )


@dataclass(frozen=True, slots=True)
class Dataset:
    """A named collection of labelled samples."""

    name: str
    locale: str
    samples: tuple[Sample, ...]
    description: str = ""
    source: str = "synthetic"

    def __len__(self) -> int:
        return len(self.samples)

    def __iter__(self) -> Iterator[Sample]:
        return iter(self.samples)

    @property
    def annotation_count(self) -> int:
        return sum(len(sample.annotations) for sample in self.samples)

    def types(self) -> frozenset[str]:
        """Every entity type that appears in the labels."""
        return frozenset(
            annotation.entity_type for sample in self.samples for annotation in sample.annotations
        )

    @classmethod
    def load(cls, path: Path) -> Dataset:
        """Read a dataset file."""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigurationError(f"could not read dataset: {path}") from exc
        return cls.from_payload(payload, origin=str(path))

    @classmethod
    def from_payload(cls, payload: object, origin: str = "<memory>") -> Dataset:
        """Build a dataset from already-parsed JSON."""
        if not isinstance(payload, dict):
            raise ConfigurationError(f"dataset must be an object: {origin}")
        if payload.get("format_version") != _FORMAT_VERSION:
            raise ConfigurationError(f"unsupported dataset format: {origin}")

        raw_samples = payload.get("samples")
        if not isinstance(raw_samples, list):
            raise ConfigurationError(f"dataset has no samples: {origin}")

        samples: list[Sample] = []
        seen: set[str] = set()
        for index, raw in enumerate(raw_samples):
            if not isinstance(raw, dict):
                raise ConfigurationError(f"sample {index} is not an object: {origin}")
            sample_id = str(raw.get("id") or f"{payload.get('name', 'sample')}-{index:03d}")
            if sample_id in seen:
                raise ConfigurationError(f"duplicate sample id {sample_id!r}: {origin}")
            seen.add(sample_id)
            annotated = raw.get("annotated")
            if not isinstance(annotated, str):
                raise ConfigurationError(f"sample {sample_id} has no annotated text: {origin}")
            text, annotations = parse_annotated(annotated)
            samples.append(
                Sample(
                    id=sample_id,
                    text=text,
                    annotations=annotations,
                    note=str(raw.get("note", "")),
                )
            )

        return cls(
            name=str(payload.get("name", "unnamed")),
            locale=str(payload.get("locale", "")),
            samples=tuple(samples),
            description=str(payload.get("description", "")),
            source=str(payload.get("source", "synthetic")),
        )


def parse_annotated(annotated: str) -> tuple[str, tuple[Annotation, ...]]:
    """Strip ``[[TYPE:value]]`` markup and return the text with its spans.

    Raises:
        ConfigurationError: the markup is malformed, or an annotation is empty.
    """
    pieces: list[str] = []
    annotations: list[Annotation] = []
    cursor = 0
    length = 0

    for match in _MARKUP_RE.finditer(annotated):
        before = annotated[cursor : match.start()]
        pieces.append(before)
        length += len(before)

        value = match.group(2)
        if not value:
            raise ConfigurationError(f"empty annotation in: {annotated[:60]!r}")
        pieces.append(value)
        annotations.append(
            Annotation(entity_type=match.group(1), span=Span(length, length + len(value)))
        )
        length += len(value)
        cursor = match.end()

    tail = annotated[cursor:]
    pieces.append(tail)
    text = "".join(pieces)

    if "[[" in text or "]]" in text:
        raise ConfigurationError(f"unbalanced annotation markup in: {annotated[:60]!r}")

    _assert_disjoint(annotations, annotated)
    return text, tuple(annotations)


def _assert_disjoint(annotations: Sequence[Annotation], origin: str) -> None:
    """Gold labels must not overlap: a character belongs to one entity or none."""
    previous_end = 0
    for annotation in sorted(annotations, key=lambda a: a.span.start):
        if annotation.span.start < previous_end:
            raise ConfigurationError(f"overlapping annotations in: {origin[:60]!r}")
        previous_end = annotation.span.end


def bundled_datasets(locale: str | None = None) -> tuple[Dataset, ...]:
    """Load the datasets shipped with the package.

    Args:
        locale: Restrict to one locale code, or ``None`` for all of them.
    """
    datasets = [Dataset.load(path) for path in sorted(_DATA_DIR.glob("*.json"))]
    if locale is not None:
        datasets = [dataset for dataset in datasets if dataset.locale == locale]
    return tuple(datasets)


#: Where the bundled datasets live. Exposed so a contributor can find them.
DATA_DIR = _DATA_DIR
