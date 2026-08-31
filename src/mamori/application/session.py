"""The main entry point: a privacy session."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from types import TracebackType

from ..domain.corrections import CorrectionLog
from ..domain.placeholder import PlaceholderStyle
from ..domain.policy import PrivacyPolicy
from ..ports.detector import Detector
from ..ports.mapping_store import MappingStore
from ..prompts.library import EXTERNAL_PROMPT_ID, PromptLibrary, default_library
from .protection import ProtectionService
from .restoration import RestorationService
from .results import ProtectionResult, RestorationResult
from .streaming import StreamingRestorer

__all__ = ["PrivacySession"]


class PrivacySession:
    """A conversation-scoped protect/restore pair.

    One session is one scope: the same value keeps the same placeholder across
    every ``protect`` call, so a multi-turn conversation stays coherent and a
    response in turn five can still be restored with a value from turn one.

    Mappings live in memory and are discarded by :meth:`close`. That is
    deliberate. A persisted mapping table is a file containing exactly the
    values you were trying to keep off other people's machines; creating one by
    default would trade a transmission risk for a storage risk without asking.

    Example:
        >>> with PrivacySession() as session:
        ...     protected = session.protect("Mail tanaka@example.com about it.")
        ...     protected.protected_text
        'Mail <EMAIL_001> about it.'
    """

    def __init__(
        self,
        *,
        detectors: Sequence[Detector] | None = None,
        policy: PrivacyPolicy | None = None,
        store: MappingStore | None = None,
        scope: str | None = None,
        locales: Sequence[str] | str | None = None,
        prompts: PromptLibrary | None = None,
        corrections: CorrectionLog | None = None,
        surrogate_types: Iterable[str] = (),
        placeholder_style: PlaceholderStyle = PlaceholderStyle.ANGLE,
        trace: bool = False,
    ) -> None:
        """
        Args:
            detectors: Replaces the default detector set entirely.
            policy: Defaults to :meth:`PrivacyPolicy.default`.
            store: Defaults to an in-memory store.
            scope: Defaults to a generated identifier.
            locales: Language pack codes to enable, e.g. ``["ja", "en"]``.
                ``None`` enables all of them, which is the safer default: an
                unexpected language in a document is exactly the case nobody
                redacted by hand. Ignored when ``detectors`` is given.
            prompts: Where :meth:`external_system_prompt` comes from.
            corrections: Values the operator has ruled on. The only input
                that can reduce what is detected, and the one place a
                credential cannot be ruled away.
            trace: Record every candidate the pipeline considered and what
                became of it, on ``ProtectionResult.trace``. Off by default.
            placeholder_style: Which brackets go into the protected text.
                ``<PERSON_001>`` by default. ``SQUARE`` for HTML and XML, where
                the default form is an unknown element rather than a word: a
                browser drops it and a model asked to edit the document is
                being shown a tag. Restoration accepts every form whatever this
                is set to, because a placeholder's identity is its
                ``(type, index)`` pair and the brackets are surface.
            surrogate_types: Types replaced by a plausible value rather than a
                token. Any iterable of names -- it was annotated
                ``frozenset[str]`` while the body accepted anything, so every
                caller reading the signature built a frozenset it did not need,
                and every one that passed a list was correct and looked
                wrong. Empty by default. Read
                :mod:`mamori.domain.surrogate` before turning it on: an
                unrestored placeholder is obvious and an unrestored surrogate
                is a sentence about the wrong person.

        To build one from a :class:`~mamori.config.MamoriConfig`, call
        :meth:`~mamori.config.MamoriConfig.session`. Settings assemble a
        session; a session does not read settings. That direction is what
        keeps this layer from depending on the adapters a configuration names.
        """
        from ..infrastructure.detectors import default_detectors
        from ..infrastructure.storage import InMemoryMappingStore

        self._store: MappingStore = store if store is not None else InMemoryMappingStore()
        self._policy = policy if policy is not None else PrivacyPolicy.default()
        self._detectors: tuple[Detector, ...] = (
            tuple(detectors) if detectors is not None else default_detectors(locales)
        )
        self._prompts = prompts if prompts is not None else default_library()
        self._scope = scope or f"session-{uuid.uuid4().hex[:12]}"
        self._corrections = corrections if corrections is not None else CorrectionLog()
        self._protection = ProtectionService(
            self._detectors,
            self._policy,
            self._store,
            self._corrections,
            surrogate_types=frozenset(surrogate_types),
            placeholder_style=placeholder_style,
            trace=trace,
        )
        self._restoration = RestorationService(self._store)

    @property
    def scope(self) -> str:
        """Identifier the placeholders of this session are allocated under."""
        return self._scope

    @property
    def policy(self) -> PrivacyPolicy:
        return self._policy

    @property
    def surrogate_types(self) -> frozenset[str]:
        """Types a plausible value stands in for, rather than a token."""
        return self._protection.surrogate_types

    @property
    def placeholder_style(self) -> PlaceholderStyle:
        """Which brackets go into the protected text."""
        return self._protection.placeholder_style

    def protect(self, text: str) -> ProtectionResult:
        """Detect sensitive values in ``text`` and replace them.

        Raises:
            DetectionError: a detector failed; nothing is emitted.
            PolicyViolationError: the policy blocked at least one entity.
        """
        return self._protection.protect(text, self._scope)

    def restore(self, text: str) -> RestorationResult:
        """Replace this session's placeholders in ``text`` with real values.

        A placeholder stands for a **value**, not for a site. When one value is
        written two ways that NFKC folds together -- ``Y0@a.example.com`` and
        ``Ｙ0@a.example.com``, or ``株式会社ABC`` and ``㍿ABC`` -- both sites get
        the same token, and both come back spelled the way the first one was.

        That is the intended half working: they are the same address and the
        same company, and one token for both is what lets a model treat them as
        one thing. The consequence is that restoration returns the value's
        spelling and not each site's, and there is no fixing it from here --
        what comes back from a model is an answer, not the document, so there
        is no site to match a token to.
        """
        return self._restoration.restore(text, self._scope)

    def external_system_prompt(self) -> str:
        """What to tell the service model about the placeholders.

        Prepend this to your own system prompt. It costs a few hundred tokens
        and it is the cheapest recall the library offers: every placeholder
        that comes back intact is one restoration does not have to recover from
        a mangled form, and a placeholder nobody recovers is an answer with a
        hole in it.

            >>> with PrivacySession() as session:
            ...     "placeholders" in session.external_system_prompt()
            True
        """
        return self._prompts.render(EXTERNAL_PROMPT_ID).text

    def stream_restore(self) -> StreamingRestorer:
        """Start restoring a response that arrives in pieces.

        Feeding a streamed answer through this produces exactly the text
        :meth:`restore` would produce for the whole response, so nothing is lost
        by not waiting for the last token.
        """
        return StreamingRestorer(self._store, self._scope)

    def close(self) -> None:
        """Discard every mapping held for this session."""
        self._store.purge(self._scope)

    def __enter__(self) -> PrivacySession:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
