# 21. A long document is windowed, not skipped

**Status:** accepted

**Supersedes** the refusal behaviour introduced with the model pass in 0.4.0.

## Context

A model has a context limit and a document can be longer than it. 0.4.0 chose
between two options and picked the safer one.

**Truncate** was rejected outright, and correctly: a pass that scanned the
first 8000 characters would report success on a document it never read, which
is the exact failure this library exists to prevent.

**Refuse** was what shipped. Over the limit, the model pass returned nothing.
The pattern rules still ran, so the guarantee held, and the reasoning written
in the code was sound as far as it went.

What it missed is that the improvement then stops applying at the length where
documents get interesting. A one-line message gets the model tier. A long email
thread, a contract, a support transcript — the documents most likely to contain
a name no rule can anchor — get patterns only, silently, with nothing in the
output to say so. That is a recall hole with a length threshold on it, and the
standing instruction for this library is to lean towards catching everything.

## Decision

A text longer than the limit is cut into overlapping windows, and every window
is scanned.

**The windows overlap.** This is the whole difficulty. An entity lying across a
cut is, to each piece, a fragment: `tanaka@exa` and `mple.com` are not an email
address to anybody. The overlap is 400 characters by default, comfortably
longer than any entity this library detects, so anything cut by one boundary is
whole inside its neighbour.

**Cuts prefer a boundary.** A blank line, a newline, a sentence ending — in the
CJK forms as well as the ASCII ones, because a Japanese document contains no
ASCII full stops at all. A cut looks backwards only a quarter of a window; past
that, honouring a boundary costs more window than it saves. A hard cut mid-word
is acceptable, because the overlap covers it.

**Offsets travel with the window.** A detection at position 12 of the third
window is not at position 12 of the document, and getting that wrong would cut
characters out of the wrong sentence at replacement time. The arithmetic lives
in one place, in the domain layer, with the offset carried beside the text
rather than recomputed by each caller.

**Duplicates from the overlap are dropped.** Overlap resolution would collapse
them anyway, but the overlap exists for the library's own reasons and should
not show up in the user's counts on the way there.

Alongside this, `BatchLLMProvider` is an **optional** capability: a provider
that implements it is handed the whole document's windows at once. A shared
model on another machine is dominated by round trips, and ten windows should
not mean ten times the latency. It is advertised by implementation rather than
by a flag — the same shape as `supports_structured_output` — so nothing
existing changes, and a provider wrapping a model in this process, which gains
nothing from batching, simply does not implement it. This is the sibling
`kiseki` project's ADR-0015 argument: write the port for the harder case before
retrofitting it becomes a breaking change to every implementation.

## Consequences

- The model tier now applies at every length, which is where its value was
  always going to be.
- A long document costs several model calls instead of none. That is a real
  cost and the honest one: the alternative was paying nothing and getting
  nothing while appearing to have scanned.
- The overlap is repeated work — about 5% at the default window size, more at
  small ones. Cheaper than a missed name.
- Windowing is pure text arithmetic with two properties worth stating as
  properties, so both are tested with Hypothesis over arbitrary text: every
  character appears in some window, and every window is a real slice of the
  document at its stated offset.
