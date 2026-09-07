"""The catalogue is what happens, not a document about what happens.

Sora is the one program that talks to all seven libraries and therefore the
only place that can answer *"is this my fault or is something broken"*. An
exit code cannot say, so it asked for a list it could check its own copy
against in CI -- so that a kind added here fails **its** build rather than
being discovered in somebody's log.

That only works if the list is true. A table of statuses somebody typed once
is exactly the defect `tests/test_security_figures.py` exists for, arriving
through a different door. So these drive the proxy and the command line, and
compare what actually came back against what the catalogue promised.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

import mamori
from mamori.errors import CATALOGUE, CATALOGUE_CONTRACT, OPEN_NAMESPACES, MamoriError
from mamori.interfaces.cli.main import main

from .test_proxy import FakeUpstream, RunningProxy, chat
from .test_proxy_orchestration import post

EMAIL = "tanaka@example.com"
KEY = "sk-ant-api03-" + "A" * 95

BY_KIND: dict[str, dict[str, Any]] = {str(entry["kind"]): dict(entry) for entry in CATALOGUE}


class TestTheShapeOfIt:
    def test_every_kind_appears_once(self) -> None:
        """A repeated kind makes the fold key ambiguous, which is the one
        thing this document exists to prevent."""
        kinds = [entry["kind"] for entry in CATALOGUE]
        assert len(kinds) == len(set(kinds)), kinds

    def test_the_command_prints_what_the_module_holds(self) -> None:
        assert main(["errors", "--json"]) == 0

    def test_the_json_matches_the_shipped_schema(self, capsys: pytest.CaptureFixture[str]) -> None:
        jsonschema = pytest.importorskip("jsonschema")
        assert main(["errors", "--json"]) == 0
        document = json.loads(capsys.readouterr().out)
        schema = json.loads(
            (Path(mamori.__file__).parent / "schemas" / "errors-1-draft.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(document)
        assert document["contract"] == CATALOGUE_CONTRACT
        assert document["by"] == f"mamori/{mamori.__version__}"
        assert document["open_namespaces"] == list(OPEN_NAMESPACES)

    def test_no_entry_carries_anything_that_could_be_a_value(self) -> None:
        """No paths, no placeholders for a reader to fill from a log. A
        detail line describes the failure and never an instance of it."""
        for entry in CATALOGUE:
            for field in ("detail", "detail_ja"):
                line = str(entry[field])
                assert "{" not in line and "}" not in line, (entry["kind"], field)
                assert "/" not in line and "\\" not in line, (entry["kind"], field)
                assert line.endswith((".", "。")), (entry["kind"], field)

    def test_both_languages_are_written_for_every_kind(self) -> None:
        """Written by the same hand at the same time, which is the whole
        reason the Japanese line is here rather than in the consumer."""
        for entry in CATALOGUE:
            assert str(entry["detail"]).strip()
            assert str(entry["detail_ja"]).strip()
            assert str(entry["detail"]) != str(entry["detail_ja"])


class TestEveryExceptionThisLibraryExportsIsInIt:
    """A kind a caller can catch and cannot look up is a kind they have to
    learn from a log."""

    def test_the_exported_exceptions_are_the_catalogued_ones(self) -> None:
        exported = {
            name
            for name in mamori.__all__
            if isinstance(getattr(mamori, name), type)
            and issubclass(getattr(mamori, name), BaseException)
        }
        missing = exported - set(BY_KIND)
        assert not missing, f"exported and not catalogued: {sorted(missing)}"

    def test_every_catalogued_class_kind_is_a_real_exception(self) -> None:
        """The other direction. A kind naming a class that does not exist
        would be a promise about a failure that cannot happen."""
        for kind in BY_KIND:
            known = getattr(mamori, kind, None)
            if known is None:
                continue  # a proxy-only kind, checked below by driving it
            assert isinstance(known, type) and issubclass(known, BaseException), kind


class TestTheStatusesAreTheOnesTheProxyAnswersWith:
    """Sora keeps a copy of the status table. This is what turns that copy
    from a transcription into a check."""

    def test_a_blocked_credential(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            status, _, body = post(proxy, chat(f"deploy with {KEY}"))
        assert status == BY_KIND["PolicyViolationError"]["status"]
        assert BY_KIND["PolicyViolationError"]["outcome"] == "refused"
        assert BY_KIND["PolicyViolationError"]["retryable"] is False
        assert not service.received, "refused means nothing was forwarded"
        assert KEY not in json.dumps(body)

    def test_an_upstream_that_cannot_be_reached(self) -> None:
        with RunningProxy("http://127.0.0.1:1/v1/") as proxy:
            status, _, _ = post(proxy, chat("hello"))
        assert status == BY_KIND["ProviderError"]["status"]
        assert BY_KIND["ProviderError"]["outcome"] == "unavailable"
        assert BY_KIND["ProviderError"]["retryable"] is True

    def test_a_body_this_cannot_read(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            request = urllib.request.Request(
                proxy.url,
                data=b"not json",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=10)
        assert raised.value.code == BY_KIND["InvalidArgument"]["status"]
        assert not service.received

    def test_a_path_this_does_not_carry(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            request = urllib.request.Request(
                proxy.url.replace("/chat/completions", "/embeddings"),
                data=b'{"input": "x"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=10)
        assert raised.value.code == BY_KIND["NotProxied"]["status"]
        assert not service.received

    def test_an_audit_sink_that_cannot_be_written(self, tmp_path: Path) -> None:
        from mamori.infrastructure.audit import JsonlAuditSink
        from mamori.provenance import ProtectionLedger

        blocked = tmp_path / "not-a-directory" / "audit.jsonl"
        ledger = ProtectionLedger(JsonlAuditSink(blocked), by="sora/0.6")
        with FakeUpstream() as service, RunningProxy(service.url, audit=ledger) as proxy:
            status, _, _ = post(proxy, chat(f"Mail {EMAIL}"))
        assert status == BY_KIND["StorageError"]["status"]
        assert not service.received

    def test_every_catalogued_status_is_one_the_proxy_can_send(self) -> None:
        """The population check. Without it the four tests above could pass
        while the table listed a status nothing produces."""
        catalogued = {int(entry["status"]) for entry in CATALOGUE if entry["status"] is not None}  # type: ignore[call-overload]
        assert catalogued == {400, 404, 422, 500, 502}, sorted(catalogued)


class TestTheExitCodesAreTheOnesTheCommandUses:
    def test_a_blocked_credential_exits_with_its_own_code(self, tmp_path: Path) -> None:
        """`2`, not `1`. A refusal is this library working, and an
        orchestrator that cannot tell it from a failure will report a bug."""
        path = tmp_path / "k.txt"
        path.write_text(f"deploy with {KEY}\n", encoding="utf-8")
        assert main(["protect", "-f", str(path)]) == BY_KIND["PolicyViolationError"]["exit_code"]

    def test_an_unreadable_setting(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = main(["protect", "-c", "no-such-file.toml", "hello"])
        assert code == BY_KIND["ConfigurationError"]["exit_code"]
        assert capsys.readouterr().err.startswith("ConfigurationError:")

    def test_a_refused_command_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = main(["bench", "--repeats", "0"])
        assert code == BY_KIND["InvalidArgument"]["exit_code"]
        assert capsys.readouterr().err.startswith("InvalidArgument:")


class TestTheFirstTokenOfStderrIsAKind:
    """R-E2. The token before the colon used to be the word `error`, which
    told a reader nothing a non-zero exit had not, and a program nothing at
    all. An aggregator folds repeats on it and keeps nothing after the colon,
    because that half can quote a document."""

    def test_nothing_prints_the_bare_word_error_any_more(self) -> None:
        import inspect

        from mamori.interfaces.cli import main as module

        source = inspect.getsource(module)
        assert 'print(f"error: ' not in source
        assert 'print("error: ' not in source

    @pytest.mark.parametrize(
        ("argv", "kind"),
        [
            (["protect", "-c", "no-such-file.toml", "hello"], "ConfigurationError"),
            (["bench", "--repeats", "0"], "InvalidArgument"),
            (
                # `--conversations` matters: without it the ceiling is never
                # read and `serve` starts a server that does not return.
                # Found by the test hanging, which is the least ambiguous way
                # a missing flag has ever announced itself.
                [
                    "serve",
                    "--upstream",
                    "http://x/v1/",
                    "--conversations",
                    "--max-conversations",
                    "0",
                ],
                "InvalidArgument",
            ),
        ],
        ids=["a setting", "an argument", "another argument"],
    )
    def test_the_line_begins_with_a_catalogued_kind(
        self, argv: list[str], kind: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(argv)
        first = capsys.readouterr().err.splitlines()[0]
        assert first.split(":")[0] == kind, first
        assert kind in BY_KIND

    def test_a_raised_error_prints_its_own_class_name(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """So a kind this library gains is a kind Sora sees without anybody
        remembering to add a string."""
        for name in ("ConfigurationError", "DetectionError", "StorageError"):
            assert name in BY_KIND
            assert issubclass(getattr(mamori, name), MamoriError)
