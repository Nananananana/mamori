"""Command line interface.

    mamori inspect  -- what would be detected, and nothing else
    mamori protect  -- print the text that is safe to send
    mamori restore  -- put the values back into a response
    mamori policy   -- show the active policy
    mamori locales  -- show the language packs and when each one runs
    mamori config   -- show the settings that would be used, and where from
    mamori eval     -- score the detectors against labelled data
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
from ...config import MamoriConfig, load_config_file
from ...domain.entity_types import BUILTIN_TYPES
from ...domain.policy import PrivacyPolicy
from ...domain.script import scripts_in
from ...errors import MamoriError, PolicyViolationError
from ...evaluation import (
    Dataset,
    EvaluationReport,
    MatchMode,
    bundled_datasets,
    evaluate,
)
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

    def add_config_args(p: argparse.ArgumentParser) -> None:
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
        p.add_argument(
            "-c", "--config", metavar="PATH", help="settings file (.json, or .toml on 3.11+)"
        )
        p.add_argument(
            "--min-confidence",
            type=float,
            metavar="F",
            help="ignore detections below this confidence; trades coverage for fewer"
            " spurious placeholders",
        )
        p.add_argument(
            "--no-co-occurrence",
            action="store_true",
            help="do not propagate a confirmed value to its other mentions in the text",
        )

    def add_input_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("text", nargs="?", help="text to process; omit to read stdin")
        p.add_argument("-f", "--file", help="read the text from a file instead")
        add_config_args(p)

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

    config_cmd = sub.add_parser("config", help="show the settings that would be used")
    add_config_args(config_cmd)
    config_cmd.add_argument("--json", action="store_true", help="emit JSON")
    sub.add_parser("demo", help="run a full round trip on a sample text")

    evaluate_cmd = sub.add_parser("eval", help="score the detectors against labelled data")
    evaluate_cmd.add_argument(
        "-d", "--dataset", metavar="PATH", help="dataset file; omit to use the bundled ones"
    )
    evaluate_cmd.add_argument(
        "-l", "--locale", metavar="CODE", help="restrict to the bundled datasets for one locale"
    )
    evaluate_cmd.add_argument(
        "--match",
        choices=[mode.value for mode in MatchMode],
        default=MatchMode.OVERLAP.value,
        help="how closely a detection must line up with a label (default: overlap)",
    )
    evaluate_cmd.add_argument(
        "--min-confidence",
        type=float,
        default=0.0,
        metavar="F",
        help="drop detections below this confidence before scoring",
    )
    evaluate_cmd.add_argument(
        "--show-leaks",
        action="store_true",
        help="list the samples that leaked, worst first",
    )
    evaluate_cmd.add_argument("--json", action="store_true", help="emit JSON")

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


def _settings_from(args: argparse.Namespace) -> MamoriConfig:
    """Layer the settings: defaults, then file, then environment, then flags.

    Later layers win, so a shared config file can be checked in and one machine
    or one invocation can still differ without editing it.
    """
    settings = MamoriConfig()
    path = getattr(args, "config", None)
    if path:
        settings = settings.merged_with(load_config_file(Path(path)))
    settings = settings.merged_with(MamoriConfig.from_env())

    changes: dict[str, object] = {}
    if getattr(args, "locale", None):
        changes["locales"] = tuple(args.locale)
    if getattr(args, "min_confidence", None) is not None:
        changes["min_confidence"] = args.min_confidence
    if getattr(args, "no_co_occurrence", False):
        changes["co_occurrence"] = False
    return settings.replace(**changes) if changes else settings


def _cmd_config(args: argparse.Namespace) -> int:
    settings = _settings_from(args)
    if args.json:
        print(json.dumps(_settings_as_json(settings), ensure_ascii=False, indent=2))
        return _EXIT_OK

    print("effective settings\n")
    print(f"  locales                      {', '.join(settings.locales or ['(all)'])}")
    print(f"  default action               {settings.default_action.value}")
    print(f"  min confidence               {settings.min_confidence}")
    print(f"  co-occurrence                {'on' if settings.co_occurrence else 'off'}")
    print(f"  co-occurrence min confidence {settings.co_occurrence_min_confidence}")
    print(f"  mask token                   {settings.mask_token}")
    if settings.rules:
        print("\n  rules")
        for name, action in sorted(settings.rules.items()):
            print(f"    {name:<20} {action.value}")
    print(
        "\nLayered: built-in defaults, then --config, then MAMORI_* environment\n"
        "variables, then the flags on this command line. Later wins."
    )
    return _EXIT_OK


def _settings_as_json(settings: MamoriConfig) -> dict[str, object]:
    return {
        "locales": list(settings.locales) if settings.locales else None,
        "rules": {name: action.value for name, action in settings.rules.items()},
        "category_defaults": {
            category.value: action.value for category, action in settings.category_defaults.items()
        },
        "default_action": settings.default_action.value,
        "min_confidence": settings.min_confidence,
        "co_occurrence": settings.co_occurrence,
        "co_occurrence_min_confidence": settings.co_occurrence_min_confidence,
        "mask_token": settings.mask_token,
    }


def _cmd_inspect(args: argparse.Namespace) -> int:
    text = _read_input(args.text, args.file)
    settings = _settings_from(args)
    # Inspection must report on credentials rather than refuse, so it uses a
    # permissive policy. It never prints a protected text, so nothing here is
    # a step towards sending anything.
    policy = PrivacyPolicy.permissive().with_min_confidence(settings.min_confidence)
    with PrivacySession(config=settings, policy=policy) as session:
        result = session.protect(text)
        if args.json:
            print(json.dumps({"entities": _reports_as_json(result)}, ensure_ascii=False, indent=2))
        else:
            _print_reports(result)
    return _EXIT_OK


def _cmd_protect(args: argparse.Namespace) -> int:
    text = _read_input(args.text, args.file)
    settings = _settings_from(args)
    policy = (
        PrivacyPolicy.permissive().with_min_confidence(settings.min_confidence)
        if args.permissive
        else settings.policy()
    )
    store = InMemoryMappingStore()
    session = PrivacySession(config=settings, policy=policy, store=store)
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


def _report_as_json(report: EvaluationReport) -> dict[str, object]:
    return {
        "dataset": report.dataset,
        "locale": report.locale,
        "match": report.match_mode.value,
        "leak_rate": report.leak_rate,
        "over_redaction_rate": report.over_redaction_rate,
        "precision": report.overall.precision,
        "recall": report.overall.recall,
        "f1": report.overall.f1,
        "samples": len(report.samples),
        "clean_samples": report.clean_samples,
        "by_type": {
            name: {
                "support": score.support,
                "precision": score.precision,
                "recall": score.recall,
                "f1": score.f1,
            }
            for name, score in report.by_type.items()
        },
        "leaking_samples": [
            {"id": sample.sample_id, "leaked_characters": sample.leaked_characters}
            for sample in report.leaking_samples()
        ],
    }


def _print_report(report: EvaluationReport, show_leaks: bool) -> None:
    print(f"{report.dataset}  ({report.locale}, {len(report.samples)} samples)")
    print(
        f"  leak rate           {report.leak_rate:>7.2%}"
        f"   ({report.leaked_characters}/{report.sensitive_characters} sensitive chars"
        " left uncovered)"
    )
    print(
        f"  over-redaction      {report.over_redaction_rate:>7.2%}"
        f"   ({report.over_redacted_characters}/{report.ordinary_characters} ordinary chars"
        " replaced)"
    )
    print(
        f"  entity P / R / F1   {report.overall.precision:.3f} / "
        f"{report.overall.recall:.3f} / {report.overall.f1:.3f}"
        f"   (match: {report.match_mode.value})"
    )
    print(f"  clean samples       {report.clean_samples}/{len(report.samples)}\n")

    width = max((len(name) for name in report.by_type), default=4)
    print(f"  {'type':<{width}}  {'n':>4}  {'prec':>6}  {'rec':>6}  {'f1':>6}")
    for name, score in report.by_type.items():
        print(
            f"  {name:<{width}}  {score.support:>4}  {score.precision:>6.3f}"
            f"  {score.recall:>6.3f}  {score.f1:>6.3f}"
        )

    leaking = report.leaking_samples()
    if show_leaks and leaking:
        print("\n  leaked:")
        for sample in leaking:
            types = ", ".join(sorted({a.entity_type for a in sample.missed})) or "partial span"
            print(f"    {sample.sample_id}  {sample.leaked_characters:>3} chars  {types}")
    print()


def _cmd_eval(args: argparse.Namespace) -> int:
    datasets: tuple[Dataset, ...]
    if args.dataset:
        datasets = (Dataset.load(Path(args.dataset)),)
    else:
        datasets = bundled_datasets(args.locale)
    if not datasets:
        print("no datasets matched", file=sys.stderr)
        return _EXIT_ERROR

    reports = [
        evaluate(
            dataset,
            match=MatchMode(args.match),
            min_confidence=args.min_confidence,
        )
        for dataset in datasets
    ]

    if args.json:
        print(json.dumps([_report_as_json(r) for r in reports], ensure_ascii=False, indent=2))
        return _EXIT_OK

    for report in reports:
        _print_report(report, args.show_leaks)
    print(
        "leak rate is the share of labelled sensitive characters that no detection\n"
        "covered -- the part that would have left the machine. Over-redaction is what\n"
        "it cost in ordinary text. Neither number is meaningful without the other."
    )
    return _EXIT_OK


_COMMANDS = {
    "inspect": _cmd_inspect,
    "protect": _cmd_protect,
    "restore": _cmd_restore,
    "policy": _cmd_policy,
    "config": _cmd_config,
    "locales": _cmd_locales,
    "demo": _cmd_demo,
    "eval": _cmd_eval,
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
