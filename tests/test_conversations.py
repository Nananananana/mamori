"""Conversations: sessions that outlive one request.

Two things are under test here and they are not the same thing.

The first is the registry itself -- what it holds, for how long, and what it
does when it is full. Those are the properties that decide how much real data
this process is sitting on, so they are tested with an injected clock rather
than by waiting.

The second is the case the registry exists for. A client that resends its whole
conversation each turn never needed any of this, and there is a test below that
proves it rather than assuming it. A client that sends only the new turn did,
and before 0.16 it got a placeholder printed at a human.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from mamori import MamoriConfig, PrivacySession
from mamori.application.conversations import ConversationRegistry
from mamori.interfaces.proxy.server import END_HEADER, SESSION_HEADER

from .test_proxy import NAME, FakeUpstream, RunningProxy, chat, completion


class FakeClock:
    """Monotonic seconds that only move when a test says so."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def registry(**kwargs: Any) -> ConversationRegistry:
    return ConversationRegistry(PrivacySession, **kwargs)


class TestNamingAConversation:
    def test_a_new_conversation_gets_a_token(self) -> None:
        conversation = registry().resume(None)
        assert conversation.token
        assert len(conversation.token) >= 20

    def test_two_conversations_are_not_the_same_one(self) -> None:
        reg = registry()
        first, second = reg.resume(None), reg.resume(None)
        assert first.token != second.token
        assert first.session is not second.session
        assert first.session.scope != second.session.scope

    def test_a_known_token_comes_back_to_the_same_session(self) -> None:
        reg = registry()
        first = reg.resume(None)
        again = reg.resume(first.token)
        assert again is first
        assert again.turns == 1

    def test_an_unknown_token_starts_a_new_conversation(self) -> None:
        """It does not say the token was unknown.

        Answering "no such conversation" would tell anybody who asked which
        tokens exist, and the caller wanted a conversation rather than an
        answer about one.
        """
        reg = registry()
        mine = reg.resume(None)
        theirs = reg.resume("not-a-token-anybody-minted")
        assert theirs.token != mine.token
        assert theirs.session is not mine.session

    def test_a_token_is_not_derived_from_anything_the_caller_sent(self) -> None:
        reg = registry()
        tokens = {reg.resume(None).token for _ in range(20)}
        assert len(tokens) == 20


