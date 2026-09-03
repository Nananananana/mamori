"""Put the original values back once the external service has replied."""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.mapping import Mapping
from ..domain.occurrences import find_occurrences
from ..domain.placeholder import Placeholder
from ..domain.placeholder_matching import PlaceholderOccurrence, scan_placeholders
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

        # Both kinds of substitution are decided against the **same** text and
        # spliced once. Doing them in two passes -- placeholders, then
        # surrogates over the rewritten result -- meant a value just put back
        # was eligible to be matched as the next mapping's surrogate, and it
        # happened: a surrogate allocated for one document is a real name, and
        # if that name is another document's real value in the same scope,
        # restoring the first rewrote the second. Two people, one name, and the
        # reply named the wrong one.
        # (start, end, replacement, the occurrence when a placeholder claimed
        # it). A surrogate has no occurrence: it was found by searching for a
        # string, not by recognising a token, and the two are reported apart.
        claims: list[tuple[int, int, str, PlaceholderOccurrence | None, Placeholder]] = []
        for occurrence in occurrences:
            if not occurrence.known:
                continue
            mapping = by_placeholder[occurrence.placeholder]
            claims.append(
                (
                    occurrence.span.start,
                    occurrence.span.end,
                    mapping.original_value,
                    occurrence,
                    occurrence.placeholder,
                )
            )

        # A placeholder wins every character it covers. It is an exact token
        # this library minted; a surrogate is a string search over words the
        # model wrote.
        taken = {index for start, end, *_ in claims for index in range(start, end)}
        for start, end, value, mapping in _surrogate_claims(
            text, [m for m in mappings if m.is_surrogate]
        ):
            if any(index in taken for index in range(start, end)):
                continue
            claims.append((start, end, value, None, mapping.placeholder))
            taken |= set(range(start, end))

        claims.sort(key=lambda claim: claim[0])

        pieces: list[str] = []
        cursor = 0
        restored: list[PlaceholderOccurrence] = []
        seen: set[Placeholder] = set()
        for start, end, value, claimed_by, placeholder in claims:
            pieces.append(text[cursor:start])
            pieces.append(value)
            cursor = end
            seen.add(placeholder)
            if claimed_by is not None:
                restored.append(claimed_by)
        pieces.append(text[cursor:])
        result = "".join(pieces)

        unknown = [occurrence.surface for occurrence in occurrences if not occurrence.known]
        missing = tuple(sorted(known - seen))

        return RestorationResult(
            text=result,
            restored=tuple(restored),
            unknown=tuple(unknown),
            missing=missing,
        )


def surrogate_claims(text: str, mappings: Sequence[Mapping]) -> list[tuple[int, int, str, Mapping]]:
    """Public alias so the streaming path decides surrogates the same way.

    The two paths are documented as indistinguishable. They were not: streaming
    had no surrogate handling at all, so a session with surrogates on returned
    the invented name whole -- presented to a reader as a real one, which the
    surrogate module calls the most dangerous thing in the library. Sharing the
    function is what makes the promise checkable rather than repeated.
    """
    return _surrogate_claims(text, mappings)


def _surrogate_claims(
    text: str, mappings: Sequence[Mapping]
) -> list[tuple[int, int, str, Mapping]]:
    """Where each surrogate sits in ``text``, longest surface first.

    Every span is found against the text as the model wrote it, so nothing
    this function proposes can be an artefact of a substitution it made
    earlier. Longest first so a surrogate containing another claims its
    occurrences whole rather than being cut in half by its own substring.
    """
    claims: list[tuple[int, int, str, Mapping]] = []
    taken: set[int] = set()
    for mapping in sorted(mappings, key=lambda m: -len(m.surface)):
        for span in find_occurrences(
            text, mapping.surface, min_length=1, fold_case=True, fold_wrapping=True
        ):
            if any(index in taken for index in range(span.start, span.end)):
                continue
            claims.append((span.start, span.end, mapping.original_value, mapping))
            taken |= set(range(span.start, span.end))
    return claims
