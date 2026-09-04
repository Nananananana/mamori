"""Sessions that outlive one request.

A :class:`~mamori.application.session.PrivacySession` already keeps its
placeholders across every ``protect`` call it is given, so a multi-turn
conversation held in one process has always been coherent. What did not survive
was the *request*: the proxy built a session, used it, and purged it, which
made "the proxy remembers nothing" true and left one case broken.

The broken case is not exotic. A client that resends the whole conversation
each turn is fine -- the same values meet the same allocator in the same order
and land on the same placeholders. A client that sends only the new turn,
because the service keeps the history for it, is not: the reply comes back
talking about ``<PERSON_001>`` and nothing in the process knows who that was.
That client gets a placeholder printed at a human, which is the one failure
this library is supposed to prevent.

This registry is the smallest thing that fixes it:

* **The server names the conversation, not the caller.** An identifier arrives
  from outside the process, and an identifier that outsiders can guess is a
  way to read somebody else's mappings. Tokens are minted here from
  :mod:`secrets`, and an unrecognised one silently starts a new conversation
  rather than reporting that it was unrecognised.
* **It is bounded in both directions.** A conversation expires after an idle
  period and the registry holds a fixed number of them; the oldest goes when
  it is full. Both bounds purge the mappings they drop, so the worst case is
  a client that has to start again, never one that keeps something forever.
* **Off unless asked for.** The default is still one scope per request. What
  is being traded is a real property -- a proxy that holds nothing at all --
  and a trade that happens without being chosen is not a trade.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from .session import PrivacySession

__all__ = [
    "DEFAULT_IDLE_SECONDS",
    "DEFAULT_MAX_CONVERSATIONS",
    "Conversation",
    "ConversationRegistry",
]

#: How long a conversation may sit untouched before it is discarded. Thirty
#: minutes is longer than a person leaves a chat window and much shorter than
#: a working day, which is the range that matters: this holds real values in
#: memory, so the question is not "when is it inconvenient to expire" but "how
#: long is it defensible to keep".
DEFAULT_IDLE_SECONDS = 30 * 60

#: How many conversations may be held at once. A bound is not optional. Without
#: one, a caller who never reuses a token can make this process hold every
#: value it has ever seen.
DEFAULT_MAX_CONVERSATIONS = 64

#: How many mappings one conversation may hold before it is started again.
#:
#: The ceiling above counts *conversations*, and this module claimed to be
#: "bounded in both directions" while each one held a store with no cap and a
#: retention of forever. Measured: 400 requests on one token, two fresh
#: addresses each, **800 mappings in one scope**, registry length 1 of a
#: capacity of 64. Sixty-four tokens kept warm held every value ever sent, for
#: as long as the process ran.
#:
#: Generous on purpose: a long working session over one document is nowhere
#: near it, and the number exists to bound a client that never stops rather
#: than to shape ordinary use.
DEFAULT_MAX_MAPPINGS = 5000

#: Bytes of entropy in a conversation token. 16 is 128 bits, which is not
#: guessable; the token is the only thing standing between one caller and
#: another caller's mappings.
_TOKEN_BYTES = 16


@dataclass(slots=True)
class Conversation:
    """One named session, and when it was last spoken to."""

    token: str
    session: PrivacySession
    last_used: float
    turns: int = 0
    #: How many requests are currently inside this conversation.
    #:
    #: Guarded by the registry's lock and read by nothing else. Eviction and
    #: expiry both call `session.close()`, which purges the scope -- and both
    #: could pick a conversation another thread was *between protect and
    #: restore on*. `_evict_oldest` chooses the least recently used, and an
    #: in-flight request set `last_used` when it started, so with more
    #: concurrent conversations than the ceiling it chose an active one.
    #: Measured: 12 concurrent callers against a ceiling of 8, and **4 of 12
    #: replies came back with a raw placeholder in them** -- printed at a
    #: human, for a name that caller sent in that same request.
    in_use: int = 0


class ConversationRegistry:
    """Named sessions with an idle timeout and a ceiling.

    Args:
        factory: Makes a new session. Injected rather than built here so this
            layer never has to know what a configuration is.
        idle_seconds: How long a conversation survives untouched.
        max_conversations: How many may be held at once.
        clock: Monotonic seconds. Injected so the expiry rules can be tested
            without sleeping through them.

    Example:
        >>> registry = ConversationRegistry(PrivacySession)
        >>> first = registry.resume(None)
        >>> registry.resume(first.token) is first
        True
        >>> registry.end(first.token)
        True
    """

    def __init__(
        self,
        factory: Callable[[], PrivacySession],
        *,
        idle_seconds: float = DEFAULT_IDLE_SECONDS,
        max_conversations: int = DEFAULT_MAX_CONVERSATIONS,
        max_mappings: int = DEFAULT_MAX_MAPPINGS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if idle_seconds <= 0:
            raise ValueError("idle_seconds must be positive")
        if max_conversations < 1:
            raise ValueError("max_conversations must be at least 1")
        if max_mappings < 1:
            raise ValueError("max_mappings must be at least 1")
        self._factory = factory
        self._idle = idle_seconds
        self._max = max_conversations
        self._max_mappings = max_mappings
        self._clock = clock
        self._lock = threading.RLock()
        self._live: dict[str, Conversation] = {}

    # -- the two calls a caller makes ---------------------------------------

    def resume(self, token: str | None) -> Conversation:
        """Return the conversation ``token`` names, or start a new one.

        An unknown token is not an error and does not say it is unknown. A
        registry that answered "no such conversation" would confirm which
        tokens exist to anybody who asked, and the caller can do nothing with
        the answer anyway: what it wanted was a conversation, and it gets one.
        """
        with self._lock:
            self.sweep()
            existing = self._live.get(token) if token else None
            if existing is not None and not self._outgrown(existing):
                existing.last_used = self._clock()
                existing.turns += 1
                return existing
            if existing is not None:
                self._live.pop(existing.token).session.close()
            return self._open()

    def hold(self, token: str) -> None:
        """Say a request is inside a conversation, so nothing may purge it.

        Deliberately **not** folded into :meth:`resume`. A `resume` that held
        would need a `release` from every caller, and a caller who forgot would
        leave a conversation nothing can ever evict -- trading a purged scope
        for one that lives forever, which is the worse of the two in a library
        whose whole point is not keeping values. :meth:`checkout` is the
        pairing that cannot be forgotten, and it is what the proxy uses.
        """
        with self._lock:
            conversation = self._live.get(token)
            if conversation is not None:
                conversation.in_use += 1

    def release(self, token: str) -> None:
        """Say a request has finished with a conversation.

        Every :meth:`resume` needs one, or the conversation becomes
        un-evictable and the ceiling stops meaning anything. :meth:`checkout`
        is the pairing that cannot be forgotten.
        """
        with self._lock:
            conversation = self._live.get(token)
            if conversation is not None and conversation.in_use > 0:
                conversation.in_use -= 1

    @contextmanager
    def checkout(self, token: str | None) -> Iterator[Conversation]:
        """Resume a conversation and release it when the block ends.

        What a request handler should use. While the block runs, neither expiry
        nor eviction can purge this conversation's scope out from under it --
        which they could, and did.
        """
        conversation = self.resume(token)
        self.hold(conversation.token)
        try:
            yield conversation
        finally:
            self.release(conversation.token)

    def end(self, token: str) -> bool:
        """Discard a conversation and its mappings. True if it existed."""
        with self._lock:
            conversation = self._live.pop(token, None)
            if conversation is None:
                return False
            conversation.session.close()
            return True

    # -- the bounds ---------------------------------------------------------

    def sweep(self) -> int:
        """Discard everything idle for longer than the timeout. Returns how many.

        Called on every resume, so expiry needs no background thread. A
        timer that purges secrets is a timer whose failure is silent; doing it
        on the path that touches the registry means the work happens exactly
        when there is something to do it for.
        """
        with self._lock:
            cutoff = self._clock() - self._idle
            # `in_use` is the whole point: a request taking longer than the
            # idle timeout would otherwise have its own scope swept away by the
            # next request to arrive, and answer with a raw placeholder.
            stale = [t for t, c in self._live.items() if c.last_used <= cutoff and c.in_use == 0]
            for token in stale:
                self._live.pop(token).session.close()
            return len(stale)

    def close_all(self) -> int:
        """Discard every conversation. Returns how many there were."""
        with self._lock:
            count = len(self._live)
            for conversation in self._live.values():
                conversation.session.close()
            self._live.clear()
            return count

    # -- what it is holding -------------------------------------------------

    def __len__(self) -> int:
        with self._lock:
            return len(self._live)

    def __iter__(self) -> Iterator[Conversation]:
        with self._lock:
            return iter(tuple(self._live.values()))

    @property
    def capacity(self) -> int:
        return self._max

    @property
    def idle_seconds(self) -> float:
        return self._idle

    def describe(self) -> str:
        """One line for an operator. Counts and durations, never a value."""
        minutes = self._idle / 60
        return (
            f"{len(self)} of {self._max} conversation(s) held, "
            f"discarded after {minutes:.0f} minute(s) idle"
        )

    # -- internals ----------------------------------------------------------

    def _open(self) -> Conversation:
        """Mint a token and a session. Caller holds the lock."""
        while len(self._live) >= self._max and self._evict_oldest():
            pass
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        conversation = Conversation(token=token, session=self._factory(), last_used=self._clock())
        self._live[token] = conversation
        return conversation

    def _outgrown(self, conversation: Conversation) -> bool:
        """Whether a conversation holds more mappings than it is allowed to.

        The ceiling above counts *conversations*, and this module claimed to be
        *"bounded in both directions"* while each one held an
        `InMemoryMappingStore` with no cap and a retention of forever.
        Measured: 400 requests on one token, two fresh addresses each, **800
        mappings in one scope**, registry length 1 of a capacity of 64. Sixty
        four tokens kept warm held every value ever sent, for as long as the
        process ran.

        Checked at `resume`, before a request begins, and never mid-request --
        so nothing a live call depends on is taken away. Exceeding it ends the
        conversation and starts a fresh one, which is exactly what eviction
        already does and what a client already handles: it comes back to a new
        conversation and re-protects its history.

        Expiring individual mappings instead would be worse. A conversation
        exists so that turn fifty can be restored with a value from turn one;
        dropping the oldest would break that silently, at a moment nobody
        chose.
        """
        if conversation.in_use:
            # A request is inside it. Ending it here is the defect this module
            # fixed one commit ago, arrived at from the other side.
            return False
        return len(conversation.session.mappings()) > self._max_mappings

    def _evict_oldest(self) -> bool:
        """Drop the least recently used idle conversation. Caller holds the lock.

        Returns whether one was dropped. Eviction purges, like expiry does. A
        caller whose conversation was evicted comes back to a new one and
        re-protects its history, which is the behaviour it had before this
        module existed -- **but only when it is not that caller's own live
        request being purged**, which is what `in_use` prevents.

        When every conversation is in flight there is nothing to evict, and the
        ceiling is exceeded rather than an active scope destroyed or a client
        refused. The excess is bounded by the number of concurrent requests,
        which the server bounds already; the ceiling bounds what is *kept*, and
        a request in progress is not being kept.
        """
        idle = [c for c in self._live.values() if c.in_use == 0]
        if not idle:
            return False
        oldest = min(idle, key=lambda c: c.last_used)
        self._live.pop(oldest.token).session.close()
        return True
