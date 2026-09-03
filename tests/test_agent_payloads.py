"""Where an agent's personal data actually lives.

A chat payload is not one place with text in it. By the time an application is
an agent, most of the personal data has moved out of the prose and into the
structure around it: the arguments of a tool call, the name on a message, the
example in a tool's description, the end-user identifier.

Until 0.18 this library protected the prose. ``messages.py`` said a tool call
was "not text" and passed it through untouched, which was true of the *call*
and false of its ``arguments`` -- a JSON string that a caller wrote and that
routinely holds an address, a name and a phone number at once.

The tests are written from the leak outwards: what went upstream in the clear,
then what came back that an application could not use.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from mamori import MamoriConfig, PrivacySession
from mamori.errors import MamoriError
from mamori.interfaces.proxy.exchange import (
    StreamRestoration,
    protect_request,
    restore_reply,
)
from mamori.interfaces.proxy.messages import request_texts, with_texts

EMAIL = "jane.doe@example.com"
NAME = "Jane Doe"
PHONE = "415-555-0198"


def tool_call(arguments: dict[str, Any], name: str = "send_email") -> dict[str, Any]:
    return {
        "id": "call_1",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def agent_payload() -> dict[str, Any]:
    """One turn of an agent loop: a request, a call, a result."""
    return {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "Email the contract to Jane."},
            {
                "role": "assistant",
                "tool_calls": [tool_call({"to": EMAIL, "body": f"Dear {NAME},"})],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": f"sent to {EMAIL}"},
        ],
    }


def sent(payload: dict[str, Any]) -> str:
    """Everything that would go over the wire, as one string to search."""
    return json.dumps(payload, ensure_ascii=False)


class TestWhatUsedToGoUpstream:
    @pytest.mark.parametrize("value", [EMAIL, NAME])
    def test_a_tool_calls_arguments_are_protected(self, value: str) -> None:
        with PrivacySession() as session:
            protected, _ = protect_request(session, agent_payload(), add_guidance=False)
        assert value not in sent(protected)

    def test_the_arguments_are_still_json(self) -> None:
        """An application parses them. A protected span that crossed a quote
        would turn a payload into a parse error in somebody else's process."""
        with PrivacySession() as session:
            protected, _ = protect_request(session, agent_payload(), add_guidance=False)
        arguments = protected["messages"][1]["tool_calls"][0]["function"]["arguments"]
        parsed = json.loads(arguments)
        assert set(parsed) == {"to", "body"}
        assert parsed["to"].startswith("<EMAIL_")

    def test_the_tool_name_is_not_touched(self) -> None:
        """It is a function name in the caller's own code."""
        with PrivacySession() as session:
            protected, _ = protect_request(session, agent_payload(), add_guidance=False)
        assert protected["messages"][1]["tool_calls"][0]["function"]["name"] == "send_email"

    def test_a_participant_name_is_a_name(self) -> None:
        payload = {"messages": [{"role": "user", "name": NAME, "content": "hello"}]}
        with PrivacySession() as session:
            protected, _ = protect_request(session, payload, add_guidance=False)
        assert NAME not in sent(protected)

    def test_an_example_in_a_tool_description(self) -> None:
        payload = {
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "send_email",
                        "description": f"Send mail. Example: to={EMAIL}",
                        "parameters": {
                            "type": "object",
                            "properties": {"to": {"type": "string", "description": f"e.g. {NAME}"}},
                        },
                    },
                }
            ],
        }
        with PrivacySession() as session:
            protected, _ = protect_request(session, payload, add_guidance=False)
        assert EMAIL not in sent(protected)
        assert NAME not in sent(protected)

    def test_the_schema_itself_survives(self) -> None:
        """Only `description` is text. Replacing `"type": "string"` would turn
        a valid schema into a broken one."""
        payload = {
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "send_email",
                        "description": f"mail {EMAIL}",
                        "parameters": {
                            "type": "object",
                            "required": ["to"],
                            "properties": {"to": {"type": "string"}},
                        },
                    },
                }
            ],
        }
        with PrivacySession() as session:
            protected, _ = protect_request(session, payload, add_guidance=False)
        assert (
            protected["tools"][0]["function"]["parameters"]
            == payload["tools"][0]["function"]["parameters"]  # type: ignore[index]
        )

    def test_the_end_user_identifier(self) -> None:
        payload = {"messages": [{"role": "user", "content": "hi"}], "user": "tanaka@example.com"}
        with PrivacySession() as session:
            protected, _ = protect_request(session, payload, add_guidance=False)
        assert protected["user"].startswith("<EMAIL_")

    def test_metadata(self) -> None:
        payload = {
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"requested_by": NAME, "ticket": "SUP-4127"},
        }
        with PrivacySession() as session:
            protected, _ = protect_request(session, payload, add_guidance=False)
        assert NAME not in sent(protected)
        assert protected["metadata"]["ticket"] == "SUP-4127"

    def test_every_slot_is_counted_in_the_report(self) -> None:
        with PrivacySession() as session:
            _, report = protect_request(session, agent_payload(), add_guidance=False)
        assert report.scanned_messages == len(request_texts(agent_payload()))
        assert report.total_replaced >= 3

    def test_the_report_still_never_holds_a_value(self) -> None:
        with PrivacySession() as session:
            _, report = protect_request(session, agent_payload(), add_guidance=False)
        described = " ".join(slot.where for slot in report.slots)
        assert EMAIL not in described
        assert NAME not in described


