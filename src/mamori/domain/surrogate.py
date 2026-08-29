"""Substituting a plausible value instead of an obvious token.

`<PERSON_001>さんへ` is unambiguous and it is also not a sentence. Some models
reason visibly worse about text full of tokens: they lose track of who is who,
they refuse to draft a reply to a placeholder, and they sometimes describe the
token instead of using it. Substituting `山田一郎` keeps the text readable, and
the answer usually comes back better.

**This is the most dangerous option in the library, and the danger is the
point of the design.**

A placeholder that is never restored is obvious. Somebody reading
`<PERSON_001>さんへ` knows immediately that something did not finish. A
surrogate that is never restored is a plausible sentence about the wrong
person, and nobody notices. Every decision below exists to narrow that.

**Reserved values wherever any exist.** Emails use `example.com` (RFC 2606),
addresses use the documentation ranges of RFC 5737, telephone numbers use the
fictional ranges broadcasters use. A surrogate that escapes is then harmless
*and* identifiable: somebody who sees `192.0.2.7` in a log can look it up and
find out it means nothing.

**Names are the residual risk and there is no fixing it.** No standards body
reserves personal names. The pools here are invented and common enough to read
naturally, which is exactly what makes an unrestored one hard to spot. That is
stated in the docs, reported by `mamori privacy`, and is the reason this is off
by default.

**Chosen by allocation order, never derived from the value.** `PERSON_001`
takes the first name in the pool whatever it stands for. Deriving the surrogate
from the original -- hashing it, say -- would be tidier and would create a
correlation channel: the same real person would get the same fake name in every
document, so an observer holding two protected documents could tell they are
about the same individual. Order is the property that keeps a surrogate from
carrying information about what it replaced.

**A surrogate never collides with the text it enters.** If the pool's choice
already appears in the document, the next one is used, because restoring the
wrong occurrence would corrupt the caller's own words.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

__all__ = ["SURROGATE_POOLS", "SurrogatePool", "supported_types", "surrogate_for"]


@dataclass(frozen=True, slots=True)
class SurrogatePool:
    """Invented stand-ins for one entity type, in one language."""

    entity_type: str
    locale: str
    values: tuple[str, ...]
    #: Why these are safe to substitute. Shown by ``mamori privacy``, because
    #: "it is reserved for documentation" and "it is a plausible name we made
    #: up" are very different promises.
    basis: str = ""

    def __len__(self) -> int:
        return len(self.values)


_JA_PEOPLE = (
    "山田一郎",
    "佐々木花",
    "小川健",
    "森田美咲",
    "北村誠",
    "橋本葵",
    "西野拓真",
    "東雲結衣",
    "藤原直樹",
    "菅野さくら",
    "宮下亮",
    "白石真央",
)
_EN_PEOPLE = (
    "Alex Rivera",
    "Jordan Blake",
    "Sam Okafor",
    "Casey Lindqvist",
    "Morgan Ashby",
    "Riley Nakamura",
    "Devon Marsh",
    "Quinn Delacroix",
    "Harper Nwosu",
    "Rowan Castellan",
    "Emery Vaszary",
    "Sloane Petrakis",
)
_ZH_PEOPLE = (
    "林小舟",
    "赵知远",
    "孙敏行",
    "周慕白",
    "吴清和",
    "郑一帆",
    "何若谷",
    "许南星",
    "邓乐山",
    "冯听澜",
)

#: Names are the one type with nothing reserved behind them.
_INVENTED = "invented; nothing is reserved for personal names"
_RESERVED = "reserved for documentation, so it means nothing anywhere"

SURROGATE_POOLS: tuple[SurrogatePool, ...] = (
    SurrogatePool("PERSON", "ja", _JA_PEOPLE, _INVENTED),
    SurrogatePool("PERSON", "en", _EN_PEOPLE, _INVENTED),
    SurrogatePool("PERSON", "zh", _ZH_PEOPLE, _INVENTED),
    SurrogatePool(
        "COMPANY_NAME",
        "ja",
        ("株式会社エグザンプル", "有限会社サンプル", "合同会社テストワークス"),
        _INVENTED,
    ),
    SurrogatePool(
        "COMPANY_NAME",
        "en",
        ("Example Holdings Ltd", "Sample Industries Inc", "Placeholder Works LLC"),
        _INVENTED,
    ),
    SurrogatePool(
        "COMPANY_NAME", "zh", ("示例科技有限公司", "样本工业集团", "测试实业有限公司"), _INVENTED
    ),
    # RFC 2606 reserves example.com, example.net and example.org for exactly
    # this, so an address that escapes cannot reach anybody.
    SurrogatePool(
        "EMAIL",
        "*",
        tuple(f"{name}@example.com" for name in ("a.person", "b.person", "c.person", "d.person"))
        + tuple(f"{name}@example.org" for name in ("e.person", "f.person", "g.person")),
        "RFC 2606: example.com and example.org exist to be written down",
    ),
    # RFC 5737 TEST-NET blocks. Routed nowhere, by standard.
    SurrogatePool(
        "INTERNAL_IP",
        "*",
        ("192.0.2.10", "192.0.2.11", "198.51.100.10", "198.51.100.11", "203.0.113.10"),
        "RFC 5737 TEST-NET, which is routed nowhere",
    ),
    # The ranges broadcasters and regulators keep aside for fiction.
    SurrogatePool(
        "PHONE",
        "en",
        ("415-555-0142", "415-555-0167", "212-555-0188", "+1 415 555 0113"),
        "the 555-01xx range, reserved for fiction",
    ),
    SurrogatePool(
        "PHONE",
        "ja",
        ("090-0000-0100", "080-0000-0142", "03-0000-0167"),
        "0000 exchange, which is not allocated",
    ),
    SurrogatePool("PHONE", "zh", ("138-0013-8000", "010-0000-0142"), "unallocated ranges"),
    SurrogatePool(
        "INTERNAL_URL",
        "*",
        ("https://wiki.example.com/page", "https://docs.example.org/guide"),
        "RFC 2606 domains",
    ),
)

_BY_KEY: Mapping[tuple[str, str], SurrogatePool] = {
    (pool.entity_type, pool.locale): pool for pool in SURROGATE_POOLS
}


def supported_types() -> frozenset[str]:
    """Types a surrogate can be produced for. Everything else stays a token."""
    return frozenset(pool.entity_type for pool in SURROGATE_POOLS)


def pool_for(entity_type: str, locale: str) -> SurrogatePool | None:
    """The pool for a type, preferring the language and falling back to any."""
    exact = _BY_KEY.get((entity_type, locale))
    if exact is not None:
        return exact
    return _BY_KEY.get((entity_type, "*"))


def surrogate_for(
    entity_type: str,
    index: int,
    *,
    locale: str = "*",
    avoid: Sequence[str] | frozenset[str] = (),
) -> str | None:
    """A stand-in for the ``index``-th value of this type, or ``None``.

    Args:
        entity_type: What is being replaced.
        index: Allocation order, from one. **Not** derived from the value: two
            documents mentioning the same person give it different surrogates,
            which is what stops a surrogate carrying information.
        locale: Language pack, so a Japanese name is replaced by one.
        avoid: Strings already in the document, or already used. A surrogate
            that collides with real text would be restored in the wrong place.

    Returns:
        ``None`` when no pool covers this type, or every candidate collides.
        The caller falls back to a placeholder, which is always safe.
    """
    pool = pool_for(entity_type, locale)
    if pool is None or not pool.values:
        return None

    forbidden = frozenset(avoid)
    start = max(index - 1, 0)
    for offset in range(len(pool.values)):
        candidate = pool.values[(start + offset) % len(pool.values)]
        if candidate not in forbidden:
            return candidate
    return None
