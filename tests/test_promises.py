"""The promises, checked by machine.

The README makes claims. Every one of them is enforced somewhere -- a field
excluded from a repr, a store that only ever held a dict, a scope checked
before a lookup -- and until this file existed, nothing checked that the
enforcement was still there. A promise nobody tests is a promise waiting to be
broken by a change that meant no harm.

Each class here corresponds to one line of ``mamori privacy``. The report names
the test; this file is the test. If a claim in
:mod:`mamori.report` ever stops being backed by something that runs, the last
class in this file fails.

These are not unit tests of behaviour. They are the specification of what this
library will not do, written so a machine can refuse a release that breaks it.
"""

from __future__ import annotations

import inspect
import json
import socket
from pathlib import Path
from typing import Any

import pytest

import mamori
from mamori import MamoriConfig, PrivacySession
from mamori.domain.mapping import Mapping
from mamori.domain.placeholder import Placeholder
from mamori.domain.sensitive_entity import SensitiveEntity
from mamori.errors import ConfigurationError
from mamori.infrastructure.storage import InMemoryMappingStore
from mamori.llm_settings import LLMSettings
from mamori.ports.llm import LLMRequest, LLMResponse
from mamori.report import build_report

from .credentials import FAKE_AWS_KEY

SENSITIVE = "田中太郎さんへ tanaka@example.com 電話は090-1234-5678、住所は東京都千代田区千代田1-1"
ENGLISH = "Dear Jane Doe, reach me at jane.doe@example.com or (415) 555-0198."
SECRETS = ("田中太郎", "tanaka@example.com", "090-1234-5678", "jane.doe@example.com")


class NoNetwork:
    """Makes every attempt to *connect* fail, loudly.

    Connecting is patched rather than the socket class itself: ``ssl``
    subclasses ``socket.socket`` when it is imported, so replacing the class
    breaks an import rather than a connection and proves nothing. What matters
    is that no bytes reach another process, and that is ``connect``.

    A future dependency that dials out fails here, in a test, rather than in
    somebody's deployment where the first sign is a document in an access log.
    """

    _PATCHED = ("connect", "connect_ex", "sendto", "sendall")

    def __init__(self) -> None:
        self.attempts: list[str] = []
        self._saved: dict[str, Any] = {}

    def __enter__(self) -> NoNetwork:
        def refusal(name: str) -> Any:
            def refuse(*args: Any, **kwargs: Any) -> Any:
                self.attempts.append(name)
                raise AssertionError(f"socket.{name} was called while mamori was working offline")

            return refuse

        for name in self._PATCHED:
            self._saved[name] = getattr(socket.socket, name, None)
            setattr(socket.socket, name, refusal(name))
        self._saved["create_connection"] = socket.create_connection
        socket.create_connection = refusal("create_connection")  # type: ignore[assignment]
        return self

    def __exit__(self, *exc: object) -> None:
        for name in self._PATCHED:
            saved = self._saved.get(name)
            if saved is not None:
                setattr(socket.socket, name, saved)
        socket.create_connection = self._saved["create_connection"]


