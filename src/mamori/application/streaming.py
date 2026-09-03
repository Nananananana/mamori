"""Restoring a response that arrives in pieces.

An LLM answer streams token by token, and a placeholder does not respect token
boundaries: ``<PERSON_001>`` shows up as ``<PER`` then ``SON_0`` then ``01>``.
Restoring each chunk on its own would emit the fragments unchanged and lose the
value; buffering the whole answer first works but throws away the reason for
streaming.

So this holds back the shortest suffix that could still turn into a placeholder
and emits everything before it. The held part is usually a few characters, so
the reader sees the answer as it is written.

The guarantee that matters: **feeding a response in chunks produces exactly the
text that restoring it whole would produce**, for any chunking. That is a
property test in ``tests/test_streaming.py``, not an aspiration -- a streaming
path that quietly differs from the batch path is a leak waiting for the right
token boundary.

    >>> from mamori import PrivacySession
    >>> with PrivacySession() as session:
    ...     _ = session.protect("田中太郎さんへ")
    ...     stream = session.stream_restore()
    ...     "".join([stream.feed("Dear <PERS"), stream.feed("ON_001>."), stream.finish()])
    'Dear 田中太郎.'
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ..domain.placeholder import Placeholder
from ..domain.placeholder_matching import scan_placeholders
from ..ports.mapping_store import MappingStore
from .restoration import surrogate_claims

__all__ = ["StreamSummary", "StreamingRestorer"]

#: The longest run that could still become a placeholder: a 63-character type
#: name, a separator, six digits, brackets and a little whitespace. Nothing
#: further back in the buffer can be changed by more input, so the scan for a
#: partial match never has to look past this.
_MAX_HOLD = 96

#: A type name being spelled out, with its separator and index part-way in.
#:
#: This has to admit everything the batch scanner admits, or a placeholder is
#: restored when the whole reply arrives at once and not when it arrives in
#: pieces -- and the two paths are supposed to be indistinguishable. 0.14
#: widened the batch scanner to accept ``<COMPANY _ NAME _ 001>``, which is
#: what a model produces often enough to have been 195 of 1002 failures, and
#: **this was not widened with it**. The corpus that chunks at arbitrary
#: boundaries is what showed it; no hand-written test would have, because a
#: hand-written test cuts between words.
_PARTIAL_BODY = (
    r"[A-Za-z][A-Za-z0-9]*"
    r"(?:[^\S\r\n]*[_\-][^\S\r\n]*[A-Za-z0-9]*)*"
    r"[^\S\r\n]*\d*[^\S\r\n]*"
)

#: Matches a run that reaches the end of the buffer and could still grow into a
#: placeholder. Two shapes: an opening bracket with anything or nothing after it
#: yet, or a bare body with no bracket at all.
#:
#: The bracket must count on its own. A buffer ending in a lone ``<`` looks
#: harmless, and releasing it produces ``<`` followed by a restored value on the
#: next chunk -- ``<田中太郎>`` instead of ``田中太郎``. Deliberately loose
#: otherwise: holding an ordinary trailing word for one chunk costs nothing,
#: releasing half a placeholder costs a restoration.
_PARTIAL_RE = re.compile(r"(?:[<\[{]\s*(?:" + _PARTIAL_BODY + r")?|" + _PARTIAL_BODY + r")$")


def _flat(text: str) -> str:
    """Case and line breaks removed, for comparing a partial surrogate."""
    return text.replace(chr(13), "").replace(chr(10), "").casefold()


@dataclass(frozen=True, slots=True)
class StreamSummary:
    """What happened over the whole stream."""

    restored: tuple[Placeholder, ...] = ()
    tampered: tuple[Placeholder, ...] = ()
    unknown: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_clean(self) -> bool:
        """True when every placeholder-shaped run in the stream was recognised."""
        return not self.unknown


class StreamingRestorer:
    """Feed a response in chunks; get restored text back as it becomes safe.

    Not thread-safe: one restorer belongs to one stream.
    """

    def __init__(self, store: MappingStore, scope: str) -> None:
        mappings = store.list_scope(scope)
        self._by_placeholder = {mapping.placeholder: mapping for mapping in mappings}
        self._known = set(self._by_placeholder)
        #: Surrogates in this scope. A surrogate has no shape -- it is a name --
        #: so a stream has to hold back enough text for one to complete, and
        #: this path did not hold back any: a session with surrogates on
        #: streamed the invented name straight through, presented to a reader
        #: as the real one. Batch and streaming are documented as producing the
        #: same text and did not.
        self._surrogates = [mapping for mapping in mappings if mapping.is_surrogate]
        #: How far back a partial surrogate could reach. Twice the longest
        #: surface, because `find_occurrences` folds a line break between any
        #: two characters, so one can occupy up to twice its own length.
        longest = max((len(mapping.surface) for mapping in self._surrogates), default=0)
        self._surrogate_window = 2 * longest
        self._flat_surrogates = tuple(_flat(mapping.surface) for mapping in self._surrogates)
        self._buffer = ""
        self._restored: list[Placeholder] = []
        self._tampered: list[Placeholder] = []
        self._unknown: list[str] = []
        self._finished = False

    def feed(self, chunk: str) -> str:
        """Take the next chunk and return the text that is now safe to emit.

        Raises:
            RuntimeError: called after :meth:`finish`.
        """
        if self._finished:
            raise RuntimeError("cannot feed a finished stream")
        self._buffer += chunk
        hold_at = min(self._hold_boundary(self._buffer), self._surrogate_boundary(self._buffer))
        hold_at = self._not_inside_a_surrogate(self._buffer, hold_at)
        ready, self._buffer = self._buffer[:hold_at], self._buffer[hold_at:]
        return self._restore(ready)

    def finish(self) -> str:
        """Flush whatever is still held. Further calls to :meth:`feed` fail."""
        remainder, self._buffer = self._buffer, ""
        self._finished = True
        return self._restore(remainder)

    def summary(self) -> StreamSummary:
        """What was restored, altered and left unrecognised across the stream."""
        return StreamSummary(
            restored=tuple(self._restored),
            tampered=tuple(self._tampered),
            unknown=tuple(self._unknown),
        )

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _hold_boundary(buffer: str) -> int:
        """Index from which the buffer must be held back.

        Everything before it is settled: no further input can change how it is
        restored.
        """
        window_start = max(0, len(buffer) - _MAX_HOLD)
        for index in range(window_start, len(buffer)):
            candidate = unicodedata.normalize("NFKC", buffer[index:])
            if _PARTIAL_RE.fullmatch(candidate):
                return index
        return len(buffer)

    def _not_inside_a_surrogate(self, buffer: str, hold_at: int) -> int:
        """Pull a release point back out of a surrogate it would split.

        The two boundaries above answer different questions and the smaller is
        not always the safe one. `Alex Rivera ` gives a placeholder boundary of
        5 -- `Rivera ` could still grow into a token -- and a surrogate
        boundary of 12, because nothing at the tail is a partial name. Taking
        the smaller released `Alex ` and held `Rivera `, cutting a complete
        surrogate in half at a point neither check was looking at.
        """
        if not self._surrogates:
            return hold_at
        for start, end, _, _ in surrogate_claims(buffer, self._surrogates):
            if start < hold_at < end:
                hold_at = start
        return hold_at

    def _surrogate_boundary(self, buffer: str) -> int:
        """Index from which the buffer could still be growing into a surrogate.

        The placeholder boundary is not enough. Holding the last N characters
        for a surrogate to arrive still releases one character per chunk once
        the buffer is longer than N, so a surrogate straddling a release point
        is split across two calls and matched by neither -- measured: fed one
        character at a time, every surrogate came out un-restored while the
        whole string at once came out right.

        A surrogate has no shape, but it is a *known string*, so the boundary
        is exact rather than a guess: hold from the earliest position whose
        tail is a prefix of one. Line breaks and case are folded out of both
        sides, because `find_occurrences` matches through them.
        """
        if not self._flat_surrogates:
            return len(buffer)
        for index in range(max(0, len(buffer) - self._surrogate_window), len(buffer)):
            tail = _flat(buffer[index:])
            if tail and any(surface.startswith(tail) for surface in self._flat_surrogates):
                return index
        return len(buffer)

    def _restore(self, text: str) -> str:
        """Placeholders and surrogates, decided against the same text.

        The same single pass `RestorationService.restore` makes, for the same
        reason: substituting one kind and then searching the rewritten text for
        the other lets a value just put back be matched as somebody else's
        surrogate.
        """
        if not text:
            return ""

        claims: list[tuple[int, int, str, Placeholder | None, bool]] = []
        for occurrence in scan_placeholders(text, self._known):
            if not occurrence.known:
                self._unknown.append(occurrence.surface)
                continue
            claims.append(
                (
                    occurrence.span.start,
                    occurrence.span.end,
                    self._by_placeholder[occurrence.placeholder].original_value,
                    occurrence.placeholder,
                    occurrence.tampered,
                )
            )

        taken = {index for start, end, _, _, _ in claims for index in range(start, end)}
        for start, end, value, mapping in surrogate_claims(text, self._surrogates):
            if any(index in taken for index in range(start, end)):
                continue
            claims.append((start, end, value, mapping.placeholder, False))
            taken |= set(range(start, end))

        claims.sort(key=lambda claim: claim[0])
        pieces: list[str] = []
        cursor = 0
        for start, end, value, placeholder, tampered in claims:
            pieces.append(text[cursor:start])
            pieces.append(value)
            cursor = end
            if placeholder is not None:
                self._restored.append(placeholder)
            if tampered and placeholder is not None:
                self._tampered.append(placeholder)
        pieces.append(text[cursor:])
        return "".join(pieces)
