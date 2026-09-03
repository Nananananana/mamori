"""Restoring a surrogate must return the right person.

A surrogate is a plausible name substituted for a real one. Two things about
that make restoration harder than it looks, and both were wrong:

**A surrogate is a real name to somebody else.** If `Alex Rivera` stands in for
`Priya Nair` in one document, and a later document in the same scope genuinely
mentions Alex Rivera, the scope now holds a mapping whose *surface* is another
mapping's *original value*. Restoring in two passes -- placeholders first, then
searching the rewritten text for surrogates -- let a value just put back be
matched as the next mapping's surrogate. The reply named the wrong person, with
no error and nothing out of place to look at.

**A surrogate has no shape.** A placeholder can be recognised; a surrogate can
only be searched for. The streaming path did not search for one at all, so a
session with surrogates on streamed the invented name straight through -- shown
to a reader as a real one, which `domain/surrogate.py` calls the most dangerous
thing in the library. The two paths are documented as producing the same text
and did not.
"""

from __future__ import annotations

import pytest

from mamori import PrivacySession


def stream(session: PrivacySession, reply: str, size: int) -> str:
    restorer = session.stream_restore()
    out = [restorer.feed(reply[i : i + size]) for i in range(0, len(reply), size)]
    out.append(restorer.finish())
    return "".join(out)


def every_chunking(session: PrivacySession, reply: str) -> set[str]:
    """What the streaming path produces at every possible chunk size."""
    return {stream(session, reply, size) for size in range(1, len(reply) + 1)}


class TestASurrogateThatIsSomebodyElsesRealName:
    def test_the_right_person_comes_back(self) -> None:
        """Measured before the fix: `Priya Nair signed the contract. Priya Nair
        approved the invoice.` -- one person's name in both sentences."""
        with PrivacySession(surrogate_types=["PERSON"]) as session:
            first = session.protect("Priya Nair signed the contract.")
            second = session.protect("Alex Rivera approved the invoice.")
            reply = f"{first.protected_text} {second.protected_text}"
            restored = session.restore(reply).text

        assert restored == "Priya Nair signed the contract. Alex Rivera approved the invoice."

    def test_the_collision_is_the_one_being_tested(self) -> None:
        """The trigger is that the first document's surrogate *is* the second
        document's real value. Without that this test proves nothing, and the
        surrogate pool is what decides it -- so it is asserted rather than
        assumed."""
        from mamori.infrastructure.storage import InMemoryMappingStore

        store = InMemoryMappingStore()
        with PrivacySession(surrogate_types=["PERSON"], store=store) as session:
            session.protect("Priya Nair signed the contract.")
            session.protect("Alex Rivera approved the invoice.")
            mappings = store.list_scope(session.scope)

        surfaces = {m.surface for m in mappings if m.surface}
        originals = {m.original_value for m in mappings}
        assert surfaces & originals, (
            "no surrogate collided with a real value in this scope, so nothing "
            "here exercises the two-pass bug. The pool may have changed."
        )

    def test_a_value_put_back_is_not_searched_again(self) -> None:
        """The general property. Both kinds are decided against the text the
        model wrote, so nothing this restoration produces can be matched by
        the rest of it."""
        with PrivacySession(surrogate_types=["PERSON"]) as session:
            first = session.protect("Priya Nair signed it.")
            second = session.protect("Alex Rivera approved it.")
            reply = f"{first.protected_text} {second.protected_text}"
            restored = session.restore(reply).text

        assert restored.count("Priya Nair") == 1
        assert restored.count("Alex Rivera") == 1


class TestStreamingRestoresSurrogatesToo:
    """`session.stream_restore` promises to produce exactly what `restore`
    produces. It produced the invented name."""

    def test_it_agrees_with_the_batch_path(self) -> None:
        with PrivacySession(surrogate_types=["PERSON"]) as session:
            protected = session.protect("Summary: Priya Nair met Sam Okafor yesterday.")
            reply = protected.protected_text
            batch = session.restore(reply).text
            assert every_chunking(session, reply) == {batch}

    def test_the_invented_name_never_reaches_the_reader(self) -> None:
        with PrivacySession(surrogate_types=["PERSON"]) as session:
            protected = session.protect("Priya Nair called.")
            surrogate = protected.protected_text.replace(" called.", "")
            for size in range(1, len(protected.protected_text) + 1):
                assert surrogate not in stream(session, protected.protected_text, size)

    @pytest.mark.parametrize(
        "text",
        [
            "Priya Nair. Priya Nair, and Priya Nair again.",
            "Contact Priya Nair at priya@example.com or call 415-555-0198.",
            "Dear Priya Nair,\nthanks.\nRegards,\nSam Okafor",
        ],
        ids=["repeated", "mixed types", "across lines"],
    )
    def test_every_chunk_size_agrees(self, text: str) -> None:
        """A chunk boundary is where a stream differs from a whole string, so
        the property is over *all* of them rather than a chosen few."""
        with PrivacySession(surrogate_types=["PERSON", "EMAIL"]) as session:
            protected = session.protect(text)
            reply = protected.protected_text
            batch = session.restore(reply).text
            assert every_chunking(session, reply) == {batch}

    def test_a_release_point_is_pulled_out_of_a_complete_surrogate(self) -> None:
        """`Alex Rivera ` gave a placeholder boundary of 5 -- `Rivera ` could
        still grow into a token -- and a surrogate boundary of 12. Taking the
        smaller released `Alex ` and held `Rivera `, splitting a complete
        surrogate at a point neither check was looking at."""
        with PrivacySession(surrogate_types=["PERSON"]) as session:
            protected = session.protect("Priya Nair met Sam Okafor.")
            reply = protected.protected_text
            assert stream(session, reply, 1) == session.restore(reply).text

    def test_a_session_without_surrogates_is_unaffected(self) -> None:
        """The hold-back must cost nothing when there is nothing to hold for."""
        with PrivacySession() as session:
            protected = session.protect("Dear Priya Nair, mail priya@example.com.")
            reply = protected.protected_text
            assert every_chunking(session, reply) == {session.restore(reply).text}


class TestTheReportStillSaysWhatHappened:
    def test_a_surrogate_put_back_counts_as_seen(self) -> None:
        """Otherwise it is reported `missing`, and an operator reading that
        looks for a leak that is not there."""
        with PrivacySession(surrogate_types=["PERSON"]) as session:
            protected = session.protect("Priya Nair signed it.")
            result = session.restore(protected.protected_text)
        assert result.missing == ()

    def test_a_placeholder_that_never_came_back_is_still_missing(self) -> None:
        with PrivacySession() as session:
            session.protect("Priya Nair signed it.")
            assert session.restore("nothing here").missing
