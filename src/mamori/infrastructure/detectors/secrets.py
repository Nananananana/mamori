"""Which algorithm looks for the credentials the patterns cannot name.

The pattern rules always run: a vendor prefix, a PEM block, a database URL and
a keyword-assigned password are matched whatever this says. This chooses what
runs **after** them, for the secrets that have no such anchor -- and it is a
choice, selected by name, because the candidates disagree about the trade and
the deployment has to be the one to make it.

    patterns   nothing more. What every release before 0.31 did, and the
               default: a credential with no recognisable shape is missed,
               and no content hash is ever mistaken for one.
    entropy    the Shannon-entropy pass, as `detect-secrets` and `gitleaks`
               run it. Finds the bare hex key and the random session token;
               also flags a commit id and a base64 payload, and the default
               policy *blocks* what it flags.

Registered by name so a fourth algorithm -- a local model asked one question
per candidate, a Bloom filter of known-leaked keys -- is a
:func:`register_secret_algorithm` call and a config value, and not an edit to
this file. The same shape the language packs use, for the same reason.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ...errors import ConfigurationError
from ...ports.detection_pass import DetectionPass
from .entropy_pass import EntropyPass

__all__ = [
    "DEFAULT_SECRET_ALGORITHM",
    "available_secret_algorithms",
    "register_secret_algorithm",
    "secret_passes",
]

#: What runs when nobody chose. Patterns only, as before, because the other
#: choice turns a hash into a refused request and that is not a default anyone
#: should inherit without being asked.
DEFAULT_SECRET_ALGORITHM = "patterns"  # noqa: S105 - an algorithm name, not a credential

#: Name -> a factory producing the passes that name adds. The pattern rules are
#: not here because they are not optional; "patterns" adds nothing to them.
_REGISTRY: dict[str, Callable[[], Sequence[DetectionPass]]] = {
    "patterns": lambda: (),
    "entropy": lambda: (EntropyPass(),),
}


def register_secret_algorithm(name: str, factory: Callable[[], Sequence[DetectionPass]]) -> None:
    """Register an algorithm under ``name``, replacing one with the same name.

    Args:
        name: What a configuration says. Lower-case, no spaces.
        factory: Builds the passes the algorithm adds after the pattern rules.
            Called once per session, so a factory may hold something heavy --
            a model, a filter -- and hand out one instance each time.
    """
    key = name.strip().lower()
    if not key or " " in key:
        raise ValueError(f"an algorithm name must be a lower-case word, got {name!r}")
    _REGISTRY[key] = factory


def available_secret_algorithms() -> tuple[str, ...]:
    """Every registered name, sorted, with the default first."""
    rest = sorted(name for name in _REGISTRY if name != DEFAULT_SECRET_ALGORITHM)
    return (DEFAULT_SECRET_ALGORITHM, *rest)


def secret_passes(name: str) -> tuple[DetectionPass, ...]:
    """The passes ``name`` adds after the pattern rules.

    Raises:
        ConfigurationError: no algorithm has that name. Refused rather than
            fallen back on, because a deployment that wrote ``"entrpy"`` and
            silently got patterns has a config file that says it is looking
            for bare keys and a scanner that is not.
    """
    factory = _REGISTRY.get(name.strip().lower())
    if factory is None:
        known = ", ".join(available_secret_algorithms())
        raise ConfigurationError(f"unknown secrets algorithm {name!r}; available: {known}")
    return tuple(factory())
