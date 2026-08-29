# 28. The server names the conversation

**Status:** accepted

## Context

A `PrivacySession` has always kept its placeholders across every `protect` call
it is given. What did not survive was the request. The proxy built a session,
used it and purged it, which is what made "the proxy remembers nothing" a claim
that needed no qualification.

That was defended, in [ADR 0018](0018-a-proxy-on-the-standard-library.md) and in
the module itself, with an argument: a chat client resends the whole
conversation on every turn, so the same values meet the same allocator in the
same order and land on the same placeholders. The argument stood for four
releases without anybody checking it. It is checked now, in
`tests/test_conversations.py`, and it is correct — which is why the default has
not changed.

It is correct only for that client. A client whose history lives on the service
side sends one message per turn: *"and what is their address?"*. The service
answers about `<PERSON_001>` because that is what it was told in turn one, the
proxy has never heard of `<PERSON_001>`, and the caller is shown a token where
a name should be. That is not a degraded answer, it is the specific failure
this library exists to prevent, arriving from the other direction.

Continuity therefore has to be available. The question is what names it.

The obvious answer — let the client choose an identifier, `session_id=chat-42`
— is the wrong one. The thing on the other side of that identifier is a table
of real values, and an identifier an outsider can guess is a way to read
somebody else's table. On a proxy bound to loopback that is a small risk; on
the one bound to `0.0.0.0` for the team, it is a hole. A design that is only
safe on the default binding is a design that fails where it is needed.

## Decision

**The server mints the token, the client echoes it.**

- The proxy returns `X-Mamori-Session` on every reply when conversations are
  enabled. The value is 128 bits from `secrets.token_urlsafe`.
- A client that wants continuity sends it back. One that does not gets a fresh
  scope per request, exactly as before.
- **An unrecognised token starts a new conversation and does not say so.** It
  is not an error. Reporting "no such conversation" would confirm which tokens
  exist to anybody who asked, and the caller wanted a conversation rather than
  an answer about one.
- `X-Mamori-Session-End` discards one immediately, for a client that knows it
  is finished.

**It is bounded in both directions, and both bounds purge.** A conversation
expires after an idle period (30 minutes by default), and the registry holds a
fixed number (64 by default); when it is full the least recently used is
discarded. A caller whose conversation was dropped comes back to a new one and
re-protects its history, which is the behaviour it had before this existed. The
worst case is a client that starts again; there is no case where something is
kept forever.

**Expiry runs on the path that uses the registry, not on a timer.** A
background thread that purges secrets is a background thread whose failure is
silent. Sweeping on every resume means the work happens exactly when there is
something to do it for, and its absence is visible in a test.

**It is off by default.** The trade is real — a process that holds mappings for
half an hour is holding real values for half an hour — and a trade that happens
without being chosen is not a trade. `mamori serve --conversations` turns it on
and prints what will be held and for how long.

## Consequences

Continuity is available to the clients that need it without weakening the
statement for everyone else. `mamori serve` with no flag holds nothing between
requests and says so; with the flag it holds a bounded, expiring set and says
that instead. Both statements are true and neither has to be qualified.

Mappings still never touch the disk, so
[ADR 0006](0006-mappings-live-in-memory.md) is unchanged: what a conversation
extends is how long a scope lives, not where it lives. A process that is
stopped forgets everything, which is the correct behaviour for something
holding plaintext in memory and not a limitation to be worked around.

The per-session salt that [proposal 0002](../proposals/0002-the-road-to-1-0-revised.md)
adopted for this release is **not** built, and the reason is recorded here so
it is not proposed again. Its purpose was to make placeholders stable inside a
conversation and unrelated across conversations. Allocation order already gives
both properties — the index comes from the order values are met, not from the
values — so the salt would have added a keyed hash that nothing reads. What the
release actually needed was an identifier nobody outside the process can guess,
and that is a token, not a salt.
