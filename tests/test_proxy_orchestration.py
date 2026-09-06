"""What an orchestrator in front of the proxy can rely on.

Sora -- the layer that starts `mamori serve` as a child process and routes
every external conversation through it -- asked for four things, and each one
is here as the contract it gets rather than as a description of one:

- the scope a reply's placeholders were allocated in, on the reply itself,
  and the same scope on the audit lines `--audit` writes (R1);
- a status it can map to *"a credential stopped this"* without parsing prose
  (R2);
- a readiness check and a port it does not have to guess (R3);
- detections in Presidio's shape, without importing this library (R4).

And one it did not ask for but will want on a status line: what a turn
replaced, as kinds and counts, never values (U3).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from mamori import MamoriConfig
from mamori.application.conversations import ConversationRegistry
from mamori.infrastructure.audit import JsonlAuditSink
from mamori.interfaces.cli.main import main
from mamori.interfaces.proxy.server import REPLACED_HEADER, SCOPE_HEADER, SESSION_HEADER
from mamori.provenance import ProtectionLedger

from .test_proxy import FakeUpstream, RunningProxy, chat, completion

EMAIL = "tanaka@example.com"
NAME = "Jane Doe"
KEY = "sk-ant-api03-" + "A" * 95


def post(
    proxy: RunningProxy, payload: dict[str, Any], **extra: str
) -> tuple[int, dict[str, str], Any]:
    """Status, headers and body -- the helper in `test_proxy` drops the headers."""
    request = urllib.request.Request(
        proxy.url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", **extra},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), json.loads(exc.read())


def lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def ledger(path: Path) -> ProtectionLedger:
    return ProtectionLedger(JsonlAuditSink(path), by="sora/0.6")


class TestTheReplyNamesItsScope:
    def test_the_header_is_the_scope_on_the_audit_lines(self, tmp_path: Path) -> None:
        """R1 (a). The join key, on the reply and in the file."""
        audit = tmp_path / "audit.jsonl"
        with (
            FakeUpstream() as service,
            RunningProxy(service.url, audit=ledger(audit)) as proxy,
        ):
            service.reply = completion("Sent to <EMAIL_001>.")
            status, headers, body = post(proxy, chat(f"Mail {EMAIL} and call {NAME}."))

        assert status == 200
        scope = headers[SCOPE_HEADER]
        assert scope.startswith("session-")
        rows = lines(audit)
        assert rows, "nothing was written, so the join was never tested"
        assert {row["record"]["scope"] for row in rows} == {scope}
        assert {row["record"]["contract"] for row in rows} == {"mamori.protection-scope/1"}
        assert body["choices"][0]["message"]["content"] == f"Sent to {EMAIL}."

    def test_one_line_per_message_slot(self, tmp_path: Path) -> None:
        """A request with three messages protects three texts; each gets a
        record, all in one scope. An orchestrator reading the file for a scope
        gets that turn's slots, in order."""
        audit = tmp_path / "audit.jsonl"
        with (
            FakeUpstream() as service,
            RunningProxy(service.url, audit=ledger(audit)) as proxy,
        ):
            post(proxy, chat("first", f"then {EMAIL}", f"and {NAME}"))
        rows = lines(audit)
        assert len(rows) == 3
        assert len({row["record"]["scope"] for row in rows}) == 1
        assert [len(row["record"]["placeholders"]) for row in rows] == [0, 1, 1]

    def test_no_value_reaches_the_file(self, tmp_path: Path) -> None:
        audit = tmp_path / "audit.jsonl"
        with (
            FakeUpstream() as service,
            RunningProxy(service.url, audit=ledger(audit)) as proxy,
        ):
            post(proxy, chat(f"Mail {EMAIL} and call {NAME}."))
        raw = audit.read_text(encoding="utf-8")
        assert EMAIL not in raw
        assert NAME not in raw
        assert "tanaka" not in raw

    def test_the_scope_is_minted_here_and_not_accepted_from_the_caller(self) -> None:
        """The oracle argument: a caller who names the scope names the key
        its own audit trail is filed under."""
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            _, headers, _ = post(proxy, chat("hello"), **{SCOPE_HEADER: "attacker-chosen"})
        assert headers[SCOPE_HEADER] != "attacker-chosen"

    def test_a_stream_carries_it_too(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            service.stream_chunks = ["Sent to <EMA", "IL_001>."]
            request = urllib.request.Request(
                proxy.url,
                data=json.dumps(chat(f"Mail {EMAIL}", stream=True)).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.headers[SCOPE_HEADER].startswith("session-")
                assert response.headers[REPLACED_HEADER] == "EMAIL=1"

    def test_a_conversation_keeps_one_scope_across_turns(self, tmp_path: Path) -> None:
        """With `--conversations` the scope is the conversation's, so the
        lines carrying it are that conversation's turns in order -- which is
        what lets a second turn be restored with a value from the first."""
        audit = tmp_path / "audit.jsonl"
        registry = ConversationRegistry(MamoriConfig().session)
        with (
            FakeUpstream() as service,
            RunningProxy(service.url, conversations=registry, audit=ledger(audit)) as proxy,
        ):
            _, first, _ = post(proxy, chat(f"Mail {EMAIL}"))
            token = first[SESSION_HEADER]
            _, second, _ = post(proxy, chat(f"and {NAME}"), **{SESSION_HEADER: token})
        assert first[SCOPE_HEADER] == second[SCOPE_HEADER]
        rows = lines(audit)
        assert len(rows) == 2
        assert {row["record"]["scope"] for row in rows} == {first[SCOPE_HEADER]}

    def test_a_sink_that_cannot_be_written_stops_the_request(self, tmp_path: Path) -> None:
        """Strict, like the CLI. A proxy that answered and left a hole in the
        trail the operator turned on would be a trail that reads as complete
        and is not."""
        blocked = tmp_path / "not-a-directory" / "audit.jsonl"
        with (
            FakeUpstream() as service,
            RunningProxy(service.url, audit=ledger(blocked)) as proxy,
        ):
            status, _, body = post(proxy, chat(f"Mail {EMAIL}"))
        assert status == 500
        assert "audit" in body["error"]["message"].lower() or "written" in body["error"]["message"]
        assert not service.received, "the request went upstream despite the failed record"


class TestABlockHasAStatus:
    def test_a_blocked_credential_is_422_and_still_names_the_scope(self, tmp_path: Path) -> None:
        """R2. `422 Unprocessable Entity`, the status Sora maps to `refused`.

        The scope is named even on the refusal: the audit lines for it say
        what was allocated before the block, which is the honest answer to
        *"what did this turn protect"* when the answer is *"it never left"*.
        """
        audit = tmp_path / "audit.jsonl"
        with (
            FakeUpstream() as service,
            RunningProxy(service.url, audit=ledger(audit)) as proxy,
        ):
            status, headers, body = post(proxy, chat(f"deploy with {KEY}"))
        assert status == 422
        assert headers[SCOPE_HEADER].startswith("session-")
        assert body["error"]["type"] == "mamori_error"
        assert KEY not in json.dumps(body)
        assert not service.received
        assert lines(audit) == [], "a refused request must not read as a protection that happened"

    def test_the_other_statuses_are_the_ones_the_document_says(self) -> None:
        """502 for the upstream, 404 for a path this does not proxy. Pinned so
        the one-line table in the docs stays a table of facts."""
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            request = urllib.request.Request(
                proxy.url.replace("/chat/completions", "/embeddings"),
                data=b'{"input": "x"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=10)
            assert raised.value.code == 404
        with RunningProxy("http://127.0.0.1:1/v1/") as proxy:
            status, _, _ = post(proxy, chat("hello"))
        assert status == 502


class TestWhatATurnReplaced:
    def test_kinds_and_counts_and_nothing_else(self) -> None:
        """Occurrences, not distinct values: the same address twice is
        `EMAIL=2`, which is what `mamori protect` prints as *"2 value(s)
        protected"* and what a status line saying *"replaced 3 things in this
        turn"* means. A distinct count would be a fact about how many people
        are in the text, which is closer to a value than a count should get."""
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            _, headers, _ = post(proxy, chat(f"Mail {EMAIL}, {EMAIL} again, and call {NAME}."))
        assert headers[REPLACED_HEADER] == "EMAIL=2,PERSON=1"

    def test_absent_when_nothing_was_replaced(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            _, headers, _ = post(proxy, chat("The build is green."))
        assert REPLACED_HEADER not in headers


class TestReadiness:
    def test_health_answers_before_any_request(self) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            with urllib.request.urlopen(proxy.url.replace("/v1/chat/completions", "/health")) as r:
                assert r.status == 200
                assert json.loads(r.read())["status"] == "ok"

    def test_port_zero_announces_the_port_it_got(self, capsys: pytest.CaptureFixture[str]) -> None:
        """R3. The first line of stdout is the address, and it is the real
        one. An orchestrator that read `:0` could do nothing with it."""
        thread = threading.Thread(
            target=main,
            args=(["serve", "--upstream", "http://127.0.0.1:1/v1/", "--port", "0", "--quiet"],),
            daemon=True,
        )
        thread.start()
        deadline = time.monotonic() + 5
        first = ""
        while time.monotonic() < deadline and not first:
            out = capsys.readouterr().out
            first = next(
                (line for line in out.splitlines() if line.startswith("mamori proxy on")), ""
            )
            time.sleep(0.05)
        assert first, "the proxy never announced itself"
        port = int(first.rsplit(":", 1)[1].split("/")[0])
        assert port != 0
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
            assert r.status == 200


class TestPresidioShapedInspect:
    def test_four_keys_and_no_value(self, capsys: pytest.CaptureFixture[str]) -> None:
        """R4. What `iriguchi route --findings` reads, produced without an
        import. Note what is *not* here: the `--json` form's `preview` shows a
        value's first character, and this shows none."""
        assert main(["inspect", "--presidio", f"Review notes for E-45033 -- {NAME}, {EMAIL}"]) == 0
        rows = json.loads(capsys.readouterr().out)
        assert isinstance(rows, list) and rows
        for row in rows:
            assert set(row) == {"entity_type", "start", "end", "score"}
            assert 0.0 <= row["score"] <= 1.0
        assert {row["entity_type"] for row in rows} >= {"PERSON", "EMAIL"}
        rendered = json.dumps(rows)
        assert (
            EMAIL not in rendered
            and NAME not in rendered
            and "J"
            not in rendered.replace("entity_type", "")
            .replace("PERSON", "")
            .replace("EMAIL", "")
            .replace("IDENTIFIER", "")
        )

    def test_spans_index_the_text_it_was_given(self, capsys: pytest.CaptureFixture[str]) -> None:
        text = f"Mail {EMAIL} now"
        assert main(["inspect", "--presidio", text]) == 0
        rows = json.loads(capsys.readouterr().out)
        found = next(row for row in rows if row["entity_type"] == "EMAIL")
        assert text[found["start"] : found["end"]] == EMAIL


class TestAnUpstreamStatusThisLibraryHasNeverHeardOf:
    """A successful reply must not be lost to `HTTPStatus(...)`.

    The reply's status used to be relayed through the `HTTPStatus` enum, which
    raises `ValueError` on any code it does not know -- `299`, `218`, whatever
    a gateway or a later standard invents. That exception escaped `do_POST`,
    which handles `MamoriError` and nothing else, and the connection closed
    with **no response at all**: measured, a caller saw `RemoteDisconnected`
    and could not tell a protected answer that had arrived from a network that
    had failed.

    Only a 2xx reaches that line -- anything else becomes an `UpstreamError`
    and a `502` before it -- so every status this broke on was a successful
    reply being thrown away.
    """

    @pytest.mark.parametrize("status", [200, 201, 218, 226, 299])
    def test_it_is_relayed_and_the_answer_is_restored(self, status: int) -> None:
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            service.status = status
            service.reply = completion("Mailed <EMAIL_001>.")
            code, headers, body = post(proxy, chat(f"Mail {EMAIL}"))
        assert code == status
        assert body["choices"][0]["message"]["content"] == f"Mailed {EMAIL}."
        assert headers[SCOPE_HEADER].startswith("session-")

    def test_a_health_check_does_not_inherit_a_previous_reply(self) -> None:
        """`do_GET` clears the per-request state as `do_POST` does.

        Today `BaseHTTPRequestHandler` speaks HTTP/1.0 and closes after each
        reply, so one handler serves one request and there is nothing to
        inherit -- which is the point: the property would otherwise hold
        because of a default nobody wrote down, and a later
        `protocol_version = "HTTP/1.1"` would put one caller's scope on
        another's health check.
        """
        import http.client

        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            service.reply = completion("ok")
            host = proxy.url.split("//")[1].split("/")[0]
            connection = http.client.HTTPConnection(host, timeout=10)
            connection.request(
                "POST",
                "/v1/chat/completions",
                json.dumps(chat(f"Mail {EMAIL}")).encode(),
                {"Content-Type": "application/json"},
            )
            first = connection.getresponse()
            first.read()
            assert first.headers[SCOPE_HEADER].startswith("session-")

            connection.request("GET", "/health")
            second = connection.getresponse()
            second.read()
            connection.close()

        assert second.headers.get(SCOPE_HEADER) is None
        assert second.headers.get(REPLACED_HEADER) is None
