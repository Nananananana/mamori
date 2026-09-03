"""One object holding every switch.

The pieces were always swappable -- detectors, policy, store, language packs --
but only from Python, one constructor argument at a time. A team that wants the
same settings in a script, a CLI invocation and (from v0.4) a proxy had nowhere
to put them.

``MamoriConfig`` is that place. It is a plain frozen dataclass: no file format,
no parser, no dependency. :meth:`MamoriConfig.from_mapping` takes an already-
parsed mapping, so the caller decides whether that came from JSON, TOML, YAML,
a database row or a dict literal:

    >>> import json
    >>> from mamori import MamoriConfig
    >>> MamoriConfig.from_mapping({"locales": ["ja", "en"], "min_confidence": 0.7})
    MamoriConfig(locales=('ja', 'en'), ...)

Not choosing a format is the point. The moment this module imports a YAML
parser, every user of the library inherits it, and a privacy tool nobody wants
to audit is a privacy tool nobody uses.

:func:`load_config_file` is a convenience over the two formats the standard
library can already read, for callers who would rather not write the four lines
themselves.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .domain.corrections import CorrectionLog
from .domain.entity_types import Category
from .domain.placeholder import PlaceholderStyle
from .domain.policy import Action, PrivacyPolicy, Uncertain
from .domain.stance import Stance
from .errors import ConfigurationError
from .llm_settings import LLMSettings

if TYPE_CHECKING:  # imported for types only; the runtime import stays lazy
    from .application.session import PrivacySession
    from .ports.llm import LLMProvider
    from .ports.mapping_store import MappingStore
from .prompts.library import PromptLibrary, default_library

__all__ = ["MamoriConfig", "load_config_file"]

_ENV_PREFIX = "MAMORI_"
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True, slots=True)
class MamoriConfig:
    """Everything a session can be told to do differently.

    Args:
        locales: Language pack codes, or ``None`` for all of them.
        stance: Which rule tiers run. ``recall_first`` adds the wide tier --
            rules that match on shape alone, with no anchor. They find what
            nothing else can and they also fire on order numbers and product
            names. The default, because a miss is silent and a stray
            placeholder is visible.
        rules: Entity type name -> action, highest precedence.
        category_defaults: Category name -> action.
        default_action: Used when neither matches. ``block`` keeps an
            unrecognised kind of sensitive data from leaving the machine.
        min_confidence: Detections below this are discarded. Raising it trades
            coverage for answer quality; the default must stay at ``0.0``.
        co_occurrence: Whether to propagate a confidently-detected value to its
            other mentions in the same text. Off costs recall on repeated
            names and never costs safety.
        co_occurrence_min_confidence: How sure a detection must be before its
            value is trusted as a seed.
        mask_token: Text substituted for the ``mask`` action.
        prompts: Per-prompt overlays -- guidance to add, guidance to disable,
            sections to replace. This is where an organisation puts what the
            library cannot know: that their case numbers look like ACME-12345,
            or that a product name keeps coming back as a person.
        llm: A model to run as a final detection pass, on this machine or on
            the network. ``None`` means patterns only, which is what every
            release before this one did and remains a complete configuration.
        corrections: Values this operator has ruled on -- either a path to a
            log, or the entries themselves. This is the only setting that can
            *reduce* what is detected, and what it excludes is reported by
            ``mamori privacy``. A credential can never be excluded.
        uncertain: ``"discard"`` (the default) or ``"refuse"``. What to do
            with a detection below ``min_confidence``: drop it and send the
            text, or stop. Refusing does nothing at the default
            ``min_confidence`` of ``0.0``, because nothing is below zero --
            the two settings are one dial, and this is the half that says
            what happens where certainty runs out.
        placeholder_style: ``"angle"`` (the default, ``<PERSON_001>``),
            ``"square"`` (``[PERSON_001]``) or ``"curly"`` (``{PERSON_001}``).
            Square brackets for HTML and XML, where the default form is an
            unknown element rather than a word. Restoration accepts all three
            whatever this is, so changing it does not strand anything.
        surrogates: Entity types replaced by a plausible value rather than by a
            token -- ``["PERSON", "EMAIL"]``, or ``true`` for every type a pool
            covers. Off by default. It buys answer quality and costs the thing
            that makes a placeholder safe: an unrestored token is obvious, and
            an unrestored surrogate reads as a fact about the wrong person.
    """

    locales: tuple[str, ...] | None = None
    stance: Stance = Stance.RECALL_FIRST
    rules: Mapping[str, Action] = field(default_factory=dict)
    category_defaults: Mapping[Category, Action] = field(default_factory=dict)
    default_action: Action = Action.BLOCK
    min_confidence: float = 0.0
    co_occurrence: bool = True
    co_occurrence_min_confidence: float = 0.85
    mask_token: str = "[REDACTED]"  # noqa: S105 - a redaction marker, not a credential
    prompts: Mapping[str, object] = field(default_factory=dict)
    llm: LLMSettings | None = None
    corrections: str | Sequence[Mapping[str, object]] = ()
    surrogates: bool | Sequence[str] = False
    placeholder_style: str = "angle"
    uncertain: str = "discard"

    def __post_init__(self) -> None:
        for name in ("min_confidence", "co_occurrence_min_confidence"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ConfigurationError(f"{name} out of range: {value}")

    # -- building blocks ---------------------------------------------------

    def policy(self) -> PrivacyPolicy:
        """The policy these settings describe."""
        base = PrivacyPolicy.default()
        return PrivacyPolicy(
            rules={**base.rules, **self.rules},
            category_defaults=dict(self.category_defaults) or dict(base.category_defaults),
            default_action=self.default_action,
            mask_token=self.mask_token,
            min_confidence=self.min_confidence,
            uncertain=self.uncertainty(),
        )

    def detectors(self, *, provider: LLMProvider | None = None) -> tuple[Any, ...]:
        """The detector set these settings describe.

        Args:
            provider: Replaces the model these settings name, keeping
                everything else identical. Measurement needs this -- to score a
                cached provider, or a second model -- and it is a parameter
                rather than a second assembly path on purpose: a harness that
                rebuilt the pipeline by hand silently lost the co-occurrence
                pass and published a model comparison against the wrong
                baseline for two releases.

        Raises:
            ConfigurationError: an unknown locale or provider, or an endpoint
                outside its trust boundary. Raised here rather than on the
                first document, so a misconfigured model is found at startup.
        """
        from .infrastructure.detectors import CoOccurrencePass, build_pipeline
        from .infrastructure.detectors.corrections_pass import CorrectionsPass

        pass_ = (
            CoOccurrencePass(min_confidence=self.co_occurrence_min_confidence)
            if self.co_occurrence
            else None
        )
        extra = list(self.llm_passes(provider=provider))
        log = self.correction_log()
        if log.added():
            # Last, so it sees what everything else found and adds only what
            # nothing covers. An operator saying "this is sensitive" is adding
            # evidence, not relabelling a detection that already exists.
            extra.append(CorrectionsPass(log))
        return (
            build_pipeline(
                self.locales,
                co_occurrence=pass_,
                stance=self.stance,
                extra_passes=extra,
            ),
        )

    def surrogate_types(self) -> frozenset[str]:
        """Types to substitute with a plausible value rather than a token."""
        from .domain.surrogate import supported_types

        if self.surrogates is True:
            return supported_types()
        if self.surrogates is False:
            return frozenset()
        return frozenset(str(name).strip().upper() for name in self.surrogates)

    def correction_log(self) -> CorrectionLog:
        """The operator's rulings, from a path or from the settings themselves.

        Raises:
            ConfigurationError: the log names an unknown type, is malformed, or
                tries to allow-list a credential.
        """
        from .infrastructure.storage.corrections import from_mapping, load_corrections

        if isinstance(self.corrections, str):
            return load_corrections(Path(self.corrections))
        if not self.corrections:
            return CorrectionLog()
        try:
            return from_mapping(list(self.corrections), origin="<config>")
        except ValueError as exc:
            raise ConfigurationError(f"corrections: {exc}") from exc

    def llm_passes(self, *, provider: LLMProvider | None = None) -> tuple[Any, ...]:
        """The model pass these settings describe, or nothing.

        Built here rather than inside the pipeline so that a caller who wants
        to supply their own provider object -- one this configuration could not
        name, because it holds a loaded model or a client with credentials --
        can skip this entirely and pass the pass in directly.

        Args:
            provider: Used instead of the one these settings name. Everything
                else about the pass -- prompt library, locales, limits -- stays
                as configured.
        """
        if self.llm is None or not self.llm.model:
            return ()

        from .infrastructure.detectors.llm_pass import LLMDetectionPass
        from .infrastructure.llm import create_provider

        if provider is None:
            provider = create_provider(self.llm.provider, self.llm.endpoint())
        return (
            LLMDetectionPass(
                provider,
                library=self.prompt_library(),
                locales=self.llm.locales if self.llm.locales else self.locales,
                require_model=self.llm.require_model,
                max_input_characters=self.llm.max_input_characters,
            ),
        )

    def prompt_library(self) -> PromptLibrary:
        """The prompts these settings describe, overlays applied.

        Raises:
            ConfigurationError: an overlay for an unknown prompt, or one that
                disables guidance that is not there.
        """
        from .prompts.library import PromptLibrary as _Library

        return _Library.from_mapping(self.prompts) if self.prompts else default_library()

    def session(
        self,
        *,
        policy: PrivacyPolicy | None = None,
        store: MappingStore | None = None,
        scope: str | None = None,
        trace: bool = False,
    ) -> PrivacySession:
        """Build a :class:`~mamori.application.session.PrivacySession`.

        Args:
            policy: Overrides the policy the settings would produce. The CLI
                uses it for ``--permissive``; nothing else should need it.
            store: Where mappings live. ``None`` means memory, which is the
                only place they go unless a caller says otherwise.
            scope: Partition key, so two tenants cannot read each other back.

        Settings assemble a session; a session does not read settings. That
        direction is what keeps the application layer from depending on the
        adapters a configuration names, and it is checked by
        ``tests/test_architecture.py``.

        Raises:
            ConfigurationError: an unknown locale or provider, an endpoint
                outside its trust boundary, or a broken prompt overlay. Raised
                here rather than on the first document.
        """
        from .application.session import PrivacySession

        return PrivacySession(
            detectors=self.detectors(),
            policy=self.policy() if policy is None else policy,
            store=store,
            scope=scope,
            prompts=self.prompt_library(),
            corrections=self.correction_log(),
            surrogate_types=self.surrogate_types(),
            placeholder_style=self.style(),
            trace=trace,
        )

    def uncertainty(self) -> Uncertain:
        """What happens to a detection below the confidence threshold.

        Raises:
            ConfigurationError: an unrecognised name.
        """
        try:
            return Uncertain(self.uncertain)
        except ValueError:
            known = ", ".join(sorted(choice.value for choice in Uncertain))
            raise ConfigurationError(
                f"unknown uncertain {self.uncertain!r}; known: {known}"
            ) from None

    def style(self) -> PlaceholderStyle:
        """The placeholder style, resolved.

        Raises:
            ConfigurationError: an unrecognised name. A typo here would send a
                document out in a form the caller did not choose, which is
                exactly the class of silent mistake this module refuses.
        """
        try:
            return PlaceholderStyle(self.placeholder_style)
        except ValueError:
            known = ", ".join(sorted(style.value for style in PlaceholderStyle))
            raise ConfigurationError(
                f"unknown placeholder_style {self.placeholder_style!r}; known: {known}"
            ) from None

    def replace(self, **changes: object) -> MamoriConfig:
        """Return a copy with some fields changed."""
        return replace(self, **changes)  # type: ignore[arg-type]

    # -- loading -----------------------------------------------------------

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> MamoriConfig:
        """Build a config from an already-parsed mapping.

        Unknown keys are refused rather than ignored. A typo in a privacy
        setting that silently does nothing is the worst possible outcome: the
        user believes they tightened something and did not.

        Raises:
            ConfigurationError: an unknown key, or a value of the wrong shape.
        """
        known = {f.name for f in cls.__dataclass_fields__.values()}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ConfigurationError(
                f"unknown configuration key(s): {', '.join(unknown)}; "
                f"known keys: {', '.join(sorted(known))}"
            )

        kwargs: dict[str, object] = {}
        if "locales" in values:
            kwargs["locales"] = _as_locales(values["locales"])
        if "stance" in values:
            kwargs["stance"] = _as_stance(values["stance"])
        if "rules" in values:
            kwargs["rules"] = _as_rules(values["rules"])
        if "category_defaults" in values:
            kwargs["category_defaults"] = _as_category_defaults(values["category_defaults"])
        if "default_action" in values:
            kwargs["default_action"] = _as_action(values["default_action"], "default_action")
        if "min_confidence" in values:
            kwargs["min_confidence"] = _as_float(values["min_confidence"], "min_confidence")
        if "co_occurrence" in values:
            kwargs["co_occurrence"] = _as_bool(values["co_occurrence"], "co_occurrence")
        if "co_occurrence_min_confidence" in values:
            kwargs["co_occurrence_min_confidence"] = _as_float(
                values["co_occurrence_min_confidence"], "co_occurrence_min_confidence"
            )
        if "mask_token" in values:
            kwargs["mask_token"] = str(values["mask_token"])
        if "prompts" in values:
            kwargs["prompts"] = _as_prompts(values["prompts"])
        if "llm" in values:
            raw_llm = values["llm"]
            if raw_llm is None:
                kwargs["llm"] = None
            elif isinstance(raw_llm, Mapping):
                kwargs["llm"] = LLMSettings.from_mapping(raw_llm)
            else:
                raise ConfigurationError("llm must be a mapping or null")
        if "corrections" in values:
            kwargs["corrections"] = _as_corrections(values["corrections"])
        if "surrogates" in values:
            kwargs["surrogates"] = _as_surrogates(values["surrogates"])
        # These two were dataclass fields since 0.19 and 0.20, and were not
        # read here until 0.31. The key check above accepted them as known and
        # this method then dropped them: `{"uncertain": "refuse"}` in a file,
        # or `MAMORI_UNCERTAIN=refuse`, gave "discard" and said nothing. That
        # is precisely the outcome the paragraph above calls the worst one --
        # a safety setting the user believes they tightened and did not --
        # arrived at from the other side, by a *correct* key. The structural
        # test in `tests/test_config.py` now makes a field without a parser a
        # failure, so the next one cannot get this far.
        if "placeholder_style" in values:
            kwargs["placeholder_style"] = _as_choice(
                values["placeholder_style"], "placeholder_style", PlaceholderStyle
            )
        if "uncertain" in values:
            kwargs["uncertain"] = _as_choice(values["uncertain"], "uncertain", Uncertain)
        return cls(**kwargs)  # type: ignore[arg-type]

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> MamoriConfig:
        """Build a config from ``MAMORI_*`` environment variables.

        ``MAMORI_LOCALES=ja,en``, ``MAMORI_MIN_CONFIDENCE=0.7``,
        ``MAMORI_CO_OCCURRENCE=off``, ``MAMORI_DEFAULT_ACTION=block``.

        The whole ``MAMORI_`` prefix is reserved for settings, and an unknown
        one is an error rather than something ignored -- a misspelled privacy
        variable that silently does nothing is the worst outcome there is. That
        makes the prefix a poor place to keep an API key, so the error says so.

        Raises:
            ConfigurationError: an unknown ``MAMORI_*`` variable, or a value of
                the wrong shape.
        """
        source = os.environ if environ is None else environ
        values: dict[str, object] = {}
        origins: dict[str, str] = {}
        for key, raw in source.items():
            if not key.startswith(_ENV_PREFIX):
                continue
            name = key[len(_ENV_PREFIX) :].lower()
            origins[name] = key
            if name == "locales":
                values["locales"] = [part.strip() for part in raw.split(",") if part.strip()]
            else:
                values[name] = raw
        try:
            return cls.from_mapping(values)
        except ConfigurationError as exc:
            known = {f.name for f in cls.__dataclass_fields__.values()}
            stray = sorted(origins[name] for name in values if name not in known)
            if not stray:
                raise
            raise ConfigurationError(
                f"{exc} The MAMORI_ prefix is reserved for settings, so "
                f"{', '.join(stray)} cannot be used for anything else -- an API "
                "key variable, for instance, needs a name outside the prefix."
            ) from exc

    def merged_with(self, other: MamoriConfig) -> MamoriConfig:
        """Overlay ``other`` on this config, keeping ``other`` where it differs.

        Used to layer environment variables over a file, and command-line flags
        over both.
        """
        defaults = MamoriConfig()
        changes = {
            name: getattr(other, name)
            for name in (f.name for f in MamoriConfig.__dataclass_fields__.values())
            if getattr(other, name) != getattr(defaults, name)
        }
        return replace(self, **changes)


def load_config_file(path: Path) -> MamoriConfig:
    """Read a config from a JSON or TOML file.

    A convenience, not a commitment: :meth:`MamoriConfig.from_mapping` accepts a
    mapping from anywhere, so a caller who prefers another format parses it
    themselves and keeps this library dependency-free.

    Raises:
        ConfigurationError: unreadable, malformed, or TOML on a Python without
            ``tomllib``.
    """
    suffix = path.suffix.lower()
    try:
        if suffix == ".toml":
            payload = _load_toml(path)
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError(f"could not read config: {path}") from exc
    except ValueError as exc:
        raise ConfigurationError(f"malformed config: {path}") from exc

    if not isinstance(payload, dict):
        raise ConfigurationError(f"config must be a mapping: {path}")
    return MamoriConfig.from_mapping(payload)


def _load_toml(path: Path) -> object:
    try:
        import tomllib
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on the runtime
        raise ConfigurationError(
            f"TOML needs Python 3.11 or later; use a .json config instead: {path}"
        ) from exc
    with path.open("rb") as handle:
        return tomllib.load(handle)


# -- coercion ---------------------------------------------------------------


def _as_locales(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value)
    raise ConfigurationError(f"locales must be a list or a comma-separated string: {value!r}")


def _as_surrogates(value: object) -> bool | Sequence[str]:
    """``true``, ``false``, or the list of types to substitute."""
    from .domain.surrogate import supported_types

    if isinstance(value, bool):
        return value
    if isinstance(value, Sequence) and not isinstance(value, str):
        names = [str(name).strip().upper() for name in value]
        unknown = sorted(set(names) - supported_types())
        if unknown:
            raise ConfigurationError(
                f"no surrogate pool for {', '.join(unknown)}; "
                f"available: {', '.join(sorted(supported_types()))}"
            )
        return names
    raise ConfigurationError("surrogates must be true, false, or a list of type names")


def _as_corrections(value: object) -> str | Sequence[Mapping[str, object]]:
    """Either a path to a log, or the entries themselves.

    Both are useful and they are not the same thing. A path is a log an
    operator appends to with ``mamori correct``; entries in the settings are
    rulings that travel with the configuration and are reviewed alongside it.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        entries = list(value)
        if all(isinstance(entry, Mapping) for entry in entries):
            return entries
    raise ConfigurationError("corrections must be a path to a log, or a list of correction objects")


