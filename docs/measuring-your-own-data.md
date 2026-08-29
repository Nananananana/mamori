# Measuring mamori on your own text

Every number this project publishes comes from data it invented. That is
deliberate — the datasets ship inside the wheel, so a real name in one would be
published to everyone who installs mamori — and it is also the limit of what
those numbers can tell you. They say a change did not make things worse. They
cannot say what mamori does to *your* documents.

This is how to find out, and what to be careful about while doing it.

## Before anything else

**A labelled dataset built from your real text contains your real text.** It is
a file full of names, addresses and account numbers, sitting on a disk, in a
format designed to be shared. Everything mamori does is aimed at preventing
exactly that file from existing carelessly.

So, in order:

- Keep it out of version control. Add it to `.gitignore` before you create it.
- Keep it out of the repository directory entirely if you can.
- Do not send it anywhere. It does not need to reach us and we do not want it.
- Delete it when you are done measuring, or treat it like the production data
  it is.

Nothing in mamori will write such a file for you. `mamori eval --dataset` reads
one; that is the whole of its involvement.

## The format

One JSON file. Values are marked inline, so nobody has to count characters:

```json
{
  "format_version": 1,
  "name": "acme-support-tickets",
  "locale": "en",
  "source": "internal",
  "description": "Fifty support tickets from March, names replaced by hand.",
  "samples": [
    {
      "id": "t-001",
      "annotated": "Hi [[PERSON:Jane Doe]], your order [[IDENTIFIER:ORD-99812]] shipped."
    },
    {
      "id": "t-002",
      "note": "Negative: a version string is not an identifier.",
      "annotated": "The 2.1.0 release is out. Nothing else to report."
    }
  ]
}
```

`[[TYPE:value]]` marks something that must be found. `[[?TYPE:value]]` marks
something that is **tolerated** — finding it is neither required nor wrong.
Use the second form where the ambiguity is genuine: ten bare digits really are
an order number to one rule set and a phone number to another. Use it sparingly,
because a corpus full of tolerated spans has no opinion about anything.

`mamori locales` lists the types available.

## What to put in it

The single most useful thing you can do is **use documents, not sentences**.
mamori's own core datasets were sentence fragments for eight versions, and when
document-scale sets were finally added they found four detection bugs in the
first run. A one-line sample cannot show you what a heading does to a name
rule, or what your signature block does to over-redaction.

Aim for:

- Whole messages, as they were actually sent. Quoted replies included.
- The boring ones. A page of technical prose with nothing to protect is how you
  find out what mamori destroys.
- The cases you already know are hard for you. Product names that look like
  surnames, internal reference formats, whatever your organisation writes.

Fifty documents is worth more than five hundred sentences.

## Running it

```bash
mamori eval --dataset tickets.json
```

```text
acme-support-tickets  (en, 50 samples)
  leak rate             1.20%   (14/1163 sensitive chars left uncovered)
  over-redaction        0.90%   (98/10842 ordinary chars replaced)
  entity P / R / F1   0.945 / 0.930 / 0.937   (match: overlap)
  clean samples       46/50
```

**Read the leak rate first.** It is the share of the values you labelled that
nothing covered — the part that would have left your machine. Over-redaction is
what it cost in ordinary text. Neither means anything without the other: a tool
that redacts everything has a perfect leak rate.

`--show-leaks` names the samples that leaked, worst first, which is where to
look next.

## Comparing two configurations

A single number tells you where you are. A delta tells you whether a change
helped:

```bash
mamori eval --dataset tickets.json --compare -c mamori.json
```

This scores the rules alone alongside your configuration and prints what
changed, naming the individual samples. That last part matters more than the
aggregate: "leak rate fell from 2.0% to 1.4%" tells you something moved,
whereas "`t-014` is now covered and `t-031` lost 56 ordinary characters" tells
you what, and whether you believe it.

Use it to answer the questions that actually come up:

```bash
# Is the recall-first default worth it on my data?
mamori eval --dataset tickets.json --stance balanced
mamori eval --dataset tickets.json                    # the default

# Does a local model earn its place?
mamori eval --dataset tickets.json --compare -c with-model.json --cache answers.json
```

`--cache` remembers what the model said, keyed on the model *and the prompt*,
so re-running is free and changing one line of guidance invalidates exactly the
answers that depended on it. **It writes to disk**, and for your own data that
file is as sensitive as the dataset. The same rules apply.

## Turning what you find into rules

Two things you can do with the results without forking anything:

**A value the rules got wrong** — record it:

```bash
mamori correct "Nightingale" --always PROJECT_NAME --note "our codename"
mamori correct "Monday" --never --note "a weekday, not a name"
```

**A pattern the rules cannot know** — tell the model tier about it:

```json
{"prompts": {"detection": {
  "add": [{"id": "acme.case", "text": "Case numbers look like ACME-12345."}]
}}}
```

`mamori prompt detection --guidance` lists the rule ids, including the ones you
can turn off.

## What this cannot tell you

Your labels are one person's opinion about what is sensitive, applied to text
that person chose. Somebody else at your organisation would label it
differently, and the documents nobody thought to include are the ones most
likely to contain a surprise. A measurement on your own data is much better
evidence than a measurement on ours, and it is still not a guarantee.
