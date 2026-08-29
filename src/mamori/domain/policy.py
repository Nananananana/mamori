"""Privacy policy: what to do with each kind of detected entity.

The policy is the only place that decides whether something may leave the
machine. It is deterministic and fail-closed: an entity type nobody has an
opinion about is *blocked*, not allowed.
"""

from __future__ import annotations

from collections.abc import Mapping as MappingABC
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from .entity_types import Category, EntityType

__all__ = ["Action", "PrivacyPolicy", "Uncertain"]


class Uncertain(Enum):
    """What a detection below ``min_confidence`` does.

    The name is the question. A detector said "there might be a person here,
    and I am 0.4 sure". Discarding that is a bet that it was wrong; refusing is
    a bet that being stopped costs less than being wrong. Which bet is right
    depends on what is in the document, so it is a setting rather than a rule.
    """

    #: Drop it. The text goes out with the value still in it.
    DISCARD = "discard"
    #: Refuse the text. Nothing goes out.
    REFUSE = "refuse"


class Action(Enum):
    """What to do with a detected entity."""

    #: Leave the value untouched. The external service will see it.
    ALLOW = "allow"
    #: Replace with a placeholder; restorable.
    ANONYMIZE = "anonymize"
    #: Replace with a fixed mask. **Not** restorable, by design.
    MASK = "mask"
    #: Refuse to produce a protected text at all.
    BLOCK = "block"


_DEFAULT_BY_CATEGORY: MappingABC[Category, Action] = MappingProxyType(
    {
        Category.PII: Action.ANONYMIZE,
        Category.SECRET: Action.BLOCK,
        Category.COMPANY_CONFIDENTIAL: Action.ANONYMIZE,
        Category.BUSINESS_SENSITIVE: Action.ANONYMIZE,
        Category.INTERNAL: Action.ANONYMIZE,
        # Category.OTHER is deliberately absent: a type nobody categorised
        # falls through to ``default_action``, which blocks. A custom detector
        # added without a category should stop the request, not quietly ship
        # whatever it found.
    }
)


@dataclass(frozen=True, slots=True)
class PrivacyPolicy:
    """Maps entity types to actions.

    Resolution order: per-type rule, then per-category default, then
    ``default_action``.

    Args:
        rules: Entity type *name* -> action. Highest precedence.
        category_defaults: Category -> action.
        default_action: Used when neither of the above matches. Defaults to
            ``BLOCK`` so that an unrecognised kind of sensitive data stops the
            request instead of silently leaving the machine.
        mask_token: Text substituted for ``MASK``.
        min_confidence: Detections below this are discarded before anything
            else happens -- they are treated as never having been found.

            This is the coverage/quality dial. Raising it trades recall for
            fewer spurious placeholders, which is a real trade: a document full
            of tokens standing in for ordinary words is one nobody sends, and a
            privacy layer people stop using protects nothing.

            The default is ``0.0`` and must stay there. Lowering coverage is a
            decision for whoever is handling the data, not a default they
            inherit without being asked.
        uncertain: What to do with a detection below ``min_confidence``.

            ``DISCARD`` is the default and everything before 0.19 did it: an
            uncertain detection is treated as never having been found, and the
            text goes out with the value in it.

            ``REFUSE`` stops the text instead. It is for a deployment that
            would rather send nothing than send something it is not sure
            about -- a legal team, a clinical setting, anywhere the cost of a
            leak is not measured in answer quality. The refusal names the
            types and the confidences, never the values.

            It does nothing at the default ``min_confidence`` of ``0.0``,
            because nothing is below zero. The two settings are one dial:
            ``min_confidence`` says where certainty runs out and ``uncertain``
            says what happens there.
    """

    rules: MappingABC[str, Action] = field(default_factory=dict)
    category_defaults: MappingABC[Category, Action] = field(default_factory=dict)
    default_action: Action = Action.BLOCK
    mask_token: str = "[REDACTED]"  # noqa: S105 - a redaction marker, not a credential
    min_confidence: float = 0.0
    uncertain: Uncertain = Uncertain.DISCARD

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError(f"min_confidence out of range: {self.min_confidence}")

    def accepts(self, confidence: float) -> bool:
        """Whether a detection is confident enough to be considered at all."""
        return confidence >= self.min_confidence

    def action_for(self, entity_type: EntityType) -> Action:
        """Resolve the action for ``entity_type``."""
        by_name = self.rules.get(entity_type.name)
        if by_name is not None:
            return by_name
        by_category = self.category_defaults.get(entity_type.category)
        if by_category is not None:
            return by_category
        return self.default_action

    def with_min_confidence(self, min_confidence: float) -> PrivacyPolicy:
        """Return a copy that ignores detections below ``min_confidence``."""
        return PrivacyPolicy(
            rules=self.rules,
            category_defaults=self.category_defaults,
            default_action=self.default_action,
            mask_token=self.mask_token,
            min_confidence=min_confidence,
        )

    def with_rule(self, entity_type_name: str, action: Action) -> PrivacyPolicy:
        """Return a copy with one rule added or replaced."""
        rules = dict(self.rules)
        rules[entity_type_name] = action
        return PrivacyPolicy(
            rules=rules,
            category_defaults=self.category_defaults,
            default_action=self.default_action,
            mask_token=self.mask_token,
            min_confidence=self.min_confidence,
        )

    @classmethod
    def default(cls) -> PrivacyPolicy:
        """The recommended starting policy.

        PII and company-internal data are pseudonymized; credentials are
        blocked outright, because there is no legitimate reason to send an API
        key to a third party -- not even a placeholder-shaped one.
        """
        return cls(
            rules={
                # Text in the input that already looks like a placeholder must be
                # re-mapped, never blocked, or ordinary prose containing angle
                # brackets would stop the request.
                "TEXT": Action.ANONYMIZE,
            },
            category_defaults=dict(_DEFAULT_BY_CATEGORY),
            default_action=Action.BLOCK,
        )

    @classmethod
    def permissive(cls) -> PrivacyPolicy:
        """Anonymize everything, block nothing. For experimentation only.

        Do not use this to handle credentials: pseudonymizing an API key still
        transmits a token shaped like a secret and tells the recipient one
        exists.
        """
        return cls(category_defaults={}, default_action=Action.ANONYMIZE)
