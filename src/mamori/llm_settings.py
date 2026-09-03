"""How a model is configured, kept out of the code that uses one.

The model belongs in the same place as every other switch, and it has to be
describable without Python: which provider, which model, where it is, how far
away it is allowed to be. That is what lets a team point a laptop at
``localhost`` and a server at the GPU box with the same code and two config
files.

    {"llm": {"provider": "openai_compatible",
             "model": "qwen2.5:7b",
             "base_url": "http://llm01.corp:8000/v1/",
             "trust": "private_network"}}

**The key is named, never carried.** ``api_key_env`` holds the name of an
environment variable. A configuration file that gets committed -- and one will
-- then contains the string ``LLM_API_KEY`` rather than a key.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .domain.trust import EndpointPolicy, TrustBoundary
from .errors import ConfigurationError
from .ports.llm_endpoint import DEFAULT_BASE_URL, LLMEndpoint

__all__ = ["LLMSettings"]

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True, slots=True)
class LLMSettings:
    """Which model, where, and how much to trust it.

    Args:
        provider: A name registered with ``register_llm_provider``. Two ship:
            ``openai_compatible`` for anything speaking the OpenAI chat API,
            and whatever a deployment registers for its own client.
        model: Name the server knows, e.g. ``qwen2.5:7b``.
        base_url: Root of the API. Defaults to Ollama on this machine.
        api_key_env: Name of an environment variable holding a key. Not a key.
        timeout: Seconds for one attempt.
        retries: Extra attempts for transient failures. Only applied when the
            endpoint is on another machine -- a socket here that refuses will
            refuse again.
        backoff: Seconds before the first retry, doubling after.
        trust: How far the endpoint may be. ``private_network`` covers a model
            on this machine and one on the company's server, and refuses a
            public API endpoint.
        trusted_hosts: Names admitted whatever the boundary, for an internal
            host whose name happens to look public.
        require_model: Turn a model failure into a stopped request. Off by
            default: rules are the guarantee, the model is the improvement.
        max_input_characters: How much text goes to the model in one request.
            Longer text is **windowed** rather than refused or truncated --
            overlapping pieces, with the offsets carried back
            (:doc:`ADR 0021 </adr/0021-a-long-document-is-windowed>`), because
            a document that is too long is exactly the document somebody most
            wants protected.

            This said "refuse to send more than this" until 0.23, which was
            the behaviour before windowing existed and had been wrong ever
            since. A setting whose description and behaviour disagree is worse
            than one with no description: somebody configures the sentence
            they read.
        locales: Keep only guidance for these languages in the prompt, which
            shortens it. ``None`` keeps all of it.
    """

    provider: str = "openai_compatible"
    model: str = ""
    base_url: str = DEFAULT_BASE_URL
    api_key_env: str = ""
    timeout: float = 60.0
    retries: int = 2
    backoff: float = 0.5
    trust: TrustBoundary = TrustBoundary.PRIVATE_NETWORK
    trusted_hosts: tuple[str, ...] = ()
    require_model: bool = False
    max_input_characters: int = 8000
    locales: tuple[str, ...] | None = None
    options: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timeout <= 0:
            raise ConfigurationError(f"llm.timeout must be positive, got {self.timeout}")
        if self.retries < 0:
            raise ConfigurationError(f"llm.retries must be >= 0, got {self.retries}")
        if self.max_input_characters < 1:
            raise ConfigurationError("llm.max_input_characters must be positive")
        # A window that cannot carry the longest thing the rules look for hands
        # every detector a value cut in half, and finds it in no window at all.
        # The overlap is what covers a join, and it is clamped to half the
        # window -- so the window, not the overlap constant, is what decides.
        # `max_input_characters=100` was accepted, and lost a 52-character
        # database URL at offset 49 to the gap between two windows: measured,
        # 10 losing positions at 100 and 210 at 60. This is where that stops
        # being possible to configure by accident.
        from .domain.windowing import LONGEST_ENTITY, longest_whole

        whole = longest_whole(self.max_input_characters)
        if whole < LONGEST_ENTITY:
            raise ConfigurationError(
                f"llm.max_input_characters={self.max_input_characters} guarantees only "
                f"{whole} characters are handed to a detector whole, and a credential "
                f"can be {LONGEST_ENTITY}. A value that straddles a window join is "
                f"found by nothing and reported by nothing. Use at least "
                f"{LONGEST_ENTITY * 2}."
            )

    def endpoint(self) -> LLMEndpoint:
        """The endpoint these settings describe."""
        return LLMEndpoint(
            model=self.model,
            base_url=self.base_url,
            api_key_env=self.api_key_env,
            timeout=self.timeout,
            retries=self.retries,
            backoff=self.backoff,
            policy=EndpointPolicy(self.trust, frozenset(self.trusted_hosts)),
            options=dict(self.options),
        )

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> LLMSettings:
        """Build settings from an already-parsed mapping.

        Raises:
            ConfigurationError: an unknown key, or a value of the wrong shape.
                Unknown keys are refused for the same reason as everywhere
                else: a misspelled ``trust`` that silently does nothing leaves
                somebody believing they restricted an endpoint.
        """
        known = {f.name for f in cls.__dataclass_fields__.values()}
        if "api_key" in values:
            raise ConfigurationError(
                "llm.api_key is not accepted: put the key in an environment "
                "variable and name it with llm.api_key_env, so a config file "
                "that gets committed does not contain a credential"
            )
        unknown = sorted(set(values) - known)
        if unknown:
            raise ConfigurationError(
                f"unknown llm key(s): {', '.join(unknown)}; known keys: {', '.join(sorted(known))}"
            )

        kwargs: dict[str, object] = {}
        for name in ("provider", "model", "base_url", "api_key_env"):
            if name in values:
                kwargs[name] = str(values[name])
        for name in ("timeout", "backoff"):
            if name in values:
                kwargs[name] = _as_float(values[name], f"llm.{name}")
        for name in ("retries", "max_input_characters"):
            if name in values:
                kwargs[name] = _as_int(values[name], f"llm.{name}")
        if "require_model" in values:
            kwargs["require_model"] = _as_bool(values["require_model"], "llm.require_model")
        if "trust" in values:
            kwargs["trust"] = _as_boundary(values["trust"])
        if "trusted_hosts" in values:
            kwargs["trusted_hosts"] = tuple(
                str(h) for h in _as_sequence(values["trusted_hosts"], "llm.trusted_hosts")
            )
        if "locales" in values:
            raw = values["locales"]
            kwargs["locales"] = (
                None if raw is None else tuple(str(loc) for loc in _as_sequence(raw, "llm.locales"))
            )
        if "options" in values:
            raw_options = values["options"]
            if not isinstance(raw_options, Mapping):
                raise ConfigurationError("llm.options must be a mapping")
            kwargs["options"] = {str(k): v for k, v in raw_options.items()}
        return cls(**kwargs)  # type: ignore[arg-type]

    def as_mapping(self) -> dict[str, object]:
        """A round-trippable description. Never contains a key."""
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "timeout": self.timeout,
            "retries": self.retries,
            "backoff": self.backoff,
            "trust": self.trust.value,
            "trusted_hosts": list(self.trusted_hosts),
            "require_model": self.require_model,
            "max_input_characters": self.max_input_characters,
            "locales": list(self.locales) if self.locales else None,
        }


def _as_boundary(value: object) -> TrustBoundary:
    try:
        return TrustBoundary(str(value).strip().lower())
    except ValueError as exc:
        allowed = ", ".join(b.value for b in TrustBoundary)
        raise ConfigurationError(
            f"llm.trust: unknown boundary {value!r}; allowed: {allowed}"
        ) from exc


def _as_sequence(value: object, where: str) -> Sequence[object]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ConfigurationError(f"{where} must be a list")
    return value


def _as_float(value: object, where: str) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{where} must be a number, got {value!r}") from exc


def _as_int(value: object, where: str) -> int:
    try:
        parsed: int = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{where} must be a whole number, got {value!r}") from exc
    return parsed


def _as_bool(value: object, where: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ConfigurationError(f"{where} must be true or false, got {value!r}")
