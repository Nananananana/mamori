# 4. Normalize with an offset map instead of normalizing the text

**Status:** accepted

## Context

Japanese text mixes full-width and half-width forms freely.
`ｔａｎａｋａ＠ｅｘａｍｐｌｅ．ｃｏｍ` and `tanaka@example.com` are the same
address, and a rule written for one must match the other. The obvious fix is to
NFKC-normalize before detecting.

But NFKC changes length. `㍿` becomes `株式会社`, one character into four. `Ĳ`
becomes `IJ`. If detection runs on the normalized string and replacement runs on
the normalized string, the user gets back text they did not write — ligatures
expanded, full-width characters silently converted.

Replacement therefore has to happen in the original string, using spans found
in the normalized one.

## Decision

`NormalizedText` normalizes per character and records, for every character of
the normalized string, the range of the original it came from. A span in
normalized coordinates maps back exactly.

Detectors receive normalized text and report spans in its coordinates. The
application maps each span back and takes the value **from the original**, so
what is stored in the mapping is the substring that was actually removed.

## Consequences

Rules can be written in ASCII and match the full-width form for free.

Untouched text survives character for character.

The round trip holds for inputs where normalization changes length — which is
how the bug was found. A Hypothesis case generated `0@a.example.comĲ`, where the
email rule matched `comIJ` in normalized coordinates; storing the normalized
value would have restored `IJ` in place of `Ĳ`.

## What it costs

Normalization is per character, so combining sequences that NFKC would merge
across characters (`カ` + `゛` → `ガ`) are not merged. Merging them would make a
character-level offset map ambiguous. Detectors must not rely on that merging,
and `NormalizedText` says so.

Two extra integer tuples per protected text. Irrelevant at prompt sizes.

## Found later: folding decides identity, and identity decides restoration

A property test turned up `Y0@a.example.com:Ｙ0@a.example.com` — one address
written twice, once with a full-width `Ｙ`. NFKC folds them together, so they
share an identity key, so they share a **placeholder**, so restoration puts the
first spelling at both sites and `restore(protect(x)) == x` is false.

Every step of that is this ADR working. Folding is what makes the two spellings
one address, and one address is what should get one token — a model shown two
different tokens for one mailbox has lost exactly what the placeholder was for.

What has to be given up instead is the exact spelling at each site, and it
cannot be recovered later: restoration reads a model's **answer**, where a
token may appear anywhere, more than once, or not at all. There is no site to
match it to. A mapping therefore holds one surface per value, and the honest
statement of the round trip is that it returns the value's spelling rather than
each site's.

The same shape reaches further than mailboxes. `㍿ABC` and `株式会社ABC` are one
company, and a document using both comes back using whichever came first.
