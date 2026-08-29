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
from pathlib import Path
from typing import Any

from .domain.entity_types import Category
from .domain.policy import Action, PrivacyPolicy
from .domain.stance import Stance
from .errors import ConfigurationError
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
        )

    def detectors(self) -> tuple[Any, ...]:
        """The detector set these settings describe."""
        from .infrastructure.detectors import CoOccurrencePass, build_pipeline

        pass_ = (
            CoOccurrencePass(min_confidence=self.co_occurrence_min_confidence)
            if self.co_occurrence
            else None
        )
        return (build_pipeline(self.locales, co_occurrence=pass_, stance=self.stance),)

    def prompt_library(self) -> PromptLibrary:
        """The prompts these settings describe, overlays applied.

        Raises:
            ConfigurationError: an overlay for an unknown prompt, or one that
                disables guidance that is not there.
        """
        from .prompts.library import PromptLibrary as _Library

        return _Library.from_mapping(self.prompts) if self.prompts else default_library()

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
        return cls(**kwargs)  # type: ignore[arg-type]

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> MamoriConfig:
        """Build a config from ``MAMORI_*`` environment variables.

        ``MAMORI_LOCALES=ja,en``, ``MAMORI_MIN_CONFIDENCE=0.7``,
        ``MAMORI_CO_OCCURRENCE=off``, ``MAMORI_DEFAULT_ACTION=block``.

        Raises:
            ConfigurationError: an unknown ``MAMORI_*`` variable, or a value of
                the wrong shape.
        """
        source = os.environ if environ is None else environ
        values: dict[str, object] = {}
        for key, raw in source.items():
            if not key.startswith(_ENV_PREFIX):
                continue
            name = key[len(_ENV_PREFIX) :].lower()
            if name == "locales":
                values["locales"] = [part.strip() for part in raw.split(",") if part.strip()]
            else:
                values[name] = raw
        return cls.from_mapping(values)

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


def _as_prompts(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"prompts must be a mapping, got {type(value).__name__}")
    # Validated eagerly: an overlay that only fails when a model is finally
    # wired up is an overlay nobody notices is broken.
    from .prompts.library import PromptLibrary as _Library

    overlays = {str(key): item for key, item in value.items()}
    _Library.from_mapping(overlays)
    return overlays


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
