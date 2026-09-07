# Brief for a corpus somebody else wrote

Every number in this project comes from text its own author wrote. Twelve
bundled datasets, three adversarial sets, six generated corpora — one hand, all
of them. [open-questions.md](open-questions.md#nothing-here-was-written-by-anybody-else)
says why that is a problem rather than a caveat, and
[README](../README.md#who-wrote-the-documents-these-numbers-come-from) says it
before it says anything else.

This is the document you would hand to somebody outside the project. It is
here, in the repository, rather than in a drawer, because the standard it sets
is part of what the published figures claim.

Nothing has been commissioned yet. Scope below is the recommendation, not a
record.

---

## What independence means here

**The values must be invented, and must not be real.** What has to be
independent is the hand, not the data. An outside writer using invented values
in real formats satisfies every constraint at once: redistributable under a
licence they can grant, free of anybody's actual details, and written by
somebody who has not read these rules. The bundled corpora already meet the
first two — all 34 addresses use RFC 2606 reserved domains, the telephone
numbers use ranges kept aside for fiction. What is missing is only the third.

**The labels come from the same hand as the text.** A document somebody else
wrote and we annotated leaves the classification ours, and the classification is
the half that decides what counts as a value. `Provenance` records the two
separately for exactly this reason. A writer who hands over text and lets us
label it has fixed nothing.

**The writer must not read the rules first.** Not `SECURITY.md`, not the
language packs, not this repository's corpora. A corpus written against a rule
list measures the rule list. The brief below is deliberately written so it can
be followed without seeing any of them.

---

## Recommended scope

### Volume

| | Documents | Why |
|---|---|---|
| Japanese | 150 | The primary language, and the one whose name rules are dictionary-anchored |
| English | 150 | The second-largest bundled set, and where the unanchored-name gap lives |
| Chinese | 100 | The smallest shipped locale; enough to move a rate, not enough to claim parity |
| **Total** | **400** | |

Documents are the unit that gets commissioned; **entity instances** are the unit
that decides whether a rate means anything. At roughly five values per document
this is about 2,000 labelled instances, or 500–750 per language — enough that a
leak rate near 2% has an interval narrower than the differences being argued
about, and small enough to be one commission rather than a programme.

### Shapes, not just prose

Split roughly evenly across six shapes. A corpus of clean paragraphs measures a
detector against the easiest input it will ever see.

- a support ticket or its reply
- an email thread, quoted history included
- a meeting note, with the ragged punctuation meeting notes have
- a form or a table — values in cells, with a header rather than a sentence
  around them
- a chat log, several short turns
- a configuration file, a log excerpt, or a code comment

### Length

Most documents short — under 1,000 characters. **At least 15 per language over
4,000 characters**, because a recogniser with a fixed input window answers
*"nothing here"* for the far end of a long document in exactly the same shape as
it answers for a clean one, and only a long document can tell those apart.

### Coverage floor

Each of these should appear at least **20 times per language**, or be reported
as absent so the gap is on the record rather than in the noise:

    ADDRESS   COMPANY_NAME   CREDIT_CARD   DATE_OF_BIRTH   EMAIL
    EMPLOYEE_ID   IDENTIFIER   INTERNAL_IP   INTERNAL_URL   PERSON
    PHONE   POSTAL_CODE   PROJECT_NAME

and these, which are the ones a policy blocks outright rather than replaces, at
least **10 times per language**:

    ACCESS_TOKEN   API_KEY   DATABASE_URL   PASSWORD   PRIVATE_KEY

Locale-specific identifiers — `MY_NUMBER` and `RESIDENT_ID` in Japanese, `SSN`
in English — at least 20 times in their own language and **not** translated into
the others.

### The half that is easy to forget

**Text that looks like a value and is not.** This is what measures
over-redaction, and a brief that asks only for values gets a corpus that can
only report one of the two numbers this project publishes.

Ask for it explicitly, at roughly one in four documents:

- a long run of digits that is an order number, a build id, a page count
- a hexadecimal or base64 run that is a commit id, a checksum, an encoded image
- a capitalised pair of words that is a product, a place, a team, a station
- a department where a person's name would sit — "Reported by: Facilities"
- a company-shaped name that is a public brand rather than a customer

The writer should label these too, as *not* a value. A span nobody labelled and
a span labelled "not sensitive" are different facts, and only the second one can
fail a test.

### Two halves, one published

**Commission twice the volume and publish half.**

Commissioned text is unpublished, so a model cannot have memorised it — until it
is committed here under Apache-2.0, at which point it becomes training data for
whatever comes next. Rule-tier figures are unaffected, being deterministic.
**Model-tier figures decay from the day of publication**, and the only defence
is a half that never ships: kept off the internet, used to check that the
published half is still saying the same thing.

The published half is what makes the numbers reproducible by a reader. The
held-out half is what keeps them true a year later. Neither alone does both.

**Record the publication date** of the half that ships. It is the floor under
any model-tier claim the corpus supports.

---

## What the labels must carry

Per span: character offsets into the document as delivered, the type from the
lists above, and whether the writer considers it identifying **on its own** or
only in combination with something else in the same document. The third field
is the one this project cannot supply for itself — re-identification from what
remains is listed as *not mitigated*, and an outside judgement about which
combinations do it is worth more than the spans.

Offsets into the document as delivered, in UTF-8, with the encoding and line
endings stated. An offset scheme this project has to guess at is a labelling we
did after all.

---

## What we are not asking for

- **Real data.** Not anybody's actual details, not scraped text, not a redacted
  extract of something that happened. If a document could embarrass a real
  person it is the wrong document, whatever it would prove.
- **Adversarial writing.** Three of the five findings from the 900-document
  adversarial corpus were resolved by deciding what its generator should have
  been able to write. A corpus that refutes only its author's imagination looks
  exactly like this one from the inside. Ordinary documents, written ordinarily.
- **Agreement with these rules.** If the writer labels something this library
  does not detect, that is the corpus working.

---

## What it settles

The open questions waiting on this, in the order the plan takes them:

1. **A bare eleven-digit Chinese mobile at the balanced stance** — whether an
   eleven-digit run is a number often enough to be worth what a wide rule costs.
2. **An unanchored English personal name** — the largest gap `SECURITY.md`
   names.
3. **An uncommon Japanese surname with no honorific and no label** —
   `ja.py` says the dictionary-anchored rules do not recover it; nothing
   measures how often that matters.
4. **What the entropy pass costs** — it needs documents carrying real secrets
   *and* real hex that is not one, in the same file.
