"""The two registries added in 0.32, and what they default to.

Both default to what shipped before them, so an upgrade changes no behaviour
and every published figure holds. Turning one on is a decision with a stated
cost, and `mamori privacy` reports which is running.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...ports.detection_pass import DetectionPass
from .algorithms import AlgorithmRegistry

__all__ = [
    "DEFAULT_NLP_ALGORITHM",
    "DEFAULT_PHONE_ALGORITHM",
    "available_nlp_algorithms",
    "available_phone_algorithms",
    "nlp_passes",
    "phone_passes",
    "register_nlp_algorithm",
    "register_phone_algorithm",
]

#: No model. What every release before 0.32 did, and the default: a personal
#: name with no anchor is found by the wide tier or not at all, which is the
#: gap `SECURITY.md` calls the largest in the library.
DEFAULT_NLP_ALGORITHM = "none"

#: Shape only. The documented cost is that an unseparated digit run is not
#: matched, because an order number looks identical to a regular expression.
DEFAULT_PHONE_ALGORITHM = "patterns"


def _spacy() -> Sequence[DetectionPass]:
    from .nlp import NlpPass, SpacyRecognizer

    return (NlpPass(SpacyRecognizer()),)


def _phonenumbers() -> Sequence[DetectionPass]:
    from .phone import PhoneNumberPass

    return (PhoneNumberPass(),)


_NLP = AlgorithmRegistry(
    "nlp",
    DEFAULT_NLP_ALGORITHM,
    {DEFAULT_NLP_ALGORITHM: lambda: (), "spacy": _spacy},
)

_PHONE = AlgorithmRegistry(
    "phone",
    DEFAULT_PHONE_ALGORITHM,
    {DEFAULT_PHONE_ALGORITHM: lambda: (), "phonenumbers": _phonenumbers},
)


def register_nlp_algorithm(name: str, factory: object) -> None:
    """Add a named recogniser -- a transformer, a remote service, a stub.

    The factory returns detection passes, so an implementation is free to be
    anything that can read text; :class:`~mamori.ports.nlp_recognizer
    .NlpRecognizer` with :class:`~mamori.infrastructure.detectors.nlp.NlpPass`
    around it is the short way, and not the only one.
    """
    _NLP.register(name, factory)  # type: ignore[arg-type]


def register_phone_algorithm(name: str, factory: object) -> None:
    """Add a named way of deciding a run of digits is a telephone number."""
    _PHONE.register(name, factory)  # type: ignore[arg-type]


def available_nlp_algorithms() -> tuple[str, ...]:
    return _NLP.available()


def available_phone_algorithms() -> tuple[str, ...]:
    return _PHONE.available()


def nlp_passes(name: str) -> tuple[DetectionPass, ...]:
    return _NLP.passes(name)


def phone_passes(name: str) -> tuple[DetectionPass, ...]:
    return _PHONE.passes(name)
