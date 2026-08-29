"""The layering rules, enforced rather than promised.

Every document in this repository says the domain imports nothing but the
standard library and that dependencies point inwards. Until now that was a
convention, upheld by whoever last read `CONTRIBUTING.md`, and conventions
about imports lose to autocomplete.

This walks the source with `ast` and checks it. The rules are the same ones
`docs/architecture.md` states, so if one changes, both change together or this
fails.

The one that matters most is the first: `domain/` may import only the standard
library. It holds every security-relevant decision -- resolution, policy,
placeholder identity, restoration, trust boundaries -- and the reason those can
be tested without a model, a network or a database is that nothing in there
knows such things exist.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

import mamori

PACKAGE_ROOT = Path(mamori.__file__).parent
PACKAGE = "mamori"

#: Which layers each layer may import from. A layer absent from a value cannot
#: be reached from that key, whatever the import looks like.
ALLOWED: dict[str, frozenset[str]] = {
    # Pure. Stdlib only: no ports, no adapters, no prompts, no configuration.
    "domain": frozenset(),
    # Interfaces the application depends on. They speak in domain terms.
    "ports": frozenset({"domain"}),
    # What to tell a model, and how to read what it says back.
    "prompts": frozenset({"domain"}),
    # Orchestration. Reaches infrastructure for one thing only -- supplying a
    # default detector set and a default store so that PrivacySession() works
    # with no arguments -- and TestDefaultConstructionIsTheOnlyException below
    # pins exactly which files and symbols that covers, so the exception cannot
    # spread quietly into the rest of the layer.
    "application": frozenset({"domain", "ports", "prompts", "infrastructure"}),
    # Adapters. They implement ports and may render prompts.
    "infrastructure": frozenset({"domain", "ports", "prompts"}),
    # Measurement runs the real pipeline, so it reaches the application.
    "evaluation": frozenset({"domain", "ports", "application", "infrastructure"}),
    # Settings assemble everything, so they may name everything.
    "config": frozenset(
        {"domain", "ports", "prompts", "application", "infrastructure", "llm_settings"}
    ),
    "llm_settings": frozenset({"domain", "ports"}),
    # A description of a configuration. It reads settings and the domain
    # vocabulary they resolve to, and nothing else -- a report that ran a
    # detector or opened a socket would be doing rather than describing.
    "report": frozenset({"domain", "config", "llm_settings"}),
    # The outside edge. Nothing imports it.
    "interfaces": frozenset(
        {
            "domain",
            "ports",
            "prompts",
            "application",
            "infrastructure",
            "evaluation",
            "config",
            "llm_settings",
            "report",
        }
    ),
    # Exceptions are shared by everything and import nothing.
    "errors": frozenset(),
}

#: Layers that only the outermost edge may import. An adapter reaching into the
#: evaluation harness, or anything at all reaching into the CLI, is a layering
#: mistake that would otherwise surface only as a strange import cycle.
NEVER_IMPORTED = frozenset({"interfaces", "evaluation"})

#: The one layer allowed to import those, because driving them is its job.
OUTERMOST = "interfaces"


def source_files() -> Iterator[Path]:
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" not in path.parts:
            yield path


def layer_of(path: Path) -> str:
    """The top-level layer a file belongs to."""
    relative = path.relative_to(PACKAGE_ROOT)
    return relative.parts[0] if len(relative.parts) > 1 else relative.stem


def imported_layers(path: Path) -> set[str]:
    """Layers this file imports from, resolving relative imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    depth_to_root = len(path.relative_to(PACKAGE_ROOT).parts) - 1
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                # `from ...domain.trust import X` at depth 2 -> level 3 is the
                # package root, so the module names the layer.
                if node.level - 1 == depth_to_root and node.module:
                    found.add(node.module.split(".")[0])
            elif node.module and node.module.split(".")[0] == PACKAGE:
                parts = node.module.split(".")
                if len(parts) > 1:
                    found.add(parts[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == PACKAGE and len(parts) > 1:
                    found.add(parts[1])
    return found


ALL_FILES = list(source_files())
FILE_IDS = [str(p.relative_to(PACKAGE_ROOT)) for p in ALL_FILES]


class TestLayering:
    def test_the_rules_cover_every_layer(self) -> None:
        """A new top-level module must be placed deliberately, not by default."""
        layers = {layer_of(path) for path in ALL_FILES} - {"__init__", "py"}
        unplaced = sorted(layers - set(ALLOWED))
        assert not unplaced, (
            f"no layering rule for {unplaced}. Add it to ALLOWED in this file and "
            "to the table in docs/architecture.md, in the same change."
        )

    @pytest.mark.parametrize("path", ALL_FILES, ids=FILE_IDS)
    def test_a_file_imports_only_what_its_layer_may(self, path: Path) -> None:
        layer = layer_of(path)
        if layer in {"__init__", "py"}:
            pytest.skip("the package root re-exports everything by design")
        allowed = ALLOWED.get(layer, frozenset())
        for target in imported_layers(path) - {layer, "errors"}:
            assert target in allowed, (
                f"{path.relative_to(PACKAGE_ROOT)} is in '{layer}' and imports "
                f"'{target}', which '{layer}' may not reach. Allowed: "
                f"{sorted(allowed) or 'stdlib only'}."
            )

    @pytest.mark.parametrize("path", ALL_FILES, ids=FILE_IDS)
    def test_nothing_imports_the_outer_layers(self, path: Path) -> None:
        layer = layer_of(path)
        for target in imported_layers(path):
            if target in NEVER_IMPORTED and layer not in {target, OUTERMOST}:
                pytest.fail(
                    f"{path.relative_to(PACKAGE_ROOT)} imports '{target}'. Nothing "
                    "may depend on the CLI or the evaluation harness."
                )


class TestDomainPurity:
    """The rule the whole design rests on."""

    def domain_files(self) -> list[Path]:
        return [p for p in ALL_FILES if layer_of(p) == "domain"]

    def test_there_is_a_domain_to_protect(self) -> None:
        assert len(self.domain_files()) >= 10

    def test_the_domain_imports_no_other_layer(self) -> None:
        for path in self.domain_files():
            reached = imported_layers(path) - {"domain"}
            assert not reached, f"{path.name} imports {sorted(reached)}"

    def test_the_domain_imports_no_third_party_package(self) -> None:
        """No pydantic, no SQLAlchemy, no LLM SDK. Not even indirectly."""
        allowed_stdlib = {
            "__future__",
            # Added in 0.22 for overlap resolution, which was quadratic and
            # took thirteen seconds on a half-megabyte document. A binary
            # search over the accepted spans is the whole fix, and `bisect` is
            # as much of the standard library as `re` is.
            "bisect",
            "collections",
            "dataclasses",
            "enum",
            "hashlib",
            "ipaddress",
            "re",
            "types",
            "typing",
            "unicodedata",
            "urllib",
        }
        for path in self.domain_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                roots: list[str] = []
                if isinstance(node, ast.Import):
                    roots = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                    roots = [node.module.split(".")[0]]
                for root in roots:
                    assert root in allowed_stdlib, (
                        f"{path.name} imports {root!r}. The domain holds every "
                        "security decision and stays testable with no model, no "
                        "network and no database, which only works while it "
                        "imports nothing but the standard library. If this is "
                        "genuinely needed, it belongs in another layer."
                    )

    def test_the_security_decisions_are_all_in_the_domain(self) -> None:
        """Named explicitly, so moving one out is a deliberate act."""
        names = {path.stem for path in self.domain_files()}
        for module in (
            "resolution",  # which overlapping detection survives
            "policy",  # what happens to a detected entity
            "placeholder",  # which value gets which placeholder
            "placeholder_matching",  # whether a run of response text resolves
            "normalization",  # whether a span maps back correctly
            "trust",  # where a detector may live
        ):
            assert module in names, f"{module} must stay in the domain"


class TestDefaultConstructionIsTheOnlyException:
    """The application may reach an adapter to build a default. Nothing else.

    A library whose first example is ``PrivacySession()`` has to construct
    *something*, and the alternatives are worse: requiring every caller to wire
    adapters, or a registry indirection that buys purity and costs readability.

    So the coupling is permitted and fenced. This says which files may do it
    and which names they may use; anything else in the application layer that
    touches an adapter fails here, which is the point -- an exception nobody
    checks becomes the rule.
    """

    #: file -> the only infrastructure names it may import.
    PERMITTED: ClassVar[dict[str, frozenset[str]]] = {
        "session.py": frozenset({"default_detectors", "InMemoryMappingStore"}),
    }

    def application_files(self) -> list[Path]:
        return [p for p in ALL_FILES if layer_of(p) == "application"]

    def test_only_the_named_files_reach_infrastructure(self) -> None:
        for path in self.application_files():
            if "infrastructure" not in imported_layers(path):
                continue
            assert path.name in self.PERMITTED, (
                f"{path.name} imports an adapter. Only "
                f"{sorted(self.PERMITTED)} may, and only for default construction."
            )

    def test_only_the_named_symbols_cross(self) -> None:
        for path in self.application_files():
            allowed = self.PERMITTED.get(path.name)
            if allowed is None:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                if "infrastructure" not in node.module:
                    continue
                imported = {alias.name for alias in node.names}
                extra = sorted(imported - allowed)
                assert not extra, (
                    f"{path.name} imports {extra} from infrastructure. Permitted "
                    f"there: {sorted(allowed)}. Anything more belongs behind a port."
                )

    def test_the_exception_does_not_reach_the_services(self) -> None:
        """Protection and restoration know only ports. That is not negotiable."""
        for name in ("protection.py", "restoration.py", "streaming.py"):
            path = next(p for p in self.application_files() if p.name == name)
            assert "infrastructure" not in imported_layers(path)


class TestPortsStayThin:
    """A port is a promise. One that grows behaviour stops being swappable."""

    def port_files(self) -> list[Path]:
        return [p for p in ALL_FILES if layer_of(p) == "ports" and p.stem != "__init__"]

    def test_ports_import_only_the_domain(self) -> None:
        for path in self.port_files():
            reached = imported_layers(path) - {"ports"}
            assert reached <= {"domain"}, f"{path.name} imports {sorted(reached)}"

    def test_every_port_module_defines_a_protocol_or_a_value_object(self) -> None:
        for path in self.port_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
            assert classes, f"{path.name} defines no types"


class TestNoCycles:
    def test_the_layer_graph_is_acyclic(self) -> None:
        edges = {layer: set(allowed) for layer, allowed in ALLOWED.items()}

        def reaches(start: str, target: str, seen: set[str]) -> bool:
            if start in seen:
                return False
            seen.add(start)
            for nxt in edges.get(start, set()):
                if nxt == target or reaches(nxt, target, seen):
                    return True
            return False

        for layer in edges:
            assert not reaches(layer, layer, set()), f"'{layer}' can reach itself"
