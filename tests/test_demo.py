"""The guided tour.

A demo is documentation that runs, which means it can be wrong in the one way
documentation cannot: it can stop matching the library. These tests are cheap
and exist so that a scenario which quietly stops demonstrating anything fails
the build instead of confusing somebody on their first five minutes.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from mamori import MamoriConfig
from mamori.interfaces.cli.demo import DEMO_TEXT, SCENARIOS, LiveSettings, run_demo
from mamori.interfaces.cli.main import main


class TestTheTour:
    def test_every_scenario_runs(self, capsys: pytest.CaptureFixture[str]) -> None:
        for name in SCENARIOS:
            assert main(["demo", "--scenario", name]) == 0
            assert capsys.readouterr().out.strip(), f"{name} printed nothing"

    def test_the_whole_tour_runs(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["demo"]) == 0
        out = capsys.readouterr().out
        for heading in ("round trip", "streamed", "longer than a sentence"):
            assert heading in out

    def test_the_demo_text_actually_has_something_to_find(self) -> None:
        """A demo of a detector that detects nothing is a screenshot."""
        with MamoriConfig().session() as session:
            assert session.protect(DEMO_TEXT).entity_count >= 5

    def test_no_value_from_the_demo_text_survives_into_the_protected_form(self) -> None:
        with MamoriConfig().session() as session:
            protected = session.protect(DEMO_TEXT).protected_text
        for secret in ("田中太郎", "tanaka@example.com", "090-1234-5678", "John Smith"):
            assert secret not in protected

    def test_the_round_trip_really_round_trips(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["demo", "--scenario", "roundtrip"]) == 0
        out = capsys.readouterr().out
        assert "<PERSON_001>" in out, "the protected form must be shown"
        assert "田中太郎様" in out, "and the restored form after it"

    def test_the_streaming_scenario_reassembles_a_split_placeholder(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["demo", "--scenario", "stream"]) == 0
        out = capsys.readouterr().out
        assert "'<PER'" in out, "the split chunk must be visible"
        assert "田中太郎" in out, "and the value it became"

    def test_the_conversation_scenario_shows_the_failure_and_the_fix(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Both halves, or it is an advertisement rather than a demonstration."""
        assert main(["demo", "--scenario", "conversation"]) == 0
        out = capsys.readouterr().out
        without, with_one = out.split("with a conversation")
        assert "<PERSON_001>さんの住所" in without, "unrestored, because the scope is new"
        assert "田中太郎さんの住所" not in without
        assert "田中太郎さんの住所" in with_one, "restored, because the conversation held it"

    def test_the_conversation_scenario_does_not_print_a_whole_token(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """It is a credential for a table of real values."""
        assert main(["demo", "--scenario", "conversation"]) == 0
        for line in capsys.readouterr().out.splitlines():
            if "X-Mamori-Session" in line:
                shown = line.split(":")[-1].strip()
                assert shown.endswith("...")
                assert len(shown) <= 12

    def test_the_corrections_scenario_shows_a_before_and_an_after(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["demo", "--scenario", "corrections"]) == 0
        out = capsys.readouterr().out
        before, after = out.split("after two corrections")
        assert "<PERSON_001>, the contract" in before, "Monday is a false positive first"
        assert "Dear Monday" in after, "and left alone after the correction"
        assert "COMPANY_NAME_001" in after, "while Acme is now found"

    def test_the_blocked_scenario_actually_blocks(self, capsys: pytest.CaptureFixture[str]) -> None:
        """It said 'this should not happen' for a while, and it was happening."""
        assert main(["demo", "--scenario", "blocked"]) == 0
        out = capsys.readouterr().out
        assert "refused" in out
        assert "should not happen" not in out

    def test_no_scenario_prints_a_credential(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["demo"]) == 0
        assert "hunter2spring" not in capsys.readouterr().out


class TestYourOwnText:
    def test_text_is_used_instead_of_the_sample(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["demo", "--scenario", "roundtrip", "--text", "Call 415-555-0198"]) == 0
        out = capsys.readouterr().out
        assert "PHONE_001" in out
        assert "田中太郎" not in out

    def test_a_file_is_read(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = tmp_path / "draft.txt"
        path.write_text("Dear Jane Doe, reach me at jane.doe@example.com", encoding="utf-8")
        assert main(["demo", "--scenario", "roundtrip", "-f", str(path)]) == 0
        out = capsys.readouterr().out
        # Only the block that says what leaves the machine. The restored block
        # further down is *supposed* to contain the address again.
        sent = out.split("the model sees")[-1].split("replaced")[0]
        assert "jane.doe@example.com" not in sent
        assert "Jane Doe" not in sent
        assert "EMAIL_001" in sent

    def test_json_is_machine_readable(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["demo", "--json", "--text", "Call 415-555-0198"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["replaced"] == {"PHONE": 1}
        assert "415-555-0198" not in payload["protected"]

    def test_text_with_nothing_in_it_is_not_an_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["demo", "--scenario", "roundtrip", "--text", "hello there"]) == 0


class TestLiveMode:
    """The mode that actually sends something. A fake service stands in."""

    class Service:
        def __init__(self, answer: str) -> None:
            self.answer = answer
            self.received: list[dict[str, Any]] = []
            self._server: ThreadingHTTPServer | None = None

        def __enter__(self) -> TestLiveMode.Service:
            outer = self

            class Handler(BaseHTTPRequestHandler):
                def do_POST(self) -> None:
                    length = int(self.headers.get("Content-Length", "0"))
                    outer.received.append(json.loads(self.rfile.read(length)))
                    body = json.dumps(
                        {"choices": [{"message": {"content": outer.answer}}]},
                        ensure_ascii=False,
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *args: Any) -> None:
                    pass

            self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            threading.Thread(target=self._server.serve_forever, daemon=True).start()
            return self

        def __exit__(self, *exc: object) -> None:
            if self._server is not None:
                self._server.shutdown()
                self._server.server_close()

        @property
        def url(self) -> str:
            assert self._server is not None
            return f"http://127.0.0.1:{self._server.server_port}/v1/"

        @property
        def raw(self) -> str:
            return json.dumps(self.received, ensure_ascii=False)

    def test_the_service_receives_no_real_value(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The claim the whole demo is making, checked against the bytes."""
        with self.Service("<PERSON_001>さんに返信しました") as service:
            live = LiveSettings(base_url=service.url, model="fake")
            assert run_demo(MamoriConfig(), live=live) == 0
        for secret in ("田中太郎", "tanaka@example.com", "090-1234-5678"):
            assert secret not in service.raw
        assert "PERSON_001" in service.raw

    def test_the_answer_is_restored(self, capsys: pytest.CaptureFixture[str]) -> None:
        with self.Service("<PERSON_001>さんに返信しました") as service:
            live = LiveSettings(base_url=service.url, model="fake")
            run_demo(MamoriConfig(), live=live)
        assert "田中太郎さんに返信しました" in capsys.readouterr().out

    def test_the_briefing_is_sent_so_placeholders_come_back_intact(self) -> None:
        with self.Service("ok") as service:
            run_demo(MamoriConfig(), live=LiveSettings(base_url=service.url, model="fake"))
        assert service.received[0]["messages"][0]["role"] == "system"

    def test_an_unreachable_service_fails_with_advice(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        live = LiveSettings(base_url="http://127.0.0.1:1/v1/", model="fake", timeout=2.0)
        assert run_demo(MamoriConfig(), live=live) == 1
        assert "mamori llm --check" in capsys.readouterr().out

    def test_live_needs_a_model_and_an_endpoint(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["demo", "--live"]) == 1
        assert "--model" in capsys.readouterr().err

    def test_a_missing_key_variable_is_reported(self, capsys: pytest.CaptureFixture[str]) -> None:
        argv = ["demo", "--live", "--model", "m", "--api", "http://x/v1/", "--api-key-env", "NOPE"]
        assert main(argv) == 1
        assert "NOPE" in capsys.readouterr().err
