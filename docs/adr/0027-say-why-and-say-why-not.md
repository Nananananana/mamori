# 27. Say why, and say why not

**Status:** accepted

Delivers `kiseki` ADR-0063 ("evidence names its source"), which
[proposal 0001](../proposals/0001-the-road-to-1-0.md) listed as still open.

## Context

Every detection has recorded which rule found it and how confident that rule
was since 0.1.0. Almost nothing surfaced it. So the two questions every user
asks had different answers:

**Why was this redacted?** Answerable, awkwardly, by reading `inspect` output
and knowing what the columns meant.

**Why was this *not* redacted?** Not answerable at all. A miss is the failure
this library exists to prevent, and the only available response was "the rules
did not match", which is a restatement rather than an explanation.

There was also a quieter problem. Overlap resolution keeps one detection per
character and throws the losers away without a word. A user asking "why is this
a `PERSON` when it is obviously a company?" — a real question, and in 0.9 a
real bug — had nothing to look at.

## Decision

**A trace, off by default.** `ProtectionResult.trace` records every candidate
the pipeline considered and what became of it: kept, below the confidence
threshold, ruled away by a correction, or displaced by an overlapping detection
that won. Four things can happen and only one of them was visible.

Traced resolution is the *same loop* as the real one, with the losers collected
rather than dropped, and a test asserts the two keep identical sets. An
explanation that drifts from the thing it explains is worse than none.

Every displacement says which preference decided it — wider span, higher
severity, higher confidence, earlier offset, or a stable tie-break — which
makes the resolution order inspectable instead of a paragraph in
[ADR 0005](0005-overlap-resolution.md).

**`mamori trace`** prints that, and then answers the harder question the only
honest way available: it runs the *other* stance and says what the wider rules
would have caught, as a shape rather than a value. When neither stance finds
anything more, it says so and points at the two things that can help — a
correction for a value you can name, the model tier for the general case — with
`mamori eval --compare` as the way to find out what either costs.

**`mamori audit`** asks the same of a corpus: which rules carry the load, and
which have never fired once. Rules are run individually rather than through the
pipeline, because a rule that fires and always loses an overlap looks identical
to one that never fires, and those are different problems.

Rules gain stable identifiers — `en.PERSON.2`, `universal.EMAIL.1` — derived
from pack, type and declaration order. Naming a hundred rules by hand is a
hundred chances to name one wrongly; an explicit `name=` is available where a
rule deserves one.

## What it found immediately

**Three rules shipped in 0.10 had never been measured.** The prose password
rules — `the password is X`, `パスワードは X`, `密码是 X` — were added because
prose is how somebody actually pastes a credential into a chat window, and no
dataset sample exercised any of them. Credential detection, added without
evaluation coverage, in the release that was about not trusting unmeasured
things.

**A UK-shaped phone rule had never fired either**, for the same reason: no
sample used the format.

Samples for all four now exist, in three languages, including the negatives
that matter more — "my password is fine" must not stop a request.

**The remaining ten dead rules are the vendor-prefixed credential rules**, and
they cannot have samples: a literal key in a file that ships inside the wheel
trips the secret scanner of everyone who clones the repository. `audit` says so
rather than listing them beside genuine findings, and a test pins that nothing
*else* is dead — so the next unexplained one is visible.

**And a stale published figure.** The `ja-docs` leak rate in 0.9 was measured
before a fix that landed in the same release, and was published at 2.49% when
it was 1.83%. Corrected here.

## Consequences

**The trace carries previews, never values.** It is exactly the sort of output
somebody pastes into a bug report. Masking happens where the decision is
recorded rather than at the edge, so there is no path from a trace to a value
even by accident, and a test checks it.

**It costs a list of every candidate**, which is why it is off by default and
why `protect` is unchanged when nobody asks.

**`audit` is only as good as the text you give it.** Over the bundled corpus it
says which rules that corpus exercises. Pointed at your own documents with
`--file` it says which rules matter to you, which is the more useful question
and the reason the flag exists.

**The overlap-resolution question is now visible rather than settled.**
Severity is still preferred over confidence, so a low-confidence guess can
outrank an anchored rule of another type when spans are equal. The trace shows
it happening. Whether to change the order is a question for evidence, and the
evidence is now collectable.
