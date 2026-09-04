"""The public API is a contract, checked the way the promises are.

`test_promises.py` pins what this library will not do. This pins what it *is*:
the names a caller may rely on, and the shapes behind them. Both exist for the
same reason — a guarantee nobody checks is a sentence in a README.

The list below is deliberately written out rather than derived. Deriving it
from `mamori.__all__` would make this test agree with any change, which is the
opposite of a contract: adding a name should be a line in this file and
removing one should fail.

Found when it was written: nine releases of features were reachable only by a
deep import, `ConversationRegistry` and `LLMSettings` among them, both of which
the README tells people to use.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import pathlib
import pkgutil
from types import ModuleType

import pytest

import mamori

#: Every name `import mamori` offers, and nothing else.
PUBLIC = {
    # Entry points
    # `protect` and `inspect` are the two-line surface: one call, one scope,
    # and the restore closure that is the whole argument for this library over
    # a redactor. `inspect` shadows a stdlib module name under `import *`,
    # which is a real if small cost, paid because `PrivacySession.inspect` has
    # been the name for that question since 0.32 and two names for it would be
    # worse.
    "protect",
    "inspect",
    "Protected",
    "PrivacySession",
    "MamoriConfig",
    "load_config_file",
    "ConversationRegistry",
    "Conversation",
    # Results
    "ProtectionResult",
    "RestorationResult",
    "EntityReport",
    "StreamingRestorer",
    "StreamSummary",
    # Vocabulary
    "EntityType",
    "Category",
    "register_type",
    "Placeholder",
    "PlaceholderStyle",
    "Action",
    "Uncertain",
    "PrivacyPolicy",
    "LLMSettings",
    # Errors
    "MamoriError",
    "ConfigurationError",
    "DetectionError",
    "PolicyViolationError",
    "ProviderError",
    "StorageError",
    # Metadata
    "__version__",
}


class TestTheSurface:
    def test_it_is_exactly_this(self) -> None:
        exported = set(mamori.__all__)
        assert exported - PUBLIC == set(), "a name was added without a line in this test"
        assert PUBLIC - exported == set(), "a name this test guarantees is gone"

    @pytest.mark.parametrize("name", sorted(PUBLIC))
    def test_every_promised_name_is_importable(self, name: str) -> None:
        assert hasattr(mamori, name), f"mamori.{name} is promised and missing"

    def test_the_error_hierarchy_is_complete(self) -> None:
        """A caller catching `MamoriError` must catch everything this raises.

        `ProviderError` was missing from the top level for nine releases, so
        somebody catching mamori's errors by importing them from `mamori` would
        have missed one.
        """
        from mamori import errors

        raised = {
            name
            for name, value in vars(errors).items()
            if inspect.isclass(value) and issubclass(value, Exception)
        }
        assert raised <= set(mamori.__all__), sorted(raised - set(mamori.__all__))

    def test_every_error_descends_from_the_base(self) -> None:
        from mamori import errors

        for name in dir(errors):
            value = getattr(errors, name)
            if inspect.isclass(value) and issubclass(value, Exception):
                assert issubclass(value, mamori.MamoriError), name


class TestTheShapesBehindTheNames:
    """Field names are part of the contract; a rename is a breaking change."""

    @pytest.mark.parametrize(
        ("cls", "fields"),
        [
            (
                mamori.ProtectionResult,
                {"protected_text", "entities", "scope", "trace"},
            ),
            (
                mamori.RestorationResult,
                {"text", "restored", "unknown", "missing"},
            ),
            (
                mamori.EntityReport,
                {
                    "entity_type",
                    "action",
                    "span",
                    "confidence",
                    "source",
                    "preview",
                    "placeholder",
                    "surrogate",
                },
            ),
            (mamori.Placeholder, {"entity_type_name", "index"}),
        ],
    )
    def test_the_fields(self, cls: type, fields: set[str]) -> None:
        assert {f.name for f in dataclasses.fields(cls)} == fields

    @pytest.mark.parametrize(
        ("cls", "names"),
        [
            (mamori.Action, {"ALLOW", "ANONYMIZE", "MASK", "BLOCK"}),
            (mamori.Uncertain, {"DISCARD", "REFUSE"}),
            (mamori.PlaceholderStyle, {"ANGLE", "SQUARE", "CURLY"}),
            (
                mamori.Category,
                {
                    "PII",
                    "SECRET",
                    "COMPANY_CONFIDENTIAL",
                    "BUSINESS_SENSITIVE",
                    "INTERNAL",
                    "OTHER",
                },
            ),
        ],
    )
    def test_the_enum_members(self, cls: type, names: set[str]) -> None:
        assert {member.name for member in cls} == names  # type: ignore[attr-defined]

    def test_the_session_methods(self) -> None:
        expected = {
            "protect",
            "restore",
            "stream_restore",
            "external_system_prompt",
            "close",
            "scope",
            "policy",
        }
        actual = {name for name in dir(mamori.PrivacySession) if not name.startswith("_")}
        assert expected <= actual, sorted(expected - actual)

    def test_the_config_fields_a_caller_sets(self) -> None:
        """Every one of these appears in the README or the changelog, which
        makes each of them somebody's configuration file."""
        promised = {
            "locales",
            "stance",
            "rules",
            "category_defaults",
            "default_action",
            "min_confidence",
            "uncertain",
            "co_occurrence",
            "co_occurrence_min_confidence",
            "mask_token",
            "placeholder_style",
            "prompts",
            "llm",
            "corrections",
            "surrogates",
        }
        actual = {f.name for f in dataclasses.fields(mamori.MamoriConfig)}
        assert promised <= actual, sorted(promised - actual)


