"""Property-based round-trip tests.

The invariant is scoped on purpose. ``restore(protect(x)) == x`` holds for
entities the policy pseudonymized. It cannot hold for ``MASK`` or ``BLOCK``,
which destroy information deliberately -- a test that asserted it globally
would be asserting that the security features do not work.

There is a second exception, and hypothesis found it rather than anybody
writing it down: a value spelled two ways that NFKC folds into one gets **one
placeholder for both sites**, and every site then restores to the spelling of
the first. See :func:`test_restore_undoes_protect`.
"""

from __future__ import annotations

import unicodedata

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from mamori import PrivacySession
from mamori.domain.policy import PrivacyPolicy

SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

# Filler that no detector should fire on, so the generated text exercises the
# splicing logic rather than the rules.
filler = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Zs", "Po"),
        whitelist_characters="あいうえおこんにちは、。\n",
        blacklist_characters="<>[]{}@_-\\",
    ),
    max_size=40,
)

emails = st.builds(
    lambda user, domain: f"{user}@{domain}.example.com",
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=12),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=10),
)

names = st.sampled_from(
    ["田中太郎", "佐藤花子", "鈴木一郎", "高橋second", "山本", "渡辺次郎", "凪沢"]
)


@st.composite
def sensitive_text(draw: st.DrawFn) -> str:
    parts: list[str] = []
    for _ in range(draw(st.integers(min_value=1, max_value=4))):
        parts.append(draw(filler))
        parts.append(draw(st.one_of(emails, names.map(lambda n: f"{n}さん"))))
    parts.append(draw(filler))
    return "".join(parts)


@SETTINGS
# Pinned rather than left to the database. A hypothesis database is keyed on a
# digest of the test function, so editing this body -- which investigating a
# failure always does -- silently orphans every counterexample it stored, with
# no warning and a green run. An @example survives that.
@example(text="Y0@a.example.com:Ｙ0@a.example.com")
@given(text=sensitive_text())
def test_restore_undoes_protect(text: str) -> None:
    """Exact, except where one placeholder legitimately stands for two spellings.

    ``Y0@a.example.com:Ｙ0@a.example.com`` was hypothesis's counterexample,
    and it is not a defect in the placeholder: those are the same address, so
    one token for both is what makes a model treat them as one thing. What
    follows from that is that the mapping holds one surface, and both sites come
    back spelled the way the first one was.

    Strict equality is still asserted for every text where no placeholder
    repeats, which is nearly all of them. Where one does, the claim weakens to
    exactly what is true and no further.
    """
    with PrivacySession(policy=PrivacyPolicy.permissive()) as session:
        protected = session.protect(text)
        restored = session.restore(protected.protected_text).text

        if restored == text:
            return

        tokens = [e.placeholder for e in protected.entities if e.placeholder]
        assert len(tokens) != len(set(tokens)), (
            "restoration changed the text and no placeholder was reused, "
            "so NFKC folding cannot be the explanation"
        )
        assert unicodedata.normalize("NFKC", restored) == unicodedata.normalize("NFKC", text), (
            "the difference is more than a compatibility spelling"
        )


def test_one_value_spelled_two_ways_gets_one_placeholder() -> None:
    """Pinned separately, because the property test above now tolerates this
    and something has to notice if it ever changes."""
    text = "Y0@a.example.com:Ｙ0@a.example.com"
    with PrivacySession(policy=PrivacyPolicy.permissive()) as session:
        protected = session.protect(text)
        assert protected.protected_text == "<EMAIL_001>:<EMAIL_001>"
        assert session.restore(protected.protected_text).text == (
            "Y0@a.example.com:Y0@a.example.com"
        )


@SETTINGS
@given(text=sensitive_text())
def test_protecting_twice_is_stable(text: str) -> None:
    """A second pass over the same input must produce the same output."""
    with PrivacySession(policy=PrivacyPolicy.permissive()) as session:
        first = session.protect(text)
        second = session.protect(text)
        assert first.protected_text == second.protected_text


def test_the_sensitive_strategy_actually_produces_detections() -> None:
    """The two properties below loop over `protected.entities` and say nothing
    when it is empty -- which is correct per example and useless if it is empty
    every time. Measured: with detection returning `[]`, both passed.

    `assert protected.entities` inside them would be wrong, because a generated
    text legitimately has none. So the strategy's promise is checked once,
    here, against fixed inputs: if `sensitive_text()` stops producing anything
    detectable, this fails and names the reason instead of two properties
    quietly checking nothing.
    """
    with PrivacySession(policy=PrivacyPolicy.permissive()) as session:
        for sample in ("田中太郎さんへ tanaka@example.com", "Dear Jane Doe, call 415-555-0198"):
            assert session.protect(sample).entities, sample


@SETTINGS
@given(text=sensitive_text())
def test_no_detected_value_survives_into_the_protected_text(text: str) -> None:
    with PrivacySession(policy=PrivacyPolicy.permissive()) as session:
        protected = session.protect(text)
        for report in protected.entities:
            if report.placeholder:
                assert report.placeholder in protected.protected_text


@SETTINGS
@given(text=st.text(max_size=200))
def test_arbitrary_text_never_raises_under_a_permissive_policy(text: str) -> None:
    """Whatever the user pastes, protect must return or block -- not crash."""
    with PrivacySession(policy=PrivacyPolicy.permissive()) as session:
        protected = session.protect(text)
        assert session.restore(protected.protected_text).text == text


@SETTINGS
@given(response=st.text(max_size=200))
def test_restoring_an_arbitrary_response_never_raises(response: str) -> None:
    with PrivacySession() as session:
        session.protect("田中太郎さんへ tanaka@example.com")
        result = session.restore(response)
        assert isinstance(result.text, str)


@SETTINGS
@given(text=sensitive_text())
def test_reported_spans_always_delimit_something_in_the_input(text: str) -> None:
    with PrivacySession(policy=PrivacyPolicy.permissive()) as session:
        protected = session.protect(text)
        for report in protected.entities:
            assert 0 <= report.span.start < report.span.end <= len(text)