class TestWhatItHolds:
    def test_ending_one_discards_its_mappings(self) -> None:
        reg = registry()
        conversation = reg.resume(None)
        conversation.session.protect(f"{NAME}さんの件")
        assert reg.end(conversation.token) is True
        assert conversation.session.restore("<PERSON_001>").text == "<PERSON_001>"

    def test_ending_one_that_is_not_there(self) -> None:
        assert registry().end("nothing") is False

    def test_it_expires_when_nobody_speaks_to_it(self) -> None:
        clock = FakeClock()
        reg = registry(idle_seconds=60, clock=clock)
        conversation = reg.resume(None)
        conversation.session.protect(f"{NAME}さんの件")

        clock.advance(61)
        assert reg.sweep() == 1
        assert len(reg) == 0
        assert conversation.session.restore("<PERSON_001>").text == "<PERSON_001>"

    def test_speaking_to_it_keeps_it_alive(self) -> None:
        clock = FakeClock()
        reg = registry(idle_seconds=60, clock=clock)
        conversation = reg.resume(None)
        for _ in range(5):
            clock.advance(59)
            assert reg.resume(conversation.token) is conversation
        assert len(reg) == 1

    def test_expiry_happens_on_the_path_that_uses_it(self) -> None:
        """No background thread. A timer that purges secrets fails silently."""
        clock = FakeClock()
        reg = registry(idle_seconds=60, clock=clock)
        reg.resume(None)
        clock.advance(61)
        reg.resume(None)
        assert len(reg) == 1

    def test_the_ceiling_evicts_the_oldest(self) -> None:
        clock = FakeClock()
        reg = registry(max_conversations=2, clock=clock)
        first = reg.resume(None)
        clock.advance(1)
        second = reg.resume(None)
        clock.advance(1)
        third = reg.resume(None)

        assert len(reg) == 2
        assert reg.resume(second.token) is second
        assert reg.resume(third.token) is third
        assert reg.resume(first.token).token != first.token

    def test_an_evicted_conversation_is_purged_not_forgotten(self) -> None:
        reg = registry(max_conversations=1)
        first = reg.resume(None)
        first.session.protect(f"{NAME}さんの件")
        reg.resume(None)
        assert first.session.restore("<PERSON_001>").text == "<PERSON_001>"

    def test_closing_everything(self) -> None:
        reg = registry()
        conversations = [reg.resume(None) for _ in range(3)]
        assert reg.close_all() == 3
        assert len(reg) == 0
        for conversation in conversations:
            assert conversation.session.restore("<PERSON_001>").text == "<PERSON_001>"

    def test_the_description_is_counts_and_durations(self) -> None:
        reg = registry(idle_seconds=1800, max_conversations=8)
        reg.resume(None).session.protect(f"{NAME}さんの件")
        described = reg.describe()
        assert NAME not in described
        assert "1 of 8" in described
        assert "30 minute" in described

    @pytest.mark.parametrize(
        "kwargs", [{"idle_seconds": 0}, {"idle_seconds": -1}, {"max_conversations": 0}]
    )
    def test_a_bound_that_does_not_bind_is_refused(self, kwargs: Any) -> None:
        with pytest.raises(ValueError):
            registry(**kwargs)


class TestTheClaimThatWasMadeWithoutAConversation:
    """One scope per request was defended by an argument. This checks it.

    The argument was that a chat client resends the whole conversation each
    turn, so the same values meet the same allocator in the same order and land
    on the same placeholders. It is correct, it is why the default is still
    fine for most clients, and it had never been tested.
    """

    def test_resending_the_history_gives_the_same_placeholders(self) -> None:
        turn_one = f"{NAME}さんの契約について教えてください。"
        turn_two = "住所も確認したいです。"

        with PrivacySession() as first:
            one = first.protect(turn_one).protected_text
        with PrivacySession() as second:
            again = second.protect(turn_one).protected_text
            follow_up = second.protect(turn_two).protected_text

        assert one == again
        assert "<PERSON_001>" in one
        assert follow_up == turn_two

    def test_sending_only_the_new_turn_loses_the_mapping(self) -> None:
        """The case conversations exist for, stated as a failure.

        A fresh scope has never heard of <PERSON_001>, so a reply that uses it
        comes back with the placeholder still in it -- which is a token printed
        at a human.
        """
        with PrivacySession() as turn_one:
            turn_one.protect(f"{NAME}さんの契約について")
        with PrivacySession() as turn_two:
            restored = turn_two.restore("<PERSON_001>さんの住所は東京都です。").text
        assert "<PERSON_001>" in restored
        assert NAME not in restored


