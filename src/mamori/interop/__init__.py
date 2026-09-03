"""Speaking other libraries' shapes.

A privacy layer is adopted or not adopted on one question: how much has to be
rewritten to try it. Everything in here exists to make the answer "an import".

Nothing in this package imports `interop`, and `interop` decides nothing -- it
translates, over the same public surface any caller has. Same arrangement as
`report` and `provenance`: a description of the library that the library cannot
reach.
"""

from .presidio import (
    AnalyzerEngine,
    AnonymizerEngine,
    AnonymizerResult,
    PresidioRecognizer,
    RecognizerResult,
    from_presidio,
    to_presidio,
)

__all__ = [
    "AnalyzerEngine",
    "AnonymizerEngine",
    "AnonymizerResult",
    "PresidioRecognizer",
    "RecognizerResult",
    "from_presidio",
    "to_presidio",
]
