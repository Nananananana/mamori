"""Prompts, and the knowledge that goes into them.

The library ships two. ``detection`` asks a local model to find what patterns
cannot reach. ``external`` tells the service model to leave the placeholders
alone -- and that one needs no local model at all.

    >>> from mamori.prompts import default_library
    >>> print(default_library().render("external").text)  # doctest: +ELLIPSIS
    Some values in the following text have been replaced...

Both are assembled from addressable parts, so an organisation adds its own
guidance and drops what does not fit, without forking anything. See
:mod:`mamori.prompts.overlay`.
"""

from __future__ import annotations

from .definition import PromptDefinition, PromptSection, RenderedPrompt
from .guidance import BUILTIN_GUIDANCE, GuidanceKind, GuidanceRule, GuidanceSet
from .library import (
    DETECTION_PROMPT,
    DETECTION_PROMPT_ID,
    EXTERNAL_PROMPT,
    EXTERNAL_PROMPT_ID,
    PromptLibrary,
    default_library,
)
from .overlay import PromptOverlay
from .parsing import DETECTION_SCHEMA, ParseOutcome, parse_detection_response

__all__ = [
    "BUILTIN_GUIDANCE",
    "DETECTION_PROMPT",
    "DETECTION_PROMPT_ID",
    "DETECTION_SCHEMA",
    "EXTERNAL_PROMPT",
    "EXTERNAL_PROMPT_ID",
    "GuidanceKind",
    "GuidanceRule",
    "GuidanceSet",
    "ParseOutcome",
    "PromptDefinition",
    "PromptLibrary",
    "PromptOverlay",
    "PromptSection",
    "RenderedPrompt",
    "default_library",
    "parse_detection_response",
]
