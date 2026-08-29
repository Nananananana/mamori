# 3. Placeholders are readable tokens, not random strings

**Status:** accepted

## Context

A pseudonymized value needs a stand-in. The options:

1. A random string — `<a7f3d91e>`.
2. A typed token — `<PERSON_001>`.
3. A surrogate value — `田中太郎` becomes `山田一郎`.

Option 1 is the most conservative: the token reveals nothing. But the model
receives text it cannot reason about, and answer quality drops sharply — it
cannot tell a person from a company, so it cannot choose a greeting.

Option 3 gives the best answers, because the text stays natural. It is also the
hardest to restore: a model will inflect, translate and abbreviate a name that
looks like a name, and every such mutation is a restoration failure.

## Decision

Option 2 for v0.1: `<TYPE_NNN>`, zero-padded to three digits, stable within a
session.

Option 3 becomes a policy choice in v0.5, not a replacement.

## Consequences

The model keeps enough structure to write a sensible answer. `<PERSON_001>さん`
tells it a person is being addressed politely.

A human reviewing an outbound payload can see what was removed and roughly how
much, which makes the tool auditable by eye.

The same value keeps the same token across a whole session, so a model can tell
that two mentions are one person, and a response in a later turn still restores.

## What it costs

The token leaks its own type. A recipient learns the message mentioned three
people and two companies, and where. For most uses that is acceptable; for a
message where the *shape* is the secret, it is not, and `SECURITY.md` says so.

Answer quality is still worse than with surrogates. That is the v0.5 work.
