"""The proxy forwards nothing it could not check.

`server.py` has said since 0.6:

    **It fails closed.** Detection raising, the policy refusing, a payload it
    cannot parse: all of them are errors returned to the caller, and none of
    them forward anything.

It was true of every case that sentence names and false of the one it does
not: an unrecognised **shape**. The walk in `messages.py` is an allow-list of
OpenAI's evolving request format, and a field the allow-list has not caught up
with was neither parsed nor refused. It went upstream verbatim, with a 200.

Six shapes did, measured before the fix:

    messages as a string                    forwarded verbatim
    messages as an object                   forwarded verbatim
    functions[].description  (pre-tools)    forwarded verbatim
    prediction.content       (Predicted Outputs)  forwarded verbatim
    a content part with no "type" key       forwarded verbatim
    response_format...description           forwarded verbatim

Four are walked now. The other two, and every shape nobody has thought of yet,
are covered by the residue check: every string in the payload that no slot
claimed is inspected, and a request whose unrecognised field carries something
sensitive is refused. That is the difference between fixing six bugs and
fixing the one that produced them.
"""

from __future__ import annotations

from typing import Any

import pytest

from mamori import PrivacySession
from mamori.errors import MamoriError
from mamori.interfaces.proxy.exchange import protect_request
from mamori.interfaces.proxy.messages import request_texts, unclaimed_texts

NAME = "Priya Raman"
MAIL = "priya.raman@example.com"


def protect(payload: object) -> dict[str, Any]:
    with PrivacySession() as session:
        rebuilt, _ = protect_request(session, payload, add_guidance=False)
    return rebuilt


def forwarded(payload: object) -> str:
    """What would reach the upstream, as one string to search."""
    import json

    return json.dumps(protect(payload), ensure_ascii=False)


class TestTheShapesThatUsedToBeForwarded:
    """Each of these sent a real name and a real address to the external
    service and returned 200. Each is now either protected or refused."""

    def test_the_legacy_functions_array(self) -> None:
        """`messages.py` walks `tools[].function.description` *specifically*
        because a description carries an example address. Its own predecessor,
        still accepted by every OpenAI-compatible server, was not walked."""
        out = forwarded(
            {"messages": [], "functions": [{"name": "send", "description": f"e.g. to={MAIL}"}]}
        )
        assert MAIL not in out
        assert "<EMAIL_001>" in out

    def test_predicted_outputs(self) -> None:
        """`prediction.content` is the caller's own prior document -- usually
        the whole of what is being edited."""
        out = forwarded(
            {"messages": [], "prediction": {"type": "content", "content": f"{NAME} at {MAIL}"}}
        )
        assert NAME not in out and MAIL not in out

    def test_a_content_part_with_no_type_key(self) -> None:
        """`type` is optional in several clients and omitting it is common."""
        out = forwarded({"messages": [{"role": "user", "content": [{"text": f"{NAME} {MAIL}"}]}]})
        assert NAME not in out and MAIL not in out

    def test_a_predicted_output_written_as_parts(self) -> None:
        out = forwarded(
            {
                "messages": [],
                "prediction": {"type": "content", "content": [{"type": "text", "text": MAIL}]},
            }
        )
        assert MAIL not in out

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param({"messages": f"Dear {NAME}, mail {MAIL}."}, id="messages as a string"),
            pytest.param(
                {"messages": {"role": "user", "content": f"Dear {NAME}."}}, id="messages as a dict"
            ),
            pytest.param(
                {
                    "messages": [],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"schema": {"properties": {"to": {"description": MAIL}}}},
                    },
                },
                id="a schema description",
            ),
            pytest.param({"messages": [], "metadata": {NAME: "x"}}, id="a name used as a key"),
        ],
    )
    def test_a_shape_that_cannot_be_rewritten_is_refused(self, payload: dict[str, Any]) -> None:
        """Refused rather than protected in place: a field whose meaning is
        unknown cannot be rewritten safely -- replacing an enum value or a stop
        sequence turns a valid request into one the upstream answers
        differently."""
        with pytest.raises(MamoriError, match="does not know how to rewrite"):
            protect(payload)


class TestTheRefusalIsUsable:
    def test_it_names_the_path(self) -> None:
        with pytest.raises(MamoriError) as raised:
            protect({"messages": [], "metadata": {NAME: "x"}})
        assert "metadata" in str(raised.value)

    def test_it_names_the_kinds(self) -> None:
        with pytest.raises(MamoriError, match="PERSON") as raised:
            protect({"messages": f"Dear {NAME}."})
        assert "PERSON" in str(raised.value)

    def test_it_never_names_the_value(self) -> None:
        """An error message crosses a process boundary and lands in a log,
        which is the leak this library exists to prevent -- reached through the
        complaint about a leak."""
        with pytest.raises(MamoriError) as raised:
            protect({"messages": f"Dear {NAME}, mail {MAIL}."})
        assert MAIL not in str(raised.value)

    def test_a_key_is_named_as_a_key(self) -> None:
        """Otherwise the operator looks for a value at that path and finds
        nothing there to change."""
        with pytest.raises(MamoriError, match=r"\(key\)"):
            protect({"messages": [], "metadata": {NAME: "x"}})


