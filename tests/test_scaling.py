"""Cost as a function of input size, for input nobody chose.

Every rule in this library is a regular expression over text somebody else
wrote. That is fine until one of them is superlinear, and then the shape of a
document decides how long a request takes -- which is a denial of service
reachable by a base64 attachment, an identifier column, or a rule of hyphens
in a Markdown file. None of those is an attack; all of them are Tuesday.

**Measured before these tests existed**, at four times the input:

    protect, 8KB -> 32KB of `aaaa...`      260ms -> 4,057ms   (x15.6)
    protect, 8KB -> 32KB of `------`       270ms -> 4,186ms   (x15.5)
    restore, 8KB -> 128KB of `aaaa...`   1,298ms -> 455,890ms

Two causes, both now bounded and both bounded by somebody else's number
rather than by a preference: the email rules' unbounded local part (RFC 5321
says 64) and the lenient placeholder scanner's unbounded type name (this
library's own `TYPE_NAME_RE` says 63).

A survey of all ~100 compiled rules across the universal set and the three
language packs, against sixteen adversarial shapes at two sizes, found the two
email rules and nothing else. This file is what keeps that true.
"""

from __future__ import annotations

import time
from typing import ClassVar

import pytest

from mamori import MamoriConfig
from mamori.domain.placeholder import Placeholder
from mamori.domain.placeholder_matching import scan_placeholders
from mamori.infrastructure.detectors.locales import resolve_locales
from mamori.infrastructure.detectors.patterns import UNIVERSAL_RULES

