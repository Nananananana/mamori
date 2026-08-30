# 32. State the protection without importing it

**Status:** accepted. The document is decided here; the implementation follows.

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
3. **`mode` decides which of `placeholders` and `protected` is present.** Never
   both.

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
