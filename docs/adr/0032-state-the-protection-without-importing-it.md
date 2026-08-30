# 32. State the protection without importing it

**Status:** accepted, and implemented in 0.27. Two sections below are
amendments the implementation forced — the mixed mode, and the scope.

## Context

Five sibling projects are joined by documents. mamori is joined by a **Python
signature**:

```
tsumugi/infrastructure/adapters/mamori.py   optional import of PrivacySession
akashi/ports/restorer.py                    a Restorer Protocol, waiting
```

Both are careful — optional, behind a port — and both still bind to names in
this package. mamori is also the only one of the six that has shipped, which
makes it the only one that owes anybody API compatibility. Two consumers
coupled to the signature of the one library that has promised not to break is
the wrong way round.

The three fields they need are already agreed, in two places, in the same shape:

```
tsumugi  ContextPackage schema   provenance.protection { by, scope, reversible }
akashi   domain/package.py       Protection( by, scope, reversible )
```

Only the document is missing. `mamori.protection-scope/1` is that document: a
record of **what was protected**, carrying no values, so that a downstream that
only needs to *describe* the protection does not need to import the thing that
performed it.

Restoration still needs mamori. That is not a coupling to remove — it is what
mamori is. What can be removed is the coupling for everything that is not
restoration, which is most of it.

## The question this ADR exists to answer

Not whether to write the document. Whether it may list the placeholder tokens.

`<PERSON_001>` is not a value. But a list of them is a count and a distribution
by type, and "this document contained fourteen people and one national ID" is
information about a document even when none of it is quoted.

## Decision

**A protection record may state anything derivable from the artifact it
describes, and nothing else.**

That is the whole test, and it is worth stating as a test rather than as a list
of permitted fields, because it decides cases nobody has thought of yet.

It also gives two different answers, which is why a flat rule would have been
wrong.

### Placeholders: admissible, because the text already says so

In the default mode the protected text *is* the announcement. Anybody holding
`<PERSON_001>さんへ、<PERSON_002>から...` can recover the complete token list
with one regular expression. The record tells that reader nothing they could
not compute, and the derivability test admits it.

There is also a use for it that is not convenience. A consumer cannot otherwise
tell **a token mamori minted from a token that was in the user's text already**.
`<PERSON_001>` is a string a person can type. Without the list, a consumer that
sees one in a quotation has to guess whether it is a protection or a literal,
and every wrong guess in that direction is quiet: a real quotation reported as
a placeholder, or a placeholder restored that never stood for anything. The
enumeration is what makes that decidable.

### Surrogates: not admissible, and this is the sharp case

[ADR 0026](0026-surrogates-trade-obviousness-for-readability.md) lets a policy
replace `<PERSON_001>` with `山田一郎`. Under that mode the derivability test
gives the opposite answer, because **the text no longer announces anything** —
that is the entire feature.

A record listing the surrogates would tell its reader exactly which names in
the text are invented. Which, by elimination, tells them which are real. And it
marks the precise spans that held a real value, which is the one thing a
surrogate exists to hide. It would be strictly more revealing than the artifact
it describes, and it would defeat a feature rather than document it.

So under surrogates the record carries **`kind` and a count, and no strings**:

```json
"protected": [{"kind": "PERSON", "count": 3}]
```

The conservative option is therefore not a global fallback. It is the correct
answer for one mode and the wrong answer for the other, and a record that does
not say which mode it describes cannot be read safely at all.

### Amended while implementing: the mode is a summary, not a switch

This ADR first said a record carries `placeholders` **or** `protected`, never
both. Writing the emitter showed that to be wrong, because surrogates are
enabled **per entity type** (ADR 0026). A surrogated `PERSON` beside a
tokenised `EMAIL` is not an edge case; it is the ordinary configuration. A
`PERSON` can even land on both sides of one document, when one locale has a
surrogate pool and another does not.

So the two arrays are **both always present**, and disjoint by construction: a
token goes in one, a surrogate is counted in the other, and no surrogate string
appears anywhere. `mode` summarises which of the three shapes resulted.

Making `mode` a switch would have forced a mixed document down to counts for
everything, losing the token enumeration that is the reason akashi wants this —
and it would have made every consumer branch on key presence, which is the
shape of a bug rather than of a contract.

What replaces the old invariant is sharper, and is about the consumer rather
than about the producer:

> **A consumer that understands only `placeholder` must refuse `surrogate` and
> `mixed`** — not read `placeholders` and conclude the document is fully
> enumerated. Reading a partial list as a complete one is exactly the quiet
> failure this contract exists to prevent.

### Amended again: carried, not stated

That paragraph was still a rule somebody has to obey. A sibling session put the
distinction better than the ADR had:

> An operational rule has to be kept once per transfer. A property carried on
> the object is kept zero times.

Written as a rule, "refuse the other modes" has to be remembered by every
consumer, in every version, forever, and the cost of forgetting is silent. So
it is not a rule any more. **A record holding any surrogate declares a
different contract identifier**, `mamori.protection-scope/1+surrogate`, and a
consumer written for tokens refuses it through the check it already performs —
refusing a contract it does not recognise, which is the first thing any reader
of this document does.

Reading surrogate records becomes an explicit opt-in, which is the right shape:
knowing they exist is the whole of what makes them safe to read.

It also moved the invariant into the validator. JSON Schema 2020-12 cannot
compare two properties of one object, but splitting the identifier turned that
comparison into **two discrete cases**, and `if`/`then` states those: the plain
contract requires `protected` to be empty, and the `+surrogate` one requires it
not to be. A record that claims to hold only tokens while carrying surrogates
now fails validation rather than a code review.

