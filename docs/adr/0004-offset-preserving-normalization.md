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
