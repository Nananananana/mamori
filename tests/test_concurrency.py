"""Two callers at once, which is the only way a proxy is ever used.

Every test of the conversation registry so far has been sequential, and the
property that matters most about it is not sequential: **one caller's values
must never reach another's answer**. The registry hands out sessions, the
sessions share a store, and the store partitions by scope — three pieces of
locking whose interaction has been argued rather than exercised.

These run real threads against a real socket, because that is where an
interleaving that only happens under load would show up and nowhere else.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from typing import Any

import pytest

from mamori import MamoriConfig, PrivacySession
from mamori.application.conversations import ConversationRegistry
from mamori.interfaces.proxy.server import SESSION_HEADER

from .test_proxy import FakeUpstream, RunningProxy, chat, completion

#: One distinct person per caller, so a leak between them is unmistakable.
CALLERS = [
    ("Priya Raman", "priya.raman@example.com"),
    ("Michael Chen", "michael.chen@example.org"),
    ("Robert Lang", "robert.lang@example.net"),
    ("Sarah Klein", "sarah.klein@example.com"),
    ("Tom Baker", "tom.baker@example.org"),
    ("Ann Mercer", "ann.mercer@example.net"),
]


class TestTheRegistryUnderLoad:
    def test_conversations_do_not_borrow_each_others_values(self) -> None:
        """Six callers, one registry, one value each, all at once."""
        registry = ConversationRegistry(MamoriConfig(locales=("en",)).session)
        results: dict[str, str] = {}
        errors: list[BaseException] = []
        start = threading.Barrier(len(CALLERS))

        def caller(name: str, email: str) -> None:
            try:
                start.wait(timeout=10)
                conversation = registry.resume(None)
                for _ in range(8):
                    protected = conversation.session.protect(f"Dear {name}, mail {email}.")
                    assert name not in protected.protected_text
                    restored = conversation.session.restore(protected.protected_text).text
                    results[name] = restored
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=caller, args=pair) for pair in CALLERS]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not errors, errors
        for name, email in CALLERS:
            assert results[name] == f"Dear {name}, mail {email}."
            others = [v for k, v in results.items() if k != name]
            assert not any(name in other for other in others), "a value crossed conversations"

    def test_resuming_the_same_conversation_from_several_threads(self) -> None:
        """One client, several in-flight requests. They share a scope on
        purpose, so what must hold is that the mapping table stays coherent."""
        registry = ConversationRegistry(MamoriConfig(locales=("en",)).session)
        conversation = registry.resume(None)
        seen: list[str] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def turn(index: int) -> None:
            try:
                text = f"Dear Priya Raman, this is turn {index}."
                protected = conversation.session.protect(text)
                with lock:
                    seen.append(protected.protected_text)
                assert conversation.session.restore(protected.protected_text).text == text
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=turn, args=(index,)) for index in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not errors, errors
        # One person, one placeholder, however many threads asked for it.
        placeholders = {line.split(",")[0].removeprefix("Dear ") for line in seen}
        assert placeholders == {"<PERSON_001>"}

    def test_the_ceiling_holds_while_everybody_is_asking(self) -> None:
        """Eviction runs on the same path as resume, so it races with itself."""
        registry = ConversationRegistry(MamoriConfig(locales=("en",)).session, max_conversations=4)
        errors: list[BaseException] = []

        def churn() -> None:
            try:
                for _ in range(20):
                    conversation = registry.resume(None)
                    conversation.session.protect("Dear Priya Raman, hello.")
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=churn) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert not errors, errors
        assert len(registry) <= 4, "the ceiling is a ceiling under load too"


class TestTheProxyUnderLoad:
    """The same question over sockets, where the threading is the server's."""

    def post(self, url: str, payload: dict[str, Any], token: str | None) -> tuple[Any, str]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers[SESSION_HEADER] = token
        request = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read()), response.headers.get(SESSION_HEADER, "")

    def test_six_callers_get_their_own_values_back(self) -> None:
        registry = ConversationRegistry(MamoriConfig(locales=("en",)).session)
        answers: dict[str, str] = {}
        errors: list[BaseException] = []

        with (
            FakeUpstream() as upstream,
            RunningProxy(
                upstream.url, config=MamoriConfig(locales=("en",)), conversations=registry
            ) as proxy,
        ):
            upstream.reply = completion("Noted: <PERSON_001>.")
            start = threading.Barrier(len(CALLERS))

            def caller(name: str, email: str) -> None:
                try:
                    start.wait(timeout=10)
                    body, token = self.post(proxy.url, chat(f"Dear {name}, mail {email}."), None)
                    assert token, "a conversation was named"
                    body, _ = self.post(proxy.url, chat("and again"), token)
                    answers[name] = body["choices"][0]["message"]["content"]
                except BaseException as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=caller, args=pair) for pair in CALLERS]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)

        assert not errors, errors
        for name, _ in CALLERS:
            assert answers[name] == f"Noted: {name}.", "each caller got their own name back"

    def test_nothing_sensitive_reached_the_upstream(self) -> None:
        """The one that matters whatever else happens."""
        registry = ConversationRegistry(MamoriConfig(locales=("en",)).session)
        with (
            FakeUpstream() as upstream,
            RunningProxy(
                upstream.url, config=MamoriConfig(locales=("en",)), conversations=registry
            ) as proxy,
        ):
            upstream.reply = completion("ok")
            threads = [
                threading.Thread(
                    target=self.post,
                    args=(proxy.url, chat(f"Dear {name}, mail {email}."), None),
                )
                for name, email in CALLERS
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)
            sent = json.dumps(upstream.received, ensure_ascii=False)

        for name, email in CALLERS:
            assert name not in sent
            assert email not in sent


class TestOneSessionFromManyThreads:
    """A caller who shares a session, which the docs neither promise nor forbid."""

    def test_the_store_stays_coherent(self) -> None:
        errors: list[BaseException] = []
        with PrivacySession(locales=("en",)) as session:

            def work(index: int) -> None:
                try:
                    text = f"Dear {CALLERS[index % len(CALLERS)][0]}, hello."
                    assert session.restore(session.protect(text).protected_text).text == text
                except BaseException as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=work, args=(index,)) for index in range(24)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
        assert not errors, errors


@pytest.mark.parametrize("run", range(3))
def test_it_is_not_flaky(run: int) -> None:
    """Concurrency bugs that appear one run in ten are the ones that matter,
    so the cheapest of these runs a few times."""
    registry = ConversationRegistry(MamoriConfig(locales=("en",)).session)
    errors: list[BaseException] = []

    def caller(name: str) -> None:
        try:
            conversation = registry.resume(None)
            protected = conversation.session.protect(f"Dear {name}, hello.")
            assert name not in protected.protected_text
            assert conversation.session.restore(protected.protected_text).text == (
                f"Dear {name}, hello."
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=caller, args=(name,)) for name, _ in CALLERS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, errors
