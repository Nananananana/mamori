"""Named, swappable detection algorithms.

0.31 made secret detection a choice: `secrets="patterns"` or `"entropy"`, with
a registry so a third is a call and a configuration value rather than an edit.
That shape turned out to be the right one for every question of this kind, and
there are now three:

    secrets   what finds a credential the pattern rules cannot name
    nlp       what finds a personal name that has no anchor beside it
    phone     what decides a run of digits is a telephone number

Each defaults to what shipped before it existed, so upgrading changes nothing
and every published figure holds. Each names an algorithm rather than a
boolean, because *"better name detection: on"* is a promise and
`nlp="spacy"` is a statement about what is running.

**Why an algorithm and not just a flag.** These are not degrees of the same
thing. A regular expression, a Shannon-entropy estimate, a numbering plan and a
statistical model fail differently, cost differently and are wrong about
different documents -- and the deployment is the only party that knows which
trade it can accept. Presidio, gitleaks and detect-secrets all made the same
choice for the same reason.

**The domain never learns any of this.** A registry produces
:class:`~mamori.ports.detection_pass.DetectionPass` objects, which speak in
domain terms and are the only thing the pipeline sees. Resolution, policy and
restoration are unchanged whichever algorithm ran, which is what keeps *"a
model is never the security mechanism"* true while a model is running.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ...errors import ConfigurationError
from ...ports.detection_pass import DetectionPass

__all__ = ["AlgorithmRegistry"]

#: Builds the passes one named algorithm adds. Called once per session, so a
#: factory may hold something expensive -- a loaded model, a compiled table --
#: and hand out one instance per call.
Factory = Callable[[], Sequence[DetectionPass]]


class AlgorithmRegistry:
    """Names -> the passes they add, for one kind of decision.

    Args:
        kind: What this registry chooses, for error messages. The word a
            configuration key uses: ``secrets``, ``nlp``, ``phone``.
        default: The name meaning *what shipped before this was a choice*. It
            is listed first everywhere and is what a config that says nothing
            gets.
        algorithms: The initial contents.
    """

    def __init__(self, kind: str, default: str, algorithms: dict[str, Factory]) -> None:
        if default not in algorithms:
            raise ValueError(f"the default {default!r} is not among the {kind} algorithms")
        self._kind = kind
        self._default = default
        self._factories = dict(algorithms)

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def default(self) -> str:
        return self._default

    def register(self, name: str, factory: Factory) -> None:
        """Add an algorithm, replacing one of the same name.

        Raises:
            ValueError: the name is not a lower-case word. A configuration
                value with a space or a capital in it reads differently in a
                TOML file, a JSON file and an environment variable, and this
                library refuses settings that mean different things in
                different places.
        """
        key = name.strip().lower()
        if not key or not key.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"an algorithm name must be a lower-case word, got {name!r}")
        self._factories[key] = factory

    def available(self) -> tuple[str, ...]:
        """Every registered name, the default first."""
        return (self._default, *sorted(n for n in self._factories if n != self._default))

    def resolve(self, name: str) -> str:
        """Normalise a configured name, or refuse it.

        Raises:
            ConfigurationError: no algorithm has that name. Refused rather
                than fallen back on: a deployment that wrote ``"spcay"`` and
                silently got the pattern rules has a config file claiming it
                runs a model and a scanner that does not.
        """
        key = str(name).strip().lower()
        if key not in self._factories:
            known = ", ".join(self.available())
            raise ConfigurationError(f"unknown {self._kind} algorithm {name!r}; available: {known}")
        return key

    def passes(self, name: str) -> tuple[DetectionPass, ...]:
        """The passes ``name`` adds, after the pattern rules."""
        return tuple(self._factories[self.resolve(name)]())
