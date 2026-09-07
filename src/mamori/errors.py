"""Exception hierarchy for mamori.

Security note
-------------
No exception raised by this library carries a raw sensitive value in its
message. Error messages reference entity *types*, *placeholders* and *offsets*
only. This is enforced by tests in ``tests/test_security_leakage.py``.
"""

from __future__ import annotations

__all__ = [
    "CATALOGUE",
    "CATALOGUE_CONTRACT",
    "OPEN_NAMESPACES",
    "ConfigurationError",
    "DetectionError",
    "MamoriError",
    "PolicyViolationError",
    "ProviderError",
    "StorageError",
]

#: The frozen name of the catalogue below. A consumer that does not recognise
#: one must refuse it rather than read the fields it happens to know -- the
#: same rule the protection records follow.
CATALOGUE_CONTRACT = "mamori.errors/1-draft"

#: Kinds this library builds at run time from somebody else's vocabulary,
#: given as prefixes because their tails cannot be enumerated.
#:
#: **Empty, and that is a fact rather than an omission.** Every failure below
#: is named by a class in this module. A detector's name, a recogniser's name
#: and a custom entity type all appear in error *messages*, and none of them
#: becomes part of a *kind* -- so there is no prefix to declare and a consumer
#: can treat the list below as closed.
OPEN_NAMESPACES: tuple[str, ...] = ()

#: Every named way this library fails, as data a caller can check itself
#: against.
#:
#: Written for an orchestrator that has to answer *"is this my fault or is
#: something broken"* and cannot answer it from an exit code. It holds the
#: fields that question needs and nothing else:
#:
#:   ``kind``        the identifier that begins the first line of stderr, and
#:                   the key an aggregator folds repeats on
#:   ``status``      the HTTP status the proxy answers with, or ``None`` where
#:                   this failure has no HTTP surface
#:   ``exit_code``   what ``mamori`` exits with, or ``None`` where this failure
#:                   only ever happens inside the proxy
#:   ``outcome``     ``refused`` | ``unavailable`` | ``failed`` | ``timed_out``
#:   ``retryable``   whether asking again, unchanged, could succeed
#:   ``detail``      one line of English
#:   ``detail_ja``   the same line in Japanese, written here so that the two
#:                   cannot disagree
#:
#: **Nothing here can become a value.** No paths, no message templates with
#: holes in them, no examples that a reader would fill from a log. The detail
#: lines describe the failure, not an instance of it.
#:
#: ``retryable`` is the field only this library can fill in, and it is a
#: statement about *this library*, not advice: it says whether the same
#: request could succeed if repeated, and a caller's own policy about
#: retrying is a separate decision. `DetectionFailed` is false because the
#: detector that could not run will not run on a second attempt either.
CATALOGUE: tuple[dict[str, object], ...] = (
    {
        "kind": "PolicyViolationError",
        "status": 422,
        "exit_code": 2,
        "outcome": "refused",
        "retryable": False,
        "detail": "The policy blocked at least one detected value. Nothing was forwarded.",
        "detail_ja": "検出した値をポリシーが止めた。何も転送していない。",
    },
    {
        "kind": "ProviderError",
        "status": 502,
        "exit_code": 1,
        "outcome": "unavailable",
        "retryable": True,
        "detail": "The model or the upstream service could not be reached, or refused.",
        "detail_ja": "モデルまたは上流のサービスに届かなかった、あるいは拒否された。",
    },
    {
        "kind": "DetectionError",
        "status": 500,
        "exit_code": 1,
        "outcome": "failed",
        "retryable": False,
        "detail": "A detector failed. Nothing was emitted, so nothing partially protected left.",
        "detail_ja": "検出器が失敗した。何も出力していないので、中途半端な保護は出ていない。",
    },
    {
        "kind": "ConfigurationError",
        "status": None,
        "exit_code": 1,
        "outcome": "failed",
        "retryable": False,
        "detail": "A setting could not be read, or names something that does not exist.",
        "detail_ja": "設定を読めなかった、または存在しないものを指している。",
    },
    {
        "kind": "StorageError",
        "status": 500,
        "exit_code": 1,
        "outcome": "failed",
        "retryable": False,
        "detail": "A mapping file or an audit sink could not be read or written.",
        "detail_ja": "対応表または監査の書き出し先を読み書きできなかった。",
    },
    {
        "kind": "MamoriError",
        "status": 500,
        "exit_code": 1,
        "outcome": "failed",
        "retryable": False,
        "detail": "A failure with no more specific name. The base of every kind above.",
        "detail_ja": "より具体的な名前を持たない失敗。上のすべての基底。",
    },
    {
        "kind": "InvalidArgument",
        "status": 400,
        "exit_code": 1,
        "outcome": "failed",
        "retryable": False,
        "detail": "The request or the command line was not something this could read.",
        "detail_ja": "リクエストまたはコマンドラインを読めなかった。",
    },
    {
        "kind": "NotProxied",
        "status": 404,
        "exit_code": None,
        "outcome": "failed",
        "retryable": False,
        "detail": "A path the proxy does not carry. Only the chat completions path is proxied.",
        "detail_ja": "プロキシが扱わないパス。中継するのは chat completions のパスだけ。",
    },
)


class MamoriError(Exception):
    """Base class for every error raised by mamori.

    Every class below is raised somewhere in this package. Two that were not --
    ``AnonymizationError`` and ``RestorationError`` -- were removed in 0.28
    rather than left as names to catch.

    They had never been raised in any release, and the reason is that neither
    failure exists. Protection fails as a detector failing, a policy blocking,
    or a configuration error, each of which has its own class. Restoration does
    not fail at all: a placeholder in an answer that was never allocated, or an
    allocated one the answer did not use, are **reported** on
    :class:`~mamori.RestorationResult` as ``unknown`` and ``missing``, because a
    caller needs the restored text and the account of what was incomplete, not
    an exception instead of both.

    An exported exception that nothing raises is worse than a missing one. It
    reads as a documented failure mode, and a caller who writes ``except
    AnonymizationError`` has written dead code and believes they have handled
    something.
    """


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
