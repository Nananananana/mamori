"""Turn a text containing sensitive data into one that is safe to send out."""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.confidence import CERTAIN
from ..domain.corrections import CorrectionLog
from ..domain.entity_types import PLACEHOLDER_LITERAL
from ..domain.mapping import Mapping
from ..domain.normalization import NormalizedText
from ..domain.placeholder import STRICT_PLACEHOLDER_RE, Placeholder, PlaceholderStyle
from ..domain.policy import Action, PrivacyPolicy, Uncertain
from ..domain.resolution import (
    assert_non_overlapping,
    resolve_overlaps,
    resolve_overlaps_traced,
)
from ..domain.script import scripts_in
from ..domain.sensitive_entity import SensitiveEntity
from ..domain.span import Span
from ..domain.surrogate import pool_for, surrogate_for
from ..errors import ConfigurationError, DetectionError, PolicyViolationError
from ..ports.detector import Detector
from ..ports.mapping_store import MappingStore
from .results import EntityReport, ProtectionResult, mask_preview
from .trace import DecisionTrace, Outcome, TraceBuilder

__all__ = ["ProtectionService"]


class ProtectionService:
    """Detect, resolve, apply policy, pseudonymize.

    Fail-closed: if any detector raises, or the policy blocks anything, no
    protected text is produced at all. There is no partial result, because a
    partial result is indistinguishable from a safe one at the call site.
    """

    def __init__(
        self,
        detectors: Sequence[Detector],
        policy: PrivacyPolicy,
        store: MappingStore,
        corrections: CorrectionLog | None = None,
        surrogate_types: frozenset[str] = frozenset(),
        placeholder_style: PlaceholderStyle = PlaceholderStyle.ANGLE,
        trace: bool = False,
    ) -> None:
        self._corrections = corrections if corrections is not None else CorrectionLog()
        #: Types substituted with a plausible value instead of a token. Empty
        #: by default, and deliberately: an unrestored placeholder is obvious
        #: and an unrestored surrogate reads as a fact about the wrong person.
        self._surrogate_types = frozenset(surrogate_types)
        #: Which brackets go into the protected text. Identity is the
        #: (type, index) pair either way, so restoration is unaffected.
        self._placeholder_style = placeholder_style
        #: Record what was considered and discarded. Off by default: it
        #: costs a list of every candidate, and nothing in the normal path
        #: reads it.
        self._trace = trace
        self._detectors = tuple(detectors)
        self._policy = policy
        self._store = store

    @property
    def surrogate_types(self) -> frozenset[str]:
        """Types a plausible value stands in for. Read by provenance."""
        return self._surrogate_types

    @property
    def placeholder_style(self) -> PlaceholderStyle:
        """Which brackets go into the text. Read by provenance."""
        return self._placeholder_style

    def protect(self, text: str, scope: str) -> ProtectionResult:
        """Protect ``text``, allocating placeholders within ``scope``.

        Raises:
            DetectionError: a detector failed. Nothing is emitted.
            PolicyViolationError: the policy blocked at least one entity.
        """
        if not text:
            return ProtectionResult(protected_text="", scope=scope)

        normalized = NormalizedText.of(text)
        detections = list(self._run_detectors(normalized))
        detections.extend(self._detect_placeholder_literals(text))

        # Filter before resolution, not after: a detection the policy will not
        # consider must not be able to win a span from one it would have. The
        # same reasoning applies to a corrected-away value -- if it could win a
        # span and then be dropped, ruling out a false positive would open a
        # hole where a real detection used to be.
        builder = TraceBuilder() if self._trace else None

        confident: list[SensitiveEntity] = []
        uncertain: list[SensitiveEntity] = []
        for entity in detections:
            if not self._policy.accepts(entity.confidence.value):
                _note(
                    builder,
                    entity,
                    Outcome.BELOW_CONFIDENCE,
                    f"below min_confidence {self._policy.min_confidence}",
                )
                uncertain.append(entity)
                continue
            if self._corrections.excludes(entity):
                _note(
                    builder, entity, Outcome.CORRECTED_AWAY, "ruled not sensitive by a correction"
                )
                continue
            confident.append(entity)

        # A deployment can ask to be stopped rather than to have the doubt
        # resolved in favour of sending. Checked before resolution and before
        # anything is substituted, so nothing has been built when it fires.
        if uncertain and self._policy.uncertain is Uncertain.REFUSE:
            raise PolicyViolationError(
                tuple(
                    (e.entity_type.name, e.span.start, e.span.end)
                    for e in sorted(uncertain, key=lambda e: e.confidence.value)
                ),
                _uncertain_message(uncertain),
            )

        if builder is None:
            resolved = resolve_overlaps(confident)
        else:
            resolved, displaced = resolve_overlaps_traced(confident)
            for loss in displaced:
                _note(
                    builder,
                    loss.loser,
                    Outcome.DISPLACED,
                    f"lost to {loss.winner.entity_type.name} ({loss.reason})",
                )
            for kept in resolved:
                _note(builder, kept, Outcome.KEPT)
        assert_non_overlapping(resolved)

        decided = [(entity, self._policy.action_for(entity.entity_type)) for entity in resolved]
        trace = builder.build(len(text)) if builder is not None else None

        blocked = tuple(
            (entity.entity_type.name, entity.span.start, entity.span.end)
            for entity, action in decided
            if action is Action.BLOCK
        )
        if blocked:
            raise PolicyViolationError(blocked)

        return self._apply(text, decided, scope, trace)

    def inspect(self, text: str) -> tuple[str, ...]:
        """The entity types in ``text`` this policy would act on.

        Allocates nothing, stores nothing, raises nothing -- not even for a
        credential, which :meth:`protect` refuses. It answers one question:
        *is there anything here this configuration considers sensitive, and of
        what kind*.

        It exists because the proxy has to ask that about text it cannot
        rewrite. A payload field this library does not know the shape of
        cannot be protected in place without risking a request that no longer
        parses -- so the proxy asks what is in it and refuses to forward when
        the answer is not "nothing". Doing that through :meth:`protect` would
        allocate placeholders for a request that is about to be refused, and
        would raise on exactly the case that matters most.
        """
        if not text:
            return ()
        normalized = NormalizedText.of(text)
        detections = list(self._run_detectors(normalized))
        detections.extend(self._detect_placeholder_literals(text))
        confident = [
            entity
            for entity in detections
            if self._policy.accepts(entity.confidence.value)
            and not self._corrections.excludes(entity)
        ]
        return tuple(
            sorted(
                {
                    entity.entity_type.name
                    for entity in resolve_overlaps(confident)
                    if self._policy.action_for(entity.entity_type) is not Action.ALLOW
                }
            )
        )

    # -- internals ---------------------------------------------------------

    def _run_detectors(self, normalized: NormalizedText) -> list[SensitiveEntity]:
        found: list[SensitiveEntity] = []
        for detector in self._detectors:
            try:
                detections = detector.detect(normalized.text)
            except Exception as exc:
                raise DetectionError(detector.name, exc) from exc
            for entity in detections:
                span = normalized.to_original_span(entity.span.start, entity.span.end)
                original_value = normalized.original[span.start : span.end]
                found.append(entity.relocated(span, original_value))
        return found

    @staticmethod
    def _refuse_a_scope_that_quotes_the_document(
        decided: Sequence[tuple[SensitiveEntity, Action]], scope: str
    ) -> None:
        """A scope identifier may not contain a value from the document.

        The scope travels everywhere the protection is described -- into
        provenance records, manifests, audit logs -- precisely because it
        carries no content. mamori's own scopes are a random UUID and cannot,
        but a caller may supply one, and ``scope="tanaka-invoice"`` puts the
        value back into every place the record was safe to send.

        It is the same defect that would follow from hashing a document into
        ``policy_hash``, moved one field over, and it is worth refusing rather
        than documenting: the caller who names a scope after its subject is
        not reading this docstring.

        Values under three characters are not checked. A one-character value
        colliding with an ordinary identifier is common and means nothing,
        and refusing on it would teach callers to route around the check.
        """
        for entity, action in decided:
            if action is Action.ALLOW:
                continue  # In the text either way; the scope adds no exposure.
            if len(entity.value) >= 3 and entity.value in scope:
                raise ConfigurationError(
                    f"scope contains a detected {entity.entity_type.name}. "
                    "A scope identifier is quoted in provenance records and logs, "
                    "so it must not be derived from the document. Use the "
                    "generated default, or an identifier of your own that names "
                    "the request rather than its subject."
                )

    @staticmethod
    def _detect_placeholder_literals(text: str) -> list[SensitiveEntity]:
        """Treat placeholder-shaped text in the *input* as an entity.

        Without this, an input that already contains ``<PERSON_001>`` would be
        indistinguishable from our own token on the way back, and restoration
        would splice an unrelated value into the user's text.
        """
        return [
            SensitiveEntity(
                entity_type=PLACEHOLDER_LITERAL,
                span=Span(match.start(), match.end()),
                value=match.group(0),
                confidence=CERTAIN,
                source="placeholder-literal",
            )
            for match in STRICT_PLACEHOLDER_RE.finditer(text)
        ]

    def _apply(
        self,
        text: str,
        decided: Sequence[tuple[SensitiveEntity, Action]],
        scope: str,
        trace: DecisionTrace | None = None,
    ) -> ProtectionResult:
        self._refuse_a_scope_that_quotes_the_document(decided, scope)

        reports: list[EntityReport] = []
        pieces: list[str] = []
        cursor = 0

        for entity, action in decided:
            placeholder: Placeholder | None = None
            mapping: Mapping | None = None
            if action is Action.ALLOW:
                replacement = text[entity.span.start : entity.span.end]
            elif action is Action.MASK:
                replacement = self._policy.mask_token
            else:  # ANONYMIZE
                mapping = self._allocate(entity, scope, text)
                placeholder = mapping.placeholder
                # A surrogate is a value and goes in as it stands; a token is
                # rendered in whichever brackets this session asked for. Its
                # identity is the (type, index) pair either way, which is why
                # restoration does not have to know what was chosen.
                replacement = mapping.surface or self._styled(placeholder)

            pieces.append(text[cursor : entity.span.start])
            pieces.append(replacement)
            cursor = entity.span.end

            reports.append(
                EntityReport(
                    entity_type=entity.entity_type.name,
                    action=action,
                    span=entity.span,
                    confidence=entity.confidence.value,
                    source=entity.source,
                    preview=mask_preview(entity.value),
                    placeholder=placeholder.token if placeholder else None,
                    surrogate=mapping is not None and mapping.is_surrogate,
                )
            )

        pieces.append(text[cursor:])
        return ProtectionResult(
            protected_text="".join(pieces),
            entities=tuple(reports),
            scope=scope,
            trace=trace,
        )

    def _allocate(self, entity: SensitiveEntity, scope: str, text: str) -> Mapping:
        """Return the placeholder for this entity, reusing it within the scope.

        The same value seen twice must map to the same token, or the model
        cannot tell that two mentions refer to one person.
        """
        identity = entity.identity_key
        existing = self._store.find_by_identity(scope, identity)
        if existing is not None:
            return existing

        type_name = entity.entity_type.name
        index = self._store.next_index(scope, type_name)
        placeholder = Placeholder(type_name, index)
        mapping = Mapping(
            scope=scope,
            placeholder=placeholder,
            entity_type_name=type_name,
            original_value=entity.value,
            identity_key=identity,
            surface=self._surface_for(type_name, index, scope, text),
        )
        self._store.put(mapping)
        return mapping

    def _styled(self, placeholder: Placeholder) -> str:
        """The token as it goes into the protected text."""
        return placeholder.rendered(self._placeholder_style)

    def _surface_for(self, type_name: str, index: int, scope: str, text: str) -> str:
        """A surrogate to substitute, or empty for the placeholder token.

        Empty is the default and the safe answer. A surrogate is only produced
        when the caller asked for one for this type, a pool covers it, and the
        value it would use appears nowhere in the document and has not already
        been handed to something else -- because restoring the wrong occurrence
        would corrupt the caller's own words.
        """
        if type_name not in self._surrogate_types:
            return ""
        taken = {m.surface for m in self._store.list_scope(scope) if m.surface}
        return (
            surrogate_for(
                type_name,
                index,
                locale=self._surrogate_locale(text),
                avoid=frozenset(taken) | _appearing_in(text, type_name),
            )
            or ""
        )

    def _surrogate_locale(self, text: str) -> str:
        """Which pool to draw from, so a Japanese name is replaced by one."""
        scripts = {script.value for script in scripts_in(text)}
        if "kana" in scripts:
            return "ja"
        if "han" in scripts:
            return "zh"
        return "en"