class TestItDoesNotRefuseOrdinaryRequests:
    """A fail-closed check that fires on normal traffic is a proxy nobody
    keeps switched on."""

    def test_a_plain_request(self) -> None:
        out = protect(
            {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "What is the weather?"}],
                "temperature": 0.7,
                "max_tokens": 512,
                "stream": False,
            }
        )
        assert out["model"] == "gpt-4o"

    def test_structural_strings_are_not_mistaken_for_content(self) -> None:
        """`"gpt-4o"`, `"json_object"`, a role, a stop sequence: all unclaimed
        strings, none of them sensitive, none of them a reason to refuse."""
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "system", "content": "Be brief."}],
            "response_format": {"type": "json_object"},
            "stop": ["\n\n", "END"],
            "tool_choice": "auto",
        }
        assert protect(payload)["stop"] == ["\n\n", "END"]

    def test_a_request_that_is_protected_normally_is_not_also_refused(self) -> None:
        out = forwarded({"messages": [{"role": "user", "content": f"Dear {NAME}, at {MAIL}."}]})
        assert NAME not in out and MAIL not in out
        assert "<PERSON_001>" in out and "<EMAIL_001>" in out


class TestTheResidueItself:
    def test_a_walked_slot_is_not_in_the_residue(self) -> None:
        payload = {"messages": [{"role": "user", "content": f"Dear {NAME}."}]}
        assert len(request_texts(payload)) == 1
        assert all(NAME not in slot.text for slot in unclaimed_texts(payload))

    def test_a_key_and_its_value_are_reported_separately(self) -> None:
        """They sit at what would otherwise be the same path. The first version
        of the residue walk gave both `("metadata", "Priya Raman")`, so a name
        written as a key was filtered out as claimed by the walk of its own
        value -- the silence this exists to remove, reproduced inside it."""
        payload = {"messages": [], "metadata": {NAME: MAIL}}
        residue = unclaimed_texts(payload)
        assert any(slot.text == NAME and "(key)" in slot.where for slot in residue)

    def test_a_key_carries_no_path_because_nothing_can_rewrite_it(self) -> None:
        payload = {"messages": [], "metadata": {NAME: "x"}}
        keys = [slot for slot in unclaimed_texts(payload) if "(key)" in slot.where]
        assert keys and all(slot.path == () for slot in keys)

    def test_it_reaches_an_arbitrary_depth(self) -> None:
        payload = {"messages": [], "future_field": {"a": [{"b": {"c": MAIL}}]}}
        assert any(slot.text == MAIL for slot in unclaimed_texts(payload))

    def test_a_field_nobody_has_thought_of_yet_is_refused(self) -> None:
        """The point of the whole mechanism: this is not in any allow-list and
        never will be."""
        with pytest.raises(MamoriError, match="does not know how to rewrite"):
            protect({"messages": [], "some_field_from_2027": f"contact {MAIL}"})


class TestAPayloadThatIsNotAnObject:
    """`with_texts` refused these with a bare `ValueError`, which `do_POST`
    does not catch: the client got a connection reset and a traceback went to
    stderr, from one unauthenticated line of JSON."""

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param([{"role": "user", "content": f"Dear {NAME}"}], id="a top-level array"),
            pytest.param("just a string", id="a bare string"),
            pytest.param(42, id="a number"),
            pytest.param(None, id="null"),
        ],
    )
    def test_it_is_a_mamori_error_not_a_crash(self, payload: object) -> None:
        with PrivacySession() as session:
            with pytest.raises(MamoriError):
                protect_request(session, payload)


class TestInspect:
    """The question the residue check asks. It has to allocate nothing, or
    checking a request would consume placeholders for one about to be refused."""

    def test_it_reports_the_kinds(self) -> None:
        with PrivacySession(locales=["en"]) as session:
            assert session.inspect(f"Mail {MAIL} about it.") == ("EMAIL",)

    def test_it_allocates_nothing(self) -> None:
        with PrivacySession(locales=["en"]) as session:
            session.inspect(f"Mail {MAIL} about it.")
            session.inspect(f"Mail {MAIL} about it.")
            assert "<EMAIL_001>" in session.protect(f"Mail {MAIL}").protected_text

    def test_it_reports_a_credential_rather_than_refusing(self) -> None:
        """`protect` raises on one. A question about a text must not be a step
        towards sending it, and must not refuse to answer."""
        from .credentials import FAKE_AWS_KEY

        with PrivacySession() as session:
            assert "API_KEY" in session.inspect(f"key {FAKE_AWS_KEY}")

    def test_clean_text_reports_nothing(self) -> None:
        with PrivacySession() as session:
            assert session.inspect("The meeting is on Tuesday.") == ()

    def test_empty_text(self) -> None:
        with PrivacySession() as session:
            assert session.inspect("") == ()
