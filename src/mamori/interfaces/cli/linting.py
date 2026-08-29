"""``mamori lint``: the values that should not have been committed.

A prompt template with a real customer's address in it. A test fixture built
from a support ticket somebody pasted. A notebook whose output cell still holds
the query that produced it. None of these reach a model through this library --
they reach it through a repository, and the first time anybody looks is after
the repository has been cloned.

This is the same detector set the rest of the package uses, pointed at files
instead of prompts, with three differences that matter for the job:

**It reports lines, not spans.** A finding is something a person has to go and
look at, and what they need is a path and a line number their editor
understands.

**It never prints a value.** These outputs land in CI logs, which are archived,
searchable, and often more widely readable than the repository. A masked
preview says what shape the thing was; the file says the rest.

**It fails on credentials by default and reports the rest.** A leaked key is an
incident. A customer's name in a fixture is a decision somebody should make on
purpose, and a linter that exits non-zero for both trains its users to pass
``--no-verify``. ``--fail-on any`` is there for a repository that has made the
other decision.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from ...application.results import mask_preview
from ...config import MamoriConfig
from ...domain.entity_types import Category
from ...domain.normalization import NormalizedText
from ...ports.detector import Detector

__all__ = ["Finding", "lint_paths", "scan_file"]

#: Directories never worth walking into. Everything here is either somebody
#: else's code, a build product, or a copy of what is already being scanned.
SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "dist",
        "build",
        "site-packages",
        ".idea",
        ".vscode",
    }
)

#: Suffixes that are not text. Reading them is wasted work and any match is a
#: coincidence of bytes rather than a value somebody wrote.
SKIP_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".bmp",
        ".tif",
        ".tiff",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".7z",
        ".rar",
        ".jar",
        ".whl",
        ".mp3",
        ".mp4",
        ".mov",
        ".avi",
        ".wav",
        ".ogg",
        ".webm",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".so",
        ".dll",
        ".dylib",
        ".exe",
        ".bin",
        ".o",
        ".a",
        ".pyc",
        ".pyd",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".parquet",
    }
)

#: Files larger than this are skipped and said to have been skipped. A linter
#: that reads a gigabyte to look for a name is a linter people turn off.
DEFAULT_MAX_BYTES = 1_000_000

#: How much of a file to look at when deciding whether it is text at all.
_SNIFF_BYTES = 8192


@dataclass(frozen=True, slots=True)
class Finding:
    """One value in one place. Never the value itself."""

    path: Path
    line: int
    entity_type: str
    category: str
    confidence: float
    #: Masked form, e.g. ``t**********@e*****.com``.
    preview: str
    #: The rule that found it, for arguing with.
    source: str

    @property
    def is_credential(self) -> bool:
        return self.category == Category.SECRET.value

    def describe(self, root: Path | None = None) -> str:
        shown = self.path
        if root is not None:
            try:
                shown = self.path.relative_to(root)
            except ValueError:
                pass
        return (
            f"{shown}:{self.line}: {self.entity_type} "
            f"({self.confidence:.2f}, {self.source}) {self.preview}"
        )

    def as_mapping(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "line": self.line,
            "type": self.entity_type,
            "category": self.category,
            "confidence": round(self.confidence, 3),
            "preview": self.preview,
            "source": self.source,
        }


def scan_file(path: Path, detectors: Sequence[Detector]) -> list[Finding]:
    """Findings in one file. Empty for anything that is not readable text."""
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    if b"\x00" in raw[:_SNIFF_BYTES]:
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return []

    normalized = NormalizedText.of(text)
    findings: list[Finding] = []
    for detector in detectors:
        for entity in detector.detect(normalized.text):
            start = normalized.to_original_span(entity.span.start, entity.span.end).start
            findings.append(
                Finding(
                    path=path,
                    line=text.count("\n", 0, start) + 1,
                    entity_type=entity.entity_type.name,
                    category=entity.entity_type.category.value,
                    confidence=entity.confidence.value,
                    preview=mask_preview(entity.value),
                    source=entity.source,
                )
            )
    findings.sort(key=lambda f: (str(f.path), f.line, f.entity_type))
    return _deduplicated(findings)


def walk(
    paths: Sequence[Path], *, exclude: Sequence[str] = (), max_bytes: int = DEFAULT_MAX_BYTES
) -> Iterator[tuple[Path, str]]:
    """Yield ``(path, reason)`` for every file worth reading, reason empty.

    A skipped file yields a reason instead, so ``--verbose`` can say what was
    not looked at. A linter that quietly skips things reports a clean run it
    did not earn.
    """
    for root in paths:
        if root.is_file():
            yield from _consider(root, exclude, max_bytes)
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRECTORIES for part in path.parts):
                continue
            yield from _consider(path, exclude, max_bytes)


def lint_paths(
    config: MamoriConfig,
    paths: Sequence[Path],
    *,
    exclude: Sequence[str] = (),
    max_bytes: int = DEFAULT_MAX_BYTES,
    types: Sequence[str] = (),
) -> tuple[list[Finding], list[tuple[Path, str]]]:
    """Scan ``paths``. Returns the findings and whatever was skipped."""
    detectors = list(config.detectors())
    wanted = {name.upper() for name in types}
    findings: list[Finding] = []
    skipped: list[tuple[Path, str]] = []

    for path, reason in walk(paths, exclude=exclude, max_bytes=max_bytes):
        if reason:
            skipped.append((path, reason))
            continue
        for finding in scan_file(path, detectors):
            if wanted and finding.entity_type not in wanted:
                continue
            findings.append(finding)
    return findings, skipped


def report(
    findings: Sequence[Finding],
    skipped: Sequence[tuple[Path, str]],
    *,
    root: Path | None = None,
    as_json: bool = False,
    verbose: bool = False,
) -> None:
    """Print what was found, in the shape an editor or a machine can read."""
    if as_json:
        print(
            json.dumps(
                {
                    "findings": [f.as_mapping() for f in findings],
                    "skipped": [{"path": str(p), "reason": r} for p, r in skipped],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    for finding in findings:
        print(finding.describe(root))

    if verbose:
        for path, reason in skipped:
            print(f"  skipped {path}: {reason}")

    credentials = sum(1 for f in findings if f.is_credential)
    if not findings:
        print("nothing found." + (f" {len(skipped)} file(s) skipped." if skipped else ""))
        return
    print()
    print(
        f"{len(findings)} finding(s) in {len({f.path for f in findings})} file(s); "
        f"{credentials} credential(s)."
    )
    if skipped and not verbose:
        print(f"{len(skipped)} file(s) skipped; --verbose to list them.")


def _consider(path: Path, exclude: Sequence[str], max_bytes: int) -> Iterator[tuple[Path, str]]:
    text = str(path).replace("\\", "/")
    if any(fnmatch(text, pattern) or fnmatch(path.name, pattern) for pattern in exclude):
        yield path, "excluded"
        return
    if path.suffix.lower() in SKIP_SUFFIXES:
        yield path, f"{path.suffix} is not text"
        return
    try:
        size = path.stat().st_size
    except OSError:
        yield path, "unreadable"
        return
    if size > max_bytes:
        yield path, f"{size} bytes, over the {max_bytes} limit"
        return
    yield path, ""


def _deduplicated(findings: Sequence[Finding]) -> list[Finding]:
    """One finding per (line, type, preview).

    Several rules matching the same value is normal -- an anchored rule and a
    shape rule both firing on one address -- and reporting it three times makes
    a clean file look like an incident.
    """
    seen: set[tuple[int, str, str]] = set()
    unique: list[Finding] = []
    for finding in findings:
        key = (finding.line, finding.entity_type, finding.preview)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique
