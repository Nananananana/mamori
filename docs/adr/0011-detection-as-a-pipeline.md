# 11. Detection is a pipeline of passes

**Status:** accepted

## Context

`Detector` is a narrow contract: text in, findings out. That narrowness is a
feature. A rule set that cannot see the other rule sets' results cannot develop
opinions about them, and every detector stays testable in isolation.

Some detection does not fit it. Once `田中太郎` has been confirmed by an
honorific in one sentence, every other occurrence in the same document is the
same person. No rule looking at those occurrences alone can tell — the evidence
is *what was already found*, which a `Detector` is not given.

Two options:

1. **Hardcode the second pass** inside `ProtectionService`. Smallest diff, and
   it makes a real behaviour permanently unswitchable — exactly the coupling
   this project set out to avoid.
2. **Widen the `Detector` contract** so every detector sees prior results.
   Cheap, and it hands context to a hundred regex rules that have no use for it
   and can only be confused by it.

## Decision

A third port, `DetectionPass`, whose `run` receives a `DetectionContext` — the
text **and** everything earlier passes found — and returns what it adds.

`DetectionPipeline` runs passes in order and is itself a `Detector`, so nothing
upstream changed: `ProtectionService` still asks one object what it can see.
`DetectorPass` adapts an ordinary detector into the first pass, which keeps the
narrow contract the default.

The port earns its place under the rule from
[ADR 0007](0007-defer-the-async-machinery.md) — a port with no second
implementation is a guess. There are two on the day it lands: the rules pass and
the co-occurrence pass.

Nothing is deduplicated or resolved in the pipeline. Passes may report the same
span twice, and `mamori.domain.resolution` settles conflicts once, in one place,
as it always did.

## Consequences

Detection can be assembled rather than inherited: reorder the passes, drop one,
add one. `mamori config` shows which are active and `--no-co-occurrence` turns
the second one off, so "switchable" is something a user can do rather than
something the architecture claims.

The co-occurrence pass fell out at about sixty lines, and it moved English leak
rate from 7.4% to 2.0% and Chinese from 1.5% to 0.0% with no precision cost.

A custom pass needs no fork. `tests/contracts.py` carries the conformance suite
for the new port alongside the other two.

## What it costs

A third port is a third thing to understand, and the difference between a
`Detector` and a `DetectionPass` is subtle enough to be got wrong — the answer
is "does it need to see what else was found", and most of the time it does not.

Pass order is significant and unenforced. A pass that reasons over prior
findings placed first sees nothing and silently contributes nothing. The
pipeline could refuse to run such a pass first; it does not, because it cannot
tell them apart, and a check that guesses would be worse than none.
