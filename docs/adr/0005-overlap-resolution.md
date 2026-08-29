# 5. Resolve overlapping detections by width first

**Status:** accepted

## Context

Several rules run over the same text, so overlaps are the normal case rather
than the exception. `田中太郎(tanaka@example.com)` produces a name span, an
email span and possibly a company span, overlapping and nested.

Overlapping replacements corrupt text, so exactly one detection per character
has to win. Leaving that to whichever rule happened to run first makes the
output depend on declaration order, which is how a rule reordering turns into a
silent leak.

The first ordering tried was severity first, on the reasoning that a credential
should beat a name.

## Decision

Preference order:

1. Longer span
2. Higher entity-type severity
3. Higher detector confidence
4. Earlier start offset
5. Detector name, then type name — stable tie-breaks

Width comes first because **replacing a wider span also removes everything
inside it.** Given `https://git.corp.local/?token=ghp_xxx`, keeping the URL and
discarding the token still redacts the token; keeping the token and discarding
the URL leaves the internal hostname in the payload. Width-first is the safer of
the two, not merely the tidier one.

Severity still decides between two spans of equal width, which is where a
password assignment beats an `EMAIL` match over the same characters.

## Consequences

The result is deterministic and independent of input order, which
`test_ordering_of_the_input_does_not_change_the_outcome` asserts directly.

`assert_non_overlapping` runs as an invariant check before replacement, so a
future resolver bug surfaces as an exception rather than as corrupted output.

## What it costs

The containment argument holds only because every surviving span is replaced. A
policy mapping a *wide* type to `ALLOW` breaks it: an allowed URL would leave a
blocked token sitting inside it. `ALLOW` is therefore documented as reserved for
types whose extent you are sure about.

Passing the policy into resolution would close that hole properly. It is more
coupling than v0.1 needs, and it is written down here so the next person knows
it was a choice rather than an oversight.
