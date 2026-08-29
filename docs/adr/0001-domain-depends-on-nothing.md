# 1. The domain layer imports only the standard library

**Status:** accepted

## Context

The security-relevant logic of this library is small: decide which detections
survive, decide what happens to each one, allocate a placeholder, put the value
back. Everything else — regexes, storage, a future local model, a future
proxy — is machinery around that core.

If the core imports a model runtime, testing it requires a model. If it imports
a database driver, testing it requires a database. Both make the tests slow
enough that people stop running them, and a security property nobody re-checks
is a security property that decays.

## Decision

`src/mamori/domain/` imports nothing outside the Python standard library.

Dependencies point inwards: `interfaces → application → domain`, and
`infrastructure → ports`. The domain knows about neither.

Everything that decides what leaves the machine lives in `domain/`:
`resolution`, `policy`, `placeholder`, `placeholder_matching`, `normalization`.

## Consequences

The whole security core is testable with no model, no network, no database and
no fixtures. The suite runs in about a second, which is the reason it gets run.

Swapping a detector, a store or a provider cannot change a security decision,
because the decision is not in the swappable part.

## What it costs

No pydantic in the domain, so validation is hand-written in `__post_init__`.
That is more code than a declarative schema and it has to be kept in step with
the DTO layer by hand. It is a real cost, paid once, in exchange for a core
with no supply chain.