class TestNothingElseLooksPublic:
    def test_no_module_exports_a_private_name(self) -> None:
        """An `__all__` naming something underscored is a mixed message.

        Dunders are exempt: `__version__` is public by every convention there
        is, and the leading underscores are the convention rather than a
        signal about it.
        """
        offenders: list[str] = []
        for module in _every_module():
            for name in getattr(module, "__all__", ()):
                if name.startswith("_") and not name.startswith("__"):
                    offenders.append(f"{module.__name__}.{name}")
        assert not offenders, offenders

    def test_every_all_entry_actually_exists(self) -> None:
        """A stale `__all__` breaks `from module import *` and nothing else,
        which is why it goes unnoticed."""
        missing: list[str] = []
        for module in _every_module():
            for name in getattr(module, "__all__", ()):
                if not hasattr(module, name):
                    missing.append(f"{module.__name__}.{name}")
        assert not missing, missing


def _every_module() -> list[ModuleType]:
    modules = [mamori]
    for info in pkgutil.walk_packages(mamori.__path__, prefix="mamori."):
        try:
            modules.append(importlib.import_module(info.name))
        except ImportError:  # pragma: no cover - an optional adapter
            continue
    return modules


class TestEveryExportedErrorIsRaisedSomewhere:
    """An exception nobody raises is a documented failure mode that does not
    exist.

    `except SomethingError:` then reads as handling and is a branch that never
    runs -- the same defect as a check that cannot fail, arriving through the
    error hierarchy instead of through a test.

    Two of these were removed in 0.28 by hand: `AnonymizationError` and
    `RestorationError`, exported and documented and never raised in any commit.
    Doing it by hand does not stop a third, so this is the mechanism. Found by
    tsumugi, whose version had a sharper cause -- the only layer that could
    raise its dead error was forbidden by its own layering rules from importing
    the module defining it.

    A base class is exempt **only when something actually inherits from it**,
    checked through the class hierarchy rather than by the name looking like a
    base. That distinction matters: "it is called MamoriError so it is
    obviously a base" is the same reasoning that lets a dead class survive.
    """

    @staticmethod
    def _raised_names() -> set[str]:
        """Every name appearing as `raise Name(...)` anywhere in the package.

        AST rather than a grep, so `raise` inside a string or a comment does
        not count, and so a name that is only *mentioned* does not either.
        """
        import ast

        root = pathlib.Path(mamori.__file__).parent
        names: set[str] = set()
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Raise) or node.exc is None:
                    continue
                target = node.exc
                if isinstance(target, ast.Call):
                    target = target.func
                if isinstance(target, ast.Name):
                    names.add(target.id)
                elif isinstance(target, ast.Attribute):
                    names.add(target.attr)
        return names

    def test_nothing_in_the_hierarchy_is_dead(self) -> None:
        exported = {
            name: getattr(mamori.errors, name)
            for name in mamori.errors.__all__
            if isinstance(getattr(mamori.errors, name), type)
        }
        raised = self._raised_names()

        dead = []
        for name, cls in exported.items():
            if name in raised:
                continue
            inherited = any(
                other is not cls and issubclass(other, cls) for other in exported.values()
            )
            if not inherited:
                dead.append(name)

        assert not dead, (
            f"exported but never raised, and nothing inherits from them: {sorted(dead)}. "
            "Wire them or remove them: an exception nobody raises is a failure "
            "mode a caller will write a branch for and never enter."
        )

    def test_the_base_class_is_exempt_because_something_inherits_it(self) -> None:
        """Stated separately so the exemption is a fact rather than a habit."""
        children = [
            getattr(mamori.errors, name)
            for name in mamori.errors.__all__
            if isinstance(getattr(mamori.errors, name), type)
            and getattr(mamori.errors, name) is not mamori.errors.MamoriError
        ]
        assert children, "MamoriError is exempt only while something inherits from it"
        assert all(issubclass(child, mamori.errors.MamoriError) for child in children)
