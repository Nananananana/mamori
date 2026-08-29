# 0003. What mamori is for

**Status:** current plan, from 0.16. Supersedes
[proposal 0002](0002-the-road-to-1-0-revised.md), which stands as the record of
what was planned after 0.13 and what came of it.

Proposal 0002 was a list of features with version numbers beside them. Four
releases later, three of those numbers are wrong and two of the features were
not the thing that needed building. That is not a failure of planning so much
as evidence about what planning is worth here, and this document is written
differently because of it: what the library is **for**, what is measured, and
what the next few releases do — with the honest note that the middle of that
list has moved every time.

## What actually happened against proposal 0002

| planned | delivered | |
|---|---|---|
| 0.14 — conversations | 0.14 — a generated corpus | the corpus found five bugs in an hour; conversations waited |
| 0.15 — deployment | 0.15 — Chinese | the corpus found a gap present since the first release, worth more than any feature |
| 0.14 — per-session salt | **not built, and will not be** | [ADR 0028](../adr/0028-the-server-names-the-conversation.md) |
| 0.14 — the `mamori[ja]` morphological adapter | not built | still the right experiment; still not run |
| 0.16 — conversations | 0.16 — conversations | with a token the server mints, not a salt |
| 0.17 — the assembled prompt | 0.17 — the assembled prompt | the first version number this document got right |
| 0.18 — deployment | 0.18 — the agent-shaped payload | an audit found a leak; deployment moved to 0.19 |

Two of those are worth stating plainly rather than filing.

**The salt was adopted for a problem that was already solved.** Its purpose was
to make a placeholder stable inside one conversation and unrelated across
conversations. Allocation order gives both, because the index comes from the
order values are met rather than from the values. What the release actually
needed was an identifier that nobody outside the process can guess, which is a
token. A feature can be well-argued, correctly specified, adopted with reasons
— and redundant, and only building the thing next to it shows that.

**Twice now, generating data has been worth more than building a feature.** The
0.14 corpus found five bugs the same day; the 0.15 Chinese work came out of the
same corpus and closed the largest measured gap in the project. Both releases
began as "write the next feature" and became "measure the thing we have". That
is the third instance of the lesson from proposal 0002 — *a component can be
correct in every line and contribute nothing* — arriving from the opposite
direction: the cheapest way to find out is to count.

## What this is for

A privacy layer is not a redaction function. It is the part of somebody's
system that lets a document reach a model they do not control **without the
parts that identify a person**, and lets the answer come back in their own
words. Everything in this repository is downstream of that sentence:

- **The measurement is the product.** Anybody can write regular expressions. A
  leak rate, an over-redaction rate and the datasets behind them, published and
  reproducible on your own data (`docs/measuring-your-own-data.md`), are the
  part nobody else ships. Every release since 0.9 has moved a number, and the
  ones that moved it the wrong way are in the changelog too.
- **Recall first, and say so.** Over-redaction is a cost paid in answer
  quality. A leak is paid in somebody's name. The default errs one way, the
  stance switch makes the other available, and both are measured.
- **Nothing is kept that does not have to be.** Mappings live in memory
  ([ADR 0006](../adr/0006-mappings-live-in-memory.md)); conversations expire
  ([ADR 0028](../adr/0028-the-server-names-the-conversation.md)); the proxy
  logs counts and never values.
- **Zero runtime dependencies.** Not minimalism for its own sake: a privacy
  tool nobody will audit is a privacy tool nobody should trust, and every
  dependency is a page of somebody else's code between a reader and the claim.

## The leap: mamori is a seam, not an application

The releases so far assumed the text arrives as prose somebody typed. That is
increasingly not where sensitive text comes from. It is assembled — by a
retrieval layer, an agent framework, a tool call, a template — and the assembled
thing is what reaches the model.

