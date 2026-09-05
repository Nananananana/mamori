"""Command line interface.

    mamori inspect  -- what would be detected, and nothing else
    mamori protect  -- print the text that is safe to send
    mamori restore  -- put the values back into a response
    mamori policy   -- show the active policy
    mamori locales  -- show the language packs and when each one runs
    mamori config   -- show the settings that would be used, and where from
    mamori prompt   -- show exactly what would be sent to a model
    mamori llm      -- where the model is, and whether it answers
    mamori serve    -- an OpenAI-compatible endpoint that protects as it forwards
    mamori lint     -- values in files that should not have been committed
    mamori privacy  -- what this configuration actually does with your data
    mamori trace    -- why something was replaced, and why something was not
    mamori correct  -- rule on a value the detectors got wrong
    mamori eval     -- score the detectors against labelled data
    mamori demo     -- a full round trip in one process

``inspect`` is the command to reach for first. It answers "what is in this
file?" without producing an artefact anyone can paste anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from ... import __version__
from ...application.results import ProtectionResult, RestorationResult
from ...application.session import PrivacySession
from ...config import MamoriConfig, discover_config, load_config_file
from ...domain.entity_types import BUILTIN_TYPES
from ...domain.policy import PrivacyPolicy
from ...domain.stance import Stance
from ...errors import ConfigurationError, MamoriError, PolicyViolationError
from ...evaluation import (
    CachedProvider,
    Comparison,
    Dataset,
    EvaluationReport,
    MatchMode,
    bundled_datasets,
    compare,
    evaluate,
)
from ...infrastructure.audit import JsonlAuditSink
from ...infrastructure.detectors import (
    available_locales,
    available_nlp_algorithms,
    available_phone_algorithms,
    available_secret_algorithms,
)
from ...infrastructure.storage import InMemoryMappingStore
from ...infrastructure.storage.encrypted import (
    DEFAULT_KEY_VARIABLE,
    generate_key,
    read_encrypted_scope,
    write_encrypted_scope,
)
from ...infrastructure.storage.jsonfile import PLAINTEXT_WARNING, dump_scope, load_scope
from ...ports.detector import Detector
from ...prompts.library import EXTERNAL_PROMPT_ID
from ...provenance import ProtectionLedger, restoration_record
from .bench import SHAPES, run_bench
from .demo import SCENARIOS, LiveSettings, run_demo
from .explain import audit_rules, trace_text

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
            "-c",
            "--config",
            metavar="PATH",
            help=(
                "settings file (.json, or .toml on 3.11+). Omit it and mamori "
                "looks for mamori.toml, .mamori.toml, mamori.json, .mamori.json "
                "or a [tool.mamori] table in pyproject.toml, walking up from the "
                "working directory and stopping at the repository root"
            ),
        )
        p.add_argument(
            "--no-config",
            action="store_true",
            help="ignore any discovered settings file; use defaults, environment and flags only",
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
        p.add_argument(
            "--stance",
            choices=[stance.value for stance in Stance],
            help=(
                "which rule tiers run. recall_first (the default) adds rules that "
                "match on shape alone: fewer misses, more ordinary words replaced"
            ),
        )
        p.add_argument(
            "--secrets",
            choices=list(available_secret_algorithms()),
            help=(
                "which algorithm looks for credentials the pattern rules cannot "
                "name. patterns (the default) adds nothing; entropy also flags "
                "long evenly-spread runs -- bare hex keys, and also commit ids and "
                "base64 payloads -- as API_KEY, which the default policy blocks"
            ),
        )

        p.add_argument(
            "--nlp",
            choices=list(available_nlp_algorithms()),
            help=(
                "which recogniser looks for a personal name with no anchor beside "
                "it. none (the default) adds nothing; spacy runs a named-entity "
                "model after the rules and needs mamori[nlp] and a model"
            ),
        )
        p.add_argument(
            "--phone",
            choices=list(available_phone_algorithms()),
            help=(
                "how a run of digits becomes a telephone number. patterns (the "
                "default) matches shapes; phonenumbers reads it against real "
                "numbering plans and needs mamori[phone]"
            ),
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
        "--encrypt-mapping",
        metavar="PATH",
        help=(
            "write the mapping encrypted instead. Needs a key in "
            f"{DEFAULT_KEY_VARIABLE}; `mamori keygen` prints one. Never reads "
            "the key from a settings file"
        ),
    )
    protect.add_argument(
        "--audit",
        metavar="PATH",
        help=(
            "append a mamori.protection-scope record to PATH, one JSON line per "
            "run. Holds no protected value -- but it describes documents that "
            "do, so give it the classification of those documents and not of a "
            "log directory"
        ),
    )
    protect.add_argument(
        "--audit-by",
        metavar="NAME/VERSION",
        help=(
            "what to write in the record's 'by' field. Defaults to this mamori. "
            "Set it when the record should name the pipeline rather than the "
            "library, e.g. billing-import/2.1"
        ),
    )
    protect.add_argument(
        "--permissive",
        action="store_true",
        help="anonymize everything instead of blocking credentials",
    )

    restore = sub.add_parser("restore", help="put original values back into a response")
    add_input_args(restore)
    restore.add_argument("--mapping", required=True, metavar="PATH", help="mapping file")
    restore.add_argument(
        "--encrypted",
        action="store_true",
        help=(f"the mapping file is encrypted; read the key from {DEFAULT_KEY_VARIABLE}"),
    )
    restore.add_argument(
        "--audit",
        metavar="PATH",
        help=(
            "append a mamori.restoration-scope record to PATH, one JSON line "
            "per run -- the return half of what `protect --audit` writes. Join "
            "them on the scope and you have the lineage of one round trip. "
            "Holds no restored value, and inherits the classification of the "
            "documents it describes, exactly like the other half"
        ),
    )
    restore.add_argument(
        "--audit-by",
        metavar="NAME/VERSION",
        help="what to write in the record's 'by' field. Defaults to this mamori",
    )
    restore.add_argument(
        "--json",
        action="store_true",
        help=(
            "print the restored text and the same record `--audit` would "
            "write, as one object, for a caller that has to act on the "
            "difference between recovered, altered and never-allocated"
        ),
    )

    sub.add_parser(
        "keygen",
        help="print a new key for the encrypted mapping store, and stop",
    )

    sub.add_parser("policy", help="show the active policy")
    sub.add_parser("locales", help="show the language packs and when each runs")

    config_cmd = sub.add_parser("config", help="show the settings that would be used")
    add_config_args(config_cmd)
    config_cmd.add_argument("--json", action="store_true", help="emit JSON")

    prompt_cmd = sub.add_parser("prompt", help="show exactly what would be sent to a model")
    prompt_cmd.add_argument(
        "name",
        nargs="?",
        default=EXTERNAL_PROMPT_ID,
        help="prompt id: external (for the service model) or detection (for a local one)",
    )
    add_config_args(prompt_cmd)
    prompt_cmd.add_argument(
        "--guidance",
        action="store_true",
        help="list the guidance ids instead of the text, so they can be disabled",
    )

    llm_cmd = sub.add_parser("llm", help="where the model is, and whether it answers")
    add_config_args(llm_cmd)
    llm_cmd.add_argument(
        "--check",
        action="store_true",
        help="ask the endpoint whether it is there; worth running once after "
        "pointing this at a server on another machine",
    )
    llm_cmd.add_argument("--json", action="store_true", help="emit JSON")

    serve_cmd = sub.add_parser(
        "serve", help="an OpenAI-compatible endpoint that protects what passes through"
    )
    add_config_args(serve_cmd)
    serve_cmd.add_argument(
        "--upstream",
        required=True,
        help="the service your application calls today, e.g. https://api.openai.com/v1/",
    )
    serve_cmd.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address. The default accepts connections from this machine only; "
        "anything that can reach this port can send documents through it",
    )
    serve_cmd.add_argument("--port", type=int, default=8100, help="bind port (default 8100)")
    serve_cmd.add_argument(
        "--no-guidance",
        action="store_true",
        help="do not prepend the briefing that tells the model to leave placeholders alone",
    )
    serve_cmd.add_argument("--quiet", action="store_true", help="do not print a line per request")
    serve_cmd.add_argument(
        "--conversations",
        action="store_true",
        help="keep mappings between requests for clients that ask, so a reply "
        "about <PERSON_001> can still be restored when the client sent only "
        "the new turn. Off by default: the default holds nothing at all",
    )
    serve_cmd.add_argument(
        "--conversation-idle",
        type=float,
        default=30.0,
        metavar="MINUTES",
        help="discard a conversation after this long untouched (default 30)",
    )
    serve_cmd.add_argument(
        "--max-conversations",
        type=int,
        default=64,
        metavar="N",
        help="how many conversations may be held at once (default 64)",
    )

    lint_cmd = sub.add_parser(
        "lint", help="find values in files that should not have been committed"
    )
    add_config_args(lint_cmd)
    lint_cmd.add_argument(
        "paths", nargs="*", default=["."], help="files or directories (default: .)"
    )
    lint_cmd.add_argument(
        "--fail-on",
        choices=["credential", "any", "never"],
        default="credential",
        help="what makes this exit non-zero. 'credential' (the default) fails on a "
        "secret and reports the rest: a leaked key is an incident, a name in a "
        "fixture is a decision somebody should make on purpose, and a linter that "
        "fails on both teaches people to skip it",
    )
    lint_cmd.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="skip paths matching this, repeatable",
    )
    lint_cmd.add_argument(
        "--types",
        default="",
        metavar="A,B",
        help="only report these entity types",
    )
    lint_cmd.add_argument(
        "--max-bytes",
        type=int,
        default=1_000_000,
        help="skip files larger than this (default 1000000)",
    )
    lint_cmd.add_argument("--verbose", action="store_true", help="list what was skipped")
    lint_cmd.add_argument("--json", action="store_true", help="emit JSON")

    privacy_cmd = sub.add_parser(
        "privacy", help="what this configuration actually does with your data"
    )
    add_config_args(privacy_cmd)
    privacy_cmd.add_argument(
        "--upstream", help="a proxy destination, to include it in the destinations"
    )
    privacy_cmd.add_argument("--json", action="store_true", help="emit JSON")

    trace_cmd = sub.add_parser(
        "trace", help="why something was replaced, and why something else was not"
    )
    add_config_args(trace_cmd)
    trace_cmd.add_argument("text", nargs="?", help="the text to explain")
    trace_cmd.add_argument("-f", "--file", help="read the text from a file")
    trace_cmd.add_argument("--json", action="store_true", help="emit JSON")

    audit_cmd = sub.add_parser(
        "audit", help="which rules carry the load, and which never fire at all"
    )
    add_config_args(audit_cmd)
    audit_cmd.add_argument("-f", "--file", help="audit against a file of your own")
    audit_cmd.add_argument(
        "-d", "--dataset", metavar="PATH", help="audit against a labelled dataset"
    )
    audit_cmd.add_argument(
        "--dead", action="store_true", help="list only the rules that never fired"
    )
    audit_cmd.add_argument("--json", action="store_true", help="emit JSON")

    correct_cmd = sub.add_parser("correct", help="rule on a value the detectors got wrong")
    add_config_args(correct_cmd)
    correct_cmd.add_argument("value", help="the value being ruled on")
    verdict = correct_cmd.add_mutually_exclusive_group(required=True)
    verdict.add_argument(
        "--never",
        action="store_true",
        help="this value is not sensitive here. The only setting that reduces "
        "what mamori protects, so it is logged and reported. A credential "
        "cannot be ruled this way",
    )
    verdict.add_argument(
        "--always",
        metavar="TYPE",
        help="this value is sensitive here, of this type, wherever it appears",
    )
    correct_cmd.add_argument("--note", default="", help="why. Worth writing")
    correct_cmd.add_argument(
        "--log",
        metavar="PATH",
        help="the log to append to. Defaults to the 'corrections' path in your settings",
    )

    corrections_cmd = sub.add_parser(
        "corrections", help="show what has been ruled on, and what it costs"
    )
    add_config_args(corrections_cmd)
    corrections_cmd.add_argument("--json", action="store_true", help="emit JSON")
    demo_cmd = sub.add_parser("demo", help="see it work, on the sample text or on yours")
    add_config_args(demo_cmd)
    demo_cmd.add_argument("--text", help="run the tour on your own text")
    demo_cmd.add_argument("-f", "--file", help="run the tour on a file")
    demo_cmd.add_argument(
        "--scenario",
        action="append",
        choices=sorted(SCENARIOS),
        help="just one part of the tour; repeatable",
    )
    demo_cmd.add_argument(
        "--live",
        action="store_true",
        help="actually send the protected prompt to a model and restore its "
        "answer. Needs --model and --api",
    )
    demo_cmd.add_argument("--model", help="model name, for --live")
    demo_cmd.add_argument(
        "--api",
        metavar="URL",
        help="the service to ask, for --live, e.g. http://localhost:11434/v1/",
    )
    demo_cmd.add_argument(
        "--api-key-env",
        metavar="NAME",
        help="environment variable holding the key for --api, if it needs one",
    )
    demo_cmd.add_argument("--json", action="store_true", help="emit JSON")

    bench_cmd = sub.add_parser(
        "bench", help="how fast this configuration is on this machine, measured"
    )
    add_config_args(bench_cmd)
    bench_cmd.add_argument(
        "--shape",
        action="append",
        choices=sorted(SHAPES),
        help="one document shape; repeatable. Omit for all of them",
    )
    bench_cmd.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="runs per measurement; the best is kept, since noise only ever adds time",
    )
    bench_cmd.add_argument("--json", action="store_true", help="rows as JSON")

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
        "--stance",
        choices=[stance.value for stance in Stance],
        help=(
            "which rule tiers to score. Omit to use the stance in --config, or "
            "recall_first when there is none"
        ),
    )
    evaluate_cmd.add_argument(
        "--show-leaks",
        action="store_true",
        help="list the samples that leaked, worst first",
    )
    evaluate_cmd.add_argument(
        "-c",
        "--config",
        metavar="PATH",
        dest="config",
        help="settings file, so a configured model is included in the run",
    )
    evaluate_cmd.add_argument(
        "--compare",
        action="store_true",
        help="score the rules alone as well, and print what the model changed. "
        "A single number says nothing: the question is what it caught and what "
        "that cost",
    )
    evaluate_cmd.add_argument(
        "--cache",
        metavar="PATH",
        help="remember what the model answered, so the run can be repeated. "
        "The prompt is part of the key, so rewriting guidance invalidates "
        "exactly the answers that depended on it. Writes to disk",
    )
    evaluate_cmd.add_argument(
        "--replay",
        action="store_true",
        help="answer only from --cache and never call the model. Checks a "
        "scoring change without the model's variance in the way",
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


def _config_path(args: argparse.Namespace) -> Path | None:
    """The settings file this invocation reads, or ``None``.

    ``--config`` wins and is an error if it is missing or unreadable: the
    caller named it. Discovery is a search, so finding nothing is not an error,
    and neither is a `pyproject.toml` that belongs to some other tool.
    """
    named = getattr(args, "config", None)
    if named:
        return Path(named)
    if getattr(args, "no_config", False):
        return None
    return discover_config()


def _settings_from(args: argparse.Namespace) -> MamoriConfig:
    """Layer the settings: defaults, then file, then environment, then flags.

    Later layers win, so a shared config file can be checked in and one machine
    or one invocation can still differ without editing it.
    """
    settings = MamoriConfig()
    path = _config_path(args)
    if path is not None:
        settings = settings.merged_with(load_config_file(path))
    settings = settings.merged_with(MamoriConfig.from_env())

    changes: dict[str, object] = {}
    if getattr(args, "locale", None):
        changes["locales"] = tuple(args.locale)
    if getattr(args, "min_confidence", None) is not None:
        changes["min_confidence"] = args.min_confidence
    if getattr(args, "no_co_occurrence", False):
        changes["co_occurrence"] = False
    if getattr(args, "stance", None):
        changes["stance"] = Stance(args.stance)
    if getattr(args, "secrets", None):
        changes["secrets"] = args.secrets
    if getattr(args, "nlp", None):
        changes["nlp"] = args.nlp
    if getattr(args, "phone", None):
        changes["phone"] = args.phone
    return settings.replace(**changes) if changes else settings


def _cmd_config(args: argparse.Namespace) -> int:
    settings = _settings_from(args)
    if args.json:
        print(json.dumps(_settings_as_json(settings), ensure_ascii=False, indent=2))
        return _EXIT_OK

    print("effective settings\n")
    print(f"  locales                      {', '.join(settings.locales or ['(all)'])}")
    print(f"  stance                       {settings.stance.value}")
    print(f"  secrets                      {settings.secrets}")
    print(f"  nlp                          {settings.nlp}")
    print(f"  phone                        {settings.phone}")
    print(f"  default action               {settings.default_action.value}")
    print(f"  min confidence               {settings.min_confidence}")
    print(f"  co-occurrence                {'on' if settings.co_occurrence else 'off'}")
    print(f"  co-occurrence min confidence {settings.co_occurrence_min_confidence}")
    print(f"  mask token                   {settings.mask_token}")
    print(f"  below min confidence         {settings.uncertain}")
    print(f"  placeholder style            {settings.placeholder_style}")
    surrogates = settings.surrogates
    shown = (
        ("all" if surrogates else "off")
        if isinstance(surrogates, bool)
        else ", ".join(surrogates) or "off"
    )
    print(f"  surrogates                   {shown}")
    if settings.corrections:
        where = (
            settings.corrections
            if isinstance(settings.corrections, str)
            else f"{len(settings.corrections)} inline"
        )
        print(f"  corrections                  {where}")
    if settings.llm is not None and settings.llm.model:
        model = f"{settings.llm.model} at {settings.llm.base_url}"
    else:
        model = "(none -- patterns only)"
    print(f"  model                        {model}")
    if settings.rules:
        print("\n  rules")
        for name, action in sorted(settings.rules.items()):
            print(f"    {name:<20} {action.value}")
    print()
    path = _config_path(args)
    if path is None:
        print("  settings file                (none found)")
    else:
        how = "named with --config" if getattr(args, "config", None) else "discovered"
        print(f"  settings file                {path} ({how})")
    print(
        "\nLayered: built-in defaults, then the settings file, then MAMORI_*\n"
        "environment variables, then the flags on this command line. Later\n"
        "wins. Discovery walks up from the working directory and stops at the\n"
        "repository root, so a file outside the project never applies."
    )
    return _EXIT_OK


def _settings_as_json(settings: MamoriConfig) -> dict[str, object]:
    return {
        "locales": list(settings.locales) if settings.locales else None,
        "stance": settings.stance.value,
        "secrets": settings.secrets,
        "nlp": settings.nlp,
        "phone": settings.phone,
        "rules": {name: action.value for name, action in settings.rules.items()},
        "category_defaults": {
            category.value: action.value for category, action in settings.category_defaults.items()
        },
        "default_action": settings.default_action.value,
        "min_confidence": settings.min_confidence,
        "co_occurrence": settings.co_occurrence,
        "co_occurrence_min_confidence": settings.co_occurrence_min_confidence,
        "mask_token": settings.mask_token,
        "llm": settings.llm.as_mapping() if settings.llm is not None else None,
        # Four settings `mamori config --json` never showed. A view of the
        # effective settings that omits `uncertain` is one that cannot tell an
        # operator whether the refusal they configured is in force.
        "uncertain": settings.uncertain,
        "placeholder_style": settings.placeholder_style,
        "surrogates": (
            settings.surrogates
            if isinstance(settings.surrogates, bool)
            else list(settings.surrogates)
        ),
        "corrections": (
            settings.corrections
            if isinstance(settings.corrections, str)
            else [dict(entry) for entry in settings.corrections]
        ),
    }


def _cmd_correct(args: argparse.Namespace) -> int:
    from ...domain.corrections import Correction, Verdict
    from ...infrastructure.storage.corrections import append_correction

    settings = _settings_from(args)
    path = args.log or (settings.corrections if isinstance(settings.corrections, str) else None)
    if not path:
        print(
            "no correction log to append to. Give --log PATH, or put a "
            '"corrections" path in your settings.',
            file=sys.stderr,
        )
        return _EXIT_ERROR

    if args.never:
        refusal = _credential_refusal(settings, args.value)
        if refusal:
            print(refusal, file=sys.stderr)
            return _EXIT_ERROR

    try:
        correction = Correction(
            value=args.value,
            verdict=Verdict.NEVER if args.never else Verdict.ALWAYS,
            entity_type=args.always or "",
            note=args.note,
            recorded_at=_today(),
        )
        log = append_correction(Path(path), correction)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_ERROR

    verdict = "never sensitive" if args.never else f"always {args.always}"
    print(f"recorded: {args.value!r} is {verdict}")
    print(f"  log     {path} ({len(log)} entr{'y' if len(log) == 1 else 'ies'})")
    if args.never:
        print()
        print("This reduces what mamori protects. It is reported by 'mamori privacy'")
        print("and undone by recording the opposite -- nothing is deleted.")
    return _EXIT_OK


def _credential_refusal(settings: MamoriConfig, value: str) -> str:
    """Refuse to write a credential into a correction log.

    The domain refuses an exclusion that *names* a credential type, but a
    ``never`` ruling names no type at all -- the operator is saying "this value
    is not sensitive", not "this password is not a password". So the value is
    run through the detectors here, before anything is written.

    That ordering matters more than the refusal. Appending first and rejecting
    at read time would leave the credential sitting in a file on disk, which is
    the outcome this whole library exists to avoid.
    """
    from ...domain.corrections import PROTECTED_CATEGORIES

    try:
        detected = [
            entity
            for detector in settings.detectors()
            for entity in detector.detect(value)
            if entity.entity_type.category in PROTECTED_CATEGORIES
        ]
    except MamoriError:
        return ""  # a broken configuration is reported by the command itself

    if not detected:
        return ""
    names = ", ".join(sorted({e.entity_type.name for e in detected}))
    return (
        f"error: that value looks like a credential ({names}), and a credential "
        "cannot be ruled 'never'.\n"
        "Nothing was written -- recording it would have put the credential in a "
        "file on disk.\n"
        "A credential ruled not sensitive is a credential in somebody's prompt. "
        "Rotate it instead."
    )


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def _cmd_corrections(args: argparse.Namespace) -> int:
    settings = _settings_from(args)
    log = settings.correction_log()

    if args.json:
        print(json.dumps(log.as_mapping(), ensure_ascii=False, indent=2))
        return _EXIT_OK

    if not log:
        print("nothing has been ruled on.")
        print()
        print("When a detector gets a value wrong, say so:")
        print("  mamori correct Monday --never --note 'a weekday, not a name'")
        print("  mamori correct Acme --always COMPANY_NAME")
        return _EXIT_OK

    excluded = log.excluded()
    added = log.added()

    if excluded:
        print(f"Not sensitive here ({len(excluded)})")
        print()
        print("  These are no longer protected. This is the only thing in mamori")
        print("  that reduces coverage.")
        print()
        for correction in sorted(excluded, key=lambda c: c.value):
            print(f"    {correction.value}")
            if correction.note:
                print(f"      {correction.note}")
        print()

    if added:
        print(f"Sensitive here, whatever the rules think ({len(added)})")
        print()
        for correction in sorted(added, key=lambda c: c.value):
            print(f"    {correction.value}  -> {correction.entity_type}")
            if correction.note:
                print(f"      {correction.note}")
        print()

    superseded = len(log) - len(log.current())
    print(f"{len(log)} entr{'y' if len(log) == 1 else 'ies'} in the log", end="")
    print(f", {superseded} superseded" if superseded else "")
    print("The latest ruling about a value wins. Nothing is ever deleted.")
    return _EXIT_OK


def _cmd_trace(args: argparse.Namespace) -> int:
    text = _read_input(args.text, args.file)
    return trace_text(_settings_from(args), text, as_json=args.json)


#: Types the bundled datasets deliberately never contain. A literal
#: vendor-prefixed credential in a file that ships inside the wheel trips the
#: secret scanner of everybody who clones the repository, so those rules are
#: tested with fixtures assembled at runtime instead. An audit that reported
#: them as dead alongside genuinely dead rules would bury the real finding.
_NEVER_IN_A_DATASET = frozenset({"API_KEY", "ACCESS_TOKEN", "PRIVATE_KEY"})


def _cmd_audit(args: argparse.Namespace) -> int:
    settings = _settings_from(args)
    texts: list[str]
    what: str
    if args.file:
        texts = [Path(args.file).read_text(encoding="utf-8")]
        what = args.file
    elif args.dataset:
        texts = [sample.text for sample in Dataset.load(Path(args.dataset))]
        what = args.dataset
    else:
        texts = [sample.text for dataset in bundled_datasets() for sample in dataset]
        what = f"the {len(bundled_datasets())} bundled datasets"

    usage = audit_rules(texts, settings.locales or None)
    dead = [u for u in usage if u.dead]

    if args.json:
        print(
            json.dumps(
                {
                    "audited": what,
                    "texts": len(texts),
                    "rules": len(usage),
                    "never_fired": len(dead),
                    "usage": [
                        {
                            "rule": u.identifier,
                            "entity_type": u.entity_type,
                            "tier": u.tier,
                            "matches": u.matches,
                        }
                        for u in usage
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return _EXIT_OK

    print(f"{len(usage)} rules over {len(texts)} text(s) -- {what}")
    print()

    if not args.dead:
        print("What fired")
        print()
        for entry in usage[:20]:
            if entry.dead:
                break
            print(f"  {entry.matches:>6}  {entry.identifier:<28}{entry.tier}")
        print()

    expected = [e for e in dead if e.entity_type in _NEVER_IN_A_DATASET]
    unexplained = [e for e in dead if e.entity_type not in _NEVER_IN_A_DATASET]

    print(f"Never fired ({len(dead)} of {len(usage)})")
    print()
    for entry in unexplained:
        print(f"          {entry.identifier:<28}{entry.tier}")
    if not unexplained:
        print("          (none without an explanation)")

    if expected:
        print()
        print(f"  and {len(expected)} credential rule(s), which is expected here:")
        print("  a literal vendor-prefixed key in a shipped dataset trips the secret")
        print("  scanner of everyone who clones the repository, so the datasets")
        print("  deliberately contain none. Those rules are covered by")
        print("  tests/test_detectors.py, which assembles the fixtures at runtime.")

    print()
    print("A rule that never fires is either dead or waiting for data nobody has.")
    print("Neither is automatically a bug, and both are worth knowing. Run this")
    print("against your own text with --file to see which rules matter to you.")
    return _EXIT_OK


def _cmd_lint(args: argparse.Namespace) -> int:
    """Scan files, and decide whether what was found should stop a build."""
    from pathlib import Path

    from .linting import lint_paths, report

    paths = [Path(p) for p in args.paths]
    missing = [p for p in paths if not p.exists()]
    if missing:
        for path in missing:
            print(f"error: no such path: {path}", file=sys.stderr)
        return _EXIT_ERROR

    findings, skipped = lint_paths(
        _settings_from(args),
        paths,
        exclude=args.exclude,
        max_bytes=args.max_bytes,
        types=[t for t in args.types.split(",") if t],
    )
    root = paths[0] if len(paths) == 1 and paths[0].is_dir() else None
    report(findings, skipped, root=root, as_json=args.json, verbose=args.verbose)

    if args.fail_on == "never" or not findings:
        return _EXIT_OK
    if args.fail_on == "any":
        return _EXIT_BLOCKED
    return _EXIT_BLOCKED if any(f.is_credential for f in findings) else _EXIT_OK


def _cmd_privacy(args: argparse.Namespace) -> int:
    from ...report import build_report

    report = build_report(_settings_from(args), upstream=args.upstream)

    if args.json:
        print(json.dumps(report.as_mapping(), ensure_ascii=False, indent=2))
        return _EXIT_ERROR if report.warnings else _EXIT_OK

    detection = report.detection
    locales = detection["locales"]
    print("What is detected")
    print()
    print(f"  languages       {', '.join(locales) if isinstance(locales, list) else locales}")
    print(f"  stance          {detection['stance']}")
    print(f"  secrets         {detection['secrets']}")
    print(f"  names           {detection['nlp']}")
    print(f"  phone           {detection['phone']}")
    print(f"  minimum conf.   {detection['minimum_confidence']}")
    print(f"  below that      {detection['uncertain']}")
    print(f"  placeholders    {detection['placeholder_style']} brackets")
    for action, names in sorted(detection["by_action"].items()):
        shown = ", ".join(names[:6]) + (", ..." if len(names) > 6 else "")
        print(f"  {action:<15} {len(names)} types: {shown}")

    print()
    print("Where your text goes")
    print()
    for destination in report.destinations:
        print(f"  {destination['what']}")
        print(f"    address       {destination['where'] or '(nowhere)'}")
        print(f"    it sees       {destination['sees']}")
        print(f"    why           {destination['why']}")
        if destination.get("admitted") is False:
            print("    status        REFUSED -- outside the trust boundary")
        print()

    print("What is kept")
    print()
    print(f"  mappings        {report.storage['mappings']}")
    print(f"  retention       {report.storage['retention']}")
    print(f"  on disk         {'yes' if report.storage['written_to_disk'] else 'no'}")
    print(f"  {report.storage['note']}")

    print()
    print("True however this is configured")
    print()
    for claim in report.by_construction:
        print(f"  - {claim.text}")
        print(f"    checked by {claim.checked_by}")

    print()
    print("What mamori cannot check for you")
    print()
    for claim in report.your_responsibility:
        print(f"  - {claim.text}")

    if report.warnings:
        print()
        print("Warnings")
        print()
        for warning in report.warnings:
            print(f"  ! {warning}")
        return _EXIT_ERROR
    return _EXIT_OK


def _cmd_serve(args: argparse.Namespace) -> int:
    from ...application.conversations import ConversationRegistry
    from ..proxy.server import ProxySettings, serve

    config = _settings_from(args)
    registry = None
    if args.conversations:
        if args.conversation_idle <= 0:
            print("error: --conversation-idle must be positive", file=sys.stderr)
            return _EXIT_ERROR
        if args.max_conversations < 1:
            print("error: --max-conversations must be at least 1", file=sys.stderr)
            return _EXIT_ERROR
        registry = ConversationRegistry(
            config.session,
            idle_seconds=args.conversation_idle * 60,
            max_conversations=args.max_conversations,
        )

    settings = ProxySettings(
        upstream=args.upstream,
        host=args.host,
        port=args.port,
        config=config,
        guidance=not args.no_guidance,
        log=None if args.quiet else _serve_log,
        conversations=registry,
    )

    print(f"mamori proxy on {settings.url()}")
    print(f"  upstream        {settings.upstream}")
    locales = ", ".join(settings.config.locales or ()) or "all locales"
    print(f"  detection       {locales}, {settings.config.stance.value}")
    print(f"  briefing        {'prepended' if settings.guidance else 'off'}")
    print()
    print("Point your application at the address above and change nothing else.")
    if registry is None:
        print("Mappings live in memory for one request and are discarded with it.")
    else:
        idle = args.conversation_idle
        print(f"  conversations   held for {idle:g} minute(s) idle, up to {args.max_conversations}")
        print()
        print("Mappings live in memory. A client that echoes the X-Mamori-Session")
        print("header keeps its placeholders across turns; one that does not gets")
        print("a fresh scope per request. Either way nothing is written to disk,")
        print("and everything held is discarded when this process stops.")
    if settings.is_public:
        print()
        print("WARNING: this is bound to a public address. Anything that can reach")
        print("this port can send documents through it and read the restored answers.")
    print()

    try:
        serve(settings)
    except KeyboardInterrupt:
        print("stopped")
    return _EXIT_OK


def _serve_log(message: str) -> None:
    """Counts and types only. A protected value never reaches here."""
    print(f"  {message}", file=sys.stderr)


def _cmd_llm(args: argparse.Namespace) -> int:
    settings = _settings_from(args)
    llm = settings.llm
    if llm is None or not llm.model:
        print("no model configured. Detection is patterns only, which is a complete")
        print("configuration: the rules are the guarantee and a model is the improvement.")
        print()
        print("To use one, on this machine or anywhere on your network:")
        print('  {"llm": {"model": "qwen2.5:7b", "base_url": "http://llm01.corp:8000/v1/"}}')
        return _EXIT_OK

    endpoint = llm.endpoint()
    kind = endpoint.policy.classify(llm.base_url)
    where = "another machine" if endpoint.is_remote else "this machine"
    admitted = endpoint.policy.admits(llm.base_url)

    if args.json:
        payload = dict(llm.as_mapping())
        payload["host_kind"] = kind.value
        payload["is_remote"] = endpoint.is_remote
        payload["admitted"] = admitted
        if args.check and admitted:
            payload["reachable"] = _health(settings)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return _EXIT_OK if admitted else _EXIT_ERROR

    on_failure = "stop the request" if llm.require_model else "carry on with the rules"
    print("model")
    print()
    print(f"  provider        {llm.provider}")
    print(f"  model           {llm.model}")
    print(f"  endpoint        {llm.base_url}")
    print(f"  host            {kind.value} ({where})")
    print(f"  trust boundary  {llm.trust.value}")
    if llm.trusted_hosts:
        print(f"  trusted hosts   {', '.join(sorted(llm.trusted_hosts))}")
    print(f"  api key from    {llm.api_key_env or '(none)'}")
    print(f"  timeout         {llm.timeout}s, {llm.retries} retries")
    print(f"  on failure      {on_failure}")

    if not admitted:
        # Reported here rather than on the first document. This endpoint is
        # refused when the pass is built, and finding that out mid-request is
        # too late to be useful.
        print()
        print("REFUSED. This model will not be used:")
        print()
        for line in endpoint.policy.explain(llm.base_url).splitlines():
            print(f"  {line}")
        return _EXIT_ERROR

    if args.check:
        reachable = _health(settings)
        print()
        print(f"  reachable       {'yes' if reachable else 'NO'}")
        if not reachable:
            print()
            print("The endpoint did not answer. Detection still works, because the rules")
            print("run either way and the model pass degrades to nothing, but nothing is")
            print("gained from the model until this is fixed.")
            return _EXIT_ERROR
    return _EXIT_OK


def _health(settings: MamoriConfig) -> bool:
    """Ask the configured provider whether it is there, if it can say."""
    passes = settings.llm_passes()
    if not passes:
        return False
    check = getattr(passes[0].provider, "health_check", None)
    return bool(check()) if check is not None else False


def _cmd_prompt(args: argparse.Namespace) -> int:
    settings = _settings_from(args)
    library = settings.prompt_library()
    rendered = library.render(args.name, settings.locales)

    if args.guidance:
        prompt = library.get(args.name)
        print(f"{args.name} v{rendered.version}  ({len(prompt.guidance)} guidance rules)\n")
        width = max((len(rule.id) for rule in prompt.guidance), default=4)
        for rule in prompt.guidance:
            locales = ",".join(rule.locales) or "any"
            marker = " " if rule.origin == "builtin" else "*"
            print(f" {marker}{rule.id:<{width}}  {rule.kind.value:<8}  {locales}")
        print(
            "\n* = added by an overlay. Disable any of these with\n"
            '  {"prompts": {"' + args.name + '": {"disable": ["<id>"]}}}'
        )
        return _EXIT_OK

    print(rendered.text)
    print(
        f"-- {args.name} v{rendered.version}, fingerprint {rendered.fingerprint}, "
        f"{len(rendered)} characters, {len(rendered.guidance_ids)} guidance rules",
        file=sys.stderr,
    )
    return _EXIT_OK


def _cmd_inspect(args: argparse.Namespace) -> int:
    text = _read_input(args.text, args.file)
    settings = _settings_from(args)
    # Inspection must report on credentials rather than refuse, so it uses a
    # permissive policy. It never prints a protected text, so nothing here is
    # a step towards sending anything.
    policy = PrivacyPolicy.permissive().with_min_confidence(settings.min_confidence)
    with settings.session(policy=policy) as session:
        result = session.protect(text)
        if args.json:
            print(json.dumps({"entities": _reports_as_json(result)}, ensure_ascii=False, indent=2))
        else:
            _print_reports(result)
    return _EXIT_OK


def _emit(text: str) -> None:
    """Write transformed text to stdout, exactly.

    `print` appends a newline to text that usually already ends with one, so
    every pass through the CLI grew the document by a byte: protect once and it
    has one extra, restore it and it has two. A round trip was not byte-exact,
    and a pipeline of these -- which is what the sibling projects assemble --
    accumulated one per hop.

    That matters beyond tidiness. Downstream tools resolve spans back to byte
    offsets in an original, and a document that gains a trailing byte at every
    stage is a document those offsets are measured against and no longer match.

    So: the text, and nothing else. What came in without a trailing newline
    goes out without one, the way `sed` and `cat` behave, and for the same
    reason -- a filter that adds a byte is not a filter.

    The exception is a terminal, where the missing newline runs the shell
    prompt into the output and there is no pipeline to keep exact. Piped, it is
    byte-for-byte; watched, it is tidy.
    """
    sys.stdout.write(text)
    if text and not text.endswith(chr(10)) and sys.stdout.isatty():
        sys.stdout.write(chr(10))


def _cmd_keygen(_: argparse.Namespace) -> int:
    """Print a key and stop.

    On stdout so it can be captured, with the instructions on stderr so that
    `export MAMORI_MAPPING_KEY=$(mamori keygen)` gets the key and not the
    prose. The key is generated rather than derived from a passphrase: a KDF
    needs a salt and a work factor, and both are somewhere else to be wrong.
    """
    _emit(generate_key())
    print(
        f"\nSet {DEFAULT_KEY_VARIABLE} to this. It is never read from a "
        "settings file, because a settings file ends up in version control. "
        "Store it away from the mapping files it opens.",
        file=sys.stderr,
    )
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
    session = settings.session(policy=policy, store=store)
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

    if args.encrypt_mapping:
        path = Path(args.encrypt_mapping)
        count = write_encrypted_scope(store, session.scope, path)
        print(f"wrote {count} encrypted mappings to {path}", file=sys.stderr)
        print(
            "The key is not in that file. Keep it somewhere the file is not: "
            "a key beside the ciphertext is a decorative lock.",
            file=sys.stderr,
        )

    if args.audit:
        # After the mapping files and before the output. A record saying a
        # protection happened, written once the protection has happened and
        # everything it produced is on disk -- not before, which would record a
        # run that could still fail on the next line.
        #
        # Strict, so a path that cannot be written stops the command. The
        # alternative is a run that prints protected text, exits 0, and leaves
        # nothing in the file the operator turned on in order to have
        # something.
        _ledger(args, recall=settings.stance.value).record(result, session=session)

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
        _emit(result.protected_text)
        if result.entities:
            print(f"\n-- {result.entity_count} value(s) protected", file=sys.stderr)
    return _EXIT_OK


def _ledger(args: argparse.Namespace, *, recall: str | None = None) -> ProtectionLedger:
    """The audit ledger `--audit` asked for, built the same way by both halves.

    Strict, so a path that cannot be written stops the command: a run that
    prints its output, exits 0 and leaves nothing in the file the operator
    turned on in order to have something is worse than one that stops.
    `recall` is passed by `protect` and not by `restore`, because it describes
    how detection ran and the return half must not repeat a fact the outbound
    half already recorded -- two halves of one round trip that could disagree
    about the run that produced them.
    """
    return ProtectionLedger(JsonlAuditSink(Path(args.audit)), by=args.audit_by or "", recall=recall)


def _cmd_restore(args: argparse.Namespace) -> int:
    text = _read_input(args.text, args.file)
    store = InMemoryMappingStore()
    if args.encrypted:
        scope = read_encrypted_scope(store, Path(args.mapping))
    else:
        scope = load_scope(store, Path(args.mapping))
    session = PrivacySession(store=store, scope=scope)
    result: RestorationResult = session.restore(text)

    if args.audit:
        # Before the output, and strict, for the same reason the outbound half
        # is: a command that prints a restored answer, exits 0 and leaves
        # nothing in the file the operator turned on is worse than one that
        # stops.
        _ledger(args).record_restoration(result, scope=scope)

    if args.json:
        # The record itself, not a second rendering of the same facts. Two
        # shapes for one thing drift, and the one that drifts is whichever
        # nothing validates -- this one is checkable against the schema the
        # package ships.
        print(
            json.dumps(
                {
                    "text": result.text,
                    "record": restoration_record(result, scope=scope, by=args.audit_by or ""),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return _EXIT_OK

    _emit(result.text)
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


def _cmd_bench(args: argparse.Namespace) -> int:
    if args.repeats < 1:
        print("error: --repeats must be at least 1", file=sys.stderr)
        return _EXIT_ERROR
    return run_bench(
        _settings_from(args), shapes=args.shape, repeats=args.repeats, as_json=args.json
    )


def _cmd_demo(args: argparse.Namespace) -> int:
    text: str | None = None
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        text = args.text

    live: LiveSettings | None = None
    if args.live:
        if not args.model or not args.api:
            print("--live needs --model and --api", file=sys.stderr)
            return _EXIT_ERROR
        key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
        if args.api_key_env and not key:
            print(f"{args.api_key_env} is not set", file=sys.stderr)
            return _EXIT_ERROR
        live = LiveSettings(base_url=args.api, model=args.model, api_key=key)

    return run_demo(
        _settings_from(args),
        text=text,
        scenarios=args.scenario,
        live=live,
        as_json=args.json,
    )


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
        # Next to the numbers, not in a footer. A consumer that reads this JSON
        # and drops the provenance is making a choice; one that never saw it is
        # not making one.
        "provenance": report.provenance.as_mapping(),
        "independent_of_mamori": report.independent_of("mamori"),
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


def _print_provenance(report: EvaluationReport) -> None:
    """Say who wrote the data, in the same block as the rates it qualifies.

    ADR-0025 already said the corpus was written by the same hand as the rules.
    It said so in a document nobody has open while looking at a leak rate, and
    the figure travelled without it anyway. What was missing was never more
    awareness; it was putting the sentence where the number is.
    """
    print(f"  corpus written by   {report.provenance.describe()}")
    reason = report.provenance.why_not("mamori")
    if reason is not None:
        print(f"                      {reason}")
        print("                      Read the rates above as a regression floor,")
        print("                      not as a probability your documents are safe.")


def _print_unanswered(report: EvaluationReport) -> None:
    """Say when the model never answered, because the rates cannot.

    A model that returns nothing and a model that finds nothing produce
    identical numbers. Without this line a comparison reads "contributed
    nothing", which is a statement about the model, when the true statement is
    that it was never heard from.
    """
    if not report.unanswered_samples:
        return
    print(
        f"  MODEL UNREAD        {report.unanswered_samples}/{len(report.samples)}"
        " samples -- the answer could not be read, so these rates are the"
        " rules' alone"
    )


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
    print(f"  clean samples       {report.clean_samples}/{len(report.samples)}")
    _print_unanswered(report)
    _print_provenance(report)
    print()

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

    # `--stance` wins when it is given and stays out of the way when it is not.
    # It used to carry a default, so `mamori eval --config settings.json` threw
    # away whatever stance that file asked for and scored recall-first without
    # saying so: a setting read, then silently overwritten by a default.
    settings = load_config_file(Path(args.config)) if args.config else MamoriConfig()
    if args.stance is not None:
        settings = settings.replace(stance=Stance(args.stance))

    # The baseline for `--compare` is these settings with the model taken out,
    # not a fresh default. Rebuilt by hand it would lose the locales, the
    # co-occurrence pass and the corrections along with the model, and the
    # comparison would attribute all of that to the model. `MamoriConfig.
    # detectors` carries a docstring about the last time that happened.
    rules_only = settings.replace(llm=None)

    cache: CachedProvider | None = None
    if args.cache:
        cache = _eval_cache(settings, Path(args.cache), replay=args.replay)
    elif args.replay:
        print("--replay needs --cache", file=sys.stderr)
        return _EXIT_ERROR

    comparisons: list[Comparison] = []
    try:
        detectors = list(_eval_detectors(settings, cache))
        reports = [
            evaluate(
                dataset,
                detectors=detectors,
                match=MatchMode(args.match),
                min_confidence=args.min_confidence,
            )
            for dataset in datasets
        ]

        if args.compare:
            baseline_detectors = list(rules_only.detectors())
            for dataset, report in zip(datasets, reports, strict=True):
                baseline = evaluate(
                    dataset,
                    detectors=baseline_detectors,
                    match=MatchMode(args.match),
                    min_confidence=args.min_confidence,
                )
                comparisons.append(
                    compare(
                        baseline,
                        report,
                        baseline_name="rules only",
                        candidate_name=_candidate_name(settings),
                    )
                )
    finally:
        if cache is not None:
            cache.save()

    if args.json:
        payload: object
        if args.compare:
            payload = [c.as_mapping() for c in comparisons]
        else:
            payload = [_report_as_json(r) for r in reports]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return _EXIT_OK

    if args.compare:
        for comparison in comparisons:
            _print_comparison(comparison)
        if cache is not None:
            print(f"cache  {cache.hits} hit(s), {cache.misses} miss(es) -> {cache.path}")
            if cache.failures:
                print()
                print(
                    f"WARNING: the model failed on {cache.failures} of "
                    f"{cache.hits + cache.misses} request(s)."
                )
                print("A model that never answers produces exactly the numbers above:")
                print("no change to anything. That is not a result -- the pass degrades")
                print("to nothing by design, and the comparison has measured the rules")
                print("against themselves. Check `mamori llm --check`, and the timeout.")
                return _EXIT_ERROR
        return _EXIT_OK

    for report in reports:
        _print_report(report, args.show_leaks)
    print(
        "leak rate is the share of labelled sensitive characters that no detection\n"
        "covered -- the part that would have left the machine. Over-redaction is what\n"
        "it cost in ordinary text. Neither number is meaningful without the other."
    )
    return _EXIT_OK


def _candidate_name(settings: MamoriConfig) -> str:
    if settings.llm is not None and settings.llm.model:
        return f"+ {settings.llm.model}"
    return "candidate"


def _eval_cache(settings: MamoriConfig, path: Path, *, replay: bool) -> CachedProvider:
    """Wrap the configured model so a run can be repeated.

    Raises:
        ConfigurationError: No model is configured, so there is nothing to
            cache and asking for one is a mistake worth reporting.
    """
    passes = settings.llm_passes()
    if not passes:
        raise ConfigurationError(
            "--cache needs a model. Point --config at settings with an 'llm' section."
        )
    return CachedProvider(passes[0].provider, path, read_only=replay)


def _eval_detectors(settings: MamoriConfig, cache: CachedProvider | None) -> Sequence[Detector]:
    """The detectors to score, with the cache spliced in when there is one.

    Assembly is the settings' job, not this function's. An earlier version
    rebuilt the pipeline here and quietly left out the co-occurrence pass,
    which meant every cached model measurement was scored against a baseline
    that had it -- so the model looked worse than it was, for two releases.
    """
    return list(settings.detectors(provider=cache))


def _print_comparison(comparison: Comparison) -> None:
    base, cand = comparison.baseline, comparison.candidate
    print(f"{cand.dataset}  ({cand.locale}, {len(cand.samples)} samples)")
    print()
    width = max(len(comparison.baseline_name), len(comparison.candidate_name), 10)
    header = f"{comparison.baseline_name:>{width}}{comparison.candidate_name:>{width + 2}}"
    print(f"  {'':<20}{header}       delta")
    print(
        f"  {'leak rate':<20}{base.leak_rate:>{width}.2%}{cand.leak_rate:>{width + 2}.2%}"
        f"{comparison.leak_delta:>+12.2%}"
    )
    print(
        f"  {'over-redaction':<20}{base.over_redaction_rate:>{width}.2%}"
        f"{cand.over_redaction_rate:>{width + 2}.2%}{comparison.over_redaction_delta:>+12.2%}"
    )
    print(
        f"  {'entity precision':<20}{base.overall.precision:>{width}.3f}"
        f"{cand.overall.precision:>{width + 2}.3f}{comparison.precision_delta:>+12.3f}"
    )
    print(
        f"  {'entity recall':<20}{base.overall.recall:>{width}.3f}"
        f"{cand.overall.recall:>{width + 2}.3f}{comparison.recall_delta:>+12.3f}"
    )
    print()

    if comparison.newly_clean:
        print(f"  now fully covered   {', '.join(comparison.newly_clean)}")
    if comparison.still_leaking:
        print(f"  still leaking       {', '.join(comparison.still_leaking)}")
    if comparison.regressions:
        print("  REGRESSIONS -- these leak now and did not before:")
        for change in comparison.regressions:
            print(f"    {change.sample_id}  {change.describe()}")
    cost = [c for c in comparison.changes if c.over_redaction_added and not c.leak_fixed]
    if cost:
        print("  cost with nothing gained:")
        for change in cost[:10]:
            print(f"    {change.sample_id}  {change.describe()}")
    print()


_COMMANDS = {
    "inspect": _cmd_inspect,
    "protect": _cmd_protect,
    "restore": _cmd_restore,
    "keygen": _cmd_keygen,
    "policy": _cmd_policy,
    "config": _cmd_config,
    "prompt": _cmd_prompt,
    "llm": _cmd_llm,
    "serve": _cmd_serve,
    "lint": _cmd_lint,
    "privacy": _cmd_privacy,
    "trace": _cmd_trace,
    "audit": _cmd_audit,
    "correct": _cmd_correct,
    "corrections": _cmd_corrections,
    "locales": _cmd_locales,
    "demo": _cmd_demo,
    "bench": _cmd_bench,
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