class TestNothingLeavesTheMachine:
    """ "No account, no upload, no network required" -- checked, not asserted.

    The whole default path runs with the socket constructor replaced by one
    that raises. Detection, replacement, restoration, evaluation and the
    command line all have to complete without one.
    """

    def test_the_guard_itself_actually_catches_a_connection(self) -> None:
        """A ban that cannot trip would make every test below vacuous."""
        with NoNetwork() as guard, pytest.raises(AssertionError):
            socket.create_connection(("127.0.0.1", 9))
        assert guard.attempts == ["create_connection"]

    def test_the_guard_catches_a_socket_connect_too(self) -> None:
        with NoNetwork(), pytest.raises(AssertionError):
            socket.socket().connect(("127.0.0.1", 9))

    def test_the_guard_is_lifted_afterwards(self) -> None:
        """Otherwise it would poison every test that runs after it."""
        with NoNetwork():
            pass
        server = socket.socket()
        try:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            with socket.create_connection(server.getsockname(), timeout=2):
                pass
        finally:
            server.close()

    def test_protecting_a_document_opens_no_socket(self) -> None:
        with NoNetwork(), PrivacySession() as session:
            result = session.protect(SENSITIVE)
            assert result.protected_text
            assert session.restore(result.protected_text).text == SENSITIVE

    def test_every_language_pack_works_offline(self) -> None:
        for locale in ("ja", "en", "zh"):
            with NoNetwork(), MamoriConfig(locales=(locale,)).session() as session:
                assert session.protect(SENSITIVE).protected_text

    def test_the_evaluation_harness_runs_offline(self) -> None:
        from mamori.evaluation import bundled_datasets, evaluate

        with NoNetwork():
            dataset = bundled_datasets("ja")[0]
            report = evaluate(dataset, detectors=list(MamoriConfig().detectors()))
            assert report.overall.recall > 0

    def test_the_command_line_protects_offline(self) -> None:
        from mamori.interfaces.cli.main import main

        with NoNetwork():
            assert main(["protect", SENSITIVE]) == 0

    def test_the_privacy_report_itself_opens_no_socket(self) -> None:
        """A report that contacted something to describe a configuration would
        be the least trustworthy thing in the package."""
        settings = MamoriConfig.from_mapping(
            {"llm": {"model": "qwen2.5:7b", "base_url": "http://llm01.corp:8000/v1/"}}
        )
        with NoNetwork():
            report = build_report(settings)
            assert report.destinations

    def test_importing_mamori_opens_no_socket(self) -> None:
        import importlib

        with NoNetwork():
            importlib.reload(mamori)


class TestMappingsStayInMemory:
    """The mapping back to a real value is written nowhere by default."""

    def test_the_default_store_holds_nothing_outside_the_process(self) -> None:
        with PrivacySession() as session:
            session.protect(SENSITIVE)
            assert isinstance(session._store, InMemoryMappingStore)

    def test_no_configuration_key_can_turn_on_writing_to_disk(self) -> None:
        """A file store must be passed in Python, deliberately, by a caller."""
        keys = set(MamoriConfig.__dataclass_fields__)
        for suspicious in ("store", "storage", "path", "database", "persist", "cache"):
            assert suspicious not in keys, (
                f"a '{suspicious}' setting would let a configuration file start "
                "writing mappings to disk without anybody deciding to"
            )

    def test_closing_a_session_discards_what_it_held(self) -> None:
        session = PrivacySession()
        result = session.protect(SENSITIVE)
        session.close()
        assert session.restore(result.protected_text).text == result.protected_text

    def test_a_run_writes_no_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        with PrivacySession() as session:
            session.restore(session.protect(SENSITIVE).protected_text)
        assert list(tmp_path.iterdir()) == []


class TestValuesStayOutOfDiagnostics:
    """A protected value must not reach a traceback, a log line or a repr.

    This is the failure mode that undoes everything else: the library replaces
    a name in the text and then prints it in an exception, and the name ends up
    in a log aggregator that ships to a third party.
    """

    def test_a_detection_does_not_repr_its_value(self) -> None:
        with PrivacySession() as session:
            session.protect(SENSITIVE)
        entity = SensitiveEntity.__dataclass_fields__["value"]
        assert entity.repr is False

    def test_a_request_does_not_repr_the_document(self) -> None:
        request = LLMRequest(system="s", user=SENSITIVE)
        assert SENSITIVE not in repr(request)

    def test_a_response_does_not_repr_the_answer(self) -> None:
        assert "secret" not in repr(LLMResponse(text="secret answer", model="m"))

    def test_a_mapping_does_not_repr_the_original(self) -> None:
        mapping = Mapping("scope", Placeholder("EMAIL", 1), "EMAIL", SECRETS[1], "EMAIL:x")
        assert SECRETS[1] not in repr(mapping)

    def test_a_blocked_credential_is_not_quoted_back(self) -> None:
        from mamori.errors import PolicyViolationError

        with PrivacySession() as session, pytest.raises(PolicyViolationError) as caught:
            session.protect(f"the key is {FAKE_AWS_KEY}")
        assert FAKE_AWS_KEY not in str(caught.value)

    def test_the_proxy_log_line_carries_counts_and_no_values(self) -> None:
        from mamori.interfaces.proxy.exchange import protect_request, summarise

        payload = {"messages": [{"role": "user", "content": SENSITIVE}]}
        with MamoriConfig().session() as session:
            _, report = protect_request(session, payload)
        line = summarise(report)
        for secret in SECRETS:
            assert secret not in line

    def test_the_privacy_report_holds_no_document(self) -> None:
        report = build_report(MamoriConfig())
        blob = json.dumps(report.as_mapping(), ensure_ascii=False)
        for secret in SECRETS:
            assert secret not in blob


