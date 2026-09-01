"""How long a store keeps what it keeps, as something a caller can read.

A mapping table holds every original value and its position. Nothing in this
library has ever expired one: `purge()` deletes a scope when somebody calls it,
and until `0.29` nobody had to.

The shape of the answer was decided before the code was, in proposal 0002, and
is worth restating because it rules out the obvious implementation:

    retention as a **stated rule** rather than a background process

A sweeper thread deletes things at times the caller cannot predict, cannot
observe, and did not ask for. It also means a store's contents depend on how
long the process has been running, which makes a test either slow or a lie. A
rule the caller can read has none of those properties: `Retention.forever()`
and `Retention.of(minutes=30)` say what will happen, `mamori privacy` prints
it, and expiry happens when the store is next used.

**Expiry is not erasure.** Dropping a reference in Python does not overwrite
memory, and the threat model has said so since the first release. What this
buys is that a store asked for a value it should no longer have does not
produce one -- which is the property a caller can actually rely on.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Retention"]


@dataclass(frozen=True, slots=True)
class Retention:
    """How long a store keeps a mapping after it was written.

    ``seconds`` of ``None`` means forever, which is what every store did
    before this existed and remains the default: expiring by surprise would be
    a worse change than not expiring at all.
    """

    seconds: float | None = None

    @classmethod
    def forever(cls) -> Retention:
        """Keep until something calls ``purge``. The default."""
        return cls()

    @classmethod
    def of(cls, *, seconds: float = 0, minutes: float = 0, hours: float = 0) -> Retention:
        """Keep for a period, then stop answering for it.

        Raises:
            ValueError: a period of zero or less. A store that forgets
                everything the instant it is written is not a retention
                policy, it is a bug that would look like one.
        """
        total = seconds + minutes * 60 + hours * 3600
        if total <= 0:
            raise ValueError("a retention period must be positive")
        return cls(seconds=total)

    @property
    def is_forever(self) -> bool:
        return self.seconds is None

    def expired(self, written_at: float, now: float) -> bool:
        """Whether something written at ``written_at`` may still be answered for.

        ``now`` is passed in rather than read here. The domain holds the rule;
        reading a clock is the store's job, and the architecture test that
        caught this was right to -- a domain that reads the time is a domain
        whose behaviour depends on when you run it.

        Both are expected to come from a monotonic source, so that a clock
        adjustment cannot resurrect an expired mapping or retire a live one.
        """
        if self.seconds is None:
            return False
        return (now - written_at) >= self.seconds

    def describe(self) -> str:
        """One line, for `mamori privacy`.

        Says what happens rather than naming a policy, because the reader of
        that report is deciding whether to trust this with a document.
        """
        if self.seconds is None:
            return "kept until the process ends or something calls purge()"
        if self.seconds >= 3600 and self.seconds % 3600 == 0:
            period = f"{self.seconds / 3600:g} hour(s)"
        elif self.seconds >= 60 and self.seconds % 60 == 0:
            period = f"{self.seconds / 60:g} minute(s)"
        else:
            period = f"{self.seconds:g} second(s)"
        return (
            f"dropped {period} after it was written, on the next use of the "
            "store -- not erased from memory, which Python cannot promise"
        )
