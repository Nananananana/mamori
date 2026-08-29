"""Local changes to a bundled prompt, kept separate from it.

An organisation always knows things the library cannot. Their internal
codenames look like ordinary words. Their case numbers have a format nobody
else uses. Their documents are full of a product name that keeps coming back as
a person.

The wrong answer is to edit the prompt: the change is invisible, it collides
with every upgrade, and six months later nobody can say what was altered or
why. The right answer is to record the *difference* -- add these rules, drop
those, replace this section -- and apply it to whatever the library ships.

    >>> from mamori.prompts import PromptOverlay
    >>> overlay = PromptOverlay.from_mapping({
    ...     "disable": ["en.person.unanchored"],
    ...     "add": [{
    ...         "id": "acme.case-number",
    ...         "text": "A case number looks like ACME-12345 and is sensitive.",
    ...         "entity_types": ["IDENTIFIER"],
    ...     }],
    ... })
    >>> overlay.disable
    ('en.person.unanchored',)

A disable that matches nothing is an error, not a no-op. A team that misspells
a rule id believes they turned something off and did not, which is the same
failure mode as an ignored configuration key and just as quiet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ..errors import ConfigurationError
from .definition import PromptDefinition, PromptSection
from .guidance import GuidanceKind, GuidanceRule, GuidanceSet

__all__ = ["PromptOverlay"]


@dataclass(frozen=True, slots=True)
class PromptOverlay:
    """A difference to apply to a prompt.

    Args:
        add: Guidance to append, or to replace an existing rule of the same id
            in place.
        disable: Rule ids to drop.
        sections: Section id -> replacement body.
        strict: Refuse a disable or a section replacement that matches nothing.
            On by default, and turning it off should be rare.
    """

    add: tuple[GuidanceRule, ...] = ()
    disable: tuple[str, ...] = ()
    sections: Mapping[str, str] = field(default_factory=dict)
    strict: bool = True

    def is_empty(self) -> bool:
        return not (self.add or self.disable or self.sections)

    def apply(self, prompt: PromptDefinition) -> PromptDefinition:
        """Return ``prompt`` with this overlay applied.

        Raises:
            ConfigurationError: in strict mode, an id that matches nothing.
        """
        if self.strict:
            self._check(prompt)

        guidance = prompt.guidance.without(self.disable).with_rules(self.add)
        result = prompt.with_guidance(guidance)

        if self.sections:
            replacements = []
            for section_id, body in self.sections.items():
                existing = prompt.section(section_id)
                heading = existing.heading if existing else ""
                replacements.append(PromptSection(id=section_id, body=body, heading=heading))
            result = result.with_sections(replacements)
        return result

    def _check(self, prompt: PromptDefinition) -> None:
        known_rules = set(prompt.guidance.ids())
        missing = sorted(set(self.disable) - known_rules)
        if missing:
            raise ConfigurationError(
                f"prompt {prompt.id!r}: cannot disable unknown guidance {missing}; "
                f"available: {sorted(known_rules)}"
            )
        known_sections = set(prompt.section_ids())
        unknown_sections = sorted(set(self.sections) - known_sections)
        if unknown_sections:
            raise ConfigurationError(
                f"prompt {prompt.id!r}: cannot replace unknown section(s) "
                f"{unknown_sections}; available: {sorted(known_sections)}"
            )

    def merged_with(self, other: PromptOverlay) -> PromptOverlay:
        """Stack another overlay on this one. Useful for org then team then run."""
        return PromptOverlay(
            add=GuidanceSet(self.add).with_rules(other.add).rules,
            disable=tuple(dict.fromkeys((*self.disable, *other.disable))),
            sections={**self.sections, **other.sections},
            strict=self.strict and other.strict,
        )

    @classmethod
    def from_mapping(
        cls, values: Mapping[str, object], *, origin: str = "overlay"
    ) -> PromptOverlay:
        """Build an overlay from an already-parsed mapping.

        Same stance as the rest of the configuration: no file format is chosen
        here, and unknown keys are refused rather than ignored.

        Raises:
            ConfigurationError: an unknown key, or a value of the wrong shape.
        """
        known = {"add", "disable", "sections", "strict"}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ConfigurationError(
                f"unknown prompt overlay key(s): {', '.join(unknown)}; "
                f"known keys: {', '.join(sorted(known))}"
            )

        return cls(
            add=tuple(_as_rule(item, origin) for item in _as_list(values.get("add", ()), "add")),
            disable=tuple(str(item) for item in _as_list(values.get("disable", ()), "disable")),
            sections=_as_sections(values.get("sections", {})),
            strict=_as_bool(values.get("strict", True)),
        )


def _as_list(value: object, where: str) -> Sequence[object]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ConfigurationError(f"prompt overlay {where} must be a list")
    return value


def _as_sections(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ConfigurationError("prompt overlay sections must be a mapping")
    return {str(key): str(body) for key, body in value.items()}


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"prompt overlay strict must be true or false, got {value!r}")


def _as_rule(value: object, origin: str) -> GuidanceRule:
    if not isinstance(value, Mapping):
        raise ConfigurationError("each added guidance rule must be a mapping")

    known = {"id", "text", "kind", "entity_types", "locales", "examples"}
    unknown = sorted(set(value) - known)
    if unknown:
        raise ConfigurationError(
            f"unknown guidance key(s): {', '.join(unknown)}; known keys: {', '.join(sorted(known))}"
        )

    rule_id = str(value.get("id", "")).strip()
    text = str(value.get("text", "")).strip()
    if not rule_id:
        raise ConfigurationError("an added guidance rule needs an id, so it can be disabled later")
    if not text:
        raise ConfigurationError(f"guidance {rule_id!r} has no text")

    raw_kind = value.get("kind", GuidanceKind.FIND.value)
    try:
        kind = GuidanceKind(str(raw_kind).strip().lower())
    except ValueError as exc:
        allowed = ", ".join(k.value for k in GuidanceKind)
        raise ConfigurationError(
            f"guidance {rule_id!r}: unknown kind {raw_kind!r}; allowed: {allowed}"
        ) from exc

    return GuidanceRule(
        id=rule_id,
        text=text,
        kind=kind,
        entity_types=tuple(str(t) for t in _as_list(value.get("entity_types", ()), "entity_types")),
        locales=tuple(str(loc) for loc in _as_list(value.get("locales", ()), "locales")),
        examples=tuple(str(e) for e in _as_list(value.get("examples", ()), "examples")),
        origin=origin,
    )
