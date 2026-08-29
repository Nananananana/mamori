# 13. Recall first, by default

**Status:** accepted

## Context

Every detection rule sits on one trade: catch more, or be wrong less often.
Until now the library made that choice once, per rule, at the moment the rule
was written, and offered no way to move it.

That produced a coherent but silently conservative set. `POSTAL_CODE` needed the
〒 marker. `PHONE` refused an unseparated digit run. English names needed a
title, a salutation or a label. Each refusal was correct in isolation and each
was a documented gap, and together they meant the library was tuned for
precision by accident rather than by decision.

The two costs are not symmetric:

- **A miss** sends somebody's data to a third party. It is silent, permanent,
  and the thing this library exists to prevent.
- **A false positive** replaces an ordinary word with a token. It costs answer
  quality, and it is *visible* -- somebody reading a protected prompt notices a
  word that should not have been replaced. Nobody notices the name that was not.

Enough false positives cost adoption, and a privacy layer people stop using has
a real-world miss rate of 100%. So the asymmetry is real but not unbounded.

## Decision

Every rule declares a **tier**, and a **stance** decides which tiers run.

- `CORE` -- anchored on something rarely anything else: a checksum, a vendor
  prefix, an honorific, a label.
- `WIDE` -- shape alone. Ten bare digits, two capitalised words, a long
  random-looking token.

`Stance.RECALL_FIRST` runs both and **is the default**. `Stance.BALANCED` runs
core only.

Measured on the bundled datasets:

| | leak rate | | over-redaction | |
|---|---|---|---|---|
| | balanced | recall-first | balanced | recall-first |
| `ja-core` | 0.71% | **0.00%** | 0.00% | 6.34% |
| `en-core` | 2.01% | **0.67%** | 0.65% | 2.95% |
| `zh-core` | 0.00% | **0.00%** | 2.34% | 11.71% |

The stance changes **no security decision**. Policy still decides what leaves,
resolution still picks one detection per character, credentials are still
blocked. A wider stance only proposes more candidates, which is what makes
"recall-first never leaks more than balanced" a property worth testing rather
than a hope.

Wide rules are `LOW` confidence, so `min_confidence` can switch them off
without changing stance -- two dials on the same trade, at different
granularities.

## Consequences

The documented gaps that could be closed by accepting false positives are
closed: an unanchored English name, an unseparated phone number, a credential
with no vendor prefix, a postal code with no marker.

The cost is stated in the same table rather than buried. Roughly one ordinary
character in sixteen is replaced in Japanese, one in eight in Chinese.

Much of the measured over-redaction is the wide rules doing exactly their job.
`ja-007` is labelled "an order number, not a phone number" and recall-first
catches it; that is a deliberate cost recorded against balanced-stance labels,
not a defect.

## What it costs

Answer quality, measurably. A document with 6% of its ordinary characters
replaced reads worse and a model writes worse from it, and for a team whose
documents are full of product names that keep coming back as people, the right
setting is `balanced` -- which is why it is still there.

Two stoplists now carry weight they will never fully bear: Japanese katakana
loanwords and English title-case words. Both cut the noise substantially
(English over-redaction from 8.4% to 2.9%) and neither will ever be complete.
Both are the same admission the core rules already make.

Chinese over-redaction at 11.7% is the highest and the least defensible. It
comes from dropping the ordinary-word stoplist, which is the only thing keeping
`高兴` from being a person. Chinese is the secondary language and this is where
that shows.
