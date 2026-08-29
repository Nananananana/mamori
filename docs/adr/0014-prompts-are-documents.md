# 14. Prompts are documents with addressable parts

**Status:** accepted

## Context

Two models are involved in the finished system, facing opposite directions. A
local one is asked to *find* what patterns cannot reach. The service model is
told to leave the placeholders alone.

Both need a prompt, and a prompt written as one long f-string cannot be changed.
An organisation always knows things the library cannot: their internal codenames
look like ordinary words, their case numbers have a local format, a product name
in their documents keeps coming back as a person. Editing the prompt to say so
makes the change invisible, collides with every upgrade, and leaves nobody able
to say six months later what was altered or why.

There is also knowledge worth not throwing away. Everything learned writing the
regular expressions -- that an honorific fixes the right edge of a Japanese
name, that `森林` is a forest and not two people, that an English name in prose
has no anchor at all -- is knowledge about *languages*, not about regular
expressions. Starting the model tier from a blank prompt would discard it.

## Decision

**Guidance is a shared, addressable knowledge base.** Each piece has an id
(`ja.person.honorific`), a kind (find / ignore / boundary / output), the
languages it applies to, and examples. The pattern rules implement what they can
express; the prompt carries the rest to a model that can.

**A prompt is a small ordered document**: named sections plus selected guidance,
rendered deterministically. The same definition and overlay produce the same
characters every time, and a fingerprint on the result proves it.

**Local changes are an overlay, not an edit.** `add`, `disable`, `sections`,
applied on the way out and loaded from a mapping like the rest of the
configuration:

```json
{"prompts": {"detection": {
  "disable": ["en.person.unanchored"],
  "add": [{"id": "acme.case", "text": "Case numbers look like ACME-12345."}]
}}}
```

A disable that matches nothing is refused. A team that misspells a rule id
believes they turned something off and did not, which is the same failure mode
as an ignored configuration key.

**Two prompts ship.** `detection` for a local model; `external` for the service
model. The second needs no local model at all, and it pays for itself
immediately: every placeholder that comes back intact is one restoration does
not have to recover from a mangled form. `session.external_system_prompt()`
hands it over.

## Consequences

`mamori prompt` prints exactly what would be sent, with its version and
fingerprint. `mamori prompt --guidance` lists the ids so they can be disabled,
marking which came from an overlay.

Narrowing to one locale drops the prompt from 6.7k to 4.6k characters, which
matters on a small local model with a short context.

The regex knowledge is now written down twice -- once as patterns, once as
guidance -- and the second copy is readable by people who will never open
`patterns.py`.

## What it costs

Two copies of the same knowledge can drift, and nothing enforces that a change
to a rule reaches its guidance. A shared registry generating both was
considered and rejected: what a regex can express and what a model should be
told are genuinely different, and forcing one shape on both would make each
worse.

Rendering means a prompt cannot be read as a single file. `mamori prompt`
exists because of that, not despite it.

Prompt *content* is Python rather than versioned markdown files, which the
original design charter sketched. Typed, testable rules with ids beat parsing
prose, and the overlay gives the edit-without-code path the file layout was
reaching for.
