"""One conversation's values cannot come back in another's answer.

Sora puts more than one **person** on one machine -- profiles, switched like
Amazon's or YouTube's -- and asked for the guarantee in writing rather than
inferring it: *can A's `<PERSON_001>` ever be restored into B's answer?*

The answer is no, and it is worth being precise about why, because the
mechanism is not the one somebody would guess. Placeholder numbering restarts
per scope, so two conversations both mint `<PERSON_001>`; the tokens collide
by design. What keeps them apart is that **restoration resolves only what its
own scope allocated** -- a lookup keyed by `(scope, placeholder)`, not by
placeholder. So B's answer carrying `<PERSON_001>` resolves to B's person, and
A's value is not reachable from B's session at all.

That is the sentence `docs/orchestrating-the-proxy.md` states, and this file
is what it points at.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from mamori import MamoriConfig, PrivacySession
from mamori.application.conversations import ConversationRegistry
from mamori.infrastructure.audit import JsonlAuditSink
from mamori.infrastructure.storage import InMemoryMappingStore
from mamori.interfaces.proxy.server import SESSION_HEADER
from mamori.provenance import ProtectionLedger

from .test_proxy import FakeUpstream, RunningProxy, chat, completion
from .test_proxy_orchestration import post

ALICE = "alice@a.example.com"
BOB = "bob@b.example.com"


class TestTheConversationBoundaryIsTheRestorationBoundary:
    """The property Sora asked to be able to quote.

    **Two failures, and these tests do not both catch both.** Measured by
    poisoning: with the scope filter removed from `list_scope`, only
    `test_the_lookup_is_keyed_by_scope_and_token_together` goes red. The four
    proxy-level tests stay green, because the proxy gives each conversation
    its own store and a store that has forgotten how to filter still has only
    one conversation in it.

    So they cover different halves and it is worth saying which. The proxy
    tests catch a **routing** failure -- a request handed the wrong
    conversation's session, a token accepted that nothing minted. The shared
    store test catches a **lookup** failure -- a scope stopping being half the
    key. Neither alone would be enough, and a reader who assumed the four
    covered the mechanism would be assuming the wrong thing.
    """

    def test_one_conversation_cannot_restore_another_ones_value(self) -> None:
        """Both conversations mint `<EMAIL_001>`. Each gets its own back.

        This is the whole question in one test: the tokens *do* collide, and
        the values do not, because the lookup is keyed by scope and token
        together.
        """
        registry = ConversationRegistry(MamoriConfig().session)
        with FakeUpstream() as service, RunningProxy(service.url, conversations=registry) as proxy:
            service.reply = completion("ok")
            _, alice_headers, _ = post(proxy, chat(f"Mail {ALICE}"))
            _, bob_headers, _ = post(proxy, chat(f"Mail {BOB}"))
            alice_token = alice_headers[SESSION_HEADER]
            bob_token = bob_headers[SESSION_HEADER]
            assert alice_token != bob_token

            # The upstream answers Bob's conversation with the token Alice's
            # conversation also minted. If anything crossed, Alice's address
            # would arrive here.
            service.reply = completion("I have written to <EMAIL_001>.")
            _, _, bob_reply = post(proxy, chat("and again?"), **{SESSION_HEADER: bob_token})
            _, _, alice_reply = post(proxy, chat("and again?"), **{SESSION_HEADER: alice_token})

        assert bob_reply["choices"][0]["message"]["content"] == f"I have written to {BOB}."
        assert ALICE not in json.dumps(bob_reply)
        assert alice_reply["choices"][0]["message"]["content"] == f"I have written to {ALICE}."
        assert BOB not in json.dumps(alice_reply)

    def test_a_token_nothing_minted_starts_a_conversation_that_knows_nothing(self) -> None:
        registry = ConversationRegistry(MamoriConfig().session)
        with FakeUpstream() as service, RunningProxy(service.url, conversations=registry) as proxy:
            service.reply = completion("ok")
            post(proxy, chat(f"Mail {ALICE}"))
            service.reply = completion("I have written to <EMAIL_001>.")
            _, headers, reply = post(proxy, chat("hello"), **{SESSION_HEADER: "not-a-real-token"})

        # Nothing resolved it, so it is still standing where a reader can see it.
        assert reply["choices"][0]["message"]["content"] == "I have written to <EMAIL_001>."
        assert ALICE not in json.dumps(reply)
        assert headers[SESSION_HEADER] != "not-a-real-token"

    def test_without_conversations_every_request_is_its_own_boundary(self) -> None:
        """The default. One scope per request, purged on the way out, so a
        second request cannot resolve the first one's tokens either."""
        with FakeUpstream() as service, RunningProxy(service.url) as proxy:
            service.reply = completion("ok")
            post(proxy, chat(f"Mail {ALICE}"))
            service.reply = completion("I have written to <EMAIL_001>.")
            _, _, reply = post(proxy, chat("hello"))
        assert reply["choices"][0]["message"]["content"] == "I have written to <EMAIL_001>."
        assert ALICE not in json.dumps(reply)

    def test_the_lookup_is_keyed_by_scope_and_token_together(self) -> None:
        """The mechanism, under the proxy, so a change to it fails here too.

        A store is asked for `(scope, placeholder)`. Sharing one store between
        two scopes -- which the proxy does not do, but a caller might -- still
        keeps them apart, because the scope is half the key.
        """
        store = InMemoryMappingStore()
        with (
            PrivacySession(store=store, scope="alice") as alice,
            PrivacySession(store=store, scope="bob") as bob,
        ):
            alice_text = alice.protect(f"Mail {ALICE}").protected_text
            bob_text = bob.protect(f"Mail {BOB}").protected_text
            assert alice_text == bob_text, "the tokens must collide, or this proves nothing"

            assert bob.restore(alice_text).text == f"Mail {BOB}"
            assert alice.restore(bob_text).text == f"Mail {ALICE}"

    def test_ending_a_conversation_purges_it(self) -> None:
        registry = ConversationRegistry(MamoriConfig().session)
        with FakeUpstream() as service, RunningProxy(service.url, conversations=registry) as proxy:
            service.reply = completion("ok")
            _, headers, _ = post(proxy, chat(f"Mail {ALICE}"))
            token = headers[SESSION_HEADER]
            post(proxy, chat("done"), **{SESSION_HEADER: token, "X-Mamori-Session-End": "true"})

            service.reply = completion("I have written to <EMAIL_001>.")
            _, _, after = post(proxy, chat("hello"), **{SESSION_HEADER: token})
        assert after["choices"][0]["message"]["content"] == "I have written to <EMAIL_001>."
        assert ALICE not in json.dumps(after)