#: Shapes chosen to make a backtracking engine work: long runs of the
#: characters the rules are built out of, with no match anywhere in them.
SHAPES: dict[str, object] = {
    "alnum run": lambda n: "a" * n,
    "digits": lambda n: "1" * n,
    "dots": lambda n: "a." * (n // 2),
    "hyphens": lambda n: "-" * n,
    "underscores": lambda n: "a_" * (n // 2),
    "at signs": lambda n: "a@" * (n // 2),
    "slashes": lambda n: "a/" * (n // 2),
    "colons": lambda n: "a:" * (n // 2),
    "spaces": lambda n: "a " * (n // 2),
    "plus": lambda n: "a+" * (n // 2),
    "percent": lambda n: "a%" * (n // 2),
    "mixed": lambda n: "aA1-_." * (n // 6),
    "cjk": lambda n: "田" * n,
    "kana": lambda n: "た" * n,
    "quotes": lambda n: 'a"' * (n // 2),
    "equals": lambda n: "a=" * (n // 2),
}

SMALL = 4_000
LARGE = 16_000

#: Four times the input. Linear is about 4; the email rules were about 16.
#: Eight is the line between them, with room for a noisy machine on the small
#: measurement -- and the failure this catches is a factor of four out, not a
#: few percent.
MAX_GROWTH = 8.0


def _fastest(work: object, repeats: int = 3) -> float:
    """The best of a few runs. Scheduling noise only ever adds time."""
    return min(_once(work) for _ in range(repeats))  # type: ignore[arg-type]


def _once(work: object) -> float:
    start = time.perf_counter()
    work()  # type: ignore[operator]
    return time.perf_counter() - start


def _scan(pattern: object, text: str) -> object:
    """A closure over *this* pattern, not over the loop variable."""
    return lambda: list(pattern.finditer(text))  # type: ignore[attr-defined]


def _all_rules() -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = [("universal", rule) for rule in UNIVERSAL_RULES]
    for pack in resolve_locales(None):
        found.extend((pack.code, rule) for rule in pack.rules)
    return found


class TestNoRuleIsSuperlinear:
    """One parametrisation per shape, over every rule this library ships.

    Per rule rather than per pipeline: a pipeline test says *something* got
    slow, and this says which pattern and on what -- which is the difference
    between a bug report and an afternoon.
    """

    @pytest.mark.parametrize("shape", sorted(SHAPES))
    def test_four_times_the_input_costs_about_four_times(self, shape: str) -> None:
        build = SHAPES[shape]
        small_text = build(SMALL)  # type: ignore[operator]
        large_text = build(LARGE)  # type: ignore[operator]

        offenders: list[str] = []
        for origin, rule in _all_rules():
            pattern = rule.pattern  # type: ignore[attr-defined]
            small = _fastest(_scan(pattern, small_text))
            large = _fastest(_scan(pattern, large_text))
            if large > MAX_GROWTH * small and large > 0.005:
                offenders.append(
                    f"{origin}/{rule.entity_type.name} "  # type: ignore[attr-defined]
                    f"{small * 1000:.1f}ms -> {large * 1000:.1f}ms "
                    f"(x{large / small:.1f})"
                )
        assert not offenders, f"superlinear on {shape!r}: " + "; ".join(offenders)


class TestTheWholePipelineStaysLinear:
    """The rules are linear individually; this says the assembly is too."""

    BUDGET_SECONDS = 5.0

    @pytest.mark.parametrize("shape", ["alnum run", "hyphens", "dots", "cjk"])
    def test_a_large_document_is_inspected_within_budget(self, shape: str) -> None:
        text = SHAPES[shape](200_000)  # type: ignore[operator]
        session = MamoriConfig().session()
        elapsed = _once(lambda: session.inspect(text))
        assert elapsed < self.BUDGET_SECONDS, (
            f"{shape}: 200,000 characters took {elapsed:.1f}s. Before the email "
            "bounds, 32,000 took four seconds and this would take minutes."
        )


class TestTheScanOfAnAnswerStaysLinear:
    """`restore` reads the whole of a model's answer, whatever is in it."""

    BUDGET_SECONDS = 5.0

    ANSWERS: ClassVar[dict[str, str]] = {
        "one alphanumeric run": "a" * 200_000,
        "a base64 blob": "here it is: " + ("QUJDREVGR0hJSktMTU5PUFFSU1Q" * 7_500),
        "a word then spaces": "PERSON" + " " * 200_000 + "!",
        "brackets": "<" * 200_000,
        "underscored run": "PERSON_" * 28_000,
    }

    @pytest.mark.parametrize("shape", sorted(ANSWERS))
    def test_a_large_answer_is_scanned_within_budget(self, shape: str) -> None:
        known = frozenset({Placeholder("PERSON", 1)})
        elapsed = _once(lambda: scan_placeholders(self.ANSWERS[shape], known))
        assert elapsed < self.BUDGET_SECONDS, (
            f"{shape}: {len(self.ANSWERS[shape])} characters took {elapsed:.1f}s"
        )


class TestManyRulesCostWhatManyRulesShouldCost:
    """The other half of *"after release, with a lot of patterns"*.

    Rules are applied one at a time, so a deployment that registers a hundred
    of its own pays a hundred times one rule -- linear in rules, which is the
    honest answer and worth stating rather than discovering. What must **not**
    happen is worse than linear.
    """

    def test_cost_grows_with_the_number_of_rules_and_no_faster(self) -> None:
        from mamori.domain import entity_types as t
        from mamori.domain.confidence import MEDIUM
        from mamori.infrastructure.detectors.patterns import compile_rule
        from mamori.infrastructure.detectors.regex_detector import RegexDetector

        text = ("The quick brown fox jumps over the lazy dog. " * 400)[:16_000]
        made = [
            compile_rule(t.IDENTIFIER, rf"(?<![A-Za-z0-9])ZZ{index:03d}-\d{{4}}", MEDIUM)
            for index in range(200)
        ]

        few = _fastest(lambda: RegexDetector("few", tuple(made[:25])).detect(text))
        many = _fastest(lambda: RegexDetector("many", tuple(made)).detect(text))
        # Eight times the rules. Linear is about 8; the assertion is that
        # nothing quadratic in rule count crept into the detector.
        assert many < few * 16, (
            f"25 rules took {few * 1000:.1f}ms and 200 took {many * 1000:.1f}ms, "
            f"a factor of {many / few:.1f} for eight times the rules"
        )
