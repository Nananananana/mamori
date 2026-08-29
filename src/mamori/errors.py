"""Exception hierarchy for mamori.

Security note
-------------
No exception raised by this library carries a raw sensitive value in its
message. Error messages reference entity *types*, *placeholders* and *offsets*
only. This is enforced by tests in ``tests/test_security_leakage.py``.
"""

from __future__ import annotations

__all__ = [
    "AnonymizationError",
    "ConfigurationError",
    "DetectionError",
    "MamoriError",
    "PolicyViolationError",
    "ProviderError",
    "RestorationError",
    "StorageError",
]


class MamoriError(Exception):
    """Base class for every error raised by mamori."""


class ConfigurationError(MamoriError):
    """Invalid or inconsistent configuration."""


class DetectionError(MamoriError):
    """A detector failed. Fail-closed: nothing may be sent externally."""

    def __init__(self, detector: str, cause: BaseException | None = None) -> None:
        reason = type(cause).__name__ if cause else "unknown"
        super().__init__(f"detector {detector!r} failed: {reason}")
        self.detector = detector
        self.cause = cause


class PolicyViolationError(MamoriError):
    """The policy forbids sending this text to an external service.

    Carries only entity *types* and offsets, never the offending values.
    """

    def __init__(self, violations: tuple[tuple[str, int, int], ...], reason: str = "") -> None:
        """
        Args:
            violations: ``(type name, start, end)`` per offending span.
            reason: Why the policy stopped this, when it was not simply the
                action for the type -- an uncertain detection under a
                fail-closed policy, for instance. Types and offsets only, like
                everything else here.
        """
        summary = ", ".join(f"{name}@{start}:{end}" for name, start, end in violations)
        detail = f"{reason}: {summary}" if reason else f"blocked by policy: {summary}"
        super().__init__(detail)
        self.violations = violations
        self.reason = reason


class AnonymizationError(MamoriError):
    """The protected text could not be produced."""


class RestorationError(MamoriError):
    """The original text could not be restored from a response."""


class StorageError(MamoriError):
    """A mapping store operation failed."""


class ProviderError(MamoriError):
    """A model provider failed.

    Carries the provider name and a short reason. Never the prompt, the answer
    or the server's response body -- an error from a detector is one of the few
    places the unprotected text is in scope, so nothing from it is repeated.
    """

    def __init__(self, provider: str, reason: str, *, retryable: bool = False) -> None:
        super().__init__(f"provider {provider!r} failed: {reason}")
        self.provider = provider
        self.reason = reason
        #: Whether trying again could plausibly work. A busy server or a
        #: dropped connection, yes; a malformed request or a rejected key, no
        #: -- retrying those burns time and, on a rate limit, makes it worse.
        self.retryable = retryable
