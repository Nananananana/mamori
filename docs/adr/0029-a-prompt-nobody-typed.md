# 29. A prompt nobody typed

**Status:** accepted

## Context

Every dataset in this repository until 0.17 was prose somebody wrote: an email,
a ticket, a set of minutes. The rules were built against that and measured
against that, and the measurements were honest about length
([ADR 0025](0025-measure-at-the-length-people-send.md)) while assuming the
shape.

That assumption is going stale. A growing share of what reaches a model is
*assembled*: a retrieval layer selects passages out of local files, an agent
framework interpolates a template, a tool call carries arguments. The sibling
project [tsumugi](https://github.com/Nananananana/tsumugi) is a concrete
producer — it renders a **ContextPackage**, a structured prompt with named
sections, a header per passage, and an account of what was left out — and its
[ADR 0009](https://github.com/Nananananana/tsumugi/blob/main/docs/adr/0009-restore-before-you-verify.md)
specifies the seam from the other side.

Three hundred rendered packages, generated with tsumugi's own domain classes
rather than an imitation of its output, said what the assumption had been
hiding. **The leak rate on assembled prompts was 15–22%**, against 0.35–2.7% on
prose from the same generator.

## Decision

**Assembled prompts are a measured shape, with their own bundled datasets**
(`en-context`, `ja-context`, `zh-context`) and their own quality floors. Three
kinds of thing share one document and they are scored differently:

- **Passages** are prose and are scored as prose.
- **Headers carry a file path**, and a path names a person: `/home/p.doe/`,
  `C:\Users\sato.hanako\`. A new universal rule takes the segment after a home
  root and nothing else — the rest of the path is provenance somebody may be
  checking. System accounts (`runner`, `Public`, `www-data`) are refused from a
  closed list, the same argument that justifies the weekday list in Chinese.
- **Structure is a negative set.** Item ids, content hashes, character offsets,
  budget numbers. Every one of them is labelled as ordinary text, so anything
  replaced there is a bug with a number attached rather than a matter of taste.
  This is the part that has no analogue in prose: over-redacting a word costs
  answer quality, and over-redacting a hash produces a package whose id no
  longer verifies — indistinguishable, downstream, from one that was tampered
  with.

**A quotation must restore exactly.** A consumer that verifies citations does
it by matching text, so the property is not "restoration mostly works" but *the
restored quotation equals the original, character for character*. One character
of drift is a false accusation of fabrication, and an evidence system that
reports honest citations as fabricated is worse than one with no verification
at all. Three hundred generated answers check it; all three hundred hold,
including the 168 whose quoted span contains placeholders.

**Reversibility is data.** `ProtectionResult.reversible` and `masked_types` say
whether what was done can be undone. The caller cannot see this from the text —
`<PERSON_001>` and `[REDACTED]` look equally replaced — and downstream it is
the difference between *unsupported* and *unverifiable*, which is the
difference between accusing a model of inventing something and admitting you
cannot tell.

**No dependency, in either direction.** mamori does not import tsumugi and
never will; the corpus generator in the development repository does, because a
corpus that imitates the thing it is testing against measures the imitation.
The shapes are what the library knows about.

## Consequences

Four bugs came out of the first run and three of them were not about assembled
prompts at all — they were general and had been there for releases:

| | |
|---|---|
| A home directory names its owner | the largest leak, in all three languages |
| A digit run inside `5b469054284c` was read as an identifier and an SSN | any hash, any commit, any UUID |
| `(?=[^A-Z]*[A-Z])` in the secret rule | scans past the token, so any capital later in the document satisfied it; every long path qualified as a credential |
| `プロジェクト鶴の残作業は?` was a codename called `鶴の残作業は?` | and the same project in two sentences got two different placeholders |

The last one is the one that matters most for this composition and would never
have shown up as a leak: it is over-redaction that *also* breaks identity, so a
quotation restores to a different string than the passage it came from.

The `-context` sets leak more at the balanced stance than the document sets do
— 47% against 20% in English — and the reason is worth stating rather than
filing. **Selection strips anchors.** A passage chosen out of a note arrives
without the salutation, the signature block and the form label that made its
values detectable; the anchor stayed behind in the part that was not selected.
Assembled prompts need the recall-first default more than prose does.

The cost is a third scale to keep measured, and the datasets to keep honest.
That is the same cost [ADR 0025](0025-measure-at-the-length-people-send.md)
accepted for documents, and it bought the same thing: numbers that describe
what people actually send.