class TestThroughTheProxy:
    """The same thing, over a socket, which is where clients actually meet it."""

    def post(
        self, proxy: RunningProxy, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> tuple[int, Any, dict[str, str]]:
        request = urllib.request.Request(
            proxy.url,
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read()), dict(response.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read()), dict(exc.headers)

    def test_the_default_names_no_conversation(self) -> None:
        with FakeUpstream() as upstream:
            upstream.reply = completion("承知しました。")
            with RunningProxy(upstream.url) as proxy:
                _, _, headers = self.post(proxy, chat("こんにちは"))
        assert SESSION_HEADER not in headers

    def test_a_conversation_is_named_on_the_way_back(self) -> None:
        with FakeUpstream() as upstream:
            upstream.reply = completion("承知しました。")
            with RunningProxy(upstream.url, conversations=registry()) as proxy:
                _, _, headers = self.post(proxy, chat("こんにちは"))
        assert headers[SESSION_HEADER]

    def test_a_later_turn_restores_a_value_from_an_earlier_one(self) -> None:
        """The whole point. Turn two sends only the new message."""
        with (
            FakeUpstream() as upstream,
            RunningProxy(upstream.url, conversations=registry()) as proxy,
        ):
            upstream.reply = completion("確認します。")
            _, _, headers = self.post(proxy, chat(f"{NAME}さんの契約について"))
            token = headers[SESSION_HEADER]

            # The service answers the second turn talking about the placeholder
            # it was given in the first.
            upstream.reply = completion("<PERSON_001>さんの住所は東京都です。")
            _, body, again = self.post(proxy, chat("住所は？"), {SESSION_HEADER: token})

        assert again[SESSION_HEADER] == token
        assert NAME in body["choices"][0]["message"]["content"]
        assert "<PERSON_001>" not in body["choices"][0]["message"]["content"]

    def test_without_the_header_the_same_second_turn_does_not_restore(self) -> None:
        with (
            FakeUpstream() as upstream,
            RunningProxy(upstream.url, conversations=registry()) as proxy,
        ):
            upstream.reply = completion("確認します。")
            self.post(proxy, chat(f"{NAME}さんの契約について"))
            upstream.reply = completion("<PERSON_001>さんの住所は東京都です。")
            _, body, _ = self.post(proxy, chat("住所は？"))

        assert "<PERSON_001>" in body["choices"][0]["message"]["content"]

    def test_a_forged_token_reaches_nobody_elses_mappings(self) -> None:
        with (
            FakeUpstream() as upstream,
            RunningProxy(upstream.url, conversations=registry()) as proxy,
        ):
            upstream.reply = completion("確認します。")
            _, _, headers = self.post(proxy, chat(f"{NAME}さんの契約について"))
            stolen = headers[SESSION_HEADER]

            upstream.reply = completion("<PERSON_001>さんの住所は東京都です。")
            _, body, given = self.post(
                proxy, chat("住所は？"), {SESSION_HEADER: stolen[:-4] + "aaaa"}
            )

        assert given[SESSION_HEADER] != stolen
        assert "<PERSON_001>" in body["choices"][0]["message"]["content"]

    def test_a_client_can_end_its_conversation(self) -> None:
        reg = registry()
        with FakeUpstream() as upstream, RunningProxy(upstream.url, conversations=reg) as proxy:
            upstream.reply = completion("確認します。")
            _, _, headers = self.post(proxy, chat(f"{NAME}さんの契約について"))
            token = headers[SESSION_HEADER]
            assert len(reg) == 1
            self.post(proxy, chat("ありがとう"), {SESSION_HEADER: token, END_HEADER: "1"})
        assert len(reg) == 0

    def test_the_end_header_needs_a_clear_yes(self) -> None:
        reg = registry()
        with FakeUpstream() as upstream, RunningProxy(upstream.url, conversations=reg) as proxy:
            upstream.reply = completion("確認します。")
            _, _, headers = self.post(proxy, chat("こんにちは"))
            self.post(
                proxy,
                chat("まだ続きます"),
                {SESSION_HEADER: headers[SESSION_HEADER], END_HEADER: "later"},
            )
        assert len(reg) == 1

    def test_health_says_whether_anything_is_kept(self) -> None:
        with FakeUpstream() as upstream:
            with RunningProxy(upstream.url) as plain:
                assert self._health(plain)["conversations"] is False
            with RunningProxy(upstream.url, conversations=registry()) as keeping:
                assert self._health(keeping)["conversations"] is True

    def test_health_says_nothing_about_how_many(self) -> None:
        reg = registry()
        with FakeUpstream() as upstream, RunningProxy(upstream.url, conversations=reg) as proxy:
            upstream.reply = completion("ok")
            self.post(proxy, chat(f"{NAME}さんの件"))
            body = self._health(proxy)
        assert set(body) == {"status", "proxies", "conversations"}

    def _health(self, proxy: RunningProxy) -> Any:
        url = proxy.url.replace("/v1/chat/completions", "/health")
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read())


