# 25. Measure at the length people actually send

**Status:** accepted

## Context

Every quality number this project has published since 0.2.0 came from 123
samples with a median length of **28 to 44 characters**. The whole corpus was
4,254 characters — about two pages.

mamori is for documents. It has a proxy for chat applications, a windowing path
for texts over 8,000 characters, a propagation pass whose entire purpose is to
carry a name from where it was anchored to where it was not, and a streaming
restorer for long answers. None of those were exercised by a single sample. The
windowing path, added in 0.6.0, had never once run during an evaluation.

This was known and stated — `SECURITY.md` has always said the sets are small
and synthetic. What was not known is how much the numbers changed at the length
people actually send things, and that is not a caveat, it is a measurement
nobody had taken.

## Decision

A second tier of bundled datasets: `en-docs`, `ja-docs`, `zh-docs`. Business
documents at real length — reply chains with quoted blocks, meeting minutes
with attendee lists, support tickets with log excerpts, a CV, a contract
extract, a technical note with almost nothing to protect, and a document with
an instruction to a model buried in it.

The core sets stay exactly as they are. They are good regression guards and
cheap to run, and replacing them would throw away the history behind every
floor. Both tiers are measured, both are published, and the quality floors
cover all six.

## What it found immediately

Four bugs, all of them invisible at 44 characters and all of them serious in
prose:

**A name spanned a blank line.** The wide English name rule joined its words
with `\s+`, so a heading and the first word of the next paragraph became
`Headcount\n\nOne` — a person. Every document with headings in it.

**A legal suffix read as a surname.** `Umbrella Ltd` matched the wide name
rule, and `Where Umbrella Ltd` matched it more widely still. Because the widest
span wins overlap resolution, the anchored company rule lost to a shape guess:
the value was protected under the wrong type, with the wrong placeholder, under
a different policy category, and an ordinary word was redacted with it.

**An address at the end of a sentence was missed.** The internal-IP rule
refused any trailing dot, to avoid matching the first four parts of
`1.2.3.4.5`. A sentence-ending full stop is also a trailing dot, so `on
10.0.4.31.` found nothing. In one-line samples an address is never followed by
a full stop; in documents it usually is.

**The Japanese wide name rule reported 37 loanwords as people** across eight
documents — ホスト, プール, ゲートウェイ, ノード, エンジニア — and not one true
positive the anchored rules did not already have. It was filtered by a stoplist
of loanwords whose own comment admitted it "will never be complete".

That last one is the interesting one, and it was fixed by deleting the rule
rather than extending the list. Japanese business writing borrows freely and
coins loanwords faster than anyone maintains a list, so such a list encodes one
author's vocabulary and is wrong for the next document — the argument the
sibling `kiseki` project makes in its ADR-0069. **A bare katakana run is not
weak evidence of a name; it is no evidence of one, and the wide tier is for
weak evidence rather than for none.** What replaced it is anchored: a middle
dot (a Japanese convention for foreign personal names specifically), an
honorific, or a label. Those were added at the *core* tier, and closed a real
gap — `ジョンさん` was not detected by any rule before 0.9, while `ホスト` was.

## Consequences

**The rules got better at both scales.** Nothing regressed:

| recall-first | leak before → after | over-redaction | precision |
|---|---|---|---|
| `en-core` | 0.67% → 0.67% | 1.44% → **0.78%** | 0.938 → **0.979** |
| `ja-core` | 0.00% → 0.00% | 3.11% → **2.42%** | 0.908 → **0.937** |
| `ja-docs` | — | 6.08% → **1.06%** | 0.600 → **0.934** |

**Documents leak several times more than fragments, and that is now published.**
At the default stance: `en-docs` 3.55% against `en-core` 0.67%; `zh-docs` 6.11%
against `zh-core` 0.00%. The fragment numbers were not wrong, but read alone
they described the library at its easiest.

**At the balanced stance, English documents leak 20.3%.** A fifth of the
sensitive characters, because a document is full of names with no anchor near
them — in an attendee list, under a sign-off, after "Reported by:". This is the
strongest evidence the project has for why recall-first is the default, and it
is pinned as a floor so it stays visible rather than being discovered by
somebody's deployment.

**The floors now cover both tiers**, twelve in total. A rule change that helps
sentences and hurts documents turns the build red.

**Still not enough, and stated as such.** Twenty documents is better than 123
fragments and is not a corpus. The sets are still invented, still written by
the same hand as the rules, and still cannot say what mamori does on somebody
else's inbox. What they can now do is fail when a change makes documents worse,
which nothing could do before.

## Added later: a timing measurement must record what it ran on

This ADR is cited by sibling projects as the pattern for measuring latency, so
the trap it did *not* cover belongs in it.

Every per-document timing this project published for the model tier — from
twenty seconds to three hundred and forty-five — was **CPU inference on a
machine with an idle 16 GB GPU**. An interrupted Ollama update had removed the
CUDA library and died partway through writing its replacement, so GPU discovery
failed in 0.19 seconds instead of the 6.7 it takes when it succeeds. The server
logged `library=cpu` and `total_vram="0 B"` at every start for six days, and
nothing in the harness read that line.

The number even had an explanation. The slowest model was three times the size
of the fastest and six times slower, which was attributed to VRAM contention
between resident models — a story that fit the effect, was checkable, and was
not checked. **A plausible cause that accounts for the size of an effect is not
evidence for it**, and `nvidia-smi` was one command away the whole time.

So, for anything measuring elapsed time rather than counting characters:

- **Record the device the work ran on, in the output**, next to the number. Not
  in a README written afterwards from memory of what the machine had.
- **Assert it**, where the harness can. A run that silently falls back to a
  slower device produces numbers that look like a finding about the model.
- **Distrust an explanation that arrives with the anomaly.** The convincing
  ones are the expensive ones, because they end the search.

What separates this from a quality measurement is worth naming: a leak rate is
a property of the code and the corpus, and it reproduces anywhere. A duration
is a property of the code, the corpus, **and the machine** — and the machine is
the term nobody writes down. Everything else in this ADR survived the mistake
untouched — **except that the last clause of that sentence was itself an
assertion.** "The device does not change what a model returns" was written
here, and in five other places, as the reason the accuracy figures survived the
mix-up. It was never measured.

It has been now, and it is false: changing only the device, on a pinned version,
one model redacts 44% more on CPU than on GPU and reproduces exactly. What did
hold is the narrower thing this ADR actually needed — the leak rate and the
entity recall are byte-identical across devices, so the numbers being defended
were fine and the sentence defending them was not.

Which is this ADR's own lesson landing on this ADR: **the convincing
explanation is the expensive one, because it ends the search.** This one ended
it for the accuracy column, and the fix was to run four hours of measurement
rather than to write a better sentence.
