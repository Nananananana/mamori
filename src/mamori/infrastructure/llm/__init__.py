"""Local model adapters.

One real one, for any server that speaks the OpenAI chat API, and two for
tests. All of them talk to something on this machine: the text reaches a
detector *before* it is protected, so a detector that is not local is the leak.
"""

from __future__ import annotations

from .openai_compatible import OpenAICompatibleProvider
from .scripted import FailingProvider, ScriptedProvider

__all__ = ["FailingProvider", "OpenAICompatibleProvider", "ScriptedProvider"]