class TestTheRegistryIsBuiltFromSettings:
    def test_a_config_makes_the_sessions(self) -> None:
        config = MamoriConfig(locales=("ja",))
        reg = ConversationRegistry(config.session)
        conversation = reg.resume(None)
        assert "<PERSON_001>" in conversation.session.protect(f"{NAME}さんの件").protected_text
        reg.close_all()


class TestAnInFlightConversationIsNotPurged:
    """Eviction and expiry both call `session.close()`, which purges a scope.

    Both could pick a conversation another thread was *between protect and
    restore on*: `_evict_oldest` chooses the least recently used, and an
    in-flight request set `last_used` when it started. Measured over HTTP with
    a slow upstream: 12 concurrent callers against a ceiling of 8, and **4 of
    12 replies came back with a raw `<PERSON_001>` in them** -- a placeholder
    printed at a human, for a name that caller sent in that same request.
    """

    def registry(self, **kwargs: object) -> ConversationRegistry:
        return ConversationRegistry(PrivacySession, **kwargs)  # type: ignore[arg-type]

    def test_a_held_conversation_is_not_evicted(self) -> None:
        registry = self.registry(max_conversations=1)
        with registry.checkout(None) as busy:
            registry.resume(None)  # forces the ceiling
            assert registry.resume(busy.token) is busy

    def test_a_held_conversation_is_not_swept(self) -> None:
        clock = [0.0]
        registry = self.registry(idle_seconds=1.0, clock=lambda: clock[0])
        with registry.checkout(None) as busy:
            clock[0] = 100.0
            assert registry.sweep() == 0
            assert registry.resume(busy.token) is busy

    def test_its_mappings_survive_the_whole_request(self) -> None:
        """The failure as a caller sees it: a value protected at the start of a
        request and a placeholder still in the answer at the end."""
        registry = self.registry(max_conversations=1)
        with registry.checkout(None) as busy:
            protected = busy.session.protect("Dear Priya Raman, hello.").protected_text
            registry.resume(None)  # another caller arrives and forces eviction
            assert "Priya Raman" in busy.session.restore(protected).text

    def test_the_ceiling_is_exceeded_rather_than_an_active_scope_destroyed(self) -> None:
        """When everything is in flight there is nothing to evict. The excess is
        bounded by the number of concurrent requests, which the server bounds
        already; the ceiling bounds what is *kept*, and a request in progress is
        not being kept."""
        registry = self.registry(max_conversations=1)
        with registry.checkout(None), registry.checkout(None):
            assert len(registry) == 2

    def test_it_is_evictable_again_afterwards(self) -> None:
        registry = self.registry(max_conversations=1)
        with registry.checkout(None) as first:
            pass
        registry.resume(None)
        assert registry.resume(first.token) is not first

    def test_resume_alone_does_not_hold(self) -> None:
        """Deliberate. A `resume` that held would need a `release` from every
        caller, and one who forgot would leave a conversation nothing can ever
        evict -- trading a purged scope for one that lives forever, which is
        worse in a library whose point is not keeping values."""
        registry = self.registry(max_conversations=1)
        first = registry.resume(None)
        registry.resume(None)
        assert registry.resume(first.token) is not first

    def test_release_is_forgiving_of_an_unknown_token(self) -> None:
        registry = self.registry()
        registry.release("no such token")

    def test_holding_twice_needs_releasing_twice(self) -> None:
        registry = self.registry(max_conversations=1)
        conversation = registry.resume(None)
        registry.hold(conversation.token)
        registry.hold(conversation.token)
        registry.release(conversation.token)
        registry.resume(None)
        assert registry.resume(conversation.token) is conversation
