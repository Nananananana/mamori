"""``mamori trace`` and ``mamori audit``: saying why.

Two questions, and the second is the one that matters.

**Why was this redacted?** Answerable from a result, awkwardly, and now
directly: the trace lists every candidate the pipeline considered, what became
of it, and — for the ones that lost an overlap — what took the span and on
which preference.

**Why was this *not* redacted?** Not previously answerable at all. A miss is
the failure this library exists to prevent, and "it found nothing" is not an
explanation. What `trace` does about it is cheap and honest: it runs the other
stance as well, and says what the wider rules *would* have caught. If the
answer is "nothing at either stance", that is a real answer too, and it points
at a correction or the model tier rather than leaving somebody guessing.

`audit` asks the same question of a whole corpus instead of one text: which
rules carry the load, and — more useful — which have never fired once. A rule
that never fires is either dead or is waiting for data nobody has, and both are
worth knowing about a hundred-rule detector.

Everything here shows masked previews. These are outputs somebody pastes into a
bug report.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from ...config import MamoriConfig
from ...domain.stance import Stance
from ...infrastructure.detectors import available_locales
from ...infrastructure.detectors.patterns import PatternRule, identify

__all__ = ["RuleUsage", "audit_rules", "trace_text"]


def trace_text(config: MamoriConfig, text: str, *, as_json: bool = False) -> int:
    """Explain what happened to one text."""
    with config.session(trace=True) as session:
        result = session.protect(text)
    trace = result.trace
    assert trace is not None

    other = Stance.BALANCED if config.stance is Stance.RECALL_FIRST else Stance.RECALL_FIRST
    with config.replace(stance=other).session(trace=True) as session:
        alternative = session.protect(text)

    if as_json:
        print(
            json.dumps(
                {
                    "stance": config.stance.value,
                    "trace": trace.as_mapping(),
                    "other_stance": {
                        "stance": other.value,
                        "found": [
                            {"entity_type": e.entity_type, "start": e.span.start}
                            for e in alternative.entities
                        ],
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"{len(text)} characters, stance {config.stance.value}")
    print()

    if not trace:
        print("Nothing was even considered here.")
    else:
        print("What was considered")
        print()
        print(f"  {'where':<10}{'type':<16}{'rules':<14}conf  outcome")
        for decision in trace:
            print(f"  {decision.describe()}")

    print()
    print("Why nothing else")
    print()
    _explain_the_gap(text, result, alternative, other)
    return 0


def _explain_the_gap(text: str, result: object, alternative: object, other: Stance) -> None:
    """The half that was never answerable: what did *not* fire, and why."""
    kept = {(e.entity_type, e.span.start) for e in result.entities}  # type: ignore[attr-defined]
    extra = [
        e
        for e in alternative.entities  # type: ignore[attr-defined]
        if (e.entity_type, e.span.start) not in kept
    ]

    if extra:
        print(f"  The {other.value} stance would additionally have found:")
        for entity in extra:
            snippet = text[entity.span.start : entity.span.end]
            shape = "".join("x" if c.isalnum() else c for c in snippet)
            print(
                f"    {entity.entity_type:<16}{entity.span.start}:{entity.span.end}  shape {shape}"
            )
        print()
        print("  Switch with --stance, and read `mamori eval` before you do:")
        print("  the wider rules cost over-redaction to buy that coverage.")
        return

    print("  Neither stance finds anything more here.")
    print()
    print("  If something in this text should have been protected, the rules")
    print("  cannot reach it and there are two things that can:")
    print("    mamori correct <value> --always <TYPE>   -- for a value you name")
    print("    an 'llm' section in your settings        -- for the general case")
    print("  `mamori eval --compare` says what either one costs on your data.")


@dataclass(frozen=True, slots=True)
class RuleUsage:
    """One rule, and how often it fired over whatever was audited."""

    identifier: str
    entity_type: str
    tier: str
    matches: int

    @property
    def dead(self) -> bool:
        return self.matches == 0


def audit_rules(texts: Sequence[str], locales: Sequence[str] | None = None) -> list[RuleUsage]:
    """Run every rule over every text and count what fired.

    Rules are run individually rather than through the pipeline on purpose. The
    pipeline resolves overlaps, so a rule that fires and always loses would look
    identical to one that never fires, and those are different problems.
    """
    from ...infrastructure.detectors.patterns import UNIVERSAL_RULES

    usage: list[RuleUsage] = []
    # The universal rules first: email, credentials, card numbers. They belong
    # to no pack, they are the ones that matter most, and leaving them out of
    # an audit would have been an odd thing to overlook twice.
    groups: list[tuple[str, Sequence[PatternRule]]] = [("universal", UNIVERSAL_RULES)]
    groups += [(pack.code, pack.rules) for pack in available_locales()]

    for code, rules in groups:
        if locales and code not in locales and code != "universal":
            continue
        names = identify(rules, code)
        for rule in rules:
            usage.append(
                RuleUsage(
                    identifier=names[id(rule)],
                    entity_type=rule.entity_type.name,
                    tier=rule.tier.value,
                    matches=sum(_count(rule, text) for text in texts),
                )
            )
    usage.sort(key=lambda u: (-u.matches, u.identifier))
    return usage


def _count(rule: PatternRule, text: str) -> int:
    found = 0
    for match in rule.pattern.finditer(text):
        value = match.group(rule.group)
        if not value:
            continue
        if rule.validator is not None and not rule.validator(value):
            continue
        found += 1
    return found
