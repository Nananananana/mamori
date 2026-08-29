"""How far to lean towards catching everything.

Every detection rule sits somewhere on one trade: catch more, or be wrong less
often. Until now the library made that choice once, per rule, and offered no way
to move it.

The two costs are not symmetric, and they are not symmetric in the same
direction for everyone:

- **A miss sends somebody's data to a third party.** It is silent, permanent,
  and the thing this library exists to prevent.
- **A false positive replaces an ordinary word with a token.** It costs answer
  quality, and enough of them cost adoption -- and a privacy layer nobody uses
  has a real-world miss rate of 100%.

So the stance is a setting rather than a constant. What it does *not* do is
change any security decision: the policy still decides what leaves, resolution
still picks one detection per character, and credentials are still blocked. A
wider stance only proposes more candidates.
"""

from __future__ import annotations

from enum import Enum

__all__ = ["RuleTier", "Stance"]


class RuleTier(Enum):
    """How much a rule can be relied on.

    Every rule declares its tier, and the stance decides which tiers run. The
    split is not "good rules and bad rules" -- a wide rule is one whose shape
    genuinely cannot be told apart from ordinary text, so it is right to run it
    when a miss matters more than a stray placeholder, and wrong otherwise.
    """

    #: Anchored on something that is rarely anything else: a checksum, a vendor
    #: prefix, an honorific, a label. Wrong occasionally; wrong loudly.
    CORE = "core"

    #: Shape alone, with no anchor. A run of ten digits, two capitalised words,
    #: a long random-looking token. These find what nothing else can, and they
    #: also fire on order numbers, product names and base64 payloads.
    WIDE = "wide"


class Stance(Enum):
    """Which rule tiers run."""

    #: Core rules only. Fewer stray placeholders, more misses.
    BALANCED = "balanced"

    #: Core and wide. More placeholders in ordinary text, fewer misses.
    #: The default, because a miss is silent and a false positive is visible:
    #: somebody reading a protected prompt notices a word that should not have
    #: been replaced, and nobody notices the name that was not.
    RECALL_FIRST = "recall_first"

    def includes(self, tier: RuleTier) -> bool:
        """Whether rules of ``tier`` run under this stance."""
        if self is Stance.RECALL_FIRST:
            return True
        return tier is RuleTier.CORE
