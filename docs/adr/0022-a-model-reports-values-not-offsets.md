# 22. A model reports values, not offsets

**Status:** accepted

**Supersedes** the response contract introduced with the model pass in 0.4.0.

## Context

The model pass asked for character offsets and verified them:

```json
{"entities": [{"type": "PERSON", "start": 0, "end": 4, "text": "田中太郎"}]}
```

A candidate survived only if `text[start:end]` was exactly the reported value.
The reasoning was sound — a hallucinated span would splice the wrong characters
out of somebody's document — and the check was three lines. It shipped in 0.4.0
and stayed through 0.5.0 and 0.6.0.

Nobody measured it. When v0.7 finally did, against 49 English samples with a
local 8B model:

| | count | share |
|---|---|---|
| offsets correct | **0** | 0.0% |
| value real, offsets wrong | 51 | 98.1% |
| value not in the document | 1 | 1.9% |

Zero. The model identified the right values almost every time and placed them
correctly not once. `'John Smith' said 4..13, actually 4..14` is the
representative case: right start, off-by-one end, discarded.

Character offsets are close to the one thing a tokeniser-based model cannot
produce. It does not see characters, it sees tokens, and counting from zero
across a mixed-script document is arithmetic performed by a system with no
arithmetic. The contract asked for the one part of the job the model was worst
at, and then threw away the part it was good at for failing.

The consequence is that **the model tier contributed essentially nothing from
0.4.0 to 0.6.0**, and the documentation described a capability that was not
there. Not because the code was wrong — every line did what it said — but
because nobody had run it against a real model and counted.

## Decision

The **value** is the answer. Offsets are a hint.

- The type must exist, or the candidate is dropped.
- Offsets, when given, are used **only if they already agree** with the
  reported value. A model that can count keeps its exact span, which also
  resolves the one case a search cannot: the same value twice, only one meant.
- Otherwise the reported value is located in the text, on word boundaries where
  the script has them, and **every occurrence** becomes a candidate. A value
  judged sensitive once is sensitive wherever it appears; protecting one
  mention and leaving the others is not protecting it.
- A value that does not appear in the text at all is dropped.

The prompt stops asking for positions and says so explicitly, because a model
told to report offsets will report offsets whether or not the schema wants
them.

`find_occurrences` moves into the domain layer, where the co-occurrence pass
was already doing the same work for the same reason — a value confirmed once
is the same value later in the document.

## Consequences

**The guarantee is unchanged, and stronger.** mamori never creates a span it
did not locate itself. A hallucinated value is not found and is discarded — the
one invented case in the measurement, a name the model inferred from an email
address, is still correctly dropped. What changed is that being useful no
longer requires the model to be good at counting.

**Measured effect, at the balanced stance with `llama3.1:8b`:** English leak
rate 2.01% → 0.67%, closing `en-006` — the unanchored name that has been a
documented gap since 0.1.0 and the exact case this tier was built for.

**One proposal can now produce several detections.** This is a behaviour change
for anyone counting entities, and it is the right one.

**A short value is refused.** Two characters is the floor; one would match most
of a CJK document. Below it the candidate is dropped rather than located
badly.

**Values are matched literally.** A reported value containing regex characters
is data, not a pattern, and a test pins that.

**The lesson generalises beyond this contract.** A verification step that
rejects almost everything looks identical, in the code and in the tests, to one
that rejects almost nothing. Only counting tells them apart, which is why
[ADR 0023](0023-the-model-tier-is-measured.md) exists.
