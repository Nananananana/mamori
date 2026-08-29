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

    def __init__(self, violations: tuple[tuple[str, int, int], ...]) -> None:
        summary = ", ".join(f"{name}@{start}:{end}" for name, start, end in violations)
        super().__init__(f"blocked by policy: {summary}")
        self.violations = violations


class AnonymizationError(MamoriError):
    """The protected text could not be produced."""


class RestorationError(MamoriError):
    """The original text could not be restored from a response."""


class StorageError(MamoriError):
    """A mapping store operation failed."""
