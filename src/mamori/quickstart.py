"""The two-line version, for the first five minutes.

Every other library in this space has a one-liner. `scrubadub.clean(text)`,
`presidio` in two engines and four objects, `anonymize(text)` in half a dozen
smaller packages. All of them return a string with the values gone and no way
to get them back, because that is all a redactor can offer.

This one gives back the string **and the way home**:

    >>> import mamori
    >>> protected, restore = mamori.protect("Mail tanaka@example.com by Friday.")
    >>> protected
    'Mail <EMAIL_001> by Friday.'
    >>> restore("I have emailed <EMAIL_001>.")
    'I have emailed tanaka@example.com.'

That is the whole library's argument in four lines, and until now the shortest
way to write it was six -- a `with` block, a session, a `.protected_text` and a
`.text`. The block is not ceremony: mappings live for as long as the session
and :meth:`~mamori.PrivacySession.close` is what discards them. So this keeps
the session and hands it back, and the object it returns closes it:

    >>> with mamori.protect("Mail tanaka@example.com by Friday.") as p:
    ...     p.text
    'Mail <EMAIL_001> by Friday.'

Outside a `with`, the mappings live until the returned object is collected.
They are in memory, in this process, and never written anywhere -- the default
store is in-memory precisely because *a persisted mapping table is a file
containing exactly the values you were trying to keep off other people's
machines*. Nothing reaches disk if you never close it. What you lose is the
moment of discarding them, and for a script that ends, that is the moment the
process ends.

**What this does not do.** One call is one scope. A multi-turn conversation
still needs a session -- `.session` on the result is one, already holding this
call's mappings.

**And do not cross two calls.** Numbering restarts per scope, so two
independent calls both mint `<EMAIL_001>` for their first address. Feeding one
call's response to the other's `restore` therefore returns *the other value*,
with nothing reported: the token is perfectly well known, it just means
somebody else. Measured, and pinned in `tests/test_quickstart.py`. The same is
true of two sessions and of two conversations, and it is the reason
restoration takes a scope at all. There is no fix from inside a scope -- a
token that another scope also minted is indistinguishable -- so the rule is
simply that the text you restore must come from the call that protected it.

A blocked entity still raises: the default policy refuses to let a credential
past, and a convenience wrapper that swallowed that would be a wrapper that
sends your API key.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from types import TracebackType

from .application.results import EntityReport
from .application.session import PrivacySession
from .config import MamoriConfig

__all__ = ["Protected", "inspect", "protect"]


@dataclass(frozen=True, slots=True)
class Protected:
    """What :func:`protect` returns: the text, and the way back.

    Unpacks as a pair, so the common case is one line::

        protected, restore = mamori.protect(text)

    and is a context manager, so the careful case is two.
    """

    #: The text with every detected value replaced by a placeholder.
    text: str
    #: Turns a response containing this call's placeholders back into one
    #: containing the real values. A `str`, not a
    #: :class:`~mamori.RestorationResult`, because that is what a one-liner is
    #: for -- and nothing is hidden by the shorter shape: a placeholder this
    #: scope never allocated is left standing in the text where you can see
    #: it. :attr:`session` has the full result, with `unknown`, `missing` and
    #: `tampered`.
    restore: Callable[[str], str]
    #: What was found, by type and placeholder. Never the original values:
    #: :class:`~mamori.EntityReport` does not carry them.
    entities: tuple[EntityReport, ...]
    #: The session holding the mappings. Use it for a second `protect` in the
    #: same scope, for streaming restoration, or for the full restoration
    #: result.
    session: PrivacySession

    def __iter__(self) -> Iterator[object]:
        """`text, restore = protect(...)`, and nothing else.

        Two items rather than four on purpose. Unpacking is positional and
        silent, so every name it yields is a name that can never be reordered;
        `entities` and `session` are attributes, where adding a third costs
        nobody anything.
        """
        yield self.text
        yield self.restore

    def close(self) -> None:
        """Discard the mappings. The placeholders become unrestorable."""
        self.session.close()

    def __enter__(self) -> Protected:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def protect(text: str, *, config: MamoriConfig | None = None) -> Protected:
    """Protect one text and keep the way back.

    Args:
        text: What to protect.
        config: Settings. Defaults to :class:`~mamori.MamoriConfig`'s, which
            is the recall-first stance and a policy that blocks credentials.

    Returns:
        A :class:`Protected`, which unpacks as ``(text, restore)``.

    Raises:
        PolicyViolationError: the policy blocked something -- by default, a
            credential. The session is closed before this leaves, so a refused
            text holds nothing afterwards.
        DetectionError: a detector failed. Nothing was emitted.
    """
    session = (config or MamoriConfig()).session()
    try:
        result = session.protect(text)
    except BaseException:
        # Including `KeyboardInterrupt`: the caller has no handle on this
        # session yet, so if the call does not return, nothing else can ever
        # close it.
        session.close()
        raise
    return Protected(
        text=result.protected_text,
        restore=lambda response: session.restore(response).text,
        entities=tuple(result.entities),
        session=session,
    )


def inspect(text: str, *, config: MamoriConfig | None = None) -> tuple[str, ...]:
    """Which kinds of sensitive value ``text`` contains, allocating nothing.

    A question, not a step: no placeholder is minted and no mapping is kept,
    so there is nothing to close and nothing to restore. Use it to decide
    *about* a text -- whether to send it, whether to warn, whether to protect
    it at all::

        if mamori.inspect(text):
            protected, restore = mamori.protect(text)

    A credential is reported here rather than refused, because refusing is an
    answer to *"send this"* and this is not that question.
    """
    session = (config or MamoriConfig()).session()
    try:
        return session.inspect(text)
    finally:
        session.close()
