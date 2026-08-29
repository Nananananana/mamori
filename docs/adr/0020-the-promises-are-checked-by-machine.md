# 20. The promises are checked by machine

**Status:** accepted

Borrowed, with thanks, from the sibling `kiseki` project's ADR-0059.

## Context

The README opens with "No model, no GPU, no network" and "the mapping never
leaves your machine". [ADR 0019](0019-privacy-is-a-report-not-a-promise.md)
made `mamori privacy` print those claims back with the settings applied. Both
are statements about behaviour, and until now the only thing behind them was
that the code had been written carefully and reviewed by people who agreed.

That holds until a change that means no harm breaks one. A convenience import
that pulls in a library which phones home on load. A debug line added while
chasing a bug and left in, printing the entity it was about. A refactor that
loses the scope check in restoration. None of these look like privacy changes
in a diff, and none of them would have failed a test.

A promise nobody tests is a promise waiting to be broken.

## Decision

`tests/test_promises.py` holds one class per claim, and each fails if the claim
fails.

- **Nothing leaves the machine.** `socket.connect`, `connect_ex`, `sendall`,
  `sendto` and `create_connection` are replaced with functions that raise, and
  then the whole default path runs: protection, restoration, every language
  pack, the evaluation harness, the command line, and importing the package.
  A future dependency that dials out fails here rather than in somebody's
  deployment.

  Connecting is patched rather than the socket *class*, because `ssl`
  subclasses `socket.socket` at import time — replacing the class breaks an
  import and proves nothing about the network. The guard has its own test that
  it can still trip, since a ban that cannot fail would make every test under
  it vacuous.

- **Mappings stay in memory.** The default store is checked, and so is the
  absence of any configuration key that could turn on writing to disk. A file
  store must be passed in Python, by a caller who decided to.

- **Values stay out of diagnostics.** Every field holding a protected value is
  checked for exclusion from its `repr`, and the blocked-credential error is
  checked for not quoting the credential back.

- **Restoration is scope-bound.** A second scope, and a placeholder that was
  never allocated, both come back unchanged.

- **Keys are never in configuration.** A literal `api_key` is refused, the
  refusal does not echo it, and no serialisation carries one.

- **The model only adds.** A silenced model leaves the rules' findings intact,
  a hostile answer removes nothing, and a hallucinated span is dropped.

Finally, a class checks the checkers: every claim in `mamori.report` must name
a test file and class that exist, and every class named as evidence must
actually contain tests.

## Consequences

- The privacy section of the README becomes a specification rather than a
  description.
- The suite is written before the versions that will need it most. Persistent
  storage, richer sources, and anything that batches work across users are all
  places where a mistake would be quiet, and the test that catches it exists
  first.
- Some of these tests are strange to read — asserting on `__dataclass_fields__`,
  monkeypatching the socket module. That strangeness is the cost of testing a
  negative, and testing a negative is exactly what a privacy guarantee is.
