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

__all__ = ["StreamSummary", "StreamingRestorer"]

#: The longest run that could still become a placeholder: a 63-character type
#: name, a separator, six digits, brackets and a little whitespace. Nothing
#: further back in the buffer can be changed by more input, so the scan for a
#: partial match never has to look past this.
_MAX_HOLD = 96

#: A type name being spelled out, with its separator and index part-way in.
_PARTIAL_BODY = r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]*)*[\s\-_]*\d*\s*"

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
        hold_at = self._hold_boundary(self._buffer)
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

    def _restore(self, text: str) -> str:
        if not text:
            return ""

        pieces: list[str] = []
        cursor = 0
        for occurrence in scan_placeholders(text, self._known):
            if not occurrence.known:
                self._unknown.append(occurrence.surface)
                continue
            pieces.append(text[cursor : occurrence.span.start])
            pieces.append(self._by_placeholder[occurrence.placeholder].original_value)
            cursor = occurrence.span.end
            self._restored.append(occurrence.placeholder)
            if occurrence.tampered:
                self._tampered.append(occurrence.placeholder)
        pieces.append(text[cursor:])
        return "".join(pieces)
