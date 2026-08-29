# 23. The model tier is measured, and the numbers are not what was claimed

**Status:** accepted

## Context

Every rule in this library has had a number against it since 0.2.0. The model
tier, added in 0.4.0, had a paragraph. The README said it "reaches what shape
cannot: an English name in running prose, a Chinese given name, a codename that
looks like an ordinary word." That was a design intention written as though it
were a result.

`mamori eval` could not even score a configured model: it ignored `--config`
and built a rules-only pipeline. The harness had existed since 0.2.0 and had
never been pointed at the thing it was most needed for.

## Decision

`mamori eval` honours the configuration, so a model in the settings is in the
run, and gains three things that make the measurement usable:

- **`--compare`** scores the rules alone as well and prints the delta, with the
  individual samples that changed named. An aggregate that moves from 2.0% to
  1.4% says something worked; a list saying `en-006` is now covered and `en-042`
  newly lost 56 ordinary characters says *what*, and whether you believe it.
  Tuning against an aggregate fits a prompt to a number instead of a language.

- **`--cache`** remembers what the model answered, keyed on the model *and the
  prompt*. Re-running is free; rewriting one line of guidance invalidates
  exactly the answers that depended on the old wording. A number nobody re-runs
  is a number nobody checks. It writes to disk, which is why it lives in the
  evaluation package and is named by no configuration key.

- **`--replay`** answers only from the cache, so a change to *scoring* can be
  checked without the model's variance in the way.

## What the numbers say

Balanced stance, `llama3.1:8b` running locally, after
[ADR 0022](0022-a-model-reports-values-not-offsets.md) fixed the contract:

| | leak: rules → +model | over-redaction | entity precision |
|---|---|---|---|
| `en-core` | 2.01% → **0.67%** | 0.66% → 4.43% | 1.000 → 0.855 |
| `ja-core` | 0.71% → 0.71% | 0.00% → 5.41% | 1.000 → 0.868 |
| `zh-core` | 0.00% → 0.00% | 2.55% → 10.18% | 0.964 → 0.871 |

**At this size, the model tier is an English-recall tool.** It closes the
English gap it was designed for and does nothing measurable for Japanese or
Chinese, while costing over-redaction in all three. The README's claim about
Chinese given names was not supported; the Chinese rules were already at 1.000
recall on this set, so there was nothing there for a model to add.

At the **recall-first** stance it is worse than useless: leak rate is unchanged
because the wide rules already reach those values, and over-redaction goes from
1.44% to 9.58%. Anyone running the default stance should leave the model off
until they have measured it against their own data.

One prompt change came out of the numbers rather than out of taste. Every
English false positive was `OTHER_SENSITIVE` — a weekday, a public IP, an error
code, a whole sentence about revenue — used as a dustbin for anything
structured. That type is blocked by the default policy, so those would have
*stopped requests*. A guidance rule stating what the type is for, what it is not
for, and that it stops the request, halved over-redaction from 8.80% to 4.43%.
Six false positives survive it, and further prompt work has visibly diminishing
returns against an 8B model that has now been told explicitly.

## Consequences

- The documentation says what was measured, with the model and the stance
  named. A number without those is not a number.
- These are 8B results on small synthetic sets. A larger model would plausibly
  do better and that is a hypothesis, not a claim: the harness to settle it now
  exists and takes one command.
- The quality floors in CI stay rules-only. Pinning a floor to a model's output
  would make the build depend on a model being installed, and on it answering
  the same way twice.
- The general lesson is the expensive one. A component can be correct in every
  line, tested at every unit, documented carefully, and contribute nothing —
  and the only thing that finds it is running it against reality and counting.
  Three releases went by.
