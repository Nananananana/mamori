# 0001. The road to 1.0

**Status:** current plan, revised after 0.11.0

A roadmap in a README is a list. This is the reasoning behind the list, which
is the part that changes when something is learned. ADRs record decisions
already made; this records what is intended and why, and is expected to be
edited.

## What the first nine versions actually established

- `0.1`–`0.3` — the core: offset-preserving normalization, deterministic
  overlap resolution, tamper-tolerant restoration, scope-partitioned mappings,
  language packs, one configuration object.
- `0.4` — a recall-first default and a prompt layer with addressable parts.
- `0.5` — the model's location and its client library became configuration; the
  layering became a test.
- `0.6` — the proxy, so applications that already exist are covered; and the
  privacy claims became answerable (`mamori privacy`) and machine-checked
  (`test_promises.py`).
- `0.7` — the model tier was measured for the first time and found to have been
  contributing nothing since 0.4, because it was asked for character offsets.
- `0.8` — corrections, so the operator has the last word.
- `0.9` — the datasets grew to document scale and found four detection bugs the
  fragment sets could not have shown.
- `0.10` — a demo that runs, a guide to measuring on your own text, and a bug
  in the harness that had been corrupting the model-tier numbers since 0.7.
- `0.11` — surrogate values, off by default, with the failure mode they carry
  made detectable rather than merely documented.

## What measuring keeps changing about the plan

Three things came out of measuring, and each moves something on the roadmap.

**A correct-looking component can do nothing for three releases.** The offsets
bug survived unit tests, ADRs and careful documentation. What found it was
running against reality and counting. Everything asserted rather than measured
is now suspect until it has a number, and the roadmap should prefer work that
produces numbers over work that produces features.

**The datasets are the weakest thing in the project.** Every published figure
rests on 123 invented sentences. They are good at catching regressions — that
is what they were built for — and weak evidence about anyone's real data. This
was always known and stated; it is now the binding constraint on how much any
claim can be trusted, which promotes it.

**There is no way for a user to disagree.** The model proposes `PERSON` for
"Monday". The wide tier redacts a part number. Today the only recourse is to
edit rules or fork the prompt library, and neither is available to somebody who
just wants their own document to come out right. Everything mamori does is
decided by the library, and the operator has no last word.

## The plan

### 0.8 — Corrections: the operator's last word

An append-only log of values the operator has ruled on. `"Monday"` is never a
name here. `"Acme"` always is a company. Latest word per value wins, so undo is
another append, and nothing rewrites a rule or a prompt.

This is the sibling `kiseki` project's ADR-0044 shape, and it is the one place
mamori will ever let something *remove* protection — which is why it needs the
most careful design in the project so far, not the least:

- a correction may never allow-list a credential; that refusal is mechanical;
- what a correction excludes is visible in `mamori privacy`, and reduces the
  protection this configuration provides;
- the promises suite pins both.

Chosen first because it is the thing every user meets on day one, and because
0.7 made false positives measurable without making them fixable.

### 0.9 — The evidence under the numbers *(delivered)*

Every claim in `SECURITY.md` rested on 123 synthetic sentences with a median
length of 44 characters, and mamori is for documents.

Delivered as document-scale datasets (`en-docs`, `ja-docs`, `zh-docs`), which
found four detection bugs on their first run and moved the published leak rate
for English documents from an implied 0.67% to a measured 3.55%. See
[ADR 0025](../adr/0025-measure-at-the-length-people-send.md).

Two parts of the original intent are **not** done and move to 0.10:

- a documented way to bring your own labelled data, so an organisation can
  measure mamori on text that looks like theirs without contributing it back.
  `mamori eval --dataset` already accepts one; what is missing is the
  documentation and the warning that such a file contains real data;
- the open question from 0.7, still open: does a model above 8B change the
  model-tier table? The harness exists and the run takes one command.

### 0.10 — A demo, and bring your own data *(delivered)*

`mamori demo` with five scenarios and a `--live` mode that sends a real request
to a real model, and
[docs/measuring-your-own-data.md](../measuring-your-own-data.md).

**The larger-model question is still open, and now has a reason.** `gemma4:12b`
times out on the hardware available here, so a run does not complete. That says
something about the machine and nothing about the model, and the honest record
of it is "not measured" rather than a table. It stays on the list.

Building the demo also found two things: a password written in prose (`the
password is X`) was not detected in any language, and a measurement where every
model call fails reported a clean zero delta. Both are fixed. The second is the
third time in four releases that something correct-looking turned out to be
doing nothing, which is beginning to look less like bad luck and more like the
shape of this kind of software.

### 0.11 — Surrogate values *(delivered)*

`田中太郎` → `山田一郎` rather than `<PERSON_001>`, off by default. Reserved
ranges wherever any exist (RFC 2606, RFC 5737, the 555-01xx block), so a
structured surrogate that escapes means nothing anywhere. Names have nothing
reserved and that is the residual risk, stated everywhere it can be.

The design turned on one observation: an unrestored placeholder is obvious and
an unrestored surrogate is a sentence about the wrong person. Restoration loses
its shape-tolerance, which cannot be avoided, so `RestorationResult.missing`
became the thing that makes the failure detectable instead of silent. See
[ADR 0026](../adr/0026-surrogates-trade-obviousness-for-readability.md).

### 0.12 — Deployment: persistence and integration

- An opt-in encrypted store, for deployments that cannot hold mappings in
  memory alone, with **retention as a rule rather than a machine**
  (`kiseki` ADR-0062): a stated policy the operator sets, not a background
  process that quietly decides.
- A Presidio adapter, so an organisation already invested there keeps its
  recognisers and gains the placeholder and restoration layer.

### 1.0 — The contract

Not a feature. 1.0 means the public API is stable, the promises suite is the
specification of what the library will not do, and the numbers in `SECURITY.md`
have data behind them that is worth the word "measured".

## Deliberately not planned

**A "sensitive words" list.** Somebody will ask. Such a list encodes one
person's idea of what is private, is wrong for the next person, and grows by
taste rather than by rule — the argument `kiseki` makes in its ADR-0069. The
corrections log in 0.8 is the shape that works instead: not a claim about what
is sensitive in general, but a record of what *this operator* has ruled on,
appended, reversible, and visible.

**Async, batching across users, a worker queue.** [ADR
0007](../adr/0007-defer-the-async-machinery.md) still holds. Nothing has asked
for it.

**A web framework in the core.** The proxy is `http.server` and its ceiling is
stated. If it ever needs more, that is a separate package.

## Ideas taken from kiseki, and what is still open

| kiseki | taken in | as |
|---|---|---|
| ADR-0026 serve on the stdlib | 0.6 | the proxy |
| ADR-0046 privacy is a report | 0.6 | `mamori privacy` |
| ADR-0059 promises checked by machine | 0.6 | `test_promises.py` |
| ADR-0015 write the port for the harder case | 0.6 | optional batching |
| ADR-0051 a reading remembers its prompt | 0.7 | the cache key |
| ADR-0044 corrections appended, applied at read | 0.8 | this proposal |
| ADR-0062 retention is a rule, not a machine | 0.12 | the encrypted store |
| ADR-0069 the gate is evidence, not a word list | 0.9 | why the katakana stoplist was deleted rather than extended, and why there is no sensitive-words list |
| ADR-0070 reading is not keeping | 0.8 | checked as a promise |

Still open, and worth revisiting: **ADR-0063, evidence names its source.**
mamori records `source` on every detection — which rule, which pack, which
model — and does not surface it consistently in reports. A user asking "why was
this redacted" should get an answer, and today they mostly do not.
