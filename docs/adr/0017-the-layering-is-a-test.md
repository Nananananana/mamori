# 17. The layering is a test

**Status:** accepted

## Context

[ADR 0001](0001-domain-depends-on-nothing.md) says the domain layer imports
only the standard library, and the wider architecture says each layer may
depend only inwards. Both were written down in `docs/architecture.md` and
enforced by nothing.

That worked for four versions because the codebase was small enough to hold in
one head. It stopped working the moment configuration grew a `session()`
factory: `MamoriConfig` names infrastructure adapters, `PrivacySession` took a
`config=` argument, and so the application layer acquired a path to every
adapter in the project. Nothing failed. Nothing warned. The diagram in the docs
was simply no longer true, and the only way to find out was to read every
import in the repository.

A rule that is documented but unchecked degrades into a description of what the
code used to be.

## Decision

`tests/test_architecture.py` parses every module with `ast` and asserts the
dependency rules directly.

- **Domain purity** — every import in `mamori.domain` is checked against an
  explicit standard-library allowlist. Anything else, including another mamori
  layer, fails.
- **Layer direction** — an `ALLOWED` table maps each layer to the layers it may
  import. The table *is* the architecture; `docs/architecture.md` describes it.
- **No cycles** — the module graph is checked for them outright.
- **Pinned exceptions** — the one place the application layer constructs a
  default adapter is named explicitly, with the specific symbols it may import.
  Widening it means editing the test, which means saying why in a diff.

## Consequences

**It found two real violations on the first run,** which is the entire
justification. `application/session.py` importing `config` was a genuine
inversion — settings must assemble a session, not the reverse — and removing
the `config=` parameter fixed the dependency and the design at once.

**Adding a legitimate dependency now costs a line in a test.** This is intended
friction, not an obstacle: the line is where a reviewer looks to see that a
boundary moved. A test that never changes is not evidence of a good
architecture, only of one nobody has pushed on.

**It checks imports, not intent.** A domain module could still reach for
`socket` from the standard library, or an adapter could hide a dependency
behind a runtime import the parser cannot see. The test raises the cost of
crossing a boundary; it does not make it impossible. Lazy imports used for
genuine cycle-breaking are visible in review precisely because they are
unusual.

**The allowlist is deliberately narrow.** Adding `json` to the domain layer
should require a moment's thought about whether that module belongs in the
domain at all. Most of the time the answer is that a value object wanted a
serializer, and the serializer belongs somewhere else.
