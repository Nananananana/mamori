# 31. The morphological adapter, measured and declined

**Status:** accepted

## Context

Proposed for 0.13, moved to 0.14, deferred in 0.19 and again in 0.22, and named
in every roadmap since as "still the right experiment; still not run". The
argument was always the same and always plausible: `川` is a surname and also
the word for river, `森` is a surname and also a forest, and no regular
expression can tell them apart. A morphological analyser can. It costs a
runtime dependency, so it would arrive as `mamori[ja]` behind the existing port
— and, per the roadmap's own rule, **be dropped if it did not win**.

It was run in 0.24. It does not win.

`janome` (IPADIC, pure Python, installs everywhere) was measured in both
directions on the bundled Japanese sets and on a thousand generated documents.

## What was measured

**Additive** — tokens tagged 固有名詞/人名 that the rules did not find. This is
the shape that fits the architecture, since every pass here only ever adds:

> **Zero.** In two hundred documents containing 1,010 rule-detected people, the
> analyser contributed **no name the rules had missed** and no spurious ones
> either. It sees what they see.

**Subtractive** — dropping a rule detection that overlaps no token the analyser
calls a person. This is where the win was expected:

| | leak | over-redaction | precision |
|---|---|---|---|
| `ja-core` | 0.00% → **1.37%** | 2.78% → 1.65% | 0.925 → 1.000 |
| `ja-docs` | 0.33% → **0.66%** | 1.06% → 0.81% | 0.938 → 0.983 |
| `ja-context` | 0.00% → **9.48%** | 0.00% → 0.00% | 1.000 → 1.000 |
| `ja-generated` | 1.37% → 1.42% | 0.72% → 0.55% | 0.983 → 1.000 |

It leaks in every set, and buys 0.2 to 1.1 points of over-redaction for it.

## Decision

**Not built.** The trade runs the wrong way for this library, which errs
towards over-redaction on purpose and says so in
[ADR 0013](0013-recall-first-by-default.md).

What it drops is exactly right some of the time — 森林 (a forest), 原因 (a
cause), 山口県 (a prefecture), サポート (support) — and exactly wrong the rest:

- **`凪沢`** — a surname IPADIC does not have. Every dictionary has an edge and
  every name outside it becomes a leak.
- **`清水`** — one of the commonest surnames in Japan, dropped because in that
  sentence the analyser read it as the ordinary word. The `川` problem, in
  reverse, at the same rate nobody measured.
- **`sato.hanako`** — a username in a file path. Not Japanese text at all, so
  the analyser has no opinion, and "no opinion" and "not a person" are the same
  answer to a filter.

That third one is decisive on its own. A filter that silently drops anything it
cannot parse is not a precision tool; it is a leak with a dictionary attached.

## Consequences

The optional dependency is not added. `pyproject.toml` gains no extra, the
port gains no adapter, and the roadmap item is closed rather than moved for a
fifth time.

The over-redaction it would have bought is real and remains available to
anybody who wants it: `mamori correct` rules a false positive out permanently
([ADR 0024](0024-corrections-are-appended-applied-at-read.md)), by name, with
the operator deciding rather than a dictionary. 森林 and 原因 are two
corrections, not a dependency.

**The way this was measured is worth keeping.** The generated corpus said the
filter was free — 22 spurious detections removed, *zero* real names lost across
two hundred documents. The hand-written bundled sets, which are a fiftieth of
the size, said it leaks. The generator draws names from pools of common ones,
which IPADIC knows; `凪沢` was invented for a test fixture in 0.16 precisely
because it is *not* in any dictionary. A corpus can only refute what its
generator can produce, and this is the second release running where that
sentence decided an answer.