def _as_prompts(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"prompts must be a mapping, got {type(value).__name__}")
    # Validated eagerly: an overlay that only fails when a model is finally
    # wired up is an overlay nobody notices is broken.
    from .prompts.library import PromptLibrary as _Library

    overlays = {str(key): item for key, item in value.items()}
    _Library.from_mapping(overlays)
    return overlays


def _as_choice(value: object, where: str, choices: type[Enum]) -> str:
    """One of an enum's values, as the string the dataclass field stores.

    Validated here rather than left to :meth:`MamoriConfig.style` and
    :meth:`MamoriConfig.uncertainty`, which check the same thing at use time:
    a bad name in a config file should be refused when the file is read, not
    on the first document, and the error should say where it came from.
    """
    text = str(value).strip().lower()
    known = sorted(choice.value for choice in choices)
    if text not in known:
        raise ConfigurationError(f"unknown {where} {value!r}; allowed: {', '.join(known)}")
    return text


def _as_stance(value: object) -> Stance:
    try:
        return Stance(str(value).strip().lower())
    except ValueError as exc:
        allowed = ", ".join(stance.value for stance in Stance)
        raise ConfigurationError(f"unknown stance {value!r}; allowed: {allowed}") from exc


def _as_action(value: object, where: str) -> Action:
    try:
        return Action(str(value).strip().lower())
    except ValueError as exc:
        allowed = ", ".join(action.value for action in Action)
        raise ConfigurationError(f"{where}: unknown action {value!r}; allowed: {allowed}") from exc


def _as_rules(value: object) -> dict[str, Action]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"rules must be a mapping, got {type(value).__name__}")
    return {str(name): _as_action(action, f"rules.{name}") for name, action in value.items()}


def _as_category_defaults(value: object) -> dict[Category, Action]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"category_defaults must be a mapping, got {type(value).__name__}")
    result: dict[Category, Action] = {}
    for name, action in value.items():
        try:
            category = Category(str(name).strip().upper())
        except ValueError as exc:
            allowed = ", ".join(c.value for c in Category)
            raise ConfigurationError(
                f"category_defaults: unknown category {name!r}; allowed: {allowed}"
            ) from exc
        result[category] = _as_action(action, f"category_defaults.{name}")
    return result


def _as_float(value: object, where: str) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{where} must be a number, got {value!r}") from exc


def _as_bool(value: object, where: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ConfigurationError(f"{where} must be true or false, got {value!r}")
