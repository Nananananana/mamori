"""The main entry point: a privacy session."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from types import TracebackType

from ..domain.policy import PrivacyPolicy
from ..ports.detector import Detector
from ..ports.mapping_store import MappingStore
from .protection import ProtectionService
from .restoration import RestorationService
from .results import ProtectionResult, RestorationResult

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
        """
        from ..infrastructure.detectors import default_detectors
        from ..infrastructure.storage import InMemoryMappingStore

        self._store: MappingStore = store if store is not None else InMemoryMappingStore()
        self._policy = policy if policy is not None else PrivacyPolicy.default()
        self._detectors = tuple(detectors) if detectors is not None else default_detectors(locales)
        self._scope = scope or f"session-{uuid.uuid4().hex[:12]}"
        self._protection = ProtectionService(self._detectors, self._policy, self._store)
        self._restoration = RestorationService(self._store)

    @property
    def scope(self) -> str:
        """Identifier the placeholders of this session are allocated under."""
        return self._scope

    @property
    def policy(self) -> PrivacyPolicy:
        return self._policy

    def protect(self, text: str) -> ProtectionResult:
        """Detect sensitive values in ``text`` and replace them.

        Raises:
            DetectionError: a detector failed; nothing is emitted.
            PolicyViolationError: the policy blocked at least one entity.
        """
        return self._protection.protect(text, self._scope)

    def restore(self, text: str) -> RestorationResult:
        """Replace this session's placeholders in ``text`` with real values."""
        return self._restoration.restore(text, self._scope)

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
