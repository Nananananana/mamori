# 19. Privacy is a report, not a promise

**Status:** accepted

Borrowed, with thanks, from the sibling `kiseki` project's ADR-0046.

## Context

Every privacy claim this library makes is enforced somewhere in code.
Credentials are blocked rather than pseudonymized. Mappings are held in memory
unless a caller passes a store that writes. A detector endpoint outside your
network is refused. Keys are read from an environment variable, and a literal
one in a config file is rejected. Each is real, each is tested, and each was
findable only by reading the source or trusting the README.

What was missing was one place to see all of it **against your own settings**.
The README describes a default configuration. It cannot tell you that *your*
config points a detector at a host outside the boundary, or that you raised
`min_confidence` to 0.8 and are now finding less than you think.

A privacy tool asks for a lot of trust. Trust extended to a document is
different in kind from trust extended to a command that answers questions about
the machine it is running on.

## Decision

`mamori privacy` describes what the loaded configuration does. It reads
settings, resolves them, and prints the answer. It runs no detector, contacts
nothing, and writes nothing.

It separates three kinds of statement, and the separation is the substance of
the decision:

**Measured** — computed from the settings in front of it. How many detectors
are active, which entity types are blocked and which are pseudonymized, where a
detection model is and whether the trust boundary admits it. Change the config
and these change.

**By construction** — true because of how the code is built, not because of a
setting. Nothing writes a protected value to a log. Restoration is scope-bound.
These cannot be switched off, and **each is printed with the name of the test
that fails if it stops being true**.

**Your responsibility** — what this library cannot check. Whether the service
you send protected text to retains it is not knowable from here, and a report
that implied otherwise would be worse than one that stayed silent.

Anything that widens exposure — a boundary set to `anywhere`, a model that will
be refused — is reported as a warning and sets a non-zero exit status, so a
deployment check can fail on it.

## Consequences

- "Trust the documentation" becomes "run the command against your own config".
- The by-construction claims are only as good as the tests they name, which is
  why [ADR 0020](0020-the-promises-are-checked-by-machine.md) exists and why a
  test asserts that every claim names a class that is really there. A report
  citing a test that does not exist would be worse than no report, because it
  would look like evidence.
- The report is a maintenance obligation. A future feature that stores
  something, or sends something somewhere, has to appear here or the command
  quietly becomes a lie. That obligation is the point: it is cheaper to
  remember when the report is a file in the repository than when it is a
  paragraph in a README nobody re-reads.
- It is not served over HTTP, including by the proxy. It is the operator's
  local view of their own machine, and publishing it would add surface without
  adding a reader.
