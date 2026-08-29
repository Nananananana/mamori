# 9. Measure leaked characters, not just entity F1

**Status:** accepted

## Context

Detector rules are precision/recall trade-offs, and a trade-off nobody measures
drifts. Until this landed, nobody — the maintainers included — could state a
recall figure for any language, so every change to a rule was an argument
between opinions.

The obvious answer is entity-level precision, recall and F1, as any NER
benchmark reports them. Those numbers are useful and they are also, on their
own, misleading here.

A detector that finds `田中` inside `田中太郎` scores as a hit under overlap
matching and as a miss under exact matching. Neither says the thing that
matters: **two characters of somebody's name were sent to a third party.** A
detector with the right span and the wrong type scores as a miss twice over —
once as a false negative, once as a false positive — while having removed the
value completely. Nothing leaked. F1 says otherwise.

## Decision

Report both families, and lead with the character-level pair.

```text
leak_rate           = labelled sensitive characters no detection covered
                      -------------------------------------------------
                      all labelled sensitive characters

over_redaction_rate = unlabelled characters that were replaced anyway
                      -----------------------------------------------
                      all unlabelled characters
```

`leak_rate` is what the library is for. `over_redaction_rate` is what it costs,
and it is not optional: a layer that mangles ordinary text stops being used, and
an unused privacy layer has a leak rate of 1.0. Neither number means anything
alone.

Entity precision, recall and F1 are still reported, per type, because they are
how you find a rule that is missing rather than merely imprecise. Match mode is
selectable: `overlap` by default, `exact` to see boundary drift.

Datasets are authored with inline markup — `[[PERSON:田中太郎]]さんへ` — and
the loader computes the offsets. Hand-written offsets are wrong often enough
that a corpus annotated that way measures the annotator.

Labels record **what a competent human redactor would remove**, not what the
current rules find. Several samples are labelled knowing they will leak; each
carries a note saying why, and a test enforces that.

## Consequences

Quality floors live in `tests/test_detection_quality.py` and run in CI, so a
rule change that improves one language and quietly wrecks another turns the
build red. The floors are a ratchet: raise them when a real improvement lands,
never lower one to make a change pass.

Writing the first datasets found five real bugs within an hour — the Japanese
address rule stopping at the first hyphen, the surname rule swallowing the
honorific, URLs eating the Japanese text after them, a date capturing a trailing
space, and a company name running into the following clause. Every one produced
wrong output on plausible input and none had been caught by example-based tests.

`evaluate()` is public, so anyone can score their own detectors on their own
data.

## What it costs

Character-level metrics need character-level labels, which means the annotation
has to be exact about boundaries even though overlap matching forgives them. It
is more work per sample than a bag-of-entities corpus.

The bundled sets are small — 45 samples each for Japanese and English, 22 for
Chinese — and synthetic. They catch regressions well and estimate real-world
recall poorly. A number from them is a floor to defend, not a claim to publish.

They also ship inside the wheel, so anything real committed to them is published
to everyone who installs the library. A test refuses vendor-prefixed credentials
in the data; the rest is discipline.
