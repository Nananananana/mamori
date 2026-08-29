"""Conformance suites for the ports.

A port is a promise, and a promise nobody checks is a comment. These mixins hold
the tests every implementation of ``Detector`` and ``MappingStore`` has to pass;
a concrete test class supplies the implementation and inherits the suite.

They are written for the adapters in this repository and for the ones that are
not: if you add a store or a detector, subclass the matching mixin and you
inherit the contract rather than guessing at it.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from mamori.domain.mapping import Mapping
from mamori.domain.normalization import NormalizedText
from mamori.domain.placeholder import Placeholder
from mamori.ports.detector import Detector
from mamori.ports.mapping_store import MappingStore

__all__ = ["DetectorContract", "MappingStoreContract"]

#: Text a detector must survive. Nothing here is expected to be detected; the
#: point is that none of it raises, hangs or reports a span outside the input.
HOSTILE_INPUTS = (
    "",
    " ",
    "\n\n\n",
    "\x00\x01\x02",
    "a" * 5000,
    "田" * 2000,
    "<<<>>>[[[]]]{{{}}}",
    "<PERSON_001>",
    "@@@@@@@@@@",
    "....................",
    "https://",
    "-----BEGIN",
    "\U0001f600\U0001f601\U0001f602",
    "​‌‍",
    "ｔｅｓｔ　全角　テスト",
)


class DetectorContract:
    """What every ``Detector`` implementation must do.

    Subclass and implement :meth:`make_detector`.
    """

    def make_detector(self) -> Detector:  # pragma: no cover - overridden
        raise NotImplementedError

    def test_it_satisfies_the_protocol(self) -> None:
        assert isinstance(self.make_detector(), Detector)

    def test_it_has_a_non_empty_name(self) -> None:
        name = self.make_detector().name
        assert isinstance(name, str) and name

    @pytest.mark.parametrize("text", HOSTILE_INPUTS)
    def test_it_survives_hostile_input(self, text: str) -> None:
        result = self.make_detector().detect(text)
        assert isinstance(result, Sequence)

    @pytest.mark.parametrize("text", HOSTILE_INPUTS)
    def test_spans_stay_inside_the_text(self, text: str) -> None:
        for entity in self.make_detector().detect(text):
            assert 0 <= entity.span.start < entity.span.end <= len(text)

    def test_the_value_is_the_text_the_span_covers(self) -> None:
        """Otherwise the application splices the wrong characters."""
        sample = NormalizedText.of(
            "田中太郎さんへ tanaka@example.com / 090-1234-5678\n"
            "Dear Jane Doe, see https://wiki.corp.local/x\n"
            "张伟先生，请拨打 13812345678"
        ).text
        for entity in self.make_detector().detect(sample):
            assert sample[entity.span.start : entity.span.end] == entity.value

    def test_every_detection_records_its_source(self) -> None:
        sample = "tanaka@example.com Dear Jane Doe, 13812345678"
        for entity in self.make_detector().detect(sample):
            assert entity.source

    def test_detection_is_repeatable(self) -> None:
        """Two runs over one text must agree, or nothing downstream is reproducible."""
        sample = "田中太郎さんへ tanaka@example.com Dear Jane Doe,"
        detector = self.make_detector()
        first = [(e.entity_type, e.span, e.value) for e in detector.detect(sample)]
        second = [(e.entity_type, e.span, e.value) for e in detector.detect(sample)]
        assert first == second

    def test_two_instances_agree(self) -> None:
        """No hidden state between constructions."""
        sample = "田中太郎さんへ tanaka@example.com"
        first = [(e.entity_type, e.span) for e in self.make_detector().detect(sample)]
        second = [(e.entity_type, e.span) for e in self.make_detector().detect(sample)]
        assert first == second

    def test_confidence_is_within_range(self) -> None:
        sample = "田中太郎さんへ tanaka@example.com Dear Jane Doe, 13812345678"
        for entity in self.make_detector().detect(sample):
            assert 0.0 <= entity.confidence.value <= 1.0


class MappingStoreContract:
    """What every ``MappingStore`` implementation must do.

    Subclass and implement :meth:`make_store`.
    """

    def make_store(self) -> MappingStore:  # pragma: no cover - overridden
        raise NotImplementedError

    @staticmethod
    def mapping(scope: str = "s", index: int = 1, value: str = "a@example.com") -> Mapping:
        return Mapping(
            scope=scope,
            placeholder=Placeholder("EMAIL", index),
            entity_type_name="EMAIL",
            original_value=value,
            identity_key=f"EMAIL:{value}",
        )

    def test_it_satisfies_the_protocol(self) -> None:
        assert isinstance(self.make_store(), MappingStore)

    def test_an_empty_store_finds_nothing(self) -> None:
        store = self.make_store()
        assert store.find_by_identity("s", "EMAIL:a") is None
        assert store.find_by_placeholder("s", Placeholder("EMAIL", 1)) is None
        assert store.list_scope("s") == ()

    def test_put_then_find_by_placeholder(self) -> None:
        store = self.make_store()
        mapping = self.mapping()
        store.put(mapping)
        found = store.find_by_placeholder("s", Placeholder("EMAIL", 1))
        assert found is not None and found.original_value == mapping.original_value

    def test_put_then_find_by_identity(self) -> None:
        store = self.make_store()
        store.put(self.mapping())
        assert store.find_by_identity("s", "EMAIL:a@example.com") is not None

    def test_put_is_idempotent(self) -> None:
        store = self.make_store()
        mapping = self.mapping()
        store.put(mapping)
        store.put(mapping)
        assert len(store.list_scope("s")) == 1

    def test_indexes_start_at_one(self) -> None:
        assert self.make_store().next_index("s", "PERSON") == 1

    def test_indexes_increment(self) -> None:
        store = self.make_store()
        assert [store.next_index("s", "PERSON") for _ in range(4)] == [1, 2, 3, 4]

    def test_indexes_are_independent_per_type(self) -> None:
        store = self.make_store()
        assert store.next_index("s", "PERSON") == 1
        assert store.next_index("s", "EMAIL") == 1

    def test_indexes_are_independent_per_scope(self) -> None:
        store = self.make_store()
        assert store.next_index("a", "PERSON") == 1
        assert store.next_index("b", "PERSON") == 1

    def test_scopes_are_isolated(self) -> None:
        """The property restoration leans on: one session cannot read another."""
        store = self.make_store()
        store.put(self.mapping(scope="a", value="a@example.com"))
        assert store.find_by_placeholder("b", Placeholder("EMAIL", 1)) is None
        assert store.find_by_identity("b", "EMAIL:a@example.com") is None

    def test_list_scope_returns_only_that_scope(self) -> None:
        store = self.make_store()
        store.put(self.mapping(scope="a", value="a@example.com"))
        store.put(self.mapping(scope="b", value="b@example.com"))
        assert len(store.list_scope("a")) == 1
        assert len(store.list_scope("b")) == 1

    def test_purge_empties_one_scope(self) -> None:
        store = self.make_store()
        store.put(self.mapping(scope="a"))
        store.purge("a")
        assert store.list_scope("a") == ()

    def test_purge_leaves_other_scopes_alone(self) -> None:
        store = self.make_store()
        store.put(self.mapping(scope="a", value="a@example.com"))
        store.put(self.mapping(scope="b", value="b@example.com"))
        store.purge("a")
        assert len(store.list_scope("b")) == 1

    def test_purge_clears_the_index_counters(self) -> None:
        """A reused scope must not resume numbering from a purged run."""
        store = self.make_store()
        store.next_index("a", "PERSON")
        store.next_index("a", "PERSON")
        store.purge("a")
        assert store.next_index("a", "PERSON") == 1

    def test_purging_an_unknown_scope_is_harmless(self) -> None:
        self.make_store().purge("never-used")

    def test_several_types_in_one_scope(self) -> None:
        store = self.make_store()
        for index, name in enumerate(("EMAIL", "PERSON", "PHONE"), start=1):
            store.put(
                Mapping(
                    scope="s",
                    placeholder=Placeholder(name, index),
                    entity_type_name=name,
                    original_value=f"value-{index}",
                    identity_key=f"{name}:value-{index}",
                )
            )
        assert len(store.list_scope("s")) == 3
