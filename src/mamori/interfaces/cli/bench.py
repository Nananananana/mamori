"""``mamori bench``: how fast this configuration is, on this machine, measured.

Every speed claim this library makes was, until now, a number somebody typed
into a document after running a script that was not shipped. `0.33` found two
quadratics that way and fixed them that way, and the fix is guarded by tests --
but a user asking *"how long will my 200-page contract take"* still had nothing
to run.

This is that. It protects and restores synthetic documents of known shape and
size, under the configuration you give it, and prints throughput per shape and
whether cost grew faster than input. Synthetic, deliberately: a benchmark over
your own documents would be a benchmark that reads your documents, and the
point of a number is that somebody else can get the same one.

What it is **not** is a leak measurement. `mamori eval` is that, and the two
questions are kept apart because a fast configuration that misses things and
a slow one that does not are both things a deployment might choose, and a
single score would hide which it had chosen.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import TextIO

from ...config import MamoriConfig
from ...domain.policy import PrivacyPolicy

__all__ = ["SHAPES", "BenchRow", "run_bench"]

#: Documents of known composition, by name. A short line repeated is not a
#: real document, and it does not need to be: the cost of a rule is the cost
#: of its scan, and what varies between real documents is the mix of scripts
#: and the density of things to find -- which is what these vary.
SHAPES: Mapping[str, str] = {
    "english-prose": (
        "Dear Jane Doe, thank you for your message about the quarterly review. "
        "Please contact john.smith@example.com or 415-555-0198 with any questions.\n"
    ),
    "japanese-prose": (
        "田中太郎さんへ。株式会社さくら商事の佐藤花子です。"
        "先日の件、tanaka@example.com か 090-1234-5678 にご返信ください。\n"
    ),
    "mixed-email": (
        "田中太郎さんへ\n株式会社さくら商事の佐藤花子です。tanaka@example.com か "
        "090-1234-5678 へ。\nCC: Mr. John Smith (Acme Inc.), 415-555-0198. Ref E-45033.\n"
    ),
    "json-payload": (
        '{"employee_id": "E-45033", "email": "priya@example.com", '
        '"phone": "415-555-0198", "ticket": "SUP-40127", "body": "see attached"}\n'
    ),
    "nothing-sensitive": (
        "The build is green and the deploy window opens at noon. "
        "Nothing in this line is anybody's business.\n"
    ),
    # The shapes that were quadratic. Kept in the default run so a regression
    # shows up here before it shows up in a proxy log.
    "one-long-token": "a",
    "base64-blob": "QUJDREVGR0hJSktMTU5PUFFSU1Q",
}

#: Sizes to compare. The ratio between them is the property being measured;
#: the absolute time is a fact about the machine and is reported as such.
SMALL = 25_000
LARGE = 100_000


@dataclass(frozen=True)
class BenchRow:
    """One shape, measured."""

    shape: str
    characters: int
    protect_ms: float
    restore_ms: float
    #: Characters per millisecond through `protect`. The number to compare
    #: across machines and configurations.
    protect_chars_per_ms: float
    #: `protect` time at four times the input, divided by the time at one
    #: times. Linear is about 4. The two quadratics 0.33 removed were about 16.
    growth: float
    entities: int


def _document(shape: str, size: int) -> str:
    unit = SHAPES[shape]
    return (unit * (size // len(unit) + 1))[:size]


def _fastest(work: Callable[[], object], repeats: int) -> float:
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        work()
        best = min(best, time.perf_counter() - start)
    return best


def measure(config: MamoriConfig, shape: str, *, repeats: int = 3) -> BenchRow:
    """Protect and restore one shape at two sizes, keeping the best of ``repeats``."""
    small_text = _document(shape, SMALL)
    large_text = _document(shape, LARGE)

    # Permissive, because this measures speed and not policy: 100,000
    # characters of base64 *is* a credential by every rule that matters, and
    # the default policy refuses to let it past. A benchmark that stopped at
    # the first block would never time the shape that was quadratic.
    with config.session(policy=PrivacyPolicy.permissive()) as session:
        small = _fastest(lambda: session.inspect(small_text), repeats)
        large = _fastest(lambda: session.inspect(large_text), repeats)
        protected = session.protect(large_text)
        restore = _fastest(lambda: session.restore(protected.protected_text), repeats)

    return BenchRow(
        shape=shape,
        characters=LARGE,
        protect_ms=round(large * 1000, 1),
        restore_ms=round(restore * 1000, 1),
        protect_chars_per_ms=round(LARGE / max(large * 1000, 1e-9)),
        growth=round(large / max(small, 1e-9), 1),
        entities=protected.entity_count,
    )


def run_bench(
    config: MamoriConfig,
    *,
    shapes: list[str] | None = None,
    repeats: int = 3,
    as_json: bool = False,
    out: TextIO | None = None,
) -> int:
    """Measure every shape and print the table, or the rows as JSON."""
    stream: TextIO = out if out is not None else sys.stdout
    names = shapes or list(SHAPES)
    rows = [measure(config, name, repeats=repeats) for name in names]

    if as_json:
        print(json.dumps([asdict(row) for row in rows], indent=2), file=stream)
        return 0

    print(
        f"{'shape':<18} {'chars':>8} {'protect':>10} {'restore':>10} "
        f"{'chars/ms':>9} {'x4 growth':>10} {'found':>6}",
        file=stream,
    )
    for row in rows:
        flag = "" if row.growth < 8 else "   <- superlinear"
        print(
            f"{row.shape:<18} {row.characters:>8,} {row.protect_ms:>8.1f}ms "
            f"{row.restore_ms:>8.1f}ms {row.protect_chars_per_ms:>9,.0f} "
            f"{row.growth:>10.1f}{row.entities:>6}{flag}",
            file=stream,
        )
    print(
        "\nchars/ms is the number to compare across machines. x4 growth is protect\n"
        "at 100,000 characters over protect at 25,000: about 4 is linear, about 16\n"
        "is the quadratic 0.33 removed. Synthetic documents on purpose -- a number\n"
        "somebody else can reproduce. Leak rates are `mamori eval`, not this.",
        file=stream,
    )
    return 0
