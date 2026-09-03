"""Incremental restoration.

The property that carries the weight: for any chunking of a response, the
streaming path emits exactly what the batch path would. A streaming restorer
that mostly agrees with ``restore`` is worse than none -- it fails at whichever
token boundary the model happens to pick, which is not reproducible and not
visible until a real value comes back mangled.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mamori import PrivacySession
from mamori.infrastructure.storage import InMemoryMappingStore

SETTINGS = settings(
    max_examples=250,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

PROMPT = (
    "田中太郎さんへ tanaka@example.com からご連絡がありました。\n"
    "Dear Jane Doe, please call 415-555-0198.\n"
    "担当は株式会社さくら商事の佐藤花子です。"
)


def stream(session: PrivacySession, chunks: list[str]) -> str:
    restorer = session.stream_restore()
    out = [restorer.feed(chunk) for chunk in chunks]
    out.append(restorer.finish())
    return "".join(out)


def chunk_every(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


class TestBasics:
    def test_a_placeholder_split_across_chunks(self) -> None:
        with PrivacySession() as session:
            session.protect("田中太郎さんへ")
            assert stream(session, ["Dear <PER", "SON_0", "01>."]) == "Dear 田中太郎."

    def test_a_placeholder_split_at_every_character(self) -> None:
        with PrivacySession() as session:
            session.protect("田中太郎さんへ")
            assert stream(session, list("Hello <PERSON_001>!")) == "Hello 田中太郎!"

    def test_one_chunk_behaves_like_restore(self) -> None:
        with PrivacySession() as session:
            session.protect("田中太郎さんへ")
            assert stream(session, ["<PERSON_001>さん"]) == "田中太郎さん"

    def test_no_chunks_at_all(self) -> None:
        with PrivacySession() as session:
            session.protect("田中太郎さんへ")
            assert stream(session, []) == ""

    def test_empty_chunks_are_harmless(self) -> None:
        with PrivacySession() as session:
            session.protect("田中太郎さんへ")
            assert stream(session, ["", "<PERSON_001>", "", ""]) == "田中太郎"

    def test_text_with_no_placeholders_passes_through(self) -> None:
        with PrivacySession() as session:
            session.protect("田中太郎さんへ")
            assert stream(session, ["Nothing ", "to see ", "here."]) == "Nothing to see here."

    def test_a_tampered_placeholder_split_across_chunks(self) -> None:
        with PrivacySession() as session:
            session.protect("田中太郎さんへ")
            assert stream(session, ["Ask PER", "SON_1 about it"]) == "Ask 田中太郎 about it"

    def test_full_width_brackets_split_across_chunks(self) -> None:
        with PrivacySession() as session:
            session.protect("田中太郎さんへ")
            assert stream(session, ["＜PERSON", "_001＞様"]) == "田中太郎様"

    def test_an_unknown_placeholder_is_reported_not_resolved(self) -> None:
        with PrivacySession() as session:
            session.protect("田中太郎さんへ")
            restorer = session.stream_restore()
            out = restorer.feed("Ask <PERSON_099> instead") + restorer.finish()
            assert "<PERSON_099>" in out
            assert restorer.summary().unknown == ("<PERSON_099>",)
            assert not restorer.summary().is_clean


class TestSummary:
    def test_it_records_what_was_restored(self) -> None:
        with PrivacySession() as session:
            session.protect("田中太郎さんへ tanaka@example.com")
            restorer = session.stream_restore()
            restorer.feed("<PERSON_001> and <EMAIL_001>")
            restorer.finish()
            summary = restorer.summary()
            assert len(summary.restored) == 2
            assert summary.is_clean

    def test_it_records_tampering(self) -> None:
        with PrivacySession() as session:
            session.protect("田中太郎さんへ")
            restorer = session.stream_restore()
            restorer.feed("PERSON_1")
            restorer.finish()
            assert len(restorer.summary().tampered) == 1

    def test_a_clean_stream_reports_clean(self) -> None:
        with PrivacySession() as session:
            session.protect("田中太郎さんへ")
            restorer = session.stream_restore()
            restorer.feed("<PERSON_001>")
            restorer.finish()
            assert restorer.summary().is_clean


class TestLifecycle:
    def test_feeding_after_finish_is_refused(self) -> None:
        with PrivacySession() as session:
            restorer = session.stream_restore()
            restorer.finish()
            with pytest.raises(RuntimeError):
                restorer.feed("more")

    def test_finish_is_idempotent(self) -> None:
        with PrivacySession() as session:
            restorer = session.stream_restore()
            restorer.feed("hello")
            assert restorer.finish() == "hello"
            assert restorer.finish() == ""

    def test_a_restorer_cannot_read_another_scope(self) -> None:
        from mamori.infrastructure.storage import InMemoryMappingStore

        store = InMemoryMappingStore()
        with PrivacySession(store=store) as owner, PrivacySession(store=store) as other:
            owner.protect("tanaka@example.com")
            restorer = other.stream_restore()
            out = restorer.feed("<EMAIL_001>") + restorer.finish()
            assert "tanaka@example.com" not in out


class TestStreamingMatchesBatch:
    """The invariant. Chunking must not change the answer."""

    @pytest.mark.parametrize("size", [1, 2, 3, 5, 7, 11, 40, 1000])
    def test_fixed_size_chunks(self, size: int) -> None:
        response = (
            "<PERSON_001>様\n\nPERSON_002 です。<EMAIL_001> と <PHONE_001> をご確認ください。\n"
            "Also cc <PERSON_003> at [EMAIL_001] and <PERSON_099>.\n"
        )
        with PrivacySession() as session:
            session.protect(PROMPT)
            expected = session.restore(response).text
            assert stream(session, chunk_every(response, size)) == expected

    @pytest.mark.parametrize("size", [1, 2, 3, 4, 5, 8, 13, 100])
    def test_a_spaced_separator_survives_any_chunking(self, size: int) -> None:
        """`<COMPANY _ NAME _ 001>` restored whole and not in pieces.

        0.14 widened the batch scanner to accept this -- it was 195 of 1002
        failures in the first reply corpus -- and the streaming partial matcher
        was not widened with it, so the two paths disagreed for four releases.
        The property test above could have found it and did not: the shape
        needs a space on both sides of an underscore *inside* a type name, and
        Hypothesis never happened to draw one.
        """
        response = "Contact <COMPANY _ NAME _ 001> or < PERSON_001 > today."
        with PrivacySession() as session:
            session.protect(PROMPT)
            expected = session.restore(response).text
            assert "COMPANY" not in expected, "the batch path restores it"
            assert stream(session, chunk_every(response, size)) == expected

    @SETTINGS
    @given(size=st.integers(min_value=1, max_value=30))
    def test_any_uniform_chunk_size(self, size: int) -> None:
        response = "Dear <PERSON_001>, mail <EMAIL_001> or PERSON_1. Regards."
        with PrivacySession() as session:
            session.protect(PROMPT)
            expected = session.restore(response).text
            assert stream(session, chunk_every(response, size)) == expected

    @SETTINGS
    @given(
        pieces=st.lists(
            st.text(
                alphabet="<>[]{}_PERSONEMAIL0123456789 .,\nさん様",
                max_size=12,
            ),
            max_size=12,
        )
    )
    def test_any_chunking_of_adversarial_text(self, pieces: list[str]) -> None:
        """Text built from the characters most likely to break the boundary logic."""
        response = "".join(pieces)
        with PrivacySession() as session:
            session.protect(PROMPT)
            expected = session.restore(response).text
            assert stream(session, pieces) == expected

    @SETTINGS
    @given(text=st.text(max_size=120))
    def test_arbitrary_text_split_in_two(self, text: str) -> None:
        with PrivacySession() as session:
            session.protect(PROMPT)
            expected = session.restore(text).text
            midpoint = len(text) // 2
            assert stream(session, [text[:midpoint], text[midpoint:]]) == expected

    def test_a_stream_with_nothing_protected(self) -> None:
        with PrivacySession() as session:
            response = "Nothing was ever protected here <PERSON_001>."
            assert stream(session, chunk_every(response, 4)) == session.restore(response).text


class TestTheStreamAndTheBatchAgreeOnEveryCut:
    """Three ways a placeholder reached the reader whole.

    All three were found by a differential fuzz -- the same reply through
    `restore` and through `feed` at every possible cut -- and none of them by a
    hand-written test, because a hand-written test cuts between words.
    """

    def chunkings(self, session: PrivacySession, reply: str) -> set[str]:
        out = set()
        for size in range(1, len(reply) + 1):
            restorer = session.stream_restore()
            pieces = [restorer.feed(reply[i : i + size]) for i in range(0, len(reply), size)]
            pieces.append(restorer.finish())
            out.add("".join(pieces))
        return out

    @pytest.mark.parametrize("separator", ["\n", "\r", "\r\n", "_", " _ ", "-"])
    def test_a_separator_the_batch_scanner_accepts_is_holdable(self, separator: str) -> None:
        r"""`_PARTIAL_BODY` used `[^\S

        ]`, which excludes a newline, while
                the batch scanner's class is `[\s_\-]`, which includes one. So
                `<PERSON\n001>` was a placeholder to `restore` and not holdable here:
                restored when the reply arrived whole, emitted verbatim when it arrived
                in pieces, and at some cuts worse -- the `<` alone, then the value."""
        with PrivacySession() as session:
            session.protect("Alex Rivera signed it.")
            reply = f"Dear <PERSON{separator}001>, hello."
            assert self.chunkings(session, reply) == {session.restore(reply).text}

    def test_a_placeholder_longer_than_the_old_window(self) -> None:
        """`_MAX_HOLD` was 96 -- the run written without spaces. The batch
        scanner accepts `<COMPANY _ NAME _ 001>`, where a 62-character type
        name is 110 characters long, so the window began after the opening
        bracket and the whole token was emitted verbatim."""
        from mamori.domain.mapping import Mapping
        from mamori.domain.placeholder import Placeholder

        long_type = "_".join(["AB"] * 21)
        store = InMemoryMappingStore()
        with PrivacySession(store=store) as session:
            store.put(
                Mapping(
                    scope=session.scope,
                    placeholder=Placeholder(long_type, 1),
                    entity_type_name=long_type,
                    original_value="Alex Rivera",
                    identity_key=f"{long_type}:alex",
                )
            )
            reply = "<" + long_type.replace("_", " _ ") + " _ 001>"
            assert len(reply) > 96
            assert self.chunkings(session, reply) == {session.restore(reply).text}

    def test_the_hold_window_still_covers_the_longest_legal_run(self) -> None:
        """The constant and the batch grammar have to move together. Widening
        one without the other is what produced the case above."""
        from mamori.application.streaming import StreamingRestorer

        longest = "<" + " _ ".join(["A"] * 63) + " _ 000001>"
        assert StreamingRestorer._hold_is_bounded(longest), len(longest)


class TestAModelsOwnWordsMustNotCrashRestoration:
    """A reply is untrusted input, and an ordinary identifier in one raised."""

    IDENTIFIER = "MAXIMUM_NUMBER_OF_CONCURRENT_BACKGROUND_REPLICATION_WORKERS_LIMIT_2"

    def test_a_long_identifier_comes_back_unchanged(self) -> None:
        """0.31 taught `Placeholder` to refuse a type name outside its grammar,
        and `scan_placeholders` was handing it untrusted text -- so a 66-
        character constant in a model's answer raised `ValueError` out of
        `restore`. The guard that would have discarded it harmlessly sits two
        lines below the throw."""
        with PrivacySession() as session:
            session.protect("Contact Alex Rivera")
            reply = f"See {self.IDENTIFIER} in the config."
            assert session.restore(reply).text == reply

    def test_the_streaming_path_survives_it_too(self) -> None:
        with PrivacySession() as session:
            session.protect("Contact Alex Rivera")
            reply = f"See {self.IDENTIFIER} in the config."
            restorer = session.stream_restore()
            assert restorer.feed(reply) + restorer.finish() == reply

    def test_a_type_name_at_the_grammar_limit_still_resolves(self) -> None:
        """63 characters is legal and 64 is not. The fix must not have made the
        legal one unrecognisable."""
        from mamori.domain.placeholder import Placeholder

        assert Placeholder.parse("<" + "A" * 63 + "_001>") is not None
        assert Placeholder.parse("<" + "A" * 64 + "_001>") is None
