# 24. Corrections are appended, applied at read

**Status:** accepted

Borrowed, with thanks, from the sibling `kiseki` project's ADR-0044.

## Context

Everything in this library decides for itself. Rules fire, a model proposes,
the resolver picks a winner, the policy acts. The person watching `Monday`
become a `PERSON` — a real false positive, produced by a salutation anchor that
is right far more often than it is wrong — has had no way to disagree.

The options available to them were editing the rule set, or writing a prompt
overlay that a pattern rule does not read. Neither is available to somebody who
simply wants their own document to come out right, and both are the wrong shape
anyway: a general rule change to fix one value in one organisation's text.

0.7 sharpened this. Measuring the model tier produced a list of false
positives — a weekday, a public IP, an error code — and made the problem
visible without making it fixable. A privacy layer that redacts words people
need, with no recourse, is one people switch off, and a privacy layer switched
off has a real-world miss rate of 100%.

## Decision

A **correction** is one appended record: a value, a verdict, a note, a date.

- `never` — this value is not sensitive here. Detections of it are dropped.
- `always` — this value is sensitive here, of this type, wherever it appears.

The log is append-only and the latest word about a value wins, so undoing a
correction is another correction and the history of what was decided survives.
It is applied at read time: `never` filters what was detected, before overlap
resolution so that a corrected-away value cannot first win a span and then
vanish, leaving a hole where a real detection would have been. `always` is a
detection pass like any other, using the same `find_occurrences` the
co-occurrence pass and the model parser already use.

Nothing is rewritten. Rules are untouched, prompts are untouched, and removing
the log restores exactly the previous behaviour.

An `always` correction carries `CERTAIN` confidence. A rule is a guess about a
shape and a model is a guess about a sentence; an operator typing a value into
a log is neither, and it should win overlap resolution against both. It runs
last and adds only what nothing else covers — a correction supplies evidence,
it does not argue with a rule that already fired.

### The part that needed the most care

**`never` can remove protection, and nothing in mamori could do that before.**
Every pass, every tier, every model proposal could only ever add, and that
one-way property is what makes it safe to let a model near a document at all.
This breaks it deliberately, so the exception is kept narrow:

- an exclusion is **visible**: `mamori privacy` names every excluded value and
  reports it as a warning with a non-zero exit status, so a deployment check
  can fail on one nobody meant to ship;
- it is **reversible**, by appending the opposite;
- it is **logged**, with a note and a date, so a reviewer can ask why;
- and it **cannot reach a credential**.

That last rule is enforced in three places, because one is not enough:

| where | catches |
|---|---|
| `CorrectionLog.appended` | an exclusion naming a credential *type* |
| `CorrectionLog.excludes` | any credential at read time, whatever a hand-edited file says |
| `mamori correct` | the value itself, by running the detectors **before writing** |

The third exists because a `never` ruling names no type at all — the operator
is saying "this value is not sensitive", not "this password is not a
password" — so the first has nothing to look at. Checking before writing also
matters more than the refusal: appending first and rejecting at read time would
leave the credential sitting in a file on disk, which is the outcome this
library exists to avoid.

## Consequences

**A false positive becomes a one-line fix** instead of a fork:

```bash
mamori correct Monday --never --note "a weekday, not a name"
mamori correct Acme --always COMPANY_NAME --note "trading name, no suffix"
```

The second closes `en-027` and `ja-020` for the organisation that hits them —
trading names with no legal suffix, a gap documented since 0.1.0 that no
pattern can close in general and any operator can close for their own data.

**The log holds values, and some of them are sensitive.** A value ruled
`always` is by definition one the operator considers sensitive, and it is now
in a file. That is their decision, and `mamori privacy` says so rather than
leaving it to be discovered. The file itself says so too, in a `_note` field,
because somebody will find it in a repository.

**It is per-value, not per-pattern, and that is the limit.** `Monday` is
excluded; `Mondays` is not. A correction is a record of what this operator
ruled on, not a rule, and the moment it grows wildcards it becomes a rule
system with none of the review a rule gets. If that is genuinely needed, the
place for it is a locale pack or a prompt overlay.

**It is not a "sensitive words" list, and must not become one.** Such a list
encodes one person's idea of what is private, is wrong for the next person, and
grows by taste rather than by rule — the argument `kiseki` makes in its
ADR-0069. This is narrower on purpose: not a claim about what is sensitive in
general, but a record of what *this operator* decided, appended and reversible.