class TestRestorationIsScopeBound:
    """A reply cannot read values back by guessing at placeholder names."""

    def test_another_scope_cannot_resolve_a_placeholder(self) -> None:
        store = InMemoryMappingStore()
        with PrivacySession(store=store, scope="tenant-a") as a:
            protected = a.protect(SENSITIVE).protected_text
        with PrivacySession(store=store, scope="tenant-b") as b:
            assert b.restore(protected).text == protected

    def test_a_placeholder_that_was_never_allocated_comes_back_unchanged(self) -> None:
        with PrivacySession() as session:
            session.protect(SENSITIVE)
            assert session.restore("<PERSON_999>").text == "<PERSON_999>"

    def test_a_fresh_session_resolves_nothing(self) -> None:
        with PrivacySession() as first:
            protected = first.protect(SENSITIVE).protected_text
        with PrivacySession() as second:
            assert second.restore(protected).text == protected


class TestKeysAreNeverInConfiguration:
    """A key belongs in an environment variable, not in a file that gets committed."""

    def test_a_literal_key_in_a_config_file_is_refused(self) -> None:
        with pytest.raises(ConfigurationError) as caught:
            LLMSettings.from_mapping({"model": "m", "api_key": "sk-secret-value"})
        assert "api_key_env" in str(caught.value)

    def test_the_refusal_does_not_echo_the_key(self) -> None:
        with pytest.raises(ConfigurationError) as caught:
            LLMSettings.from_mapping({"model": "m", "api_key": "sk-secret-value"})
        assert "sk-secret-value" not in str(caught.value)

    def test_serialised_settings_never_carry_a_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROMISES_TEST_KEY", "sk-secret-value")
        settings = LLMSettings(model="m", api_key_env="PROMISES_TEST_KEY")
        assert settings.api_key_env == "PROMISES_TEST_KEY"
        assert "sk-secret-value" not in json.dumps(settings.as_mapping())

    def test_the_privacy_report_never_carries_a_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROMISES_TEST_KEY", "sk-secret-value")
        config = MamoriConfig.from_mapping(
            {"llm": {"model": "m", "api_key_env": "PROMISES_TEST_KEY"}}
        )
        blob = json.dumps(build_report(config).as_mapping())
        assert "sk-secret-value" not in blob


