"""Speak Presidio's shapes, so trying this costs an import and not a rewrite.

Microsoft Presidio is what most teams already have. Its two objects are
`AnalyzerEngine.analyze(text, language=...) -> list[RecognizerResult]` and
`AnonymizerEngine.anonymize(text, analyzer_results) -> EngineResult`, and
everything downstream -- dashboards, notebooks, test fixtures, the code that
decides what to do with a finding -- is written against those.

So the barrier to trying mamori was never the library. It was that a finding
here is a `SensitiveEntity`, and every line that reads one had to be rewritten
before anything could be compared. This module removes that:

    -from presidio_analyzer import AnalyzerEngine
    +from mamori.interop.presidio import AnalyzerEngine

    results = AnalyzerEngine().analyze(text, language="en")
    for r in results:
        print(r.entity_type, r.start, r.end, r.score)

**Three directions, and they are different requests.**

`AnalyzerEngine` and `AnonymizerEngine` are mamori wearing Presidio's shape, so
existing code runs unchanged. :func:`to_presidio` converts a result somebody
already has. :class:`PresidioRecognizer` goes the other way -- Presidio's own
analyzer plugged in as a mamori recogniser, so its recogniser set and its
language models are available here without this library reimplementing them.

**What is deliberately not the same.** Presidio's `anonymize` replaces with
`<PERSON>` and forgets; mamori mints `<PERSON_001>` and can put the value back.
A facade that hid that would be a worse lie than no facade -- so
:meth:`AnonymizerEngine.anonymize` returns numbered placeholders and says so,
and the session that can restore them is reachable on the result.

Nothing here is imported by anything else in this package, and nothing here
decides anything: it is a translation layer over `PrivacySession`, the same
arrangement `report` and `provenance` have.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..application.session import PrivacySession
from ..config import MamoriConfig
from ..infrastructure.detectors.presidio_recognizer import PresidioRecognizer, as_recognized

if TYPE_CHECKING:  # pragma: no cover
    from ..application.results import ProtectionResult
    from ..ports.nlp_recognizer import RecognizedEntity

__all__ = [
    "AnalyzerEngine",
    "AnonymizerEngine",
    "AnonymizerResult",
    "PresidioRecognizer",
    "RecognizerResult",
    "from_presidio",
    "to_presidio",
]


@dataclass(frozen=True, slots=True)
class RecognizerResult:
    """One finding, with the four attributes Presidio's has.

    Field names and order match `presidio_analyzer.RecognizerResult` so that
    code reading `.entity_type`, `.start`, `.end` and `.score` works against
    either. It is a plain dataclass rather than a subclass because subclassing
    would require Presidio to be installed, and the point is that it need not
    be.

    Security note:
        No ``value`` field, for the same reason `RecognizedEntity` has none:
        a finding says *where*, and whoever holds the text reads it. A finding
        that carried the value would be a finding that leaks when logged.
    """

    entity_type: str
    start: int
    end: int
    score: float = 1.0
    #: What produced it. Presidio calls this `analysis_explanation`; this
    #: carries the detector or pass name, which is the part anybody reads.
    recognition_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """The JSON shape Presidio serialises to.

        For a pipeline that speaks Presidio over a wire rather than in
        process -- a dashboard, a stored fixture, another language.
        """
        return {
            "entity_type": self.entity_type,
            "start": self.start,
            "end": self.end,
            "score": self.score,
            "analysis_explanation": self.recognition_metadata or None,
        }


def to_presidio(result: ProtectionResult) -> list[RecognizerResult]:
    """A mamori result as a list of Presidio-shaped findings.

    Offsets are in the coordinates of the text that was protected, which is
    what Presidio's are too.
    """
    return [
        RecognizerResult(
            entity_type=entity.entity_type,
            start=entity.span.start,
            end=entity.span.end,
            score=entity.confidence,
            recognition_metadata={"recognizer_name": entity.source},
        )
        for entity in result.entities
    ]


def from_presidio(results: Iterable[Any]) -> list[RecognizedEntity]:
    """Presidio findings as things a mamori recogniser could have said.

    One implementation, in the adapter that also uses it -- two would drift,
    and the one that drifted would be the one nobody was running.
    """
    return as_recognized(results)


class AnalyzerEngine:
    """`analyze(text, language=...)`, answered by mamori.

    Args:
        config: The settings behind it. Everything mamori can be told to do --
            the stance, the recall dial, a local model, the secrets algorithm --
            is set here, and none of it changes the shape of what comes back.
        **_: Accepted and ignored. Presidio's constructor takes
            `nlp_engine`, `registry`, `supported_languages` and more; a facade
            that raised on them would fail on the line that is hardest to
            change, which is the constructor call somebody already has.
    """

    def __init__(self, config: MamoriConfig | None = None, **_: object) -> None:
        self._config = config or MamoriConfig()

    def analyze(
        self,
        text: str,
        language: str | None = None,
        entities: Sequence[str] | None = None,
        score_threshold: float = 0.0,
        **_: object,
    ) -> list[RecognizerResult]:
        """Findings in ``text``, in Presidio's shape.

        Args:
            text: What to look at.
            language: A locale code. Presidio requires it; mamori does not --
                omitting it enables every language pack, which is the safer
                default because an unexpected language is exactly the document
                nobody redacted by hand.
            entities: Keep only these types. Presidio's filter, applied here
                for the same reason.
            score_threshold: Drop findings below this confidence.

        Nothing is protected and nothing is allocated: this is the question,
        not the step. A credential is *reported* rather than refused, which is
        what a Presidio caller expects and what `mamori inspect` already does.
        """
        settings = self._config
        if language:
            settings = settings.replace(locales=(language,))

        from ..domain.policy import PrivacyPolicy

        # Permissive, so a credential comes back as a finding rather than
        # stopping the call. `analyze` answers a question about a text; the
        # decision to refuse belongs to `protect`.
        policy = PrivacyPolicy.permissive().with_min_confidence(settings.min_confidence)
        with settings.session(policy=policy) as session:
            protected = session.protect(text)

        wanted = {name.upper() for name in entities} if entities else None
        return [
            finding
            for finding in to_presidio(protected)
            if finding.score >= score_threshold
            and (wanted is None or finding.entity_type in wanted)
        ]


@dataclass(frozen=True, slots=True)
class AnonymizerResult:
    """What `anonymize` returns: `.text`, and the way back.

    `.text` and `.items` are Presidio's names. `.session` is not, and is the
    difference worth knowing about -- Presidio replaces a name with `<PERSON>`
    and the original is gone. mamori mints `<PERSON_001>` and keeps the mapping
    for the life of this object, so the reply from a model can be turned back
    into the caller's own words.
    """

    text: str
    items: tuple[RecognizerResult, ...]
    session: PrivacySession = field(repr=False)

    def restore(self, text: str) -> str:
        """Put the caller's values back into a model's reply."""
        return self.session.restore(text).text

    def close(self) -> None:
        """Discard the mapping. Nothing can be restored afterwards."""
        self.session.close()

    def __enter__(self) -> AnonymizerResult:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class AnonymizerEngine:
    """`anonymize(text, ...)`, answered by mamori.

    The signature is Presidio's, and the result is deliberately not identical:
    placeholders are numbered and reversible. A facade that returned `<PERSON>`
    to look more alike would throw away the property this library exists for,
    and would do it silently.
    """

    def __init__(self, config: MamoriConfig | None = None, **_: object) -> None:
        self._config = config or MamoriConfig()

    def anonymize(
        self,
        text: str,
        analyzer_results: Sequence[Any] | None = None,
        operators: Any = None,
        **_: object,
    ) -> AnonymizerResult:
        """Replace what mamori finds, and keep the way back.

        Args:
            text: The document.
            analyzer_results: Accepted and **not** used to decide what to
                replace. Presidio splits analysis and anonymisation across two
                calls; mamori runs one pipeline in which resolution and policy
                see every candidate together, and honouring a caller-supplied
                subset would mean applying a policy to findings that never went
                through it. Passing them is harmless and changes nothing.
            operators: Accepted and ignored. Presidio's operators choose
                between hashing, masking and redacting; here that is the
                policy, which is configuration rather than an argument.

        Raises:
            PolicyViolationError: the policy refuses to produce a protected
                text at all -- a credential, by default. Unlike
                :meth:`AnalyzerEngine.analyze`, this one is a step towards
                sending something, so it fails closed.
        """
        session = self._config.session()
        protected = session.protect(text)
        return AnonymizerResult(
            text=protected.protected_text,
            items=tuple(to_presidio(protected)),
            session=session,
        )