The sibling project [tsumugi](https://github.com/Nananananana/tsumugi) is a
concrete instance and the reason this section exists. tsumugi selects passages
from somebody's local notes and renders a **ContextPackage**: a structured
prompt with named sections, item headers carrying file paths and offsets,
omission counts, and a budget. Then it verifies the model's citations against
what it sent. Between the render and the send is exactly where mamori goes, and
tsumugi's [ADR 0009](https://github.com/Nananananana/tsumugi/blob/main/docs/adr/0009-restore-before-you-verify.md)
already specifies the seam from the other side: restore before you verify, or
every citation that touches a redacted value is reported as a fabrication.

That composition asks three things of this library that prose never did.

1. **Protect a structured prompt without breaking the structure.** Item
   headers, hashes, document ids, offsets and section names are not prose and
   must survive untouched. An id read as an identifier is over-redaction that
   breaks a checksum rather than a sentence.
2. **Say whether the protection is reversible.** A masked or blocked value can
   never be restored, so a claim resting on it is *unverifiable* rather than
   unsupported. The consumer needs that as data, not as a docstring.
3. **Restore exactly what was sent.** Not approximately: a citation is checked
   by matching text, so one character of drift is a false accusation of
   fabrication.

None of that requires either project to depend on the other, and neither will.
What it requires is that mamori is measured **on assembled prompts** the way it
is measured on prose — which is a corpus, and this project already knows how to
build one.

## The plan

### 0.16 — Conversations *(delivered)*

Sessions that outlive one request, named by a token the server mints. The
argument that made one-scope-per-request sufficient is now a test rather than a
paragraph, and it holds — for the clients it was about.

### 0.17 — The assembled prompt *(delivered)*

All of it, and the third item was the release again: three hundred generated
packages found four bugs, and **three of them had nothing to do with assembled
prompts**. A home directory naming its owner, a digit run inside a hash read as
an identifier, a lookahead that scanned past its own token, and a Japanese
codename that swallowed the sentence after it. Prose had never shown any of
them; they were not new.

That is now the third release in a row where generating data beat building a
feature, and the pattern is specific enough to state as a rule: **a corpus in a
shape the rules were not written against finds bugs that are not about the
shape.** The shape is what gets you to look.

`ProtectionResult.reversible` and `masked_types` shipped with it, and a bundled
`-context` dataset per language so the finding does not depend on the
development repository being present. The other half of the seam is checked
too: three hundred model answers quoting the passages they were given, restored
through the same session, **300 of 300 character for character**.

### 0.18 — The agent-shaped payload *(delivered, and not what was planned)*

Deployment was next on this list. An audit of what the proxy actually walks
came first, because it found a leak: **a tool call's arguments had never been
protected**, in either direction. In an agent loop that is where the personal
data is. A generated corpus of four hundred agent turns took requests carrying
nothing known from 106 to 397 out of 400, and turned up the second finding on
the way -- one kana character was standing the Chinese rules down for a whole
document.

The rule this project keeps rediscovering, now stated as policy: **a leak found
by audit outranks a feature on the plan.** Both of these had been present for
releases and neither was in any roadmap, because a roadmap is written from what
you already know to look at.

### 0.19 — Deployment

Carried from proposal 0002, twice postponed, unchanged and still wanted:

- The fail-closed stance: a detection below the confidence threshold escalates
  to `BLOCK` rather than being dropped, for a deployment that would rather stop
  than miss.
- The CI linter: scan files — prompt templates, fixtures, notebooks — for
  values that should not be committed.
- `<PERSON_001>` inside an HTML document reads as an unknown tag.
- A name split across two JSON keys.

### Not scheduled, and honestly so

- **The `mamori[ja]` morphological adapter.** Proposed for 0.13, moved to 0.14,
  not built in either. It is still the right experiment — an optional adapter
  behind the existing port, published against `ja-docs`, dropped if it does not
  win — and giving it a version number a third time would be a way of not
  admitting that it keeps losing to whatever the corpus turned up that week.
- **The encrypted store**, with retention as a stated rule rather than a
  background process. Wanted; blocked on nobody needing it yet.
- **Whether a model above 8B changes the model tier.** Unanswered since 0.7.
  The hardware here times out, and a measurement that cannot be run is not a
  plan.

### 1.0 — The contract

Unchanged from proposal 0001 and worth repeating. Not a feature: the public API
is stable, `test_promises.py` is the specification of what this library will not
do, and the figures in `SECURITY.md` have data behind them worth the word
"measured".

## Still deliberately not planned

Restated because a refusal nobody wrote down gets added later by somebody
meaning well: a sensitive-words list, async machinery, a web framework in the
core, a configuration format ([ADR 0012](../adr/0012-configuration-without-a-format.md)),
and a dependency on any sibling project.