### The precedent was already here

`ProtectionResult.masked_types` — *"Types whose values were masked, in
first-seen order. Not the values."* — draws this exact line, for the same
reason, for a caller who has just been told their verification is
unverifiable. This ADR generalises a decision this library already made.

### Never derivable, therefore never included

- **Offsets or lengths in the original.** A length is a value's shape, and for
  a national ID or a telephone number the shape is most of it.
- **Previews.** `EntityReport.preview` is a masked form of the original. Masked
  is not absent.
- **Confidences, sources, rule identifiers.** These describe how a value was
  found, which is a statement about the value.
- **Anything keyed by original text**, including a hash of one. A hash of a
  short value drawn from a known set is not a one-way function; it is a lookup
  table with extra steps.

`policy_hash` is admissible because it is a hash of **configuration**, and must
be computed over the policy alone. A hash mixing in anything from the document
turns the record into an oracle for guessing at content.

### Why the offset rule is absolute *here*, for anybody borrowing the test

The list above is what this test yields **in this domain**. It is not part of
the test, and reading it as though it were would be a mistake worth heading
off, because the test is meant to be borrowed.

`musubi` borrowed it for its trace-map and landed somewhere else: it kept the
spans of *removals* and dropped the spans and lengths of *findings*. That is
not a weaker application of the rule. It is the same rule, and what separates
the two cases is **whether the thing the record points at is still live**. A
removal points at a tracking parameter that is gone; the span is what lets the
owner appeal it. A finding points at a credential still sitting in the owner's
file, and an offset with a length turns the manifest into "a twenty-character
AWS key at byte 44 of `notes/setup.md`" — which the owner does not need, and
which is exactly the targeting an attacker does.

mamori has no such split because **protected text is always live**. The
original still exists somewhere, and so does a mapping that reaches it. The
absence of an exception here is a property of the domain, not a sign that this
ADR is stricter than musubi's.

So: borrow the test, and re-derive the prohibitions. Carrying this list across
unexamined would give a domain with dead records a rule harsher than its own
reasoning supports — and, worse, might let a domain with live ones think the
list is exhaustive when its own derivation would have found more.

## The scope identifier, and the oracle moving one field over

Asked after this was accepted, and the right question: `policy_hash` is
computed over settings alone, but **what is `scope` derived from?**

mamori's own is `session-` and twelve hex characters of a random UUID, with no
input from any document. But a caller may supply one, and
`scope="tanaka-invoice"` puts the value straight back into every place the
record was safe to send — the same defect as hashing a document into
`policy_hash`, moved one field over.

Documenting the obligation is not enough, because the caller who names a scope
after its subject is not reading the documentation that says not to. **mamori
refuses at protect time when a value it detected occurs in the scope.** The
check is where the original values still exist, which is the only place it can
be made; by the time a record is emitted they are gone by design.

Values under three characters are exempt. A one-character collision with an
ordinary identifier is common and means nothing, and a check that fires on
noise teaches callers to route around it.

## The record is not safe to log

The derivability test protects a reader **who holds the protected text**. A
provenance record does not always travel with the body: it goes into manifests,
audit logs, message headers, and all the places metadata goes precisely because
it is believed to be harmless.

To a reader who does not hold the document, `{"kind": "NATIONAL_ID", "count":
1}` is not a description of something they already have. It is a pointer to
which file is worth taking.

**A protection record inherits the classification of the text it describes.**
This has to be said out loud, because "it contains no values" is exactly the
sentence that gets a thing written to a log at a lower classification than the
document it came from.

## The direction of `reversible`

tsumugi and akashi defaulted this field opposite ways and settled today on
**False**: a wrong `true` fails silently, and an honest quotation gets reported
as a fabrication. The record follows that, in the form that matters for a
document rather than for a constructor:

> **A consumer that does not find `reversible` must read it as `false`.**

mamori itself never omits it — the value is computed, not defaulted, and it is
false when anything was masked, because a mask has no mapping behind it. The
rule is for readers of records mamori did not write.

## What the schema cannot check, and where it must be written instead

JSON Schema 2020-12 cannot compare two properties of the same object, so these
are invariants for the consumer's documentation, not for the validator:

1. **Every token in `placeholders` occurs in the protected text.** A record
   naming a token the body does not contain is describing a different document.
2. **A record describes exactly one `scope`.** Placeholder numbering is unique
   only within one, so two scopes merged into a single record make
   `<PERSON_001>` ambiguous — and ambiguous in the direction that restores the
   wrong person's name.
~~3. `mode` is `surrogate` or `mixed` if and only if `protected` is
   non-empty.~~ **No longer here.** Splitting the contract identifier moved
   this into the schema, where `if`/`then` enforces it. It is listed struck
   through rather than deleted because the useful thing about it is that it
   left: an invariant a consumer had to be trusted with became one the
   validator checks, and the move was available the whole time.

## Validate against emitted bytes

A frozen contract in a sibling project was found never to have been checked
against its own real output: the reference implementation validated documents
built from value objects, and the first run against actual emitted bytes found
a genuine bug.

The conformance test for this schema validates **what mamori writes**, from a
real `ProtectionResult`, in both modes.

## Consequences

`tsumugi` and `akashi` can describe a protection with no dependency on this
package, and `iriguchi` gets the record its README already promises when it
escalates a prompt. The `Restorer` Protocol stays exactly as it is: **stating
what happened becomes a document; doing the thing stays an interface.**

The cost is a second frozen surface. It is smaller than the Python API, and
unlike the Python API it is frozen on purpose.
