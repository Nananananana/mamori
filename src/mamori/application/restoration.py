"""Put the original values back once the external service has replied."""

from __future__ import annotations

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

        seen = {occurrence.placeholder for occurrence in restored}
        missing = tuple(sorted(known - seen))

        return RestorationResult(
            text="".join(pieces),
            restored=tuple(restored),
            unknown=tuple(unknown),
            missing=missing,
        )
