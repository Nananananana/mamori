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

__all__ = ["Action", "PrivacyPolicy"]


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
    """

    rules: MappingABC[str, Action] = field(default_factory=dict)
    category_defaults: MappingABC[Category, Action] = field(default_factory=dict)
    default_action: Action = Action.BLOCK
    mask_token: str = "[REDACTED]"  # noqa: S105 - a redaction marker, not a credential

    def action_for(self, entity_type: EntityType) -> Action:
        """Resolve the action for ``entity_type``."""
        by_name = self.rules.get(entity_type.name)
        if by_name is not None:
            return by_name
        by_category = self.category_defaults.get(entity_type.category)
        if by_category is not None:
            return by_category
        return self.default_action

    def with_rule(self, entity_type_name: str, action: Action) -> PrivacyPolicy:
        """Return a copy with one rule added or replaced."""
        rules = dict(self.rules)
        rules[entity_type_name] = action
        return PrivacyPolicy(
            rules=rules,
            category_defaults=self.category_defaults,
            default_action=self.default_action,
            mask_token=self.mask_token,
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