class TestReplacementFollowsThePath:
    """The walk and the rebuild are two halves of one rule.

    They used to be paired by position, which works exactly as long as both are
    edited together -- so adding a place to look was a chance to leak the place
    you added. Slots carry a path now.
    """

    def test_a_slot_knows_where_it_came_from(self) -> None:
        slots = request_texts(agent_payload())
        paths = {slot.path for slot in slots}
        assert ("messages", 0, "content") in paths
        assert ("messages", 1, "tool_calls", 0, "function", "arguments") in paths

    def test_replacements_land_where_the_slot_was(self) -> None:
        payload = agent_payload()
        texts = [f"[{index}]" for index in range(len(request_texts(payload)))]
        rebuilt = with_texts(payload, texts)
        assert rebuilt["messages"][0]["content"] == "[0]"
        assert rebuilt["messages"][1]["tool_calls"][0]["function"]["arguments"] == "[1]"
        assert rebuilt["messages"][2]["content"] == "[2]"

    def test_nothing_else_is_rewritten(self) -> None:
        payload = agent_payload()
        rebuilt = with_texts(payload, [s.text for s in request_texts(payload)])
        assert rebuilt == payload

    def test_a_miscount_is_still_refused(self) -> None:
        with pytest.raises(ValueError):
            with_texts(agent_payload(), ["only one"])


