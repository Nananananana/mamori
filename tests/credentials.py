"""Invented credentials, assembled at runtime.

Testing a secret detector means writing text shaped exactly like a secret.
Written as literals, those strings trip the push protection and scanning tools
of every repository that clones this one — GitHub rejected the first version of
these tests, which is a fair endorsement of the rules they exercise.

So the fixtures are built from a prefix and a body at import time. The values
are invented and belong to nobody; splitting them only keeps a scanner from
matching the source file.
"""

from __future__ import annotations

__all__ = [
    "CREDENTIAL_FIXTURES",
    "FAKE_ANTHROPIC_KEY",
    "FAKE_AWS_KEY",
    "FAKE_GITHUB_TOKEN",
    "FAKE_GOOGLE_KEY",
    "FAKE_SLACK_TOKEN",
]


def _fake(prefix: str, body: str) -> str:
    return prefix + body


FAKE_ANTHROPIC_KEY = _fake("sk-ant-", "api03-abcdefghijklmnopqrstuvwxyz0123456789")
FAKE_AWS_KEY = _fake("AKIA", "IOSFODNN7EXAMPLE")
FAKE_GITHUB_TOKEN = _fake("ghp_", "a" * 36)
FAKE_SLACK_TOKEN = _fake("xox", "b-123456789012-abcdefghijklmno")
FAKE_GOOGLE_KEY = _fake("AIza", "b" * 35)

CREDENTIAL_FIXTURES = [
    FAKE_ANTHROPIC_KEY,
    FAKE_AWS_KEY,
    FAKE_GITHUB_TOKEN,
    FAKE_SLACK_TOKEN,
    FAKE_GOOGLE_KEY,
]