def _appearing_in(text: str, type_name: str) -> frozenset[str]:
    """Pool values already present in the document, which must not be reused."""
    pool = pool_for(type_name, "*")
    candidates = set(pool.values) if pool else set()
    for locale in ("ja", "en", "zh"):
        located = pool_for(type_name, locale)
        if located is not None:
            candidates |= set(located.values)
    return frozenset(value for value in candidates if value in text)


def _note(
    builder: TraceBuilder | None,
    entity: SensitiveEntity,
    outcome: Outcome,
    detail: str = "",
) -> None:
    """Record one decision, if anybody asked for a trace.

    The preview is masked here rather than at the edge, so there is no path
    from a trace to a value even by accident.
    """
    if builder is None:
        return
    builder.record(
        entity_type=entity.entity_type.name,
        span=entity.span,
        preview=mask_preview(entity.value),
        source=entity.source,
        confidence=entity.confidence.value,
        outcome=outcome,
        detail=detail,
    )


def _uncertain_message(uncertain: list[SensitiveEntity]) -> str:
    """Why the text was refused: how many, and how close. Never a value.

    An operator reading this needs to know what to look at and how near it came
    to the threshold. Quoting the value back would put it in a log, which is
    the one place this library is trying to keep it out of.
    """
    closest = max(e.confidence.value for e in uncertain)
    return (
        f"{len(uncertain)} detection(s) below the confidence threshold and this "
        f"policy refuses rather than discards them (closest {closest:.2f}); nothing sent"
    )
