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

import gc
import time
import tracemalloc
from collections.abc import Callable
from typing import Any, ClassVar

import pytest

from mamori import MamoriConfig

#: Shapes chosen to make a backtracking engine work: long runs of the
#: characters the rules are built out of, with no match anywhere in them.
#:
#: **Built from `ADVERSARIAL_SHAPES`, not copied from it.** There were two
#: lists -- this one, and the one a custom rule is judged by -- and they had
#: already drifted once: neither had a long run of uppercase, and the English
#: company rule was quadratic on exactly that, found by `mamori bench` after
#: both had passed it. One list now, in the package, so a shape added because
#: a shipped rule broke is the same shape a user's rule is held to. The
#: entries below the loop are test-only extras that make sense against a
#: hundred rules and not against one.
from mamori.domain.normalization import NormalizedText
from mamori.domain.placeholder import Placeholder
from mamori.domain.placeholder_matching import scan_placeholders
from mamori.domain.policy import PrivacyPolicy
from mamori.domain.script import Script, script_regions
from mamori.infrastructure.detectors.custom import ADVERSARIAL_SHAPES
from mamori.infrastructure.detectors.locales import resolve_locales
from mamori.infrastructure.detectors.patterns import UNIVERSAL_RULES


def _repeated(unit: str) -> Callable[[int], str]:
    """``unit`` repeated to exactly ``n`` characters."""
    return lambda n: (unit * (n // len(unit) + 1))[:n]


SHAPES: dict[str, Callable[[int], str]] = {
    label: _repeated(unit) for label, unit in ADVERSARIAL_SHAPES.items()
}
SHAPES.update(
    {
        "slashes": lambda n: "a/" * (n // 2),
        "colons": lambda n: "a:" * (n // 2),
        "plus": lambda n: "a+" * (n // 2),
        "percent": lambda n: "a%" * (n // 2),
        "kana": lambda n: "た" * n,
        "quotes": lambda n: 'a"' * (n // 2),
        "equals": lambda n: "a=" * (n // 2),
    }
)

SMALL = 4_000
LARGE = 16_000

#: Four times the input. Linear is about 4; the email rules were about 16.
#: Eight is the line between them, with room for a noisy machine on the small
#: measurement -- and the failure this catches is a factor of four out, not a
#: few percent.
MAX_GROWTH = 8.0

#: Below this the large measurement is noise and its ratio to the small one
#: means nothing. A busy Windows runner reported the internal-IP rule -- a
#: pattern with every repetition bounded, linear at every size measured here
#: -- as x19.8 on the spaces shape: 0.3ms against 5.4ms, one scheduling hiccup
#: on a measurement that small. The three quadratics this file exists for
#: measured 160 to 850 milliseconds at this size, so twenty milliseconds
#: costs nothing in sensitivity and removes the flake.
MIN_MEASURED_SECONDS = 0.020

#: Best of this many. Noise only ever adds time, and a fast rule costs
#: microseconds a run, so more runs are cheap where they matter and free
#: where they do not.
REPEATS = 5


def _fastest(work: Callable[[], object], repeats: int = REPEATS) -> float:
    """The best of a few runs. Scheduling noise only ever adds time."""
    return min(_once(work) for _ in range(repeats))


def _once(work: Callable[[], object]) -> float:
    start = time.perf_counter()
    work()
    return time.perf_counter() - start


def _scan(pattern: Any, text: str) -> Callable[[], object]:
    """A closure over *this* pattern, not over the loop variable."""
    return lambda: list(pattern.finditer(text))


def _all_rules() -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = [("universal", rule) for rule in UNIVERSAL_RULES]
    for pack in resolve_locales(None):
        found.extend((pack.code, rule) for rule in pack.rules)
    return found


def _peak_per_character(work: Callable[[], object], size: int) -> float:
    """Bytes of peak Python allocation per input character.

    `tracemalloc` counts what Python allocated, not RSS. That is the right
    number here: what varies with the document is objects this library makes,
    and the interpreter's own floor is a constant that would only blur the
    measurement.
    """
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    held = work()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert held is not None
    return (peak - before) / size


class TestMemoryIsAlsoACost:
    """Peak allocation per input character, which nothing measured until 0.34.

    `mamori bench` measures time. Time was the cost that had bitten -- two
    quadratics in 0.33 -- so time is what got a command. But the proxy holds
    one thread per connection, and how many documents a machine can have in
    flight is decided by this number, not by that one.

    Measured when this class was written: a `protect` peaked at **157 bytes
    per input character**, and **80 of those were an offset map** that, for
    every one of the bench shapes, was `range(n)` and `range(1, n + 1)`
    materialised into tuples of boxed integers. A 200 KB document paid 14 MB
    to write down that character 40,000 is at character 40,000.
    """

    SIZE: ClassVar[int] = 120_000

    def document(self, unit: str) -> str:
        text = unit
        while len(text) < self.SIZE:
            text += text
        return text[: self.SIZE]

    @pytest.mark.parametrize(
        ("label", "unit"),
        [
            ("ascii", "Dear Jane Doe, please contact john.smith@example.com.\n"),
            ("japanese", "田中太郎さんへ。tanaka@example.com までご返信ください。\n"),
        ],
    )
    def test_an_offset_map_that_is_the_identity_costs_nothing(self, label: str, unit: str) -> None:
        """The common case, and the one that was paying the most.

        Both of these normalize to themselves -- ASCII always does, and
        Japanese written the ordinary way does too. `NormalizedText.of`
        already had a fast path saying so; it then built the two tuples
        anyway, one boxed `int` per character in each.
        """
        text = self.document(unit)
        normalized = NormalizedText.of(text)
        assert normalized.text == text, "this sample was supposed to fold to itself"

        cost = _peak_per_character(lambda: NormalizedText.of(text), len(text))
        assert cost < 8, f"{label}: {cost:.1f} bytes per character for an identity map"

    def test_the_map_still_maps(self) -> None:
        """The saving is only a saving if the answers did not change.

        Every position in a document long enough to be past the small-integer
        cache, where a `range` and a tuple of boxed integers stop being
        interchangeable by accident and start being interchangeable because
        indexing is indexing.
        """
        text = self.document("Contact john.smith@example.com or Jane Doe.\n")
        normalized = NormalizedText.of(text)
        for start in range(0, len(text) - 4, 997):
            span = normalized.to_original_span(start, start + 4)
            assert (span.start, span.end) == (start, start + 4)
            assert text[span.start : span.end] == normalized.text[start : start + 4]

    def test_a_fold_that_is_not_the_identity_still_maps(self) -> None:
        """The slow path, which cannot be a `range` and is measured separately.

        Half-width katakana is the shape that made this map necessary: `ﾀ` plus
        `ﾞ` is two characters that fold to one, so normalized position and
        original position stop agreeing and every later character is shifted.
        """
        text = "ﾀﾞﾝｽ " * 4000
        normalized = NormalizedText.of(text)
        assert normalized.text != text

        for start in range(0, len(normalized.text) - 2, 331):
            span = normalized.to_original_span(start, start + 2)
            assert span.end > span.start
            assert 0 <= span.start < span.end <= len(text)

        cost = _peak_per_character(lambda: NormalizedText.of(text), len(text))
        assert cost < 70, f"{cost:.1f} bytes per character on the folding path"

    def test_a_whole_protection_stays_under_what_it_used_to_cost(self) -> None:
        """The number a deployment actually feels, with a wide margin.

        This is not a target. It is the ceiling that says the offset map did
        not come back, and it is loose enough that ordinary work under it
        does not have to argue with it.
        """
        text = self.document(
            "田中太郎さんへ\n株式会社さくら商事の佐藤花子です。tanaka@example.com か "
            "090-1234-5678 へ。\nCC: Mr. John Smith (Acme Inc.), 415-555-0198.\n"
        )
        session = MamoriConfig().session(policy=PrivacyPolicy.permissive())
        cost = _peak_per_character(lambda: session.protect(text), len(text))
        assert cost < 130, f"{cost:.1f} bytes per input character at peak"


class TestNoRuleIsSuperlinear:
    """One parametrisation per shape, over every rule this library ships.

    Per rule rather than per pipeline: a pipeline test says *something* got
    slow, and this says which pattern and on what -- which is the difference
    between a bug report and an afternoon.
    """

    @pytest.mark.parametrize("shape", sorted(SHAPES))
    def test_four_times_the_input_costs_about_four_times(self, shape: str) -> None:
        build = SHAPES[shape]
        small_text = build(SMALL)
        large_text = build(LARGE)

        offenders: list[str] = []
        for origin, rule in _all_rules():
            pattern = rule.pattern  # type: ignore[attr-defined]
            small = _fastest(_scan(pattern, small_text))
            large = _fastest(_scan(pattern, large_text))
            if large > MAX_GROWTH * small and large > MIN_MEASURED_SECONDS:
                offenders.append(
                    f"{origin}/{rule.entity_type.name} "  # type: ignore[attr-defined]
                    f"{small * 1000:.1f}ms -> {large * 1000:.1f}ms "
                    f"(x{large / small:.1f})"
                )
        assert not offenders, f"superlinear on {shape!r}: " + "; ".join(offenders)


class TestTheWholePipelineStaysLinear:
    """The rules are linear individually; this says the assembly is too.

    **Growth, not a stopwatch.** The first version of this asserted that
    200,000 characters of CJK took under five seconds. It took 1.7 here and
    5.06 on a CI runner, which is a test that fails when somebody else's build
    is busy -- and a flaky test is worse than no test, because the first red is
    read as noise and so is the second. The ratio is a property of the
    patterns; the absolute time is a property of the machine.

    The budget below survives as a backstop with two orders of magnitude of
    room, for the case where something is slow in a way that does not show up
    as growth at all.
    """

    SMALL = 25_000
    LARGE = 100_000

    #: Generous by about thirty times. Before the email bounds, 32,000
    #: characters took four seconds and 100,000 would have taken forty.
    BUDGET_SECONDS = 20.0

    @pytest.mark.parametrize("shape", ["a run of letters", "hyphens", "dotted", "CJK", "base64"])
    def test_four_times_the_document_costs_about_four_times(self, shape: str) -> None:
        build = SHAPES[shape]
        session = MamoriConfig().session()
        small_text = build(self.SMALL)
        large_text = build(self.LARGE)

        small = _fastest(lambda: session.inspect(small_text), repeats=2)
        large = _fastest(lambda: session.inspect(large_text), repeats=2)

        assert large < self.BUDGET_SECONDS, (
            f"{shape}: {self.LARGE:,} characters took {large:.1f}s, which is slow "
            "in a way that does not show up as growth"
        )
        assert large < MAX_GROWTH * small, (
            f"{shape}: {self.SMALL:,} took {small * 1000:.0f}ms and {self.LARGE:,} "
            f"took {large * 1000:.0f}ms, a factor of {large / small:.1f} for four "
            "times the document"
        )


class TestTwoLanguagesInOneDocumentStayLinear:
    """The shape every other scaling test here misses.

    All of those repeat one unit, so a Japanese document is kana in every
    sentence -- and the Chinese pack is then skipped outright rather than run
    and filtered. The filtering path had no shape that reached it.

    A document that alternates is where it lives, and a Japanese office
    writing about Chinese counterparties produces one by lunchtime. Each
    sentence becomes its own region, so regions grow with the document; so do
    the candidate entities being checked against them; and the check was a
    scan over every region. Both factors linear in the length makes the whole
    thing **quadratic in the length**.

    Measured on the commit that fixed it, 25,000 -> 100,000 characters:

        scan     266 ms -> 2,254 ms   (x8.5 for x4 input; 94 -> 44 chars/ms)
        bisect    85 ms ->   349 ms   (x4.1 for x4 input; 294 -> 287 chars/ms)

    The throughput *falling* as the document grows is the signature. It is the
    fourth quadratic found in this library and the first one that needed a
    document with two languages in it to see.
    """

    SMALL: ClassVar[int] = 25_000
    LARGE: ClassVar[int] = 100_000

    #: Japanese and Chinese sentences in turn, so that no run of sentences is
    #: all one language and every boundary starts a new region.
    UNIT: ClassVar[str] = (
        "田中太郎さんへ。张伟先生请联系我们。ご確認ください。李娜女士的电话是13812345678。\n"
    )

    def document(self, size: int) -> str:
        text = self.UNIT
        while len(text) < size:
            text += text
        return text[:size]

    def test_four_times_the_document_costs_about_four_times(self) -> None:
        session = MamoriConfig().session()
        small_text = self.document(self.SMALL)
        large_text = self.document(self.LARGE)
        session.inspect(small_text[:2000])

        small = _fastest(lambda: session.inspect(small_text), repeats=2)
        large = _fastest(lambda: session.inspect(large_text), repeats=2)

        assert small > MIN_MEASURED_SECONDS, (
            f"{small * 1000:.0f}ms is too small to take a ratio from"
        )
        assert large < MAX_GROWTH * small, (
            f"{self.SMALL:,} took {small * 1000:.0f}ms and {self.LARGE:,} took "
            f"{large * 1000:.0f}ms, a factor of {large / small:.1f} for four times "
            "the document. Two languages in one document is the shape where the "
            "region check is asked once per candidate against every region."
        )

    def test_the_document_really_does_make_many_regions(self) -> None:
        """Otherwise the test above measures the path that skips the filtering.

        A run of sentences that are all one language collapses to one region,
        and `_reaches_everywhere` then drops the other pack without checking
        anything -- which is fast, correct, and not what is being measured.
        """
        regions = script_regions(self.document(self.SMALL), frozenset({Script.KANA}))
        assert len(regions) > 200, f"only {len(regions)} regions; this shape is not the shape"

    def test_both_languages_are_still_found(self) -> None:
        """Speed that lost a detection is not speed."""
        session = MamoriConfig().session()
        found = set(session.inspect(self.UNIT * 3))
        assert "PERSON" in found, f"only found {sorted(found)}"
        assert "PHONE" in found, f"only found {sorted(found)}"


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
