"""Language packs.

Register a pack with :func:`register_locale` to add a language without touching
the library.
"""

from __future__ import annotations

from collections.abc import Sequence

from ....errors import ConfigurationError
from .base import LocalePack
from .en import ENGLISH
from .ja import JAPANESE
from .zh import CHINESE

__all__ = [
    "CHINESE",
    "ENGLISH",
    "JAPANESE",
    "LocalePack",
    "available_locales",
    "get_locale",
    "register_locale",
    "resolve_locales",
]

_REGISTRY: dict[str, LocalePack] = {pack.code: pack for pack in (JAPANESE, ENGLISH, CHINESE)}


def register_locale(pack: LocalePack) -> LocalePack:
    """Register a language pack, replacing any pack with the same code."""
    _REGISTRY[pack.code] = pack
    return pack


def get_locale(code: str) -> LocalePack | None:
    """Return a registered pack by code, or ``None``."""
    return _REGISTRY.get(code)


def available_locales() -> tuple[LocalePack, ...]:
    """Every registered pack, ordered by code."""
    return tuple(_REGISTRY[code] for code in sorted(_REGISTRY))


def resolve_locales(codes: Sequence[str] | str | None) -> tuple[LocalePack, ...]:
    """Turn locale codes into packs.

    Args:
        codes: Codes to resolve, a single code, or ``None`` for every
            registered pack.

    Raises:
        ConfigurationError: a code has no registered pack. Silently ignoring an
            unknown code would leave a language unprotected while the caller
            believed they had asked for it.
    """
    if codes is None:
        return available_locales()
    wanted = [codes] if isinstance(codes, str) else list(codes)
    packs: list[LocalePack] = []
    for code in wanted:
        pack = _REGISTRY.get(code)
        if pack is None:
            known = ", ".join(sorted(_REGISTRY))
            raise ConfigurationError(f"unknown locale {code!r}; available: {known}")
        packs.append(pack)
    return tuple(packs)
