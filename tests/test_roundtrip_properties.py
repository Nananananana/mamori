"""Property-based round-trip tests.

The invariant is scoped on purpose. ``restore(protect(x)) == x`` holds for
entities the policy pseudonymized. It cannot hold for ``MASK`` or ``BLOCK``,
which destroy information deliberately -- a test that asserted it globally
would be asserting that the security features do not work.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
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
@given(text=sensitive_text())
def test_restore_undoes_protect(text: str) -> None:
    with PrivacySession(policy=PrivacyPolicy.permissive()) as session:
        protected = session.protect(text)
        assert session.restore(protected.protected_text).text == text


@SETTINGS
@given(text=sensitive_text())
def test_protecting_twice_is_stable(text: str) -> None:
    """A second pass over the same input must produce the same output."""
    with PrivacySession(policy=PrivacyPolicy.permissive()) as session:
        first = session.protect(text)
        second = session.protect(text)
        assert first.protected_text == second.protected_text


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