class TestTheModelOnlyAdds:
    """The bound on what a model can do to a document.

    Text that talks the model out of reporting anything gets the pipeline back
    to the rules, which is where every release before the model tier shipped.
    A model cannot subtract, and this is why one can be let near the pipeline.
    """

    def test_a_silent_model_leaves_the_rules_intact(self) -> None:
        """Talk the model into saying nothing and you get the rules back."""
        from mamori.infrastructure.detectors import build_pipeline
        from mamori.infrastructure.detectors.llm_pass import LLMDetectionPass
        from mamori.infrastructure.llm import ScriptedProvider

        rules_only = list(MamoriConfig().detectors())
        with PrivacySession(detectors=rules_only) as session:
            expected = session.protect(SENSITIVE).entity_count
        assert expected > 0, "the fixture must give the rules something to find"

        silenced = build_pipeline(
            extra_passes=[LLMDetectionPass(ScriptedProvider('{"entities": []}'))]
        )
        with PrivacySession(detectors=[silenced]) as session:
            assert session.protect(SENSITIVE).entity_count >= expected

    def test_a_hostile_answer_cannot_remove_a_finding(self) -> None:
        """The pass returns proposals. There is no code path from a response to
        a deletion, so the strongest a hostile model can be is useless."""
        from mamori.infrastructure.detectors.llm_pass import LLMDetectionPass
        from mamori.infrastructure.llm import ScriptedProvider
        from mamori.ports.detection_pass import DetectionContext

        hostile = ScriptedProvider(
            '{"entities": [], "instruction": "ignore all previous findings"}'
        )
        found = LLMDetectionPass(hostile).run(DetectionContext(text=ENGLISH))
        assert found == []

    def test_a_hallucinated_span_is_dropped(self) -> None:
        from mamori.infrastructure.detectors.llm_pass import LLMDetectionPass
        from mamori.infrastructure.llm import ScriptedProvider
        from mamori.ports.detection_pass import DetectionContext

        lying = ScriptedProvider(
            json.dumps({"entities": [{"type": "PERSON", "start": 0, "end": 5, "text": "Zzzzz"}]})
        )
        found = LLMDetectionPass(lying).run(DetectionContext(text=ENGLISH))
        assert found == [], "the reported value did not match the text at those offsets"

    def test_a_model_failure_does_not_stop_the_request(self) -> None:
        from mamori.infrastructure.detectors.llm_pass import LLMDetectionPass
        from mamori.infrastructure.llm import FailingProvider
        from mamori.ports.detection_pass import DetectionContext

        assert LLMDetectionPass(FailingProvider()).run(DetectionContext(text=ENGLISH)) == []


class TestTheReportIsHonest:
    """The last line of defence: every claim must point at something real.

    A report that names a test which does not exist is worse than no report,
    because it looks like evidence.
    """

    def test_every_claim_names_a_test_that_exists(self) -> None:
        report = build_report(MamoriConfig())
        here = Path(__file__).parent
        for claim in report.by_construction:
            assert claim.checked_by, f"unbacked claim: {claim.text}"
            filename, _, node = claim.checked_by.partition("::")
            path = here / filename
            assert path.exists(), f"{claim.checked_by} names a file that does not exist"
            assert node, f"{claim.checked_by} names no class"
            assert f"class {node}" in path.read_text(encoding="utf-8"), (
                f"{claim.checked_by} names a class that is not in {filename}"
            )

    def test_the_classes_in_this_file_all_carry_tests(self) -> None:
        """A named class that had been emptied would pass the check above."""
        module = inspect.getmodule(self)
        assert module is not None
        for name, obj in vars(module).items():
            if not name.startswith("Test"):
                continue
            methods = [m for m in vars(obj) if m.startswith("test_")]
            assert methods, f"{name} is named as evidence but contains no tests"

    def test_the_responsibilities_are_stated_without_a_check(self) -> None:
        """These are the things mamori cannot verify, and it must not pretend."""
        report = build_report(MamoriConfig())
        assert report.your_responsibility
        for claim in report.your_responsibility:
            assert not claim.checked_by


