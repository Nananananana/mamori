"""A prompt is a document with parts, not a string.

A prompt written as one long f-string can be read and it cannot be changed --
not by a team with an internal naming convention, not by a locale that needs one
extra sentence, not by anyone who wants to see what actually got sent. Every
change is a fork of the whole thing.

So a prompt here is a small ordered document: named sections, plus guidance
drawn from the shared knowledge base. Rendering is deterministic, which is what
makes a prompt version reproducible: the same definition and the same overlay
produce the same characters every time, and the fingerprint on the rendered
result proves it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from .guidance import GuidanceKind, GuidanceRule, GuidanceSet

__all__ = ["PromptDefinition", "PromptRole", "PromptSection", "RenderedPrompt"]

PromptRole = str

#: Heading shown above each guidance kind. Separate sections rather than one
#: list, because a model follows a short "find these" and a short "these are
#: not those" far better than a long mixture of both.
_KIND_HEADINGS: dict[GuidanceKind, str] = {
    GuidanceKind.FIND: "What counts as sensitive",
    GuidanceKind.IGNORE: "What looks sensitive and is not",
    GuidanceKind.BOUNDARY: "Where a value starts and ends",
    GuidanceKind.OUTPUT: "How to answer",
}


@dataclass(frozen=True, slots=True)
class PromptSection:
    """One addressable block of prose."""

    id: str
    body: str
    heading: str = ""

    def render(self) -> str:
        if self.heading:
            return f"## {self.heading}\n\n{self.body.strip()}"
        return self.body.strip()


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    """The exact text that will be sent, and enough to say where it came from."""

    prompt_id: str
    version: str
    role: PromptRole
    text: str = field(repr=False)
    guidance_ids: tuple[str, ...] = ()

    @property
    def fingerprint(self) -> str:
        """Short digest of the rendered text.

        Recorded alongside a result so that "why did it answer that" has an
        answer: the prompt id and version say which prompt, and this says
        whether the overlay changed it.
        """
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:12]

    def __len__(self) -> int:
        return len(self.text)


@dataclass(frozen=True, slots=True)
class PromptDefinition:
    """A prompt, assembled from sections and guidance.

    Args:
        id: Stable name, e.g. ``detection``.
        version: Bumped when the meaning changes. Recorded on every result, so
            an answer from six months ago can be explained.
        role: ``system`` or ``user``.
        sections: Ordered prose blocks, addressable by id.
        guidance: Rules rendered under their kind's heading, after the sections
            named in ``guidance_after``.
        guidance_after: Section id the guidance follows. Empty puts it last.
    """

    id: str
    version: str = "1"
    role: PromptRole = "system"
    sections: tuple[PromptSection, ...] = ()
    guidance: GuidanceSet = field(default_factory=GuidanceSet)
    guidance_after: str = ""

    def section(self, section_id: str) -> PromptSection | None:
        return next((s for s in self.sections if s.id == section_id), None)

    def section_ids(self) -> tuple[str, ...]:
        return tuple(section.id for section in self.sections)

    def with_sections(self, sections: Sequence[PromptSection]) -> PromptDefinition:
        """Replace sections by id, keeping position; append unknown ids."""
        incoming = {section.id: section for section in sections}
        kept = tuple(incoming.get(s.id, s) for s in self.sections)
        existing = {section.id for section in self.sections}
        appended = tuple(s for s in sections if s.id not in existing)
        return replace(self, sections=kept + appended)

    def with_guidance(self, guidance: GuidanceSet) -> PromptDefinition:
        return replace(self, guidance=guidance)

    def render(self, locales: Sequence[str] | None = None) -> RenderedPrompt:
        """Produce the text to send.

        Args:
            locales: Keep only guidance relevant to these languages. ``None``
                keeps all of it -- which is the right default when nobody knows
                what language the text will be in.
        """
        selected = self.guidance.for_locales(locales)
        blocks: list[str] = []
        emitted_guidance = False

        for section in self.sections:
            blocks.append(section.render())
            if self.guidance_after and section.id == self.guidance_after:
                blocks.extend(_render_guidance(selected))
                emitted_guidance = True

        if not emitted_guidance:
            blocks.extend(_render_guidance(selected))

        return RenderedPrompt(
            prompt_id=self.id,
            version=self.version,
            role=self.role,
            text="\n\n".join(block for block in blocks if block).strip() + "\n",
            guidance_ids=selected.ids(),
        )


def _render_guidance(guidance: GuidanceSet) -> list[str]:
    blocks: list[str] = []
    for kind, heading in _KIND_HEADINGS.items():
        rules = tuple(guidance.of_kind(kind))
        if not rules:
            continue
        lines = [f"## {heading}", ""]
        lines.extend(_render_rule(rule) for rule in rules)
        blocks.append("\n".join(lines))
    return blocks


def _render_rule(rule: GuidanceRule) -> str:
    line = f"- {rule.text.strip()}"
    if rule.examples:
        line += "\n" + "\n".join(f"    {example}" for example in rule.examples)
    return line
