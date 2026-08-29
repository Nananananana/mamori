"""Reading and appending a correction log.

The log is operator-authored: somebody typed these values in, the way they
typed a configuration file. That makes it different from everything else this
package writes, and the difference is worth being explicit about because
mamori's storage claim is narrow and deliberate.

**Mappings are never written.** A mapping is derived from a document without
anybody deciding, so writing one would put a document on disk as a side effect.
That claim is unchanged.

**A correction is written only when asked.** ``mamori correct`` appends one
entry, and nothing else in the package ever writes here. Loading is a read.

**The file holds what the operator typed, and some of it is sensitive.** A
value ruled ``always`` is by definition something they consider sensitive --
a customer name, an internal codename -- and it is now in a file. That is the
operator's decision to make, and ``mamori privacy`` says so rather than leaving
it to be discovered.
"""

from __future__ import annotations

import json
from pathlib import Path

from ...domain.corrections import Correction, CorrectionLog, Verdict
from ...errors import ConfigurationError, StorageError

__all__ = ["append_correction", "dump_corrections", "load_corrections"]

_FORMAT_VERSION = 1

#: Said plainly in the file, because somebody will find it in a repository and
#: need to know what it is before they read the values in it.
_NOTE = (
    "A mamori correction log. Append-only: the latest entry about a value is "
    "the one that applies. Values marked 'always' are ones this operator "
    "considers sensitive, so this file should be treated accordingly."
)


def load_corrections(path: Path) -> CorrectionLog:
    """Read a correction log.

    A missing file is an empty log rather than an error: the common case is a
    configuration naming a log that has not been written to yet.

    Raises:
        ConfigurationError: The file exists and cannot be read as a log. A
            correction that cannot be parsed is not silently skipped -- an
            operator whose ruling was ignored would not find out.
    """
    if not path.exists():
        return CorrectionLog()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigurationError(f"could not read corrections: {path}") from exc
    return from_mapping(payload, origin=str(path))


def from_mapping(payload: object, origin: str = "<memory>") -> CorrectionLog:
    """Build a log from already-parsed JSON, or from a list of entries."""
    entries = payload.get("corrections") if isinstance(payload, dict) else payload
    if isinstance(payload, dict) and payload.get("format_version") not in (
        None,
        _FORMAT_VERSION,
    ):
        raise ConfigurationError(f"unsupported corrections format: {origin}")
    if not isinstance(entries, list):
        raise ConfigurationError(f"corrections must be a list: {origin}")

    log = CorrectionLog()
    for index, raw in enumerate(entries):
        log = log.appended(_correction_from(raw, index, origin))
    return log


def dump_corrections(log: CorrectionLog, path: Path) -> None:
    """Write the whole log, replacing what was there.

    Raises:
        StorageError: The file could not be written.
    """
    payload = {
        "format_version": _FORMAT_VERSION,
        "_note": _NOTE,
        "corrections": [c.as_mapping() for c in log],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise StorageError(f"could not write corrections: {path}") from exc


def append_correction(path: Path, correction: Correction) -> CorrectionLog:
    """Add one ruling to the log at ``path`` and write it back.

    Read, append, write. Not atomic against a second process appending at the
    same moment, which is the right trade for a file one person edits by
    running a command: locking it would add a failure mode more likely than the
    one it prevents.
    """
    log = load_corrections(path).appended(correction)
    dump_corrections(log, path)
    return log


def _correction_from(raw: object, index: int, origin: str) -> Correction:
    if not isinstance(raw, dict):
        raise ConfigurationError(f"correction {index} is not an object: {origin}")
    value = raw.get("value")
    if not isinstance(value, str):
        raise ConfigurationError(f"correction {index} has no value: {origin}")
    verdict_name = str(raw.get("verdict", "")).strip().lower()
    try:
        verdict = Verdict(verdict_name)
    except ValueError as exc:
        raise ConfigurationError(
            f"correction {index}: verdict must be 'never' or 'always', "
            f"got {verdict_name!r}: {origin}"
        ) from exc
    try:
        return Correction(
            value=value,
            verdict=verdict,
            entity_type=str(raw.get("entity_type", "")),
            note=str(raw.get("note", "")),
            recorded_at=str(raw.get("recorded_at", "")),
        )
    except ValueError as exc:
        raise ConfigurationError(f"correction {index}: {exc}: {origin}") from exc
