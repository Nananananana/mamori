"""Put the original values back once the external service has replied."""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.mapping import Mapping
from ..domain.occurrences import find_occurrences
from ..domain.placeholder import Placeholder
from ..domain.placeholder_matching import scan_placeholders
from ..ports.mapping_store import MappingStore
from .results import RestorationResult

__all__ = ["RestorationService"]


class RestorationService:
    """Replace placeholders in a response with the values they stand for.

    Only placeholders allocated in the given scope are substituted. Anything
    else that merely looks like a placeholder is reported, never resolved: a
    response is untrusted input, and a lookup driven by text the responder
    chose is how a mapping table gets read out one guess at a time.
    """

    def __init__(self, store: MappingStore) -> None:
        self._store = store

    def restore(self, text: str, scope: str) -> RestorationResult:
        """Restore ``text`` using the mappings recorded in ``scope``."""
        mappings = self._store.list_scope(scope)
        by_placeholder = {mapping.placeholder: mapping for mapping in mappings}
        known = set(by_placeholder)

        if not text:
            return RestorationResult(text="", missing=tuple(sorted(known)))

        occurrences = scan_placeholders(text, known)

        pieces: list[str] = []
        cursor = 0
        restored = []
        unknown: list[str] = []

        for occurrence in occurrences:
            if not occurrence.known:
                unknown.append(occurrence.surface)
                continue
            mapping = by_placeholder[occurrence.placeholder]
            pieces.append(text[cursor : occurrence.span.start])
            pieces.append(mapping.original_value)
            cursor = occurrence.span.end
            restored.append(occurrence)

        pieces.append(text[cursor:])
        result = "".join(pieces)

        seen = {occurrence.placeholder for occurrence in restored}
        surrogates = [m for m in mappings if m.is_surrogate]
        if surrogates:
            result, put_back = _restore_surrogates(result, surrogates)
            seen |= put_back

        missing = tuple(sorted(known - seen))

        return RestorationResult(
            text=result,
            restored=tuple(restored),
            unknown=tuple(unknown),
            missing=missing,
        )


def _restore_surrogates(text: str, mappings: Sequence[Mapping]) -> tuple[str, set[Placeholder]]:
    """Put originals back where a surrogate was substituted.

    A placeholder can be recognised by its shape, so restoration tolerates a
    model that mangles one. A surrogate has no shape: it is a name, and the
    only way to find it is to look for the exact string. That is the trade
    somebody accepts when they turn surrogates on, and it is worth being blunt
    about -- a model that writes `山田さん` where it was given `山田一郎` has
    produced text this cannot restore, and there is no clever way around it.

    Longest first, so a surrogate that contains another is replaced whole
    rather than being cut in half by its own substring.
    """
    put_back: set[Placeholder] = set()
    for mapping in sorted(mappings, key=lambda m: -len(m.surface)):
        spans = find_occurrences(text, mapping.surface, min_length=1)
        if not spans:
            continue
        pieces: list[str] = []
        cursor = 0
        for span in spans:
            pieces.append(text[cursor : span.start])
            pieces.append(mapping.original_value)
            cursor = span.end
        pieces.append(text[cursor:])
        text = "".join(pieces)
        put_back.add(mapping.placeholder)
    return text, put_back
