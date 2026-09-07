"""`ClaimedSpans`, held against the set of indices it replaced.

Every pass that reads prior findings asks *does this span touch anything
already found*. That was answered by building a `frozenset` of every covered
character index -- a structure whose size is a property of the text rather
than of the findings -- and testing membership one index at a time.

The replacement keeps the findings as ranges. It is the same answer computed
differently, so it is checked against the set rather than against an argument
about it: the pattern this project already uses for the normalisation fast
path and for the script-region search.
"""

from __future__ import annotations

import gc
import tracemalloc

from hypothesis import given
from hypothesis import strategies as st

from mamori.domain import entity_types as types
from mamori.domain.claimed import ClaimedSpans
from mamori.domain.confidence import HIGH
from mamori.domain.sensitive_entity import SensitiveEntity
from mamori.domain.span import Span
from mamori.ports.detection_pass import DetectionContext


def entity(start: int, end: int) -> SensitiveEntity:
    return SensitiveEntity(
        entity_type=types.PERSON,
        span=Span(start, end),
        value="x" * (end - start),
        confidence=HIGH,
        source="probe",
    )


spans = st.lists(
    st.tuples(st.integers(0, 60), st.integers(1, 12)).map(lambda p: (p[0], p[0] + p[1])),
    max_size=12,
)


def indices(pairs: list[tuple[int, int]]) -> set[int]:
    return {index for start, end in pairs for index in range(start, end)}


class TestItAgreesWithTheSetItReplaced:
    @given(pairs=spans, start=st.integers(0, 70), width=st.integers(1, 15))
    def test_overlap_is_the_same_question(
        self, pairs: list[tuple[int, int]], start: int, width: int
    ) -> None:
        claimed = ClaimedSpans(pairs)
        naive = indices(pairs)
        want = bool(naive & set(range(start, start + width)))
        assert claimed.overlaps(start, start + width) is want

    @given(pairs=spans)
    def test_the_characters_are_the_same_characters(self, pairs: list[tuple[int, int]]) -> None:
        assert ClaimedSpans(pairs).characters() == indices(pairs)

    @given(pairs=spans, extra=spans)
    def test_adding_as_it_goes_is_the_same_as_adding_up_front(
        self, pairs: list[tuple[int, int]], extra: list[tuple[int, int]]
    ) -> None:
        """The co-occurrence, recogniser and phone passes all claim their own
        findings as they accept them, so `add` after construction has to mean
        what passing everything to the constructor means."""
        incremental = ClaimedSpans(pairs)
        for start, end in extra:
            incremental.add(start, end)
        assert incremental.characters() == indices(pairs + extra)


class TestTheEdgesOfAHalfOpenRange:
    def test_nothing_overlaps_nothing(self) -> None:
        assert not ClaimedSpans().overlaps(0, 5)
        assert not ClaimedSpans()

    def test_touching_is_not_overlapping(self) -> None:
        claimed = ClaimedSpans([(10, 20)])
        assert not claimed.overlaps(5, 10)
        assert not claimed.overlaps(20, 25)
        assert claimed.overlaps(19, 20)

    def test_an_empty_range_claims_nothing(self) -> None:
        """A detector reporting one has a bug; keeping it would make `overlaps`
        answer about a character that is not there."""
        claimed = ClaimedSpans()
        claimed.add(5, 5)
        claimed.add(9, 3)
        assert not claimed
        assert claimed.characters() == frozenset()

    def test_touching_ranges_become_one(self) -> None:
        claimed = ClaimedSpans([(0, 5), (5, 10), (10, 15)])
        assert len(claimed) == 1
        assert claimed.characters() == set(range(15))

    def test_a_range_that_swallows_several(self) -> None:
        claimed = ClaimedSpans([(0, 2), (10, 12), (20, 22)])
        assert len(claimed) == 3
        claimed.add(1, 21)
        assert len(claimed) == 1
        assert claimed.characters() == set(range(22))


class TestTheContextAsksItTheCheapWay:
    def context(self, count: int, width: int) -> DetectionContext:
        text = "x" * (count * width * 2)
        found = tuple(entity(i * width * 2, i * width * 2 + width) for i in range(count))
        return DetectionContext(text=text, found=found)

    def test_overlaps_answers_what_covered_would_have(self) -> None:
        context = self.context(40, 5)
        covered = context.covered()
        for start in range(0, 400, 3):
            want = bool(covered & set(range(start, start + 4)))
            assert context.overlaps(start, start + 4) is want

    def test_asking_does_not_build_an_index_per_character(self) -> None:
        """The measurement that made this worth doing.

        On a 100 KB mixed Japanese/English document the index set held 70,492
        integers -- 43.5 bytes per input character, more than half the peak
        allocation of a whole protection -- to state what the spans already
        stated.
        """
        context = self.context(2000, 12)
        gc.collect()
        tracemalloc.start()
        before = tracemalloc.get_traced_memory()[0]
        assert context.overlaps(500, 520) or True
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        per_character = (peak - before) / len(context.text)
        assert per_character < 4, f"{per_character:.1f} bytes per character of text"

    def test_the_index_is_built_once(self) -> None:
        context = self.context(20, 4)
        first = context.claimed()
        assert context.claimed() is first