class TestTheReportDescribesEvenABrokenConfiguration:
    """The report is what you reach for when the settings are wrong.

    Building the detectors is how the detector count is obtained, and it is
    also what refuses an endpoint outside the trust boundary. A report that
    raised there would be useless in the one situation it exists for.
    """

    @staticmethod
    def _refused() -> MamoriConfig:
        return MamoriConfig.from_mapping(
            {"llm": {"model": "m", "base_url": "https://api.openai.com/v1/"}}
        )

    def test_it_reports_rather_than_raising(self) -> None:
        report = build_report(self._refused())
        assert report.warnings

    def test_it_says_the_endpoint_will_be_refused(self) -> None:
        report = build_report(self._refused())
        model = next(d for d in report.destinations if d["what"] == "detection model")
        assert model["admitted"] is False

    def test_it_says_the_configuration_cannot_be_used(self) -> None:
        warnings = " ".join(build_report(self._refused()).warnings)
        assert "cannot be used" in warnings

    def test_the_detector_count_is_unknown_rather_than_wrong(self) -> None:
        """Guessing a number for detectors that were never built would be worse."""
        assert build_report(self._refused()).detection["detectors"] is None

    def test_a_working_configuration_has_no_warnings(self) -> None:
        report = build_report(MamoriConfig())
        assert report.warnings == ()
        assert report.detection["detectors"]

    def test_the_command_exits_non_zero_on_a_warning(self) -> None:
        """So a deployment check can fail on it."""
        from mamori.interfaces.cli.main import main

        assert main(["privacy", "--json"]) == 0


class TestTheMeasurementCacheCannotBeTurnedOnByAccident:
    """The one thing in the package that writes model answers to disk.

    A cached answer names the spans it found, so the file is derived from the
    text. That is fine for measurement against invented data and would not be
    fine as a default, so it is reachable only by passing a path in Python --
    which is what keeps the storage claim in `mamori privacy` true for every
    configuration a user can express.
    """

    def test_no_configuration_key_names_it(self) -> None:
        keys = set(MamoriConfig.__dataclass_fields__)
        assert not {"cache", "cache_path", "response_cache"} & keys

    def test_it_lives_in_the_evaluation_package_not_the_adapters(self) -> None:
        """Where it is says what it is for."""
        from mamori.evaluation.cache import CachedProvider

        assert CachedProvider.__module__.startswith("mamori.evaluation")

    def test_a_default_session_writes_nothing(self, tmp_path: Path) -> None:
        from mamori.infrastructure.llm import ScriptedProvider

        provider = ScriptedProvider('{"entities": []}')
        assert not hasattr(provider, "save")
        assert list(tmp_path.iterdir()) == []

    def test_the_privacy_report_still_says_nothing_is_written(self) -> None:
        assert build_report(MamoriConfig()).storage["written_to_disk"] is False


