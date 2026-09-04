"""Rules an organisation writes, in the configuration file.

Everything this library detects was, until now, something it shipped. A
company whose case references look like ``CS/2026/0041``, or whose employee
numbers are ``ACME-004512``, had three options and all three were bad: write a
locale pack in Python and register it at import time, rule on each value
individually with ``mamori correct``, or accept the miss.

So a rule is now four lines of a `mamori.toml`::

    [[patterns]]
    type = "EMPLOYEE_ID"
    pattern = 'ACME-\\d{6}'
    confidence = 0.95

and a type nobody has heard of is five::

    [[patterns]]
    type = "CASE_REFERENCE"
    category = "PII"
    pattern = 'CS/\\d{4}/\\d{4}'

In a `pyproject.toml` the same tables are ``[[tool.mamori.patterns]]``. Single
quotes on the pattern, because a TOML basic string would eat the backslashes
before this ever saw them.

They run beside the built-in rules, in the same pass, arbitrated by the same
resolution: a custom rule is not a special case with its own precedence, it is
a rule.

**A regular expression from a configuration file is a performance decision
somebody made without meaning to.** 0.33 removed two quadratics from this
library's own rules -- a 128KB answer with one base64 blob in it took 456
seconds -- and it would be a poor joke to close that door and then hold it
open for everybody else. So every pattern here is **timed against adversarial
input before it is accepted**, at two sizes, and one whose cost grows faster
than its input is refused at startup with the shape that did it.

That check is empirical rather than analytical on purpose. Deciding whether a
regular expression backtracks catastrophically is genuinely hard; running it
on eight thousand characters of ``aaaa...`` and looking at the clock is not.
It cannot prove a pattern is safe -- an input nobody thought of is always
possible -- and it catches every shape that broke this library's own rules,
which is the population it was built from.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from typing import Any

from ...domain.confidence import Confidence
from ...domain.entity_types import Category, EntityType, get_type, register_type
from ...domain.stance import RuleTier
from ...errors import ConfigurationError
from .patterns import PatternRule

__all__ = ["ADVERSARIAL_SHAPES", "MAX_GROWTH", "compile_custom_rules", "time_pattern"]

#: Runs of the characters rules are built out of, with no match anywhere in
#: them, so a backtracking engine does its worst. The same set
#: `tests/test_scaling.py` holds every shipped rule to -- one list, so a
#: pattern somebody writes is judged by the standard this library's own rules
#: are judged by.
ADVERSARIAL_SHAPES: Mapping[str, str] = {
    "a run of letters": "a",
    "a run of digits": "1",
    "dotted": "a.",
    "hyphens": "-",
    "underscored": "a_",
    "at signs": "a@",
    "slashes": "a/",
    "spaces": "a ",
    "mixed": "aA1-_.",
    "CJK": "田",
}

#: Sizes to compare. Small enough that a quadratic pattern costs tens of
#: milliseconds here rather than seconds, and far enough apart that the ratio
#: separates linear from quadratic without a stopwatch argument: four times the
#: input is about four times the work, or about sixteen.
_SMALL = 1_000
_LARGE = 4_000

#: Four times the input. Linear is about 4; the two quadratics this library
#: removed in 0.33 were about 16. Eight is the line between them, with room for
#: a machine that is busy -- and the failure this catches is a factor of four
#: out, not a few percent.
MAX_GROWTH = 8.0

#: Below this a measurement is noise and the ratio means nothing. A pattern
#: that takes under a millisecond on four thousand characters is not the
#: problem this check is for.
_FLOOR_SECONDS = 0.001

_KNOWN_KEYS = frozenset(
    {"type", "category", "pattern", "confidence", "tier", "group", "name", "severity"}
)

_TIERS = {"core": RuleTier.CORE, "wide": RuleTier.WIDE}


def time_pattern(pattern: re.Pattern[str]) -> tuple[str, float] | None:
    """The worst shape for this pattern and how fast its cost grew, or ``None``.

    Returns ``None`` when nothing grew faster than :data:`MAX_GROWTH`, which is
    what an ordinary pattern does.
    """
    worst: tuple[str, float] | None = None
    for label, unit in ADVERSARIAL_SHAPES.items():
        small = _fastest(pattern, unit * (_SMALL // len(unit)))
        large = _fastest(pattern, unit * (_LARGE // len(unit)))
        if large < _FLOOR_SECONDS:
            continue
        growth = large / max(small, 1e-9)
        if growth > MAX_GROWTH and (worst is None or growth > worst[1]):
            worst = (label, growth)
    return worst


def _fastest(pattern: re.Pattern[str], text: str, repeats: int = 3) -> float:
    """The best of a few runs. Scheduling noise only ever adds time."""
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        pattern.search(text)
        best = min(best, time.perf_counter() - start)
    return best


def compile_custom_rules(entries: Sequence[Mapping[str, Any]]) -> tuple[PatternRule, ...]:
    """Turn configuration entries into rules, refusing the ones that cannot be.

    Args:
        entries: One mapping per rule. ``type`` and ``pattern`` are required;
            ``category`` is required when ``type`` names a type nothing has
            registered yet.

    Raises:
        ConfigurationError: an unknown key, a missing one, a pattern that will
            not compile, or a pattern whose cost grows faster than its input.
            Every one of them is raised when the configuration is read, so a
            deployment with a bad rule fails at startup and not on somebody's
            document.
    """
    return tuple(_one(index, entry) for index, entry in enumerate(entries))


def _one(index: int, entry: Mapping[str, Any]) -> PatternRule:
    where = f"patterns[{index}]"
    if not isinstance(entry, Mapping):
        raise ConfigurationError(f"{where} must be a mapping, got {type(entry).__name__}")

    unknown = sorted(set(entry) - _KNOWN_KEYS)
    if unknown:
        raise ConfigurationError(
            f"{where}: unknown key(s) {', '.join(unknown)}; known keys: "
            f"{', '.join(sorted(_KNOWN_KEYS))}"
        )
    for required in ("type", "pattern"):
        if required not in entry:
            raise ConfigurationError(f"{where}: '{required}' is required")

    entity_type = _entity_type(where, entry)
    pattern = _pattern(where, str(entry["pattern"]))
    confidence = _confidence(where, entry.get("confidence", 0.9))
    tier = _tier(where, entry.get("tier", "core"))
    group = _group(where, entry.get("group", 0), pattern)
    name = str(entry.get("name") or f"custom.{entity_type.name}.{index + 1}")

    return PatternRule(
        entity_type=entity_type,
        pattern=pattern,
        confidence=confidence,
        group=group,
        tier=tier,
        name=name,
    )


def _entity_type(where: str, entry: Mapping[str, Any]) -> EntityType:
    """The type this rule reports, registering it when it is new.

    A new type needs a category, because the category is what the policy falls
    back to and a type with no category would inherit `OTHER` -- which the
    default policy blocks. Silently blocking every match of a rule somebody
    just wrote is not a helpful default; asking for one word is.
    """
    name = str(entry["type"]).strip().upper()
    existing = get_type(name)
    if "category" not in entry:
        if existing is None:
            raise ConfigurationError(
                f"{where}: {name!r} is not a known entity type, so 'category' is "
                f"required. Allowed: {', '.join(c.value for c in Category)}. Pick "
                "the one whose default action you want this to inherit."
            )
        return existing

    try:
        category = Category(str(entry["category"]).strip().upper())
    except ValueError as exc:
        allowed = ", ".join(c.value for c in Category)
        raise ConfigurationError(
            f"{where}: unknown category {entry['category']!r}; allowed: {allowed}"
        ) from exc

    severity = _severity(where, entry.get("severity", 60))
    try:
        return register_type(EntityType(name=name, category=category, severity=severity))
    except ValueError as exc:
        # Either the name is not a legal placeholder type, or the same name is
        # already registered with different settings. Both are worth the
        # original message, which says which.
        raise ConfigurationError(f"{where}: {exc}") from exc


def _pattern(where: str, source: str) -> re.Pattern[str]:
    try:
        compiled = re.compile(source)
    except re.error as exc:
        raise ConfigurationError(
            f"{where}: {source!r} is not a valid regular expression: {exc}"
        ) from exc

    worst = time_pattern(compiled)
    if worst is not None:
        shape, growth = worst
        raise ConfigurationError(
            f"{where}: {source!r} costs {growth:.0f}x more for four times the input "
            f"on {shape}, which means the length of a document decides how long a "
            "request takes. Bound the repetitions -- `{1,64}` rather than `+` -- or "
            "add a boundary such as `(?<![A-Za-z0-9])` so the scan cannot restart "
            "inside a run it has already rejected. Both fixes are what this "
            "library's own email rules needed."
        )
    return compiled


def _confidence(where: str, value: Any) -> Confidence:
    try:
        return Confidence(float(value))
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{where}: confidence must be a number in [0, 1]: {exc}") from exc


def _tier(where: str, value: Any) -> RuleTier:
    text = str(value).strip().lower()
    if text not in _TIERS:
        raise ConfigurationError(
            f"{where}: unknown tier {value!r}; allowed: {', '.join(sorted(_TIERS))}. "
            "'core' runs under both stances; 'wide' runs only under recall_first, "
            "which is where a rule that matches on shape alone belongs."
        )
    return _TIERS[text]


def _group(where: str, value: Any, pattern: re.Pattern[str]) -> int:
    try:
        group = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{where}: group must be an integer") from exc
    if not 0 <= group <= pattern.groups:
        raise ConfigurationError(
            f"{where}: group {group} but the pattern has {pattern.groups}. A group "
            "is how a rule matches on context and redacts only part of it -- "
            "`password: (\\S+)` replaces the password and not the word."
        )
    return group


def _severity(where: str, value: Any) -> int:
    try:
        severity = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{where}: severity must be an integer 0-100") from exc
    if not 0 <= severity <= 100:
        raise ConfigurationError(f"{where}: severity out of range: {severity}")
    return severity
