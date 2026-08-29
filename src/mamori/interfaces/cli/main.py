"""Command line interface.

    mamori inspect  -- what would be detected, and nothing else
    mamori protect  -- print the text that is safe to send
    mamori restore  -- put the values back into a response
    mamori policy   -- show the active policy
    mamori locales  -- show the language packs and when each one runs
    mamori demo     -- a full round trip in one process

``inspect`` is the command to reach for first. It answers "what is in this
file?" without producing an artefact anyone can paste anywhere.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ... import __version__
from ...application.results import ProtectionResult, RestorationResult
from ...application.session import PrivacySession
from ...domain.entity_types import BUILTIN_TYPES
from ...domain.policy import PrivacyPolicy
from ...domain.script import scripts_in
from ...errors import MamoriError, PolicyViolationError
from ...infrastructure.detectors import available_locales
from ...infrastructure.storage import InMemoryMappingStore
from ...infrastructure.storage.jsonfile import PLAINTEXT_WARNING, dump_scope, load_scope

__all__ = ["build_parser", "main"]

_EXIT_OK = 0
_EXIT_ERROR = 1
_EXIT_BLOCKED = 2


def _read_input(text: str | None, file: str | None) -> str:
    if file:
        return Path(file).read_text(encoding="utf-8")
    if text is not None:
        return text
    return sys.stdin.read()


def _force_utf8() -> None:
    """Make Japanese output survive a cp932 console."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):  # pragma: no cover - console dependent
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mamori",
        description="Local-first privacy layer for generative AI.",
    )
    parser.add_argument("--version", action="version", version=f"mamori {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_input_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("text", nargs="?", help="text to process; omit to read stdin")
        p.add_argument("-f", "--file", help="read the text from a file instead")
        p.add_argument(
            "-l",
            "--locale",
            action="append",
            metavar="CODE",
            help=(
                "language pack to enable; repeatable. Omit to enable all of them, "
                "which is the safer default"
            ),
        )

    inspect = sub.add_parser("inspect", help="report what would be detected")
    add_input_args(inspect)
    inspect.add_argument("--json", action="store_true", help="emit JSON")

    protect = sub.add_parser("protect", help="print text that is safe to send")
    add_input_args(protect)
    protect.add_argument("--json", action="store_true", help="emit JSON")
    protect.add_argument(
        "--save-mapping",
        metavar="PATH",
        help="write the mapping so a later 'restore' can use it (PLAINTEXT)",
    )
    protect.add_argument(
        "--permissive",
        action="store_true",
        help="anonymize everything instead of blocking credentials",
    )

    restore = sub.add_parser("restore", help="put original values back into a response")
    add_input_args(restore)
    restore.add_argument("--mapping", required=True, metavar="PATH", help="mapping file")

    sub.add_parser("policy", help="show the active policy")
    sub.add_parser("locales", help="show the language packs and when each runs")
    sub.add_parser("demo", help="run a full round trip on a sample text")

    return parser


def _print_reports(result: ProtectionResult) -> None:
    if not result.entities:
        print("no sensitive values detected")
        return
    print(f"{result.entity_count} detected:")
    for entity in result.entities:
        target = entity.placeholder or entity.action.value
        print(
            f"  {entity.span.start:>5}:{entity.span.end:<5} "
            f"{entity.entity_type:<16} {target:<18} "
            f"{entity.preview:<20} ({entity.source}, {entity.confidence:.2f})"
        )


def _reports_as_json(result: ProtectionResult) -> list[dict[str, object]]:
    return [
        {
            "type": entity.entity_type,
            "action": entity.action.value,
            "start": entity.span.start,
            "end": entity.span.end,
            "confidence": entity.confidence,
            "source": entity.source,
            "preview": entity.preview,
            "placeholder": entity.placeholder,
        }
        for entity in result.entities
    ]


def _cmd_inspect(args: argparse.Namespace) -> int:
    text = _read_input(args.text, args.file)
    # Inspection must report on credentials rather than refuse, so it uses a
    # permissive policy. It never prints a protected text, so nothing here is
    # a step towards sending anything.
    with PrivacySession(policy=PrivacyPolicy.permissive(), locales=args.locale) as session:
        result = session.protect(text)
        if args.json:
            print(json.dumps({"entities": _reports_as_json(result)}, ensure_ascii=False, indent=2))
        else:
            _print_reports(result)
    return _EXIT_OK


def _cmd_protect(args: argparse.Namespace) -> int:
    text = _read_input(args.text, args.file)
    policy = PrivacyPolicy.permissive() if args.permissive else PrivacyPolicy.default()
    store = InMemoryMappingStore()
    session = PrivacySession(policy=policy, store=store, locales=args.locale)
    try:
        result = session.protect(text)
    except PolicyViolationError as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        print(
            "Nothing was written. Remove the credential, or re-run with "
            "--permissive if you understand the risk.",
            file=sys.stderr,
        )
        return _EXIT_BLOCKED

    if args.save_mapping:
        path = Path(args.save_mapping)
        count = dump_scope(store, session.scope, path)
        print(f"wrote {count} mappings to {path}", file=sys.stderr)
        print(PLAINTEXT_WARNING, file=sys.stderr)

    if args.json:
        print(
            json.dumps(
                {
                    "protected_text": result.protected_text,
                    "scope": result.scope,
                    "entities": _reports_as_json(result),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(result.protected_text)
        if result.entities:
            print(f"\n-- {result.entity_count} value(s) protected", file=sys.stderr)
    return _EXIT_OK


def _cmd_restore(args: argparse.Namespace) -> int:
    text = _read_input(args.text, args.file)
    store = InMemoryMappingStore()
    scope = load_scope(store, Path(args.mapping))
    session = PrivacySession(store=store, scope=scope)
    result: RestorationResult = session.restore(text)
    print(result.text)
    if result.unknown:
        print(
            f"-- warning: {len(result.unknown)} unrecognised placeholder(s) left as-is",
            file=sys.stderr,
        )
    if result.tampered:
        print(
            f"-- note: {len(result.tampered)} placeholder(s) had been altered and were recovered",
            file=sys.stderr,
        )
    return _EXIT_OK


def _cmd_policy(_args: argparse.Namespace) -> int:
    policy = PrivacyPolicy.default()
    print("default policy\n")
    width = max(len(name) for name in BUILTIN_TYPES)
    for name, entity_type in sorted(BUILTIN_TYPES.items()):
        action = policy.action_for(entity_type)
        print(f"  {name:<{width}}  {entity_type.category.value:<22}  {action.value}")
    print(f"\n  unmatched types -> {policy.default_action.value} (fail-closed)")
    return _EXIT_OK


_DEMO_TEXT = (
    "田中太郎さんへ\n"
    "株式会社さくら商事の佐藤花子です。\n"
    "ご連絡先 tanaka@example.com / 090-1234-5678 にご返信ください。\n"
    "社内Wikiは https://wiki.corp.local/project にあります。\n"
    "CC: Mr. John Smith (Acme Inc.), 415-555-0198\n"
)


def _cmd_demo(_args: argparse.Namespace) -> int:
    print("--- 1. original (never leaves this machine) ---")
    print(_DEMO_TEXT)

    with PrivacySession() as session:
        protected = session.protect(_DEMO_TEXT)
        print("--- 2. what an external model would see ---")
        print(protected.protected_text)

        print("--- 3. what was replaced ---")
        _print_reports(protected)
        found = ", ".join(sorted(script.value for script in scripts_in(_DEMO_TEXT)))
        print(f"    scripts found: {found}")

        # Stand-in for a model that answered using the placeholders, and
        # mangled two of them on the way -- which is exactly what they do.
        reply = (
            "\n<PERSON_001>様\n\nお世話になっております。PERSON_002です。\n"
            "<EMAIL_1> 宛にご返信いたします。\n"
        )
        print("\n--- 4. a reply that came back, placeholders altered ---")
        print(reply)

        restored = session.restore(reply)
        print("--- 5. restored locally ---")
        print(restored.text)
        print(
            f"-- {len(restored.restored)} restored, "
            f"{len(restored.tampered)} had been altered, "
            f"{len(restored.unknown)} unrecognised"
        )
    return _EXIT_OK


def _cmd_locales(_args: argparse.Namespace) -> int:
    packs = available_locales()
    print("language packs\n")
    width = max(len(pack.code) for pack in packs)
    for pack in packs:
        triggers = ", ".join(sorted(s.value for s in pack.triggers)) or "always"
        line = (
            f"  {pack.code:<{width}}  {pack.name:<10}  {len(pack.rules):>2} rules"
            f"  runs on: {triggers}"
        )
        if pack.suppressed_by:
            stood_down = ", ".join(sorted(s.value for s in pack.suppressed_by))
            line += f"  (not when: {stood_down})"
        print(line)
    print(
        "\nEvery pack is enabled unless --locale narrows them: an unexpected language\n"
        "in a document is exactly the case nobody redacted by hand. Universal rules --\n"
        "email, addresses, card numbers, credentials -- run whatever the text says."
    )
    return _EXIT_OK


_COMMANDS = {
    "inspect": _cmd_inspect,
    "protect": _cmd_protect,
    "restore": _cmd_restore,
    "policy": _cmd_policy,
    "locales": _cmd_locales,
    "demo": _cmd_demo,
}


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except MamoriError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_ERROR
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
