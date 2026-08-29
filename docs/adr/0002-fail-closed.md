# 2. Fail closed, and block credentials rather than pseudonymize them

**Status:** accepted

## Context

Two failure modes are possible when something goes wrong mid-protection: return
what was produced so far, or return nothing.

At the call site the two are indistinguishable. Code that does
`send(session.protect(text).protected_text)` cannot tell a text where every
value was replaced from a text where the detector died after the first rule.
The first is safe; the second looks identical and is not.

Separately: a policy could pseudonymize an API key like any other value. That
seems tidy — `<API_KEY_001>` reveals nothing — but it is wrong for a different
reason.

## Decision

Any detector exception becomes a `DetectionError` and no protected text is
produced. Any `BLOCK` verdict raises `PolicyViolationError` before any text is
assembled. There is no partial result and no `strict=False` option.

An entity type that matches no rule and no category default falls through to
`BLOCK`, so a custom detector added without a category stops the request rather
than shipping whatever it found.

Credentials are `BLOCK`, not `ANONYMIZE`, in the default policy.

## Consequences

A bug in one detector stops the user's work rather than silently degrading
their protection. That is the intended trade: a privacy tool that fails quietly
is worse than one that fails loudly, because the quiet failure is discovered
after the data is gone.

`mamori inspect` uses a permissive policy so it can *report* on a credential
instead of refusing to look at the file. It never emits a protected text, so
nothing it does is a step towards sending anything.

## Why credentials are blocked

Pseudonymizing a key would still send a token shaped like a secret, and tell
the recipient that one exists in the source material. There is no task where
the right answer requires the model to know that. Replacing the key with a
placeholder answers a question nobody asked; refusing the request tells the
user to remove it, which is what should happen.

## What it costs

A document with one credential in a footnote cannot be protected at all without
`--permissive`. That is friction, deliberately placed.
