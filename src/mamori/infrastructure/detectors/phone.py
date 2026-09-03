"""Phone numbers, validated against real numbering plans.

The pattern rules match a shape, and `SECURITY.md` states the cost plainly:
*"unseparated digit runs, which are deliberately not matched -- an order number
looks identical."* That is true of a regular expression and false of a
numbering plan. `+81 90 1234 5678` is a number because Japan assigns
`090`-prefixed mobiles of that length; `98765432109` is not, and no shape can
tell them apart while a plan can.

`phonenumbers` is Google's libphonenumber, the same table every phone keyboard
in the world validates against, Apache-2.0. Measured against the rules that
ship:

    電話は090-1234-5678です     rules: found     plan: found
    call (415) 555-0198        rules: found     plan: found
    ring 07911123456 please    rules: MISSED    plan: found   (UK, unseparated)
    order 98765432109 shipped  rules: missed    plan: correctly not a number

**Higher recall and higher precision at once**, which a wider regular
expression cannot give: it is the same move a checksum makes, and it puts the
detection in the `CORE` tier where a validated identifier belongs rather than
in the `WIDE` tier where a shape has to be gambled on.

Off unless asked for -- `MamoriConfig(phone="phonenumbers")` -- because it is a
dependency, and this library installs with none: `pip install "mamori[phone]"`.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...domain import entity_types as t
from ...domain.confidence import HIGH
from ...domain.sensitive_entity import SensitiveEntity
from ...domain.span import Span
from ...errors import ConfigurationError, DetectionError
from ...ports.detection_pass import DetectionContext

__all__ = ["DEFAULT_REGIONS", "PhoneNumberPass"]

#: Which numbering plans to read a number against, in order.
#:
#: A number written without a country code is only interpretable against a
#: region, and there is no neutral answer -- `07911123456` is a valid UK mobile
#: and nothing at all in Japan. These are this library's three languages plus
#: the two largest English-speaking plans, and a deployment with one country
#: should say so: a shorter list is strictly more precise.
DEFAULT_REGIONS: tuple[str, ...] = ("JP", "US", "GB", "CN")


class PhoneNumberPass:
    """Report numbers a real numbering plan accepts.

    Args:
        regions: Plans to try, in order. The first that yields a *valid*
            number wins. An international number beginning `+` is understood
            whatever this says.
        strict: Require `is_valid_number` rather than `is_possible_number`.
            On by default, and the difference is the whole point -- "possible"
            means the right length, which is what a regular expression already
            knew.
        name: Recorded on every entity this produces.
    """

    def __init__(
        self,
        *,
        regions: Sequence[str] = DEFAULT_REGIONS,
        strict: bool = True,
        name: str = "phonenumbers",
    ) -> None:
        if not regions:
            raise ValueError("at least one region is needed to read a national number")
        self._regions = tuple(regions)
        self._strict = strict
        self._name = name
        self._module = self._load()

    @staticmethod
    def _load() -> object:
        try:
            import phonenumbers
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on install
            raise ConfigurationError(
                "the validated phone detector needs the `phonenumbers` package: "
                'pip install "mamori[phone]". It is optional because the pattern '
                "rules need no numbering plan, and this library installs with no "
                "runtime dependencies at all."
            ) from exc
        return phonenumbers

    @property
    def name(self) -> str:
        return self._name

    def run(self, context: DetectionContext) -> Sequence[SensitiveEntity]:
        text = context.text
        if not text:
            return []

        phonenumbers = self._module
        accepts = (
            phonenumbers.is_valid_number if self._strict else phonenumbers.is_possible_number  # type: ignore[attr-defined]
        )

        covered = context.covered()
        found: list[SensitiveEntity] = []
        seen: set[tuple[int, int]] = set()
        for region in self._regions:
            try:
                matches = list(phonenumbers.PhoneNumberMatcher(text, region))  # type: ignore[attr-defined]
            except Exception as exc:
                raise DetectionError(f"{self._name} failed for region {region}: {exc}") from exc
            for match in matches:
                span = (match.start, match.end)
                if span in seen or not accepts(match.number):
                    continue
                seen.add(span)
                if any(index in covered for index in range(match.start, match.end)):
                    continue
                found.append(
                    SensitiveEntity(
                        entity_type=t.PHONE,
                        span=Span(match.start, match.end),
                        value=text[match.start : match.end],
                        confidence=HIGH,
                        source=self._name,
                    )
                )
                covered |= set(range(match.start, match.end))
        return found
