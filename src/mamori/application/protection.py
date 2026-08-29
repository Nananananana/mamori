"""Turn a text containing sensitive data into one that is safe to send out."""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.confidence import CERTAIN
from ..domain.entity_types import PLACEHOLDER_LITERAL
from ..domain.mapping import Mapping
from ..domain.normalization import NormalizedText
from ..domain.placeholder import STRICT_PLACEHOLDER_RE, Placeholder
from ..domain.policy import Action, PrivacyPolicy
from ..domain.resolution import assert_non_overlapping, resolve_overlaps
from ..domain.sensitive_entity import SensitiveEntity
from ..domain.span import Span
from ..errors import DetectionError, PolicyViolationError
from ..ports.detector import Detector
from ..ports.mapping_store import MappingStore
from .results import EntityReport, ProtectionResult, mask_preview

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
    ) -> None:
        self._detectors = tuple(detectors)
        self._policy = policy
        self._store = store

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
        # consider must not be able to win a span from one it would have.
        confident = [
            entity for entity in detections if self._policy.accepts(entity.confidence.value)
        ]

        resolved = resolve_overlaps(confident)
        assert_non_overlapping(resolved)

        decided = [(entity, self._policy.action_for(entity.entity_type)) for entity in resolved]

        blocked = tuple(
            (entity.entity_type.name, entity.span.start, entity.span.end)
            for entity, action in decided
            if action is Action.BLOCK
        )
        if blocked:
            raise PolicyViolationError(blocked)

        return self._apply(text, decided, scope)

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
    ) -> ProtectionResult:
        reports: list[EntityReport] = []
        pieces: list[str] = []
        cursor = 0

        for entity, action in decided:
            placeholder: Placeholder | None = None
            if action is Action.ALLOW:
                replacement = text[entity.span.start : entity.span.end]
            elif action is Action.MASK:
                replacement = self._policy.mask_token
            else:  # ANONYMIZE
                placeholder = self._allocate(entity, scope)
                replacement = placeholder.token

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
                )
            )

        pieces.append(text[cursor:])
        return ProtectionResult(
            protected_text="".join(pieces),
            entities=tuple(reports),
            scope=scope,
        )

    def _allocate(self, entity: SensitiveEntity, scope: str) -> Placeholder:
        """Return the placeholder for this entity, reusing it within the scope.

        The same value seen twice must map to the same token, or the model
        cannot tell that two mentions refer to one person.
        """
        identity = entity.identity_key
        existing = self._store.find_by_identity(scope, identity)
        if existing is not None:
            return existing.placeholder

        type_name = entity.entity_type.name
        placeholder = Placeholder(type_name, self._store.next_index(scope, type_name))
        self._store.put(
            Mapping(
                scope=scope,
                placeholder=placeholder,
                entity_type_name=type_name,
                original_value=entity.value,
                identity_key=identity,
            )
        )
        return placeholder
