# 30. A tool call is text, and evidence is local

**Status:** accepted

## Context

Two findings, from one audit and one corpus, and they are in the same ADR
because they are the same mistake made twice: a rule that was written for prose
and applied to everything.

### The proxy protected the prose and forwarded the rest

`messages.py` said, in a comment that had been there since 0.6:

> Anything else — an image, an audio clip, a tool call — is passed through
> untouched, because this library reads text and has nothing to say about the
> rest.

True of the *call*. False of its `arguments`, which is a JSON string a caller
wrote and which in an agent loop is where the personal data actually is:

```json
{"to": "jane.doe@example.com", "body": "Dear Jane Doe, call 415-555-0198."}
```

Four values, four leaks, one request. And symmetrically on the way back: a
model that answers with a tool call rather than a sentence had its arguments
left unrestored, so the application was handed `{"to": "<EMAIL_001>"}` and sent
mail to nobody.

The same audit found three more places a caller's words sit and nothing looked:
`messages[].name`, `tools[].function.description` (which conventionally carries
an example, and an example is a real address in a real deployment), and `user`
— an "opaque identifier" that people fill with an email address.

### One kana character spoke for a whole document

The locale selector had a decisive and correct rule: kana appear in Japanese
and never in Chinese, so text containing kana is Japanese and the Chinese pack
stands down. That is right for a paragraph. It was applied to the whole text,
so a payload like

```json
{"subject": "契約更新のご連絡", "body": "关于朱强的事，我会和新程工业集团确认后回复。"}
```

had the Chinese body sent in the clear — and so would any bilingual thread,
ticket, or context package assembled from notes in two languages. The evidence
was local and the conclusion was global.

## Decision

**Every string a caller could have written into is protected, and the walk
carries a path.** Slots used to be yielded as strings and put back
positionally, which works exactly as long as both functions are edited
together — so adding a place to look was a chance to leak the place you added.
A slot now knows where it came from and replacement follows the same path.

**A tool call's arguments are text, both ways.** Protected on the way out,
restored on the way back, including in a stream — where each call's arguments
are their own run and get their own restorer, because feeding two interleaved
runs through one would splice one's held suffix onto the other's next chunk.

**Protection that breaks JSON fails closed.** No rule here matches across a
structural boundary, so it should never happen; it is checked anyway, at the
one place where the failure would otherwise surface as a parse error in
somebody else's process, hours later.

**A key is a label.** `{"employee_id": "B-12778"}` says what the value is as
plainly as `社員番号: B-12778` does. Seven key families are read — employee id,
postal code, phone, address, person, company, date of birth — case- and
separator-insensitively, in English, Japanese and Chinese spellings, because an
API is written in English keys whatever language its values are in. A bare
`name` is deliberately **not** one of them: in JSON it is a tool name, a model
name or a field name far more often than a person, and redacting the name of
the function an agent is calling breaks the call.

**Evidence about a script reaches to the end of its sentence and no further.**
A pack that a script would suppress now runs anyway, and its detections are
kept outside the sentences where that script actually appears. Rules still see
the whole text, so nothing loses the context it needs — only the answers are
filtered. A comma is not a boundary: `本日、会議資料を送付します` is one
sentence and the kana at the end of it are evidence about the kanji at the
start.

## Consequences

The proxy protects four places it did not, and restores one it did not. The
numbers, on four hundred generated agent turns: **106 of 400 requests carried
nothing known before this release; 397 of 400 do now.** The three that remain
are one name, `上官若谷`, and it is the known cost of the Chinese function-word
stoplist rather than anything about payloads.

Local evidence costs Japanese over-redaction: 0.72% to 0.92% on a thousand
generated documents, with the leak rate unchanged and the bundled Japanese sets
unmoved. A Han-only sentence inside a Japanese document is now ambiguous and
gets Chinese rules too, which is exactly what the module already said it did
for Han-only *text* — the change is that "text" now means "sentence".

Two things are stated rather than solved:

- **A schema's `enum` is left alone.** It is the contract the model is being
  asked to satisfy, and replacing a value changes what it is allowed to emit
  rather than what it is allowed to see. If your enum lists real people, the
  tool definition is the wrong place for it.
- **`user` is replaced.** The field is opaque to the upstream by definition, so
  nothing they can act on is lost — but their abuse tracking sees a different
  id per session, and that is a consequence worth knowing before it is
  discovered.