class TestWhatComesBack:
    """A model that answers with a call rather than a sentence."""

    def reply_with_call(self, arguments: str) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_2",
                                "type": "function",
                                "function": {"name": "send_email", "arguments": arguments},
                            }
                        ],
                    },
                }
            ]
        }

    def test_a_placeholder_in_the_arguments_is_restored(self) -> None:
        with PrivacySession() as session:
            protected, _ = protect_request(session, agent_payload(), add_guidance=False)
            arguments = protected["messages"][1]["tool_calls"][0]["function"]["arguments"]
            restored = restore_reply(session, self.reply_with_call(arguments))
        parsed = json.loads(
            restored["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        )
        assert parsed["to"] == EMAIL
        assert NAME in parsed["body"]

    def test_a_placeholder_this_session_never_allocated_is_left_alone(self) -> None:
        with PrivacySession() as session:
            session.protect("nothing sensitive here")
            restored = restore_reply(session, self.reply_with_call('{"to": "<EMAIL_042>"}'))
        arguments = restored["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        assert "<EMAIL_042>" in arguments

    def test_content_is_still_restored_too(self) -> None:
        with PrivacySession() as session:
            session.protect(f"Dear {NAME},")
            reply = {"choices": [{"message": {"content": "Hello <PERSON_001>."}}]}
            restored = restore_reply(session, reply)
        assert restored["choices"][0]["message"]["content"] == f"Hello {NAME}."


class TestStreamedToolCalls:
    """Each run of text in a reply is reassembled on its own.

    A streamed answer is the prose plus one independent run per tool call,
    arriving interleaved. One restorer for all of them would splice one run's
    held suffix onto another run's next chunk.
    """

    def chunk(self, **delta: Any) -> dict[str, Any]:
        return {"choices": [{"index": 0, "delta": delta}]}

    def arguments_chunk(self, index: int, fragment: str) -> dict[str, Any]:
        return self.chunk(tool_calls=[{"index": index, "function": {"arguments": fragment}}])

    def test_a_placeholder_split_across_chunks(self) -> None:
        with PrivacySession() as session:
            session.protect(f"Mail {EMAIL}")
            restoration = StreamRestoration(session)
            out = [
                restoration.feed(self.arguments_chunk(0, '{"to": "<EMA')),
                restoration.feed(self.arguments_chunk(0, 'IL_001>"}')),
            ]
            out.extend(restoration.finish())
        assembled = "".join(
            call["function"]["arguments"]
            for piece in out
            for choice in piece["choices"]
            for call in choice["delta"].get("tool_calls", [])
        )
        assert json.loads(assembled) == {"to": EMAIL}

    def test_two_calls_do_not_borrow_each_others_held_text(self) -> None:
        with PrivacySession() as session:
            session.protect(f"Mail {EMAIL} about {NAME}")
            restoration = StreamRestoration(session)
            pieces = [
                restoration.feed(self.arguments_chunk(0, '{"to": "<EMA')),
                restoration.feed(self.arguments_chunk(1, '{"who": "<PERS')),
                restoration.feed(self.arguments_chunk(0, 'IL_001>"}')),
                restoration.feed(self.arguments_chunk(1, 'ON_001>"}')),
            ]
            pieces.extend(restoration.finish())

        runs: dict[int, str] = {}
        for piece in pieces:
            for choice in piece["choices"]:
                for call in choice["delta"].get("tool_calls", []):
                    runs[call["index"]] = (
                        runs.get(call["index"], "") + call["function"]["arguments"]
                    )
        assert json.loads(runs[0]) == {"to": EMAIL}
        assert json.loads(runs[1]) == {"who": NAME}

    def test_prose_and_arguments_are_separate_runs(self) -> None:
        with PrivacySession() as session:
            session.protect(f"Mail {EMAIL} about {NAME}")
            restoration = StreamRestoration(session)
            pieces = [
                restoration.feed(self.chunk(content="Writing to <PERS")),
                restoration.feed(self.arguments_chunk(0, '{"to": "<EMA')),
                restoration.feed(self.chunk(content="ON_001> now. ")),
                restoration.feed(self.arguments_chunk(0, 'IL_001>"}')),
            ]
            pieces.extend(restoration.finish())

        prose = "".join(
            choice["delta"].get("content", "") for p in pieces for choice in p["choices"]
        )
        assert f"Writing to {NAME} now." in prose

    def test_what_is_still_held_at_the_end_is_flushed(self) -> None:
        """A model that stops mid-placeholder still gets its text emitted."""
        with PrivacySession() as session:
            session.protect(f"Mail {EMAIL}")
            restoration = StreamRestoration(session)
            # Ends part-way into a second placeholder, so the tail is held.
            restoration.feed(self.arguments_chunk(0, '{"to": "<EMAIL_001>", "cc": "<EMA'))
            trailing = restoration.finish()
        assert trailing, "the held suffix has to come out somewhere"
        assert "<EMA" in json.dumps(trailing)

    def test_a_chunk_with_no_tool_calls_passes_through(self) -> None:
        with PrivacySession() as session:
            restoration = StreamRestoration(session)
            assert restoration.feed({"id": "x", "choices": []}) == {"id": "x", "choices": []}


class TestItFailsClosedOnBrokenJson:
    def test_a_protected_argument_that_stopped_parsing_is_refused(self) -> None:
        """No rule matches across a structural boundary, so this should never
        fire -- which is why it is checked rather than assumed. The failure it
        prevents is a parse error in a different process, hours later."""
        payload = {
            "messages": [
                {"role": "assistant", "tool_calls": [tool_call({"to": EMAIL})]},
            ]
        }

        class BreaksJson:
            # The `Detector` protocol requires a name, and this fake did not
            # have one. It went unnoticed while the only path through it was
            # `protect`, which never reached the error-wrapping branch that
            # reads it; `session.inspect` does. A fake that does not satisfy
            # the protocol it stands in for is exercising a path no real
            # implementation takes -- which is the reason `mypy` covers the
            # tests, and this class is untyped enough to have slipped past it.
            name = "breaks-json"

            def detect(self, text: str) -> list[Any]:
                from mamori.domain.entity_types import EMAIL as EMAIL_TYPE
                from mamori.domain.sensitive_entity import SensitiveEntity
                from mamori.domain.span import Span

                if EMAIL not in text:
                    return []
                start = text.index(EMAIL) - 1  # eat the opening quote
                return [
                    SensitiveEntity(
                        entity_type=EMAIL_TYPE,
                        span=Span(start, start + len(EMAIL) + 1),
                        value=text[start : start + len(EMAIL) + 1],
                    )
                ]

        # The ignore that used to be here is gone: with a `name`, the fake now
        # satisfies the `Detector` protocol and mypy accepts it directly.
        with PrivacySession(detectors=[BreaksJson()]) as session:
            with pytest.raises(MamoriError, match="valid JSON"):
                protect_request(session, payload, add_guidance=False)

    def test_an_argument_that_was_never_json_is_not_refused(self) -> None:
        payload = {
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {"id": "c", "type": "function", "function": {"name": "f", "arguments": ""}}
                    ],
                },
                {"role": "user", "content": f"mail {EMAIL}"},
            ]
        }
        with PrivacySession() as session:
            protected, _ = protect_request(session, payload, add_guidance=False)
        assert EMAIL not in sent(protected)


class TestTheWholeLoopThroughAConfig:
    def test_an_agent_turn_round_trips(self) -> None:
        config = MamoriConfig(locales=("en",))
        with config.session() as session:
            protected, _ = protect_request(session, agent_payload(), add_guidance=False)
            assert EMAIL not in sent(protected)

            arguments = protected["messages"][1]["tool_calls"][0]["function"]["arguments"]
            reply = {
                "choices": [
                    {
                        "message": {
                            "content": "Done.",
                            "tool_calls": [
                                {"function": {"name": "send_email", "arguments": arguments}}
                            ],
                        }
                    }
                ]
            }
            restored = restore_reply(session, reply)
        recovered = restored["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        assert json.loads(recovered) == json.loads(
            agent_payload()["messages"][1]["tool_calls"][0]["function"]["arguments"]
        )
