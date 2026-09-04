"""How long a store keeps what it keeps, and that saying so is not the same
as doing it.

Proposal 0002 asked for *retention as a stated rule rather than a background
process*, and proposal 0004 found it had never been built. The distinction is
the design: a sweeper thread deletes at moments the caller cannot predict or
observe, and makes a store's contents depend on how long the process has been
running -- which turns every test of it into either a slow one or a lie.

Expiry here happens when the store is used, driven by an injected clock. That
is what lets these run in microseconds and still describe the real thing.
"""

from __future__ import annotations

import pytest

from mamori.domain.mapping import Mapping
from mamori.domain.placeholder import Placeholder
from mamori.domain.retention import Retention
from mamori.infrastructure.storage import InMemoryMappingStore

IDENTITY = "PERSON:田中太郎"


def mapping(scope: str = "s", index: int = 1) -> Mapping:
    return Mapping(
        scope=scope,
        placeholder=Placeholder("PERSON", index),
        entity_type_name="PERSON",
        original_value="田中太郎",
        identity_key=IDENTITY if index == 1 else f"{IDENTITY}:{index}",
    )


class TestTheDefaultIsUnchanged:
    """Expiring by surprise would be a worse change than not expiring."""

    def test_a_store_with_no_retention_keeps_everything(self) -> None:
        store = InMemoryMappingStore()
        store.put(mapping())
        assert store.retention.is_forever
        assert store.find_by_identity("s", IDENTITY) is not None

    def test_the_default_says_so_in_words(self) -> None:
        assert "until the process ends" in Retention.forever().describe()


class TestExpiry:
    @staticmethod
    def _store(start: float = 1000.0) -> tuple[list[float], InMemoryMappingStore]:
        """A store whose clock the test moves, so half an hour costs nothing.

        The clock belongs to the store rather than to `Retention`: the domain
        states the rule and the infrastructure reads the time, which the
        architecture test insisted on and was right about.
        """
        now = [start]
        return now, InMemoryMappingStore(retention=Retention.of(minutes=30), clock=lambda: now[0])

    def test_a_mapping_survives_until_its_period_is_up(self) -> None:
        now, store = self._store()
        store.put(mapping())

        now[0] += 29 * 60
        assert store.find_by_identity("s", IDENTITY) is not None

    def test_and_is_gone_after(self) -> None:
        now, store = self._store()
        store.put(mapping())

        now[0] += 31 * 60
        assert store.find_by_identity("s", IDENTITY) is None
        assert store.find_by_placeholder("s", Placeholder("PERSON", 1)) is None
        assert store.list_scope("s") == ()

    def test_expiry_is_per_mapping_and_not_per_store(self) -> None:
        """A mapping written later gets its own clock, which is the whole
        difference between a retention period and a session timeout."""
        now, store = self._store()
        store.put(mapping(index=1))

        now[0] += 20 * 60
        store.put(mapping(index=2))

        now[0] += 15 * 60  # 35 for the first, 15 for the second
        assert store.find_by_placeholder("s", Placeholder("PERSON", 1)) is None
        assert store.find_by_placeholder("s", Placeholder("PERSON", 2)) is not None

    def test_a_read_is_enough_to_drop_it(self) -> None:
        """Nothing starts a thread, so something has to notice. Every read and
        every write does."""
        now, store = self._store()
        store.put(mapping())
        now[0] += 31 * 60

        assert store.list_scope("s") == ()

    def test_purge_still_works_on_a_store_that_expires(self) -> None:
        now, store = self._store()
        store.put(mapping())
        store.purge("s")

        now[0] += 1
        store.put(mapping())  # the bookkeeping for the purged one must be gone too
        assert store.find_by_identity("s", IDENTITY) is not None


class TestTheRuleIsReadable:
    """`mamori privacy` prints this, so it is prose a person acts on."""

    def test_a_period_says_what_happens_and_what_does_not(self) -> None:
        described = Retention.of(minutes=30).describe()
        assert "30 minute(s)" in described
        assert "not erased from memory" in described, (
            "expiry drops a reference; Python cannot promise the string is gone, "
            "and the threat model has said so since the first release"
        )

    @pytest.mark.parametrize(
        ("retention", "expected"),
        [
            (Retention.of(hours=2), "2 hour(s)"),
            (Retention.of(minutes=5), "5 minute(s)"),
            (Retention.of(seconds=90), "90 second"),
        ],
    )
    def test_the_period_reads_in_the_unit_it_was_given(
        self, retention: Retention, expected: str
    ) -> None:
        assert expected in retention.describe()

    def test_zero_is_refused(self) -> None:
        """A store that forgets on write is not a policy, it is a bug that
        would look like one."""
        with pytest.raises(ValueError, match="must be positive"):
            Retention.of(seconds=0)

    def test_the_report_reads_it_from_the_default_rather_than_naming_it(self) -> None:
        from mamori.config import MamoriConfig
        from mamori.report import build_report

        report = build_report(MamoriConfig())
        assert report.storage["retention"] == Retention.forever().describe()


class TestExpiryDoesNotUnlinkALiveMapping:
    """Two mappings can share an identity key, and expiry unlinked the wrong one.

    `_drop_expired` popped `_by_identity[(scope, identity)]` without checking
    whether the entry still pointed at the mapping being expired. The index
    holds whichever was written last, so expiring the *older* one took the
    entry for the newer, live one with it:

        find_by_placeholder(P2)  ->  the mapping
        find_by_identity(same)   ->  None

    The store is then internally inconsistent, and the next protect of that
    value allocates yet another placeholder for something already in it --
    which is the invariant `_allocate` exists to keep.

    Reachable whenever a caller passes a non-default `Retention`, and the pair
    of mappings is what the allocation race used to produce on its own.
    """

    def store(self, clock: list[float]) -> InMemoryMappingStore:
        return InMemoryMappingStore(Retention.of(seconds=10), clock=lambda: clock[0])

    def mapping(self, index: int) -> Mapping:
        return Mapping(
            scope="s",
            placeholder=Placeholder("PERSON", index),
            entity_type_name="PERSON",
            original_value="priya",
            identity_key="PERSON:priya",
        )

    def test_the_live_mapping_is_still_findable_by_identity(self) -> None:
        clock = [0.0]
        store = self.store(clock)
        store.put(self.mapping(1))
        clock[0] = 5.0
        store.put(self.mapping(2))
        clock[0] = 11.0

        assert store.find_by_placeholder("s", Placeholder("PERSON", 2)) is not None
        assert store.find_by_identity("s", "PERSON:priya") is not None

    def test_the_two_lookups_agree(self) -> None:
        """The property, rather than the example: a store that answers one and
        not the other is one nothing downstream can reason about."""
        clock = [0.0]
        store = self.store(clock)
        store.put(self.mapping(1))
        clock[0] = 5.0
        store.put(self.mapping(2))
        clock[0] = 11.0

        by_placeholder = store.find_by_placeholder("s", Placeholder("PERSON", 2))
        by_identity = store.find_by_identity("s", "PERSON:priya")
        assert by_placeholder == by_identity

    def test_an_expired_identity_with_nothing_live_behind_it_is_gone(self) -> None:
        """The fix must not keep an index entry alive past its mapping."""
        clock = [0.0]
        store = self.store(clock)
        store.put(self.mapping(1))
        clock[0] = 11.0
        assert store.find_by_identity("s", "PERSON:priya") is None