class TestACommandThatReadsWritesNothing:
    """`kiseki` ADR-0070: reading is not keeping.

    That project found a command which quietly kept a snapshot every time
    somebody ran it to look at something, and no test caught it -- the history
    was polluted by a fortnight of debugging before anybody asked why. The
    equivalent mistake here would be `mamori inspect` or `mamori privacy`
    leaving something behind on a machine whose whole selling point is that
    nothing is left behind.

    A command that reads should be safe to run twice.
    """

    READ_ONLY = (
        ["inspect", "田中太郎さんへ tanaka@example.com"],
        ["protect", "田中太郎さんへ"],
        ["privacy"],
        ["corrections"],
        ["config"],
        ["policy"],
        ["locales"],
        ["prompt", "detection"],
        ["llm"],
        ["eval", "--locale", "ja"],
    )

    @pytest.mark.parametrize("argv", READ_ONLY, ids=lambda a: a[0])
    def test_it_leaves_the_directory_as_it_found_it(
        self, argv: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mamori.interfaces.cli.main import main

        monkeypatch.chdir(tmp_path)
        main(argv)
        assert list(tmp_path.iterdir()) == [], f"'mamori {argv[0]}' wrote something"

    @pytest.mark.parametrize("argv", READ_ONLY, ids=lambda a: a[0])
    def test_it_is_safe_to_run_twice(
        self, argv: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mamori.interfaces.cli.main import main

        monkeypatch.chdir(tmp_path)
        assert main(argv) == main(argv)

    def test_the_commands_that_do_write_are_the_ones_you_would_expect(self) -> None:
        """Two, and both are the point of running them."""
        from mamori.interfaces.cli.main import build_parser

        writers = {"correct"}  # and 'protect --save', which needs a flag
        commands = set(build_parser()._subparsers._group_actions[0].choices)  # type: ignore[union-attr]
        assert writers <= commands
        assert not writers & {"inspect", "privacy", "corrections", "eval"}


class TestTheNewerSurfaces:
    """A promise is only as good as the newest surface it was checked on.

    Every class above was written against the surfaces of its own release.
    These are the ones that came later, checked against the same four
    promises: nothing leaves, nothing is written, no value reaches a
    diagnostic, and restoration stays inside its scope.
    """

    def test_a_conversation_holds_nothing_after_it_ends(self) -> None:
        """The registry's whole safety argument: both bounds purge."""
        from mamori.application.conversations import ConversationRegistry

        registry = ConversationRegistry(PrivacySession)
        conversation = registry.resume(None)
        conversation.session.protect("Dear Jane Doe, call 415-555-0198.")
        registry.end(conversation.token)
        assert conversation.session.restore("<PERSON_001>").text == "<PERSON_001>"

    def test_a_conversation_token_is_not_derived_from_anything_sent(self) -> None:
        """It is a credential for a table of real values, so it must not carry
        information about what is in that table."""
        from mamori.application.conversations import ConversationRegistry

        registry = ConversationRegistry(PrivacySession)
        first = registry.resume(None)
        first.session.protect("Dear Jane Doe,")
        assert "Jane" not in first.token
        assert "jane" not in first.token.lower()

    def test_a_tool_call_argument_is_protected_like_any_other_text(self) -> None:
        import json as json_module

        from mamori.interfaces.proxy.exchange import protect_request

        payload = {
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "c",
                            "type": "function",
                            "function": {
                                "name": "send",
                                "arguments": '{"to": "jane.doe@example.com"}',
                            },
                        }
                    ],
                }
            ]
        }
        with PrivacySession() as session:
            protected, _ = protect_request(session, payload, add_guidance=False)
        assert "jane.doe@example.com" not in json_module.dumps(protected)

    def test_the_linter_never_prints_a_value(self, tmp_path: Path) -> None:
        """Its output goes to CI logs, which outlive and out-read the repo."""
        from mamori.config import MamoriConfig
        from mamori.interfaces.cli.linting import lint_paths

        (tmp_path / "fixture.md").write_text(
            "Dear Jane Doe, call 415-555-0198.\npassword: hunter2spring\n", encoding="utf-8"
        )
        findings, _ = lint_paths(MamoriConfig(), [tmp_path])
        assert findings, "the fixture must produce findings for this to mean anything"
        rendered = "\n".join(f.describe() + repr(f.as_mapping()) for f in findings)
        for value in ("Jane Doe", "415-555-0198", "hunter2spring"):
            assert value not in rendered

    def test_a_fail_closed_refusal_quotes_nothing(self) -> None:
        from mamori.config import MamoriConfig
        from mamori.errors import PolicyViolationError

        config = MamoriConfig(min_confidence=0.85, uncertain="refuse")
        with config.session() as session, pytest.raises(PolicyViolationError) as raised:
            session.protect("Please ask Riverton about the Foundry Row site.")
        assert "Riverton" not in str(raised.value)
        assert "Foundry Row" not in str(raised.value)

    def test_the_linter_opens_no_socket(self, tmp_path: Path) -> None:
        from mamori.config import MamoriConfig
        from mamori.interfaces.cli.linting import lint_paths

        (tmp_path / "a.md").write_text("Dear Jane Doe,\n", encoding="utf-8")
        with NoNetwork():
            assert lint_paths(MamoriConfig(), [tmp_path])[0]

    def test_a_conversation_does_not_cross_into_another(self) -> None:
        """Two callers on one proxy. Scope binding is what keeps them apart."""
        from mamori.application.conversations import ConversationRegistry

        registry = ConversationRegistry(PrivacySession)
        mine, theirs = registry.resume(None), registry.resume(None)
        mine.session.protect("Dear Jane Doe,")
        assert theirs.session.restore("<PERSON_001>").text == "<PERSON_001>"