class TestNothingTheProxyProtectsReachesADisk:
    """Why killing the process is a complete purge.

    Sora switches profiles by stopping the proxy and starting another. That is
    only a purge if there is nowhere for a mapping to have gone, so the claim
    is structural rather than observational: there is no configuration that
    gives the proxy a persistent store, so there is no file to forget to
    delete.
    """

    def test_no_setting_can_give_the_proxy_a_store(self) -> None:
        stateful = [
            name
            for name in MamoriConfig.__dataclass_fields__
            if any(word in name for word in ("stor", "persist", "mapping", "disk", "file"))
        ]
        assert stateful == [], (
            f"{stateful} could name a store, and this test is the reason the "
            "process-death guarantee in docs/orchestrating-the-proxy.md is safe to make"
        )

    def test_the_serve_command_never_passes_one(self) -> None:
        """`mamori serve` builds sessions through `config.session()` with no
        `store`, which is an `InMemoryMappingStore` every time."""
        import importlib
        import inspect

        module = importlib.import_module("mamori.interfaces.cli.main")
        source = inspect.getsource(module._cmd_serve)
        # `store=` rather than the word: the printed guidance says "restored",
        # and a check that matched prose would fail on a sentence rather than
        # on a store.
        assert "store=" not in source, source
        assert "config.session," in source, "the registry no longer builds sessions from settings"

    def test_a_session_the_proxy_would_build_holds_its_mappings_in_memory(self) -> None:
        session = MamoriConfig().session()
        try:
            session.protect(f"Mail {ALICE}")
            store = session._store
            assert isinstance(store, InMemoryMappingStore)
        finally:
            session.close()

    def test_the_only_file_the_proxy_writes_holds_no_value(self, tmp_path: Path) -> None:
        audit = tmp_path / "audit.jsonl"
        with (
            FakeUpstream() as service,
            RunningProxy(
                service.url, audit=ProtectionLedger(JsonlAuditSink(audit), by="sora/0.6")
            ) as proxy,
        ):
            service.reply = completion("ok")
            post(proxy, chat(f"Mail {ALICE} and {BOB}"))

        written = sorted(p.name for p in tmp_path.iterdir())
        assert written == ["audit.jsonl"], written
        raw = audit.read_text(encoding="utf-8")
        assert ALICE not in raw
        assert BOB not in raw


class TestStartingAndStoppingRepeatedly:
    """Sora restarts the proxy on every profile switch. It asked what that
    costs and whether a half-written audit line can be left behind."""

    def test_a_restart_costs_a_fraction_of_a_second(self) -> None:
        """Readiness, not import: the interpreter is already up in Sora's
        case because it spawns a child, but the socket and the rule set are
        what a switch pays for."""
        with FakeUpstream() as service:
            worst = 0.0
            for _ in range(3):
                start = time.perf_counter()
                with RunningProxy(service.url) as proxy:
                    with urllib.request.urlopen(
                        proxy.url.replace("/v1/chat/completions", "/health"), timeout=5
                    ) as response:
                        assert response.status == 200
                    worst = max(worst, time.perf_counter() - start)
        assert worst < 3.0, f"a start-to-ready cycle took {worst:.2f}s"

    def test_each_start_takes_its_own_free_port(self) -> None:
        ports = set()
        with FakeUpstream() as service:
            for _ in range(3):
                with RunningProxy(service.url) as proxy:
                    ports.add(proxy.url.rsplit(":", 1)[1].split("/")[0])
        assert len(ports) == 3, f"a restart reused a port: {ports}"

    def test_an_audit_line_is_written_whole_or_not_at_all(self, tmp_path: Path) -> None:
        """So a proxy killed mid-request cannot leave half a record.

        The sink encodes the line once and writes it in a single `os.write`
        under a lock. A process that dies has either written that buffer or
        not; there is no state in between for a reader to trip over.
        """
        audit = tmp_path / "audit.jsonl"
        ledger = ProtectionLedger(JsonlAuditSink(audit), by="sora/0.6")
        crowded = " ".join(f"person{n}@example.com" for n in range(200))
        with MamoriConfig().session() as session:
            ledger.record(session.protect(crowded), session=session)

        text = audit.read_text(encoding="utf-8")
        assert text.endswith("\n"), "the line was left unterminated"
        assert len(text.splitlines()) == 1
        json.loads(text)  # raises if it is not one whole record
