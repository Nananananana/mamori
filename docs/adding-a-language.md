# Adding a language

Three language packs exist and each one taught something the previous one had
not. This is what they taught, as a list you can work through — so the fourth
pack is as good as the third rather than as good as the first was.

Before any of it: **is a pack the right answer?** A rule an organisation writes
lives in [its configuration](../README.md#your-own-rules-in-the-configuration-file)
and needs none of this. A pack is for a *language*: the honorifics, the name
shapes, the national identifiers, the script detection that decides when any of
it runs.

---

## 1. Get a corpus before you write a rule

Not after. Every pack here was written rules-first and every one of them was
wrong in a way its author could not see:

- `v0.13` went after Japanese and Chinese and **learned more from the two fixes
  that failed than the two that worked**.
- `v0.14` generated a thousand documents and they found five bugs in an hour.
- `v0.15` spent that corpus on Chinese, where a name followed by an ordinary
  word had been invisible **since the first release**.

Sixty labelled samples at sentence scale and eight at document scale is the
shape the bundled sets use, and the second number is the one that matters:
`en-core` leaks 0.62% and `en-docs` leaks 2.65% with the same rules, because a
heading, a signature block and an attendee list are not sentences.

Label with `[[TYPE:value]]` markup — see `src/mamori/evaluation/data/` — and
put the corpus somewhere it can be published, or state that it cannot be.

## 2. Write the pack

`src/mamori/infrastructure/detectors/locales/<code>.py`, following `ja.py`.
The pieces:

- `triggers` — which scripts make this pack run at all. A pack that runs on
  every document costs every document.
- `suppressed_by` — scripts whose presence means another pack owns this text.
  Japanese kana suppress the Chinese pack, because a document with kana in it
  is Japanese even where a sentence is all han characters.
- `rules` — `compile_rule(...)` per pattern, with a `tier`.
- Register it with `register_locale`.

## 3. Every rule is bounded

**This is not style.** `v0.33` removed two quadratics from the universal rules;
a 128KB answer with one base64 blob took 456 seconds to restore. Unbounded
repetition (`+`, `*`) over a character class the input is made of is how both
of them happened.

- Prefer `{1,64}` to `+`. Pick the bound from a standard where one exists — RFC
  5321 says an email local part is 64 characters, RFC 1035 says a DNS label is
  63.
- Add a left boundary — `(?<![A-Za-z0-9])` — so a scan cannot restart inside a
  run it has already rejected.
- `tests/test_scaling.py` runs every shipped rule against sixteen adversarial
  shapes at two sizes. A new pack is covered by it automatically. Run it.

## 4. Decide the tier, and say why in a comment

`CORE` runs under both stances and must be right about what it claims. `WIDE`
runs only under `recall_first` and is allowed to be wrong: it is where *"ten
bare digits"* and *"two capitalised words"* live. Putting a shape-only rule in
`CORE` is how a stance stops meaning anything.

## 5. Write the negative tests first

Every pack has a stoplist and every stoplist was written after something
embarrassing. English rejects *"Social Security Number"* and *"The Quarterly
Business Review"* as names because both were detected as one. Before you claim
a rule works, write the sentences it must **not** fire on:

- a heading in title case
- a product or feature name
- a standards citation (`RFC-5321`, `ISO-8601`)
- a file path and a URL
- a content hash and a commit id
- a date, a version number, a currency amount

## 6. Add floors, not a score

`tests/test_detection_quality.py` holds a `Floor` per dataset per stance. Add
yours with the numbers you actually measured, and **tighten the leak ceiling
when you improve it** — a floor that only ever loosens is a floor that stops
saying anything.

Then add the row to the table in `SECURITY.md`.
`tests/test_security_figures.py` fails the build when a published figure stops
being what `mamori eval` prints, so the two cannot drift.

## 7. Check what the pack costs the other packs

A document is rarely one language. Run the existing datasets with the new pack
registered and compare: a pack that improves its own language and adds
over-redaction to another has not paid for itself yet. `tests/test_locales.py`
is where cross-language behaviour is pinned.

## 8. State what it cannot do

`SECURITY.md` names the gaps per language, and
`docs/adr/0008-language-packs.md` is honest that regular expressions cannot
finish the job. A pack that arrives claiming to be complete is a pack whose
author has not looked hard enough — the Chinese pack's own ADR says the design
for making it good is written down and not done.

---

## The shortest honest version

1. Corpus first, at document scale.
2. Bounded patterns, boundary-anchored.
3. Negative tests before positive ones.
4. Floors measured, ceilings tightened.
5. Say what it misses.
