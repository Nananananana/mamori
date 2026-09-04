"""The two-line entry point, and the things a two-line entry point can lose.

A convenience wrapper is where safety goes to die: it exists to skip steps,
and one of the steps is usually the one that mattered. So these are less about
`protect` working than about what it must *not* quietly do -- swallow a block,
leak a mapping when it raises, or pretend two calls share a scope.
"""

from __future__ import annotations

import gc

import pytest

import mamori
from mamori import MamoriConfig, PolicyViolationError
from mamori.domain.policy import Action, PrivacyPolicy

EMAIL = "tanaka@example.com"
TEXT = f"Mail {EMAIL} by Friday."
KEY = "sk-ant-api03-" + "A" * 48


class TestTheRoundTrip:
    def test_it_unpacks_as_text_and_a_way_back(self) -> None:
        protected, restore = mamori.protect(TEXT)
        assert EMAIL not in protected
        assert restore(f"I have emailed {protected.split()[1]}.") == f"I have emailed {EMAIL}."

    def test_the_placeholder_is_what_the_session_would_have_given(self) -> None:
        """Not a second protection path.

        The wrapper exists to save four lines, not to do anything differently.
        A convenience that produced different output from the documented route
        would be a second implementation nobody is measuring.
        """
        with mamori.PrivacySession() as session:
            expected = session.protect(TEXT).protected_text
        assert mamori.protect(TEXT).text == expected

    def test_settings_are_honoured(self) -> None:
        loud = MamoriConfig(placeholder_style="curly")
        assert "{" in mamori.protect(TEXT, config=loud).text

    def test_entities_say_what_was_found_and_never_the_value(self) -> None:
        result = mamori.protect(TEXT)
        assert [report.entity_type for report in result.entities] == ["EMAIL"]
        assert EMAIL not in repr(result.entities)


class TestWhatItMustNotSwallow:
    def test_a_blocked_value_still_raises(self) -> None:
        """The default policy refuses to let a credential past.

        A wrapper that caught this and returned the text anyway would be a
        wrapper that sends your API key, which is the one outcome this library
        exists to prevent.
        """
        with pytest.raises(PolicyViolationError):
            mamori.protect(f"export ANTHROPIC_API_KEY={KEY}")

    def test_a_refused_text_leaves_nothing_behind(self) -> None:
        """The caller never got a handle, so nothing else can close it.

        Measured by counting live sessions: without the `except BaseException`
        in `protect`, the session survives the raise with whatever it had
        already allocated, and only the garbage collector ever discards it.
        """
        before = _live_sessions()
        for _ in range(20):
            with pytest.raises(PolicyViolationError):
                mamori.protect(f"Mail {EMAIL} and use {KEY}")
        assert _live_sessions() <= before, (
            "a refused protect left its session alive; it holds the mappings "
            "allocated before the policy stopped the call"
        )


class TestTheScopeIsOneCall:
    def test_crossing_two_calls_returns_the_other_value(self) -> None:
        """The sharp edge, pinned rather than claimed away.

        Numbering restarts per scope, so both calls mint `<EMAIL_001>`. Cross
        the two and you get the *first* call's address, silently: `unknown` is
        empty and `is_clean` is true, because the token is perfectly well
        known and simply means somebody else.

        This is not new to `protect` -- two sessions and two conversations do
        the same, and it is why restoration takes a scope. It is pinned here
        because `protect` is the call that makes two scopes easy to have by
        accident, and because the first draft of its docstring claimed the
        opposite. That claim was written, not measured; this test is what
        measured it.
        """
        first = mamori.protect("Mail alice@a.example.com by Friday.")
        second = mamori.protect("Mail bob@b.example.com by Friday.")
        assert first.text == second.text, "the collision this test is about did not happen"

        crossed = first.session.restore(second.text)
        assert "alice@a.example.com" in crossed.text
        assert crossed.unknown == (), "nothing warned, which is the whole point"

    def test_the_session_is_the_way_to_a_second_turn(self) -> None:
        result = mamori.protect(TEXT)
        again = result.session.protect(f"Remind {EMAIL} tomorrow.")
        assert result.text.split()[1].strip(".") in again.protected_text

    def test_closing_makes_restoration_stop_working(self) -> None:
        result = mamori.protect(TEXT)
        token = result.text.split()[1]
        assert EMAIL in result.restore(token)
        result.close()
        assert EMAIL not in result.restore(token)

    def test_it_closes_on_the_way_out_of_a_with(self) -> None:
        with mamori.protect(TEXT) as result:
            token = result.text.split()[1]
            assert EMAIL in result.restore(token)
        assert EMAIL not in result.restore(token)


class TestInspect:
    def test_it_names_the_kinds_present(self) -> None:
        assert mamori.inspect(TEXT) == ("EMAIL",)

    def test_it_is_empty_for_ordinary_text(self) -> None:
        assert mamori.inspect("The meeting is on Friday.") == ()

    def test_it_reports_a_credential_rather_than_refusing(self) -> None:
        """`protect` raises on the same text. That is the difference between
        the two questions: *"is there anything in this"* has an answer even
        when *"send this"* does not."""
        assert "API_KEY" in mamori.inspect(f"export KEY={KEY}")

    def test_it_allocates_nothing(self) -> None:
        """No mapping outlives the call, so there is nothing to close.

        Checked by asking a permissive policy -- which would allocate for every
        one of these -- and then looking for a placeholder anywhere."""
        loose = MamoriConfig(default_action=Action.ANONYMIZE)
        assert mamori.inspect(f"Mail {EMAIL} and use {KEY}", config=loose)
        assert PrivacyPolicy.default().mask_token not in TEXT  # nothing was rewritten


def _live_sessions() -> int:
    gc.collect()
    return sum(1 for obj in gc.get_objects() if isinstance(obj, mamori.PrivacySession))
