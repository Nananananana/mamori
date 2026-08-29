# 10. Restore streamed responses by holding the shortest unsafe suffix

**Status:** accepted

## Context

An LLM answer arrives token by token, and tokens do not respect placeholders.
`<PERSON_001>` shows up as `<PER`, then `SON_0`, then `01>`. Two obvious
approaches both fail:

- **Restore each chunk as it arrives.** The fragments match nothing, so the
  placeholder is emitted raw and the value is never restored. The user reads an
  answer addressed to `<PERSON_001>`.
- **Buffer the whole answer, then restore.** Correct, and it throws away the
  reason for streaming. The user watches a spinner for the length of the
  generation.

There is a third failure mode, subtler and worse than either: a streaming path
that *usually* agrees with the batch path. It breaks at whichever token boundary
the model happens to pick, which is not reproducible, not visible in a test
written from examples, and shows up as a mangled real value in production.

## Decision

Hold back the shortest suffix of the buffer that further input could still turn
into a placeholder; emit everything before it, restored.

The held suffix is found by scanning backwards for the first position from which
the rest of the buffer matches a "could still become a placeholder" pattern — an
opening bracket, a type name part-way spelled, a separator, digits mid-way. The
scan never looks back further than the longest possible placeholder, so the work
per chunk is bounded.

The pattern is deliberately loose. Holding an ordinary trailing word for one
chunk costs a few characters of latency; releasing half a placeholder costs a
restoration. An opening bracket counts on its own, with nothing after it —
without that, a buffer ending in `<` is released and the next chunk produces
`<田中太郎>` instead of `田中太郎`.

The invariant is stated and tested rather than assumed:

> For any chunking of a response, the streaming path emits exactly what
> `restore()` would emit for the whole response.

`tests/test_streaming.py` checks it with Hypothesis over adversarial text built
from the characters most likely to break the boundary logic, plus every uniform
chunk size from 1 upward.

## Consequences

The reader sees the answer as it is written, with a lag of at most a few
characters, and the streamed text is byte-identical to the batch result.

Scope isolation carries over unchanged: a streaming restorer resolves only
placeholders allocated in its own session, so a response cannot fish values out
of another one by guessing.

The property test caught the lone-bracket bug on its first run. An
example-based test would have needed somebody to think of chunking exactly at
the `<`.

## What it costs

The holding pattern over-triggers: a trailing English word looks like a type
name being spelled out, so the last word of most chunks is held for one round.
That is the intended direction of the trade, but it means a stream of one-word
chunks emits nothing until the following chunk arrives.

The restorer is single-use and not thread-safe. One stream, one restorer.

`StreamSummary` reports which placeholders were restored, altered or left
unrecognised, but not where — offsets across a stream would have to be relative
to a text that never exists in one piece.
