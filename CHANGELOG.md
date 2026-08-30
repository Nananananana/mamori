# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the version is below `1.0.0`, the public API may change in a minor release.

## [Unreleased]

### Fixed

- **Three of the twelve figures in `SECURITY.md` were out of date**, and three
  sample counts with them. `ja-core` was the worst: over-redaction published as
  2.78% against a real 2.44%, precision 0.925 against 0.955. Nothing was broken
  — the document had simply stopped being true, at some release nobody can
  name, because the table is written by hand and the rules keep improving.

  Proposal 0002 makes *"the figures in `SECURITY.md` have data behind them
  worth the word measured"* a condition of 1.0. Two of that clause's three
  parts were already met; this was the part of the third that waits on nobody.

  `tests/test_security_figures.py` parses the table and compares every row
  against a live `evaluate()`, so the drift is now a build failure. **A
  published number that no longer holds is the same defect as a check that
  cannot fail**: it reads as evidence and is a memory of evidence.

### Removed

- **`AnonymizationError` and `RestorationError`.** Both were exported, both
  documented a failure mode, and **neither has been raised in any release** —
  not once in the history of the repository.

  Neither failure exists. Protection fails as a detector failing, a policy
  blocking, or a configuration error, and each has its own class. Restoration
  does not fail: a placeholder in an answer that was never allocated, and an
  allocated one the answer did not use, are **reported** on `RestorationResult`
  as `unknown` and `missing`, because a caller needs the restored text and the
  account of what was incomplete rather than an exception instead of both.

  An exported exception that nothing raises is worse than a missing one: it
  reads as a documented failure mode, so `except AnonymizationError` is dead
  code that its author believes is handling something. Found by a sibling
  project which had the same defect for a structural reason — the only layer
  that could raise its unused error was forbidden by its own layering rules
  from importing it. mamori's case is simpler: the layer can import it, and the
  failure never happens.

### Corrected

- **"The device does not change what a model returns" is false, and measured.** It was
  written into six documents in `0.27.0` as the reason the accuracy figures
  survived the CPU-inference mix-up, and it was asserted rather than measured —
  the same mistake as the timing it was used to excuse. A GPU re-run moves two
  rows of a five-model comparison and leaves the rest alone, and a controlled
  run — one model, one dataset, one pinned version, only the device changed,
  twice — reproduces it exactly: `7b-q4_K_M` on Japanese redacts **44% more on
  CPU than on GPU**, with different hashes over the full result.

  **What the sentence was defending held.** In the row that moves, the leak rate
  is `0.00000` on both devices and entity recall is unchanged — the model finds
  everything either way and merely redacts more besides. So withdrawing "345
  seconds is a property of this model" was right, and generalising it to "so the
  accuracy is fine" was not, and happened to be true for the numbers it covered.
  See [docs/choosing-a-model.md](docs/choosing-a-model.md).

  The seconds themselves are now measured on a GPU, with the device recorded on
  every row. The 345 seconds a document that were withdrawn are really **4.6**.

### Fixed

- **A model that never answered scored the same as a model that found
  nothing.** `EvaluationReport.unanswered_samples` counts the samples where a
  detection pass could not read its model's reply, and `mamori eval` prints a
  `MODEL UNREAD` line when there are any.

  Found by benchmarking `gemma4:12b`, which is a reasoning model: it spends the
  token budget in a `reasoning` field and returns an empty `content`. Eight
  documents came back as **"contributed nothing" at 35 seconds each**, which is
  exactly what a model with nothing to add looks like. The detection pass had
  been recording it the whole time on `last_outcome` — **nothing read it**, so
  a comparison table could call a model worthless when the honest answer was
  that it had never been heard from.

  An empty reply is also no longer reported as "response was not JSON". It is
  not malformed output, it is absent output, and the fix for it is different.

## [0.27.0] - 2026-08-30

The first release that can be installed by name, and the contract three sibling
projects were waiting for.

### Added

- **`mamori.protection-scope/1`** — a record of what was protected, carrying no
  protected value, so that a downstream needing only to *describe* a protection
  stops needing to import the thing that performed one. `mamori.provenance`
  emits it; the JSON Schema ships as package data; restoration still needs
  mamori and always will.

  The rule that decides what may go in is a test rather than a field list
  ([ADR 0032](docs/adr/0032-state-the-protection-without-importing-it.md)):
  **a record may state anything derivable from the artifact it describes, and
  nothing else.** That gives opposite answers for the two substitution modes.
  A token is in the protected text, recoverable with one regular expression, so
  listing tokens discloses nothing — and it is what lets a consumer tell a token
  mamori minted from one a user typed. A surrogate is deliberately *not*
  announced by the text, so naming one would say which values are invented and
  by elimination which are real; surrogates contribute a kind and a count.

- **A record holding surrogates declares a different contract**,
  `mamori.protection-scope/1+surrogate`. The rule it replaces — "a consumer
  that understands only placeholders must refuse the other modes" — had to be
  obeyed once per consumer, per version, forever, and the cost of forgetting
  was silent. A different identifier is obeyed **zero** times: refusing an
  unrecognised contract is the first thing any reader already does.

  It also moved the invariant into the validator. JSON Schema 2020-12 cannot
  compare two properties of one object, but splitting the identifier turned
  that comparison into two discrete cases, and `if`/`then` states those. A
  record claiming to hold only tokens while carrying surrogates now fails
  validation instead of a code review.

- **`EntityReport.surrogate`** — whether a plausible value went into the text
  instead of the token. The caller could not see this from the protected text,
  which is the point of a surrogate and also the reason it had to be said.

### Fixed

- **A phone number has no script in it.** A language pack only runs where its
  script appears, which is right for a rule that reads a name and wrong for one
  made of digits: `Please call our Tokyo office at 090-1234-5678` is an
  entirely Latin sentence, so the Japanese pack never ran and the number left
  the machine. So did a CSV row whose neighbouring column was called `phone`.

  The mobile prefix moves to the universal rules. **The landline half does
  not**, and that is measured rather than assumed: `0\d{1,3}-\d{1,4}-\d{4}`
  with no Japanese around it also matches `05-12-2024`, `Invoice 01-2345-6789`,
  `Version 02-1000-0001` and an ISBN. That half carries no evidence of its own,
  so the surrounding script has to be the evidence and it stays in the pack.

  No dataset moved — not one of the twelve, and not the three adversarial sets.
  Which is the point worth keeping: **the corpora could not have found this**,
  because none of them contains a Japanese number in a document with no
  Japanese in it. It came from a property test in a sibling session.

- **A scope identifier may not quote the document.** `scope` is repeated into
  every place a protection is described, on the grounds that it carries no
  content — so `scope="tanaka-invoice"` puts the value back into all of them.
  Refused at protect time, where the original values still exist. Values under
  three characters are exempt, because a check that fires on noise teaches
  callers to route around it.

## [0.26.0] - 2026-08-30

Japanese names and Japanese companies, and the first honest answer to "which
model should I run".

### Fixed

- **A one-character surname needs a given name.** 林, 森, 原 and 岡 are
  surnames. They are also a wood, a forest, a cause and a hill, and on their own
  the noun is commoner than the person: 林の手入れ, 森の手前, 原因, 静岡. Those
  four now require a given name; two-character surnames do not, because 田中の
  資料 is about a person and 田中 is unambiguous in a way 森 is not.

  A name still reaches the anchored rules when it has an honorific (森さん), a
  label (担当: 森) or a given name (森健太). What is given up is a bare 森 in
  running prose — the case a rule cannot tell from the noun, and which
  [ADR 0031](docs/adr/0031-the-morphological-adapter-measured-and-declined.md)
  measured an analyser on a release ago and found it could not tell either.

- **A trading name with no legal form.** 田中商事, さくら製作所, あおい技研 —
  how a Japanese company is usually written in a sentence, and a documented gap
  since 0.9. Now a MEDIUM rule over ten trading suffixes.

  It stayed open that long because **an over-detection was standing in front of
  it**. The wide tier read 田中商事 as a *person*, that span overlapped the
  COMPANY_NAME label, and the evaluation counted the company as covered. The
  miss only appeared once the over-detection was removed — so `test_stance.py`
  now asserts the opposite of what it asserted for sixteen releases, with the
  reason written down.

### Changed

| dataset | leak | over-redaction |
|---|---|---|
| `ja-core` | 0.00% | 2.78% → **2.47%** |
| `ja-adversarial` | 0.00% | 0.99% → **0.81%** |

### Documented

- **[Which model, and at what quantisation](README.md#which-model-and-at-what-quantisation).**
  Four models against `en-docs` and `ja-docs`. Every one of them finds the same
  values — the leak falls by the same 2.29 points from a 4.7 GB model as from a
  9 GB one. What differs is what else they add, so **quantisation costs
  precision, not recall**. For 16 GB of VRAM the recommendation is
  `qwen2.5:7b-instruct-q8_0`, which adds no over-redaction at all.

  The timings taken alongside those numbers were withdrawn rather than
  published: an interrupted Ollama update had left no CUDA library, GPU
  discovery had been failing in 0.19 seconds instead of 6.7, and every run was
  on the processor with the GPU idle. The 345 seconds one model took had been
  attributed to VRAM contention — a story that fit the number, was checkable,
  and had not been checked. The accuracy figures are unaffected: a model returns
  the same tokens whichever device multiplies the matrices.

## [0.25.0] - 2026-08-30

Two things 1.0 needs: a public surface that is a contract, and a corpus of text
written to be got wrong.

### Added

- **`tests/test_api.py`** — the names `import mamori` offers, written out
  rather than derived, so adding one is a line in that file and removing one
  fails. `test_promises.py` pins what this library will not do; this pins what
  it *is*.

  Writing it found that **nine releases of features were reachable only by a
  deep import**: `ConversationRegistry` and `LLMSettings` among them, both of
  which the README tells people to use, and `ProviderError`, which was missing
  from an otherwise complete error hierarchy — so a caller catching mamori's
  errors from the top level would have missed one.

- **900 adversarial documents** — text built to be got wrong in the three ways
  nothing had looked at: hard negatives (`Mark` the verb, `May` the month,
  川 the river, 高兴 the adjective), values written in forms NFKC has to fold,
  and documents whose paragraphs change language. Two thirds carry no labels at
  all, so a placeholder there is over-redaction with a location attached.

### Fixed

The corpus leaked 3.18% / 5.18% / 3.35% on first contact and found four things.

- **An address with the `@` held apart.** `jane.doe @ example.com` — not valid
  and a perfectly ordinary way for one to appear: a line wrapped, a word
  processor tidying up, somebody spacing it out deliberately. It was the only
  remaining leak class in English, 22 documents in 300. Both sides must still
  be address-shaped and one space at most, so "write to us @ the office" does
  not match.

- **Chinese: a name does not end in grammar.** `联系方式是` gave `方式是`
  fifty-two times. The relaxed right edge of 0.15 lets a match run past the
  name into the words after it, and eleven characters — 是, 的, 了, 在, 这 —
  are grammar all the way down.

  The first attempt used the existing function-word list and **cost 0.55 points
  of leak to buy 1.6 points of over-redaction**, because that list holds 和, 与,
  为 and 若, which are ordinary given-name characters. The list that stops a
  name running *into* the grammar after it is not the list of characters a name
  may not *end* with; treating them as symmetric loses 李和 and 王也.

- **Chinese: the name inside the grammar.** `发给王强了` was matching `王强了`,
  two characters ending at the comma with 了 read as part of the name. Harmless
  while it was over-redaction, and a **leak** the moment a validator started
  refusing candidates that end in grammar — the whole candidate went, and the
  name inside it with it. Function words are excluded from the given name
  itself now, which gives 王强.

- **Japanese: a given name does not end in a particle.** 0.17 let a given name
  be written in hiragana, because さくら and あおい are ordinary names. In
  `値引きは部長決裁` that produces 値引き + は with 部長 read as the honorific,
  ten times in three hundred documents.

- **English: a place is not a person.** `Rose Room` and `Fourth Street` are two
  capitalised words, which is all the wide rule asks, and Rose and Fourth are
  both given names. What settles it is the word after — a closed set of
  building words, so it costs no name, unlike a list of given names.

### Changed

| adversarial | leak | over-redaction |
|---|---|---|
| `ja` | 3.18% → **0.00%** | 1.31% → **0.99%** |
| `en` | 5.18% → **0.00%** | 1.33% → **0.57%** |
| `zh` | 3.35% → **0.00%** | 2.59% → **1.21%** |

Every existing set is unmoved or better and the thousand-document prose corpora
did not move at all. On the bundled sets the gain is small — `zh-docs`
over-redaction 1.20% to 1.12% at the recall-first default, `zh-core` 2.94%
unchanged, and at the balanced stance `zh-core` 1.63% to 0.65% and `zh-docs`
0.40% to 0.32%. The adversarial corpus is where these shapes are dense, which
is the point of having built it: the bundled sets contain one 联系方式是 and it
contains fifty-two.

### Measured, and it did not help

The 14B model against **assembled prompts** and **agent payloads**: no change
to any number. What still leaks in `en-context` is `E-45033` — an employee
number whose label stayed behind in the part of the document that was not
selected — and the model does not recover it either. It closes the anchorless
*name* and not the anchorless *identifier*, which is a sharper statement of
what a model is for than "it helps with documents".

### Left alone, and why

`林`, `森` and `原因` are still reported as people in Japanese: a one-character
surname used as an ordinary noun. Fixing it needs the sentence, which is what
[ADR 0031](docs/adr/0031-the-morphological-adapter-measured-and-declined.md)
measured and declined a release ago. The honest place for it is `mamori
correct`, where a person decides.

## [0.24.0] - 2026-08-30

The model tier, in every language this library speaks — and the last item on
the roadmap, closed by measuring it and saying no.

### Measured: 14B against documents, all three languages

`qwen2.5:14b-instruct-q4_K_M`, locally, at the recall-first default:

| set | leak: rules → +model | over-redaction | recall |
|---|---|---|---|
| `en-docs` | 3.50% → **0.36%** | 0.90% → 0.90% | 0.883 → 0.967 |
| `ja-docs` | 0.33% → **0.00%** | 1.06% → 1.06% | 0.984 → 1.000 |
| `zh-docs` | 2.37% → **0.00%** | 1.20% → 1.20% | 0.978 → 0.978 |
| `en-docs`, balanced | 20.02% → **1.69%** | 0.03% → 0.03% | 0.700 → 0.950 |

**Over-redaction does not move in any of them.** Two of the three languages
reach zero. At 8B this was "an English-recall tool that costs precision
everywhere"; at 14B it closes almost every remaining document leak and costs
nothing measurable.

It still takes 345 seconds a document on the hardware these numbers come from,
which is why the tier is off by default.

### The Chinese result was hiding behind a vocabulary

The first Chinese run said the model added **nothing at all** — every number
identical. It had proposed 33 entities; the ones that mattered were named
`CUSTOMER_NUMBER` and `WORK_NUMBER`, which this library did not recognise, so
they were dropped before anything scored them.

Accepting those two names takes `zh-docs` from 2.37% to 0.00%.

0.23 added synonyms after seeing English discard 11 of 38 entities over
spelling, and noted that on `en-docs` they changed no number because the rules
had already found those values. In Chinese the same change is the difference
between a model tier that does nothing and one that closes the last leak. A
strictness that costs nothing on the material you happened to measure can cost
everything on material you did not.

Four names stay refused, each for its own reason, all recorded in the code:
`IP_ADDRESS` would redact `8.8.8.8` when the point of `INTERNAL_IP` is that a
public address is not sensitive; `LOCATION` could be a country or a street;
`CREDENTIAL` would map onto `PASSWORD`, whose action is BLOCK; `HOSTNAME` has
no type to map to, because a URL and an address are not a name; and
`IDENTITY_NUMBER` means a 身份证号 in a Chinese document and something else
everywhere else, while `RESIDENT_ID` carries a checksum this pass cannot
verify.

### Declined: the Japanese morphological adapter

Proposed for 0.13, moved to 0.14, deferred in 0.19 and 0.22, and named in every
roadmap since as "still the right experiment; still not run". It was run.
**It does not win, and it is not built** —
[ADR 0031](docs/adr/0031-the-morphological-adapter-measured-and-declined.md).

`janome` adds **nothing**: in two hundred documents holding 1,010 rule-detected
people it found no name the rules had missed. Used the other way — dropping a
detection it does not recognise as a person — it buys 0.2 to 1.1 points of
over-redaction and leaks in every set: `ja-core` 0.00% → 1.37%, `ja-context`
0.00% → 9.48%.

What it drops is right some of the time (森林, 原因, 山口県) and wrong the
rest: `凪沢`, a surname no dictionary has; `清水`, one of the commonest
surnames in Japan, read in that sentence as the ordinary word; and
`sato.hanako`, a username in a file path, which is not Japanese text at all —
and to a filter, "no opinion" and "not a person" are the same answer.

The over-redaction it would have bought is still available, by name, from
whoever is looking at the document: 森林 and 原因 are two `mamori correct`
rulings, not a runtime dependency.

**How it was measured is the part worth keeping.** The generated corpus said
the filter was free — 22 spurious detections removed, *zero* real names lost
across two hundred documents. The hand-written bundled sets, a fiftieth of the
size, said it leaks. The generator draws from pools of common names, which the
dictionary knows; `凪沢` was invented in 0.16 precisely because it is in no
dictionary. **A corpus can only refute what its generator can produce**, and
that sentence has now decided three answers in three releases.

### Fixed

- **A test registered a global entity type and never took it back.** The
  registry is global and permanent by design — a deployment declares its types
  once at start-up — which in a test suite makes it shared mutable state. One
  test registered `CASE_NUMBER`, and three hundred tests later that silently
  changed what another test measured. It had been true for a release and nobody
  noticed, because the two happened to run in a harmless order until a synonym
  for `CASE_NUMBER` was added.

  The precedence itself is right and is now pinned by a test: **a registered
  type beats a synonym**, because a deployment's own definition is more
  specific than this library's guess about a model's wording.

### Added

- **`tests/test_concurrency.py`.** Six callers, one registry, one proxy, real
  threads and real sockets. The property is that one caller's values never
  reach another's answer, and until now the locking that provides it had been
  argued rather than exercised. It holds, including while eviction races with
  itself at the registry's ceiling.

## [0.23.0] - 2026-08-30

The oldest open question in the project, answered — and the reason it stayed
open for sixteen releases was a bug in this library.

`v0.7` asked whether a model above 8B changes the model-tier table. Every
attempt since said the same thing: the model times out on this hardware. It
does not. **`llm.timeout` did nothing above thirty seconds.**

### Fixed

- **A configured timeout that was silently discarded.** `LLMRequest.timeout`
  defaulted to `30.0` and the provider takes the smaller of the request's and
  the endpoint's, so an endpoint configured for three hundred seconds got
  thirty. Three attempts of thirty seconds plus backoff is ninety-seven, which
  looks exactly like a model too slow for the machine — and because the model
  pass degrades to nothing by design, the symptom was silence rather than an
  error.

  The request's timeout is now `None` by default and may only ask for *less*
  than the endpoint allows: the endpoint is where the operator set the limit.

- **`max_input_characters` said "refuse to send more than this"** and has
  windowed since [ADR 0021](docs/adr/0021-a-long-document-is-windowed.md). A
  setting whose description and behaviour disagree is worse than one with no
  description, because somebody configures the sentence they read.

- **The proxy body cap drops from 32 MB to 8 MB.** Protecting a 534 KB document
  peaks near **a hundred times** the size of the text — most of it detections
  rather than characters — so the cap is a memory bound rather than a bandwidth
  one, and 32 MB is gigabytes from one request. 8 MB is still about two million
  tokens, far past any model's context window.

### Measured: what the model tier is worth at 14B

`qwen2.5:14b-instruct-q4_K_M`, locally, against `en-docs` at the **recall-first
default** — the stance where the previous measurement said a model was worse
than useless:

| | rules only | + model | |
|---|---|---|---|
| leak rate | 3.50% | **0.36%** | −3.14 |
| over-redaction | 0.90% | **0.90%** | ±0.00 |
| entity precision | 0.946 | 0.935 | −0.011 |
| entity recall | 0.883 | **0.967** | +0.083 |

Three of the four leaking documents are now fully covered. **The leak rate falls
by ninety percent and over-redaction does not move at all** — which is not what
this project found at 8B, where the model bought English recall and paid for it
in over-redaction everywhere.

At the **balanced stance** it does more, not less — the rules leak 20.02%
there, and the model takes it to **1.69%** with over-redaction unmoved at
0.03%. That is worth reading twice: balanced plus a 14B model beats
recall-first rules on *both* axes at once, 1.69% against 3.50% leaked and 0.03%
against 0.90% over-redacted. Every stance table in this project describes a
trade between those two numbers, and this is the first thing that has moved
both in the same direction.

What it closes is the **anchorless name**: a name in an attendee list, under a
sign-off, after "Reported by:". That has been the largest measured gap in the
project since 0.9 and is not a regular-expression problem.

**It costs 345 seconds per document on this hardware.** That is fine for a
batch and impossible for a chat, and it is why the model tier stays off by
default. Measure it on your own hardware and your own documents before
believing any of this.

### Added

- **Near-miss type names are accepted.** In that run the model reported 38
  entities and **11 were rejected for spelling**: `ORG` for a company,
  `EMAIL_ADDRESS` for an address, `PHONE_NUMBER` for a number. Twenty-nine
  percent of a model's work discarded over a synonym.

  On `en-docs` this changes no number, because the rules had already found
  those values — which is said here rather than left for somebody to discover.
  It is kept because a document where the model's `ORG` is the only finding is
  not hypothetical.

  Four names stay refused, each for its own reason and all of them recorded in
  the code: `IP_ADDRESS` would map onto `INTERNAL_IP` and redact `8.8.8.8`,
  when the point of that type is that a public address is not sensitive;
  `LOCATION` could be a country or a street; `CREDENTIAL` would map onto
  `PASSWORD`, whose action is BLOCK, and a fuzzy label should not be able to
  stop somebody's request.

- **`test_promises.py` covers the surfaces added since 0.16** — conversations,
  tool-call arguments, the linter, the fail-closed refusal. A promise is only
  as good as the newest surface it was checked on.

## [0.22.0] - 2026-08-30

Time, which nothing here had ever measured.

Every number this project publishes is about correctness. None was about how
long protection takes, and that decides whether a privacy layer gets used at
all: one that adds a second to every request is one somebody routes around, and
a routed-around privacy layer protects nothing. The same argument as
over-redaction, in a different unit.

### Fixed

- **Overlap resolution was quadratic**, and it took thirteen seconds on a
  534 KB document.

  Each doubling of the input cost more than twice as much -- 2.3×, then 2.5×,
  then 3.4×, then 5.5× -- which is quadratic arriving slowly enough to look
  linear on anything small. Twelve of the thirteen seconds were three million
  span comparisons: every candidate checked against every span already
  accepted.

  Accepted spans never overlap each other, so they are totally ordered, and a
  candidate can only collide with the one starting immediately before it or
  immediately after. Two binary searches. **8× faster at half a megabyte, and
  flat at about 3 ms/KB from 16 KB to 534 KB.**

  The old loop is kept in `tests/test_resolution_and_policy.py` as the
  specification, and a property test asserts the new one returns exactly what
  it returned. An optimisation of a security decision is worth exactly as much
  as its equivalence proof.

### Measured

| corpus | median document | median | p95 |
|---|---|---|---|
| `ja-prose` | 172 chars | 0.96 ms | 1.53 ms |
| `en-prose` | 274 chars | 0.84 ms | 1.27 ms |
| `zh-prose` | 141 chars | 0.89 ms | 1.35 ms |
| `ja-context` | 665 chars | 3.52 ms | 4.96 ms |
| `en-context` | 943 chars | 2.14 ms | 3.11 ms |

Under a millisecond for a typical prompt, against a model call that takes
hundreds. There was no performance problem at this size and there never was --
which is worth having measured rather than assumed.

Restricting to one language pack is 30–45% faster on CJK, because the Japanese
and Chinese packs both run on Han text. The default runs every pack, because an
unexpected language is exactly the case nobody redacted by hand, and that is
what it costs.

### Changed

- **`mamori privacy` describes the settings that exist.** `uncertain` and
  `placeholder_style` were added in 0.19 and the report did not mention either,
  so a setting that stops requests was discoverable only by reading the source.
  It also **warns when `uncertain="refuse"` is set without a threshold**: at
  the default `min_confidence` of 0.0 nothing is ever uncertain, so the setting
  does nothing at all, and a privacy setting that silently does nothing is the
  worst kind there is.

- `bisect` joins the domain's allowed standard-library imports.

## [0.21.0] - 2026-08-30

The most dangerous option in the library, measured.

`surrogates=True` replaces a value with a plausible one -- `田中太郎` becomes
`山田一郎` -- because some models reason visibly worse about a page of tokens.
The module docstring has said since 0.11 that this is the most dangerous thing
here, and why: **a placeholder that is never restored is obvious, and a
surrogate that is never restored is a plausible sentence about the wrong person
that nobody notices.**

That was a paragraph. It is now 1200 replies, in six shapes, with the nine ways
a model rewrites a *name* rather than a token.

### Measured

```text
1200 surrogate replies, 3600 surrogates in them
  1261 (35.0%) were rewritten past recognition
   859 (71.6%) replies held at least one
     0 survived and were not put back -- must be 0
     0 losses went unreported by `missing` -- must be 0
```

The first two numbers are the price of the option, not a bug list: a surrogate
has no shape, so a model that writes `Alex` where it was given `Alex Rivera`
has produced text nothing can find again. They are also an upper bound rather
than a forecast -- the corpus applies the nine rewritings uniformly, and a real
model quotes intact far more often than one time in nine.

The last two are the ones that had to be zero, and are. **Every loss was
reported through `RestorationResult.missing`**, which is the whole of the
mitigation: it is what stands between an invented person's name and a reader
who is about to believe it.

| how the model wrote it | destroys the stand-in |
|---|---|
| `intact`, `possessive`, honorific | 0% |
| `case_changed` | 0% *(17% before this release)* |
| `initial` (`A. Rivera`) | 18.5% |
| `line_break` | 95.4% |
| `given_only`, `family_only` | 100% |

### Changed

**Two liberties are now taken with how a surrogate looks**, both for the same
reason and both narrowing that 35%:

- **Case is folded.** `alex rivera` is the same stand-in written carelessly,
  and the alternative to putting it back is leaving an invented name in an
  answer. 17% of the losses.
- **A name wrapped across a line is still the name.** `Alex\nRivera`. At most
  one line break per gap, so this cannot reach across a blank line and join the
  end of one paragraph to the start of the next.

Neither changes what a surrogate *is*: identity is still the whole string, and
half of one still restores nothing. `find_occurrences` grew `fold_case` and
`fold_wrapping` flags, both off by default -- the co-occurrence pass uses the
same function to decide two runs of text are the same value, and `Mark` the
name and `mark` the verb are not.

`line_break` is still 95.4% because most surrogates have no spaces in them at
all: a Japanese name, an email address, a phone number. A break inside one of
those is unrecoverable and always will be.

### Unchanged

No detection number moved. Like 0.20, this release is entirely about the other
half.

## [0.20.0] - 2026-08-30

Restoration, measured at the scale detection has had since 0.2.

Detection has thousands of labelled samples. Restoration -- the half that turns
an answer about `<PERSON_001>` back into an answer about a person -- had a
thousand, in two shapes, with five manglings. The last two releases both found
restoration-side bugs *by accident*, which is the argument for looking on
purpose.

Two thousand replies, in six shapes, with fourteen manglings applied per
occurrence, a quarter of them carrying something placeholder-shaped that was
never allocated, and every one of them also emitted as pieces cut at arbitrary
boundaries.

### Fixed

- **`<COMPANY _ NAME _ 001>` restored whole and not in pieces.** 0.14 widened
  the batch scanner to accept the spaced form -- it was 195 of 1002 failures in
  the first reply corpus, the single biggest restoration bug this project has
  had -- and the **streaming** partial matcher was never widened with it. The
  two paths have disagreed on it ever since.

  340 of the first 2000 replies were affected. A reply streamed through the
  proxy came back with a placeholder still in it where the same reply, received
  whole, came back correct.

  The property test in `tests/test_streaming.py` could have found this and did
  not. It draws from an alphabet that includes both spaces and underscores, but
  the shape needs a space on *both* sides of an underscore inside a type name,
  and Hypothesis never happened to draw one. Arbitrary chunking of realistic
  text found it on the first run. Property tests and corpora fail differently,
  which is the argument for having both.

### Measured

```text
2000 replies
  2000 restored exactly, 0 not
  0 false restoration(s) -- must be 0
  2000/2000 streamed identically to whole
  0 leftover placeholder(s) in recoverable replies
```

The second line is the one to read twice. A quarter of the replies carry
`<PERSON_042>` or `<SSN_001>` -- placeholders this scope never allocated -- and
restoring one would mean a reply can fish for values by guessing. None was
restored, which is what
[ADR 0003](docs/adr/0003-readable-placeholders.md)'s "permissive about surface,
strict about identity" is supposed to mean, now with a number behind it.

Full-width digits turn out to restore: NFKC folds them before anything looks at
them. That was expected to fail and does not, which is the normalization doing
its job.

### Unchanged

No detection number moved. This release is entirely about the other half.

## [0.19.0] - 2026-08-30

Deployment. Three things a team needs before this is allowed near production,
and none of them is a detection rule.

### Added

- **`mamori lint`** -- the values that reach a model through a *repository*
  rather than through this library. A prompt template with a real address in
  it, a fixture built from a support ticket, a notebook whose output cell still
  holds the query that produced it.

  ```bash
  mamori lint                     # this directory
  mamori lint src prompts --json  # for a machine
  ```

  It reports a path and a line number, **never a value** -- these outputs land
  in CI logs, which are archived, searchable and often more widely readable
  than the repository. It **fails on credentials and reports the rest**: a
  leaked key is an incident, a customer's name in a fixture is a decision
  somebody should make on purpose, and a linter that exits non-zero for both
  teaches people to pass `--no-verify`. `--fail-on any` is there for a
  repository that has made the other decision.

- **`placeholder_style`** -- `angle` (the default, `<PERSON_001>`), `square`
  (`[PERSON_001]`) or `curly`. `<PERSON_001>` inside an HTML or XML document is
  an unknown element: a browser drops it, a parser may drop the text around it,
  and a model asked to edit the document is being shown a tag rather than a
  token. Restoration has always been permissive about surface form, so a
  document protected in one style restores through a session configured for
  another -- identity is the `(type, index)` pair and the brackets are surface.

- **`uncertain="refuse"`** -- the fail-closed stance. The default resolves
  doubt in favour of sending: a detection below `min_confidence` is discarded
  and the text goes out with the value in it. Refusing stops instead, for a
  deployment where the cost of a leak is not measured in answer quality. The
  refusal names types and confidences, never values.

  It does nothing at the default `min_confidence` of `0.0`, because nothing is
  below zero. The two settings are one dial: `min_confidence` says where
  certainty runs out and `uncertain` says what happens there.

- **A name split across two keys.** `{"first_name": "Jane", "last_name": "Doe"}`
  -- each half is a word, and there is no prose to reach it with, because the
  structure is carrying the meaning a salutation would carry in a sentence.
  They stay two values: reassembling them would put a full name where the
  application expects a given name.

### Fixed

- **A URL was a credential.** `github.com/owner/repo/blob/main/docs/...` is a
  long run of exactly the characters a base64 key is made of, and the wide
  secret rule's left guard did not exclude a preceding dot. Found by pointing
  `mamori lint` at this repository's own documentation, which is what a linter
  is for: 910 findings became 66, and 42 credentials became 1 -- a `hunter2` in
  an ADR example, which is correct.

  No corpus number moved. The fix is free.

### The last item in proposal 0002's plan

`mamori.yml` was declined in that proposal and stays declined
([ADR 0012](docs/adr/0012-configuration-without-a-format.md)). Everything else
on the deployment list is now here, three releases after it was first written
down and twice postponed by things that turned out to matter more.

## [0.18.0] - 2026-08-30

Two leaks, found by looking at the shape of the payload rather than at the
words in it. Both are the same mistake made twice: a rule written for prose and
applied to everything.

### The proxy protected the prose and forwarded the rest

`messages.py` had said since 0.6 that a tool call was "not text". True of the
call. False of its arguments:

```json
{"to": "jane.doe@example.com", "body": "Dear Jane Doe, call 415-555-0198."}
```

Four values, four leaks, one request -- and in an agent loop that is where the
personal data is, more reliably than in the prose around it. Symmetrically on
the way back: a model that answers with a tool call had its arguments left
unrestored, so the application was handed `{"to": "<EMAIL_001>"}` and sent mail
to nobody. That one does not even look like a leak; it looks like a bug.

Four hundred generated agent turns: **106 of 400 requests carried nothing known
before this release. 397 of 400 do now.**

### One kana character spoke for a whole document

The locale selector's rule is decisive and correct -- kana appear in Japanese
and never in Chinese, so the Chinese pack stands down. It was applied to the
whole text, so this went out with the body in the clear:

```json
{"subject": "契約更新のご連絡", "body": "关于朱强的事，我会和新程工业集团确认后回复。"}
```

So would any bilingual thread, ticket or assembled context package. The
evidence was local and the conclusion was global.

### Fixed

- **A tool call's arguments are protected and restored, both ways**, including
  in a stream -- where each call's arguments are their own run of text and get
  their own restorer. Feeding two interleaved runs through one restorer splices
  one's held suffix onto the other's next chunk.

- **Three more places a caller's words sit**: `messages[].name`,
  `tools[].function.description` (which conventionally carries an example, and
  an example is a real address in a real deployment), and `user` -- an "opaque
  identifier" that people fill with an email address.

- **Evidence about a script reaches to the end of its sentence and no further.**
  A pack that a script would suppress runs anyway, and its detections are kept
  outside the sentences where that script appears. Rules still see the whole
  text; only the answers are filtered. A comma is not a boundary:
  `本日、会議資料を送付します` is one sentence.

- **The walk and the rebuild follow a path.** Slots used to be yielded as
  strings and put back positionally, which works exactly as long as both
  functions are edited together -- so adding a place to look was a chance to
  leak the place you added.

- **Protection that breaks JSON fails closed.** It should never happen, because
  no rule matches across a structural boundary; it is checked at the one place
  where the failure would otherwise surface as a parse error in somebody else's
  process, hours later.

### Added

- **A key is a label.** `{"employee_id": "B-12778"}` says what the value is as
  plainly as `社員番号: B-12778` does, and nothing read one. Seven key families
  -- employee id, postal code, phone, address, person, company, date of birth --
  case- and separator-insensitive, in English, Japanese and Chinese spellings,
  because an API is written in English keys whatever language its values are
  in. This was the largest single leak in the agent corpus: 97 employee ids and
  35 postal codes out of 145.

  A bare `name` is deliberately **not** one of them. In JSON it is a tool name,
  a model name or a field name far more often than a person, and redacting the
  name of the function an agent is calling breaks the call.

- **`en-agent`, `ja-agent`, `zh-agent`** -- bundled datasets of agent-shaped
  text, a fourth scale after fragments, documents and assembled prompts. Tool
  names, call ids and JSON schemas are a negative set in them.

- **`mamori demo --scenario agent`**, and
  [ADR 0030](docs/adr/0030-a-tool-call-is-text.md).

### Changed

| | 0.17 | 0.18 |
|---|---|---|
| agent turns carrying nothing known (of 400) | 106 | **397** |
| tool calls restored byte-identically (of 400) | 0 | **400** |
| `ja-generated` over-redaction | 0.72% | 0.92% |

That last row is the cost of local evidence, and it is the whole of it: the
Japanese leak rate did not move and the bundled Japanese sets did not move. A
Han-only sentence inside a Japanese document is now ambiguous and gets Chinese
rules too -- which is what the selector already claimed to do for Han-only
*text*. The change is that "text" now means "sentence".

### Stated rather than solved

- **A schema's `enum` is left alone.** It is the contract the model is being
  asked to satisfy, and replacing a value changes what it may emit rather than
  what it may see.
- **`user` is replaced**, so the upstream's abuse tracking sees a different id
  per session. The field is opaque to them by definition, so nothing they can
  act on is lost -- but it is a consequence worth knowing before it is
  discovered.
- **YAML keys are not read.** The rules match JSON string syntax. A
  configuration file with `employee_id: B-12778` in it is the prose-label case
  and is only covered where a locale pack has that label.

## [0.17.0] - 2026-08-30

Prompts nobody typed.

Every dataset in this repository until now was prose somebody wrote: an email,
a ticket, a set of minutes. A growing share of what reaches a model is not that
-- it is **assembled**, by a retrieval layer or an agent framework, out of
passages and headers and structure. Three hundred rendered context packages,
built with the sibling project [tsumugi](https://github.com/Nananananana/tsumugi)'s
own domain classes rather than an imitation of its output, said what that
assumption had been hiding:

| | prose | assembled |
|---|---|---|
| leak rate, ja | 2.7% | **20.4%** |
| leak rate, en | 1.5% | **21.7%** |
| leak rate, zh | 0.4% | **15.8%** |

### Fixed

Four bugs, and three of them were not about assembled prompts at all. They were
general, they had been there for releases, and prose had never shown them.

- **A home directory names its owner.** `/home/p.doe/notes/customers.md`,
  `C:\Users\sato.hanako\`. The largest leak in all three languages, and no
  rule had ever looked at a path. Only the one segment is replaced -- the rest
  is provenance somebody may be checking -- and a closed list of system
  accounts (`runner`, `Public`, `www-data`) is refused, the same argument that
  justifies the weekday list in Chinese.

- **A digit run inside a hash was read as an identifier, and as an SSN.**
  `5b469054284c` contains nine digits. The guards said `(?<!\d)` and `(?!\d)`,
  which do not stop a run in the middle of a token, so any content hash, commit
  id or UUID could be redacted -- breaking a checksum to protect nothing.

- **`(?=[^A-Z]*[A-Z])` does not mean what it looks like.** It was the wide
  secret rule's "mixed case" requirement, and `[^A-Z]*` walks straight past the
  end of the candidate: **a capital letter anywhere later in the document
  satisfied it**. In practice every document. Every long path in an assembled
  prompt was reported as a credential.

- **`プロジェクト鶴の残作業は?` was a codename called `鶴の残作業は?`** -- the
  whole question. Same in Chinese: `项目子午的进度` gave `子午的进度`. Two
  costs, and the second is worse than the over-redaction: the same project in
  two sentences got two *different* placeholders, so the model could not tell
  they were the same project and a quotation restored to a different string
  than the passage it came from.

Two more turned up in passing, both Japanese, both general:

- **A hiragana given name was invisible.** `西村さくら様` was missed while
  `西村花子様` was found: every rule wanted Han or katakana, and さくら, ゆき
  and あおい are ordinary names. Offered where an honorific or a label is
  present and nowhere else -- after a bare surname a hiragana run is a particle
  far more often than a name.

- **`社員番号は入社時にA-44881を付与予定です`** did not read as an employee id.
  The same label-gap bug fixed for Chinese in 0.15, in the other language,
  thirty times in a thousand documents.

### Added

- **`en-context`, `ja-context`, `zh-context`** -- bundled datasets of assembled
  prompts, and a third set of quality floors. Structure is a **negative** set
  in them: item ids, content hashes, character offsets and budgets are labelled
  as ordinary text, so anything replaced there is a bug with a number attached
  rather than a matter of taste.

- **`ProtectionResult.reversible`** and **`masked_types`**. The caller cannot
  see this from the text -- `<PERSON_001>` and `[REDACTED]` look equally
  replaced -- and downstream it is the difference between *unsupported* and
  *unverifiable*: between accusing a model of inventing something and admitting
  you cannot tell.

- **`mamori demo --scenario package`**, and
  [ADR 0029](docs/adr/0029-a-prompt-nobody-typed.md).

### The property that matters for this composition

A consumer that checks a model's citations does it by matching text, so
restoration has to be exact -- not nearly. One character of drift reads as a
fabricated quotation rather than a redacted one, and an evidence system that
reports honest citations as fabrications trains its reader to ignore the
signal.

Three hundred generated answers, each quoting a passage it was given, restored
through the same session: **300 of 300 exactly**, including the 168 whose quoted
span contains placeholders.

### Changed

| default stance | 0.16 | 0.17 |
|---|---|---|
| `ja-generated` leak (1000 documents) | 2.64% | **1.37%** |
| `en-context` leak | 21.68% | **9.69%** |
| `ja-context` leak | 20.42% | **3.60%** |
| `zh-context` leak | 15.82% | **3.12%** |
| `en-context` over-redaction | 1.43% | **0.18%** |
| `zh-docs` over-redaction | 1.68% | **1.20%** |

`en-context` still leaks 9.69% on the generated set, and the residue is one
class: a value whose anchor **stayed behind in the part that was not selected**.
`Progress on Meridian: 31% done` has no word "project" in it, and
`Review notes for E-45033` has no word "employee number". That is what
selection does to a document, it is measured now, and the answer to it is not a
regular expression.

The same effect is why `en-context` leaks 46.85% at the balanced stance against
`en-docs`'s 20.02%. Assembled prompts need the recall-first default more than
prose does.

## [0.16.0] - 2026-08-30

Conversations: sessions that outlive one request, for the clients that need
them, off for everybody else.

### The claim that was checked

The proxy has always held one scope per request and purged it with the reply.
That was defended with an argument -- a chat client resends the whole
conversation each turn, so the same values meet the same allocator in the same
order and land on the same placeholders -- and the argument stood for four
releases without anybody checking it. It is checked now, in
`tests/test_conversations.py`, and **it holds**, which is why the default has
not changed.

It holds only for that client. A client whose history lives on the service side
sends one message per turn. The service answers about `<PERSON_001>` because
that is what it was told in turn one, this process has never heard of
`<PERSON_001>`, and the caller is shown a token where a name should be -- the
failure this library exists to prevent, arriving from the other direction.

### Added

- **`mamori serve --conversations`.** The reply carries `X-Mamori-Session`; a
  client that echoes it keeps its placeholders across turns. The token is
  minted by the server from `secrets.token_urlsafe` and **never taken from the
  caller**: the thing behind it is a table of real values, and an identifier an
  outsider can guess is a way to read somebody else's table. An unrecognised
  token quietly starts a new conversation rather than reporting that it was
  unrecognised, which would confirm to anybody asking which tokens exist.

- **`mamori.application.conversations.ConversationRegistry`** -- the same thing
  for code that does not use the proxy. Bounded in both directions: 30 minutes
  idle and 64 conversations by default, and **both bounds purge what they
  drop**. A caller whose conversation was dropped comes back to a new one and
  re-protects its history, which is the behaviour it had before this existed.
  Expiry runs on the path that uses the registry rather than on a timer,
  because a background thread that purges secrets is one whose failure is
  silent.

- **`X-Mamori-Session-End`**, for a client that knows it is finished and would
  rather not wait out the idle timeout.

- **`mamori demo --scenario conversation`** -- the failure and the fix, side by
  side, in one screen.

- [ADR 0028](docs/adr/0028-the-server-names-the-conversation.md), and
  [proposal 0003](docs/proposals/0003-what-mamori-is-for.md), which replaces the
  roadmap.

### Not built, and it was in the plan

The **per-session salt** adopted in proposal 0002 for exactly this release. Its
purpose was to make a placeholder stable inside one conversation and unrelated
across conversations. Allocation order already gives both, because the index
comes from the order values are met rather than from the values -- so the salt
would have added a keyed hash that nothing reads. What this release actually
needed was an identifier nobody outside the process can guess, which is a token,
not a salt. The reasoning is in ADR 0028 so it is not proposed a third time.

### Unchanged

Mappings still never touch the disk. What a conversation extends is how long a
scope lives, not where it lives, so [ADR 0006](docs/adr/0006-mappings-live-in-memory.md)
stands as written: a process that stops forgets everything.

## [0.15.0] - 2026-08-30

Chinese. The corpus generated in 0.14 was pointed at it, and the first thing it
found had been there since the first release: **a Chinese name followed by an
ordinary word was invisible.**

```
张伟汇报了进度。      nothing detected
李明的报告已经收到     nothing detected
王强负责办理设备       nothing detected
<PERSON_001>，请知悉。  found -- because a comma follows
```

Chinese has no spaces, so the right edge of a name has to be guessed, and every
rule guessed it by requiring a non-Han character afterwards. That is the
unambiguous case and it is also the rare one: in Chinese prose a name is
followed by a verb or a particle far more often than by punctuation. A thousand
generated documents missed 104 names this way. It is the largest single gap the
project has measured.

### Fixed

- **The right edge of a name.** A name may now run into the next word: one
  character, or two when the second is not a function word. 李明的 gives 李明
  and 张伟汇报 gives 张伟汇 -- one character too many, which is over-redaction
  rather than a leak, and that is the direction this library errs in. The
  function-word list is a closed set, which is what makes it defensible where
  the katakana vocabulary list deleted in 0.9 was not.

- **A label separated from its value.** `工号预留为 E-52260` was not read as an
  employee ID because the rule wanted the label flush against the number. The
  same shape as the Japanese `社員番号は` fix in 0.14, found the same way,
  twenty-eight times. The gap is capped at four characters and may not cross
  punctuation.

- **山, 江 and 河 are no longer proof of a place.** They end 中山 and 长江; they
  also end 乐山, 建江 and 小河, and the organisation rules were already
  catching the places.

- **A preposition is not a name.** 于, 向, 从, 由 and 对 are surnames and also
  the commonest words in `关于上次`, `指向旧地址`, `向管委会汇报`. The relaxed
  right edge is not offered after them; the strict one still is, so 于明。 is
  still found.

- **A weekday is not a person, at any stance.** 周 is a common surname and the
  wide tier deliberately drops the stoplist, so it was reporting 周四 as a
  name fifty-three times per thousand documents. The wide tier now refuses
  exactly one word class -- the weekdays -- and nothing else. 高兴 is still
  reported there, because somebody really could be called that.

### Changed

Every Chinese number moved in the right direction, which was not the first
result. The first version of the right-edge change was a straight trade: half
the leaks for 0.06 of precision, and the quality floors were about to be
written down that way. The three fixes after it brought the precision back.

| default stance | 0.14 | 0.15 |
|---|---|---|
| `zh-docs` leak rate | 4.41% | **2.37%** |
| `zh-docs` entity recall | 0.913 | **0.978** |
| `zh-docs` over-redaction | 1.84% | **1.68%** |
| `zh-docs` entity precision | 0.894 | **0.918** |

On the thousand generated documents, where the work was done: leak rate 2.73%
-> **0.35%**, recall 0.926 -> **0.996**, precision 0.837 -> 0.868.

`zh-core` over-redaction rises from 2.29% to 2.94% -- two characters on a
306-character set, the cost of no longer treating 山 as proof of a place.

The quality floors are tightened on every axis except that one.

### Known, and left alone

Two names in the corpus are still missed and both are the cost of a stoplist:
`周一帆` (the weekday entry) and `马若谷` (若 is in the function-word list). A
stoplist that closes a leak opens a smaller one, and the residue is written
down here rather than papered over.

## [0.14.0] - 2026-08-30

A thousand generated documents and a thousand generated replies, in the
development repository rather than the package. They found five bugs in about
an hour, and one of them had been there since 0.2.

### The corpus

Twelve genres -- email, support ticket, minutes, medical referral, contract,
HR, invoice, chat, technical note, credentials in prose, and two that are
almost entirely negative -- across all three languages. **Labels are correct by
construction**: a template names a slot, the slot is filled from a pool, and
the filler is wrapped in `[[TYPE:value]]` as it goes in, so there is no step at
which a human could mislabel something.

Decoys are inserted deliberately and left unlabelled -- version strings, part
numbers, percentages, public IP addresses, error codes, weekday names -- because
a corpus without them measures only how much a detector finds and never how
much it wrecks.

The second corpus did not exist before. Detection has had hundreds of labelled
samples since 0.2 and **restoration has had a handful**, which is an odd split
for something that is half the product. Each reply fixture states the mapping a
session would have held, a reply containing the placeholders as a model would
actually mangle them, and the text that should come out.

Both live in `mamori-work/testdata/` and are not shipped: the bundled datasets
are the regression floor and are meant to stay small and readable.

### Fixed

- **Restoration failed on `<COMPANY _ NAME _ 001>`.** Spaces inside the token.
  195 of 1002 replies came back wrong, and it accounted for **every single
  failure** -- brackets dropped, case changed, full-width brackets and lost
  zero-padding all restored correctly, exactly as
  [ADR 0003](docs/adr/0003-readable-placeholders.md) claims. No hand-written
  test had thought to try a space. 1002 of 1002 now.

  The scanner is meant to be permissive about surface form and strict about
  identity; a space was a surface form it did not know about. Types now
  canonicalise `[\s_-]+` to a single underscore, and the pattern refuses to
  cross a line break so a type cannot swallow a paragraph looking for its
  index.

- **English had no `Project X` rule.** Japanese got one in 0.9 and Chinese in
  0.13; English went without until a thousand documents missed it thirty times.
  The same asymmetry, a third time, which is itself an argument for generating
  a corpus rather than writing one.

- **`社員番号は X` was not read as an identifier.** The rule wanted a colon, and
  a particle is the commoner form. `ja-docs` leak fell from 1.50% to **0.33%**.

- **The Chinese company rule swallowed the clause in front of it.**
  `甲方联系人为新程科技有限公司` came back as one company name, because the
  function-word list the rule already had was missing `为`. Same class as the
  English "Where Umbrella Ltd" bug of 0.9. That list is a stoplist and is
  defensible where the katakana one was not: function words are a closed set
  that nobody coins.

- **`en-doc-002` never labelled its own codename.** A hole in a hand-written
  document set, invisible until a rule existed that could notice.

### Changed

| default stance | leak before → after |
|---|---|
| `ja-docs` | 1.50% → **0.33%** |
| `en-docs` | 3.55% → 3.50% |
| `zh-core` over-redaction | 3.59% → **2.29%** |

On the generated corpus, which is where the work was done: Japanese leak 3.83%
→ **2.64%** with recall 0.960 → 0.977, English 2.37% → **1.47%** with recall
0.939 → 0.956.

The quality floors are tightened to match, and a regression test for the spaced
placeholder now lives in the package so the finding does not depend on the
development repository being present.

## [0.13.0] - 2026-08-30

Japanese and Chinese, which the document sets have said are the weakest since
0.9. Four rule changes were tried; two are kept, two were measured out again
the same day, and the two that failed are the more interesting half.

### Added

- **A Japanese label anchor for Han names.** `差出人: 横山` was missed because
  the label rule added in 0.9 reached katakana and stopped there, so `ja-doc-006`
  leaked the same name twice for four releases.

- **`項目X` / `项目X` without a colon**, in Chinese. The Japanese equivalent
  landed in 0.9 and the Chinese one did not, so `zh-doc-002` leaked a codename
  for two releases because only one of the two languages got the fix.

- **Customer-facing identifier labels** in both languages -- `お客様番号`,
  `客户编号`, `受理号` and the rest. The employee-id rules had the internal
  labels only.

- **Two more Chinese documents**, one of which exists specifically to catch the
  mistake described below.

### Measured out again

Both of these looked right, improved the numbers, and were reverted.

- **A "not preceded by a Han character" guard**, to stop `里程碑` being read as
  a person called `程碑`. It lifted `zh-core` precision from 0.903 to 0.933 and
  cost nothing measurable on any of the six sets.

  It was reverted because a probe *outside* the corpus lost names entirely:
  `这是张伟。` and `昨天和王强，我们谈过。` both came back untouched. Chinese has
  no spaces, so a name is usually preceded by a Han character, and the datasets
  happened to place all of theirs after punctuation. Trading a visible false
  positive for invisible misses is the wrong direction for this library, and
  the corpus was not able to say so. `zh-doc-005` exists so that the next
  attempt is measurable.

  This is the case regular expressions cannot settle, and it is now the
  concrete argument for the optional morphological adapter rather than a
  general one.

- **A Chinese `负责人：` label rule.** It changed neither the leak rate nor
  recall -- the surname rule already reaches every name a label introduces,
  because Chinese personal names begin with a character from a closed set --
  and it cost precision by reading `收件人：客服` as a person called "customer
  service". A label is weaker evidence than a surname dictionary here, which is
  the opposite of the Japanese case.

### Fixed

- `mamori audit` reported the two new identifier rules as never having fired,
  within minutes of them being written -- the same failure as 0.12, caught this
  time by the tool built for it rather than three releases later. Samples added
  in both languages.

### Changed

Every set is better or unchanged at the default stance, and the two document
sets that were weakest moved most:

| | leak before → after | recall |
|---|---|---|
| `ja-docs` | 1.83% → **1.50%** | 0.951 → **0.967** |
| `zh-docs` | 6.11% → **4.41%** | 0.903 → **0.913** |

`zh-docs` over-redaction rose from 0.78% to 1.84% and `ja-core` from 2.50% to
2.78%, because the new samples are harder than the ones they joined rather than
because anything got worse. That is what a corpus growing towards realism looks
like.

## [0.12.0] - 2026-08-30

Saying why. Every detection has recorded which rule found it since 0.1.0 and
almost nothing surfaced it, so "why was this redacted?" was awkward to answer
and "why was this **not** redacted?" was impossible.

### Added

- **`mamori trace`** -- every candidate the pipeline considered and what became
  of it: kept, below the confidence threshold, ruled away by a correction, or
  displaced by an overlapping detection that won. Each displacement says which
  preference decided it, which makes
  [ADR 0005](docs/adr/0005-overlap-resolution.md) inspectable rather than
  merely written down.

  ```text
  where     type            rules         conf  outcome
  5:11      PERSON          en            0.90  kept
  59:69     IDENTIFIER      universal     0.50  displaced -- lost to PHONE (higher severity)
  ```

  And then the harder half. It runs the *other* stance and says what the wider
  rules would have caught -- as a shape, never a value. When neither stance
  finds anything more it says so, and points at a correction or the model tier
  rather than leaving somebody guessing. See
  [ADR 0027](docs/adr/0027-say-why-and-say-why-not.md).

- **`mamori audit`** -- which rules carry the load over a corpus, and which
  have never fired once. Rules are run individually rather than through the
  pipeline: a rule that fires and always loses an overlap looks identical to
  one that never fires, and those are different problems. `--file` audits your
  own text, which is the more useful question.

- **Stable rule identifiers** (`en.PERSON.2`, `universal.EMAIL.1`), derived
  from pack, type and declaration order, with an explicit `name=` available
  where a rule deserves one.

- **`ProtectionResult.trace`**, off by default because it costs a list of every
  candidate. It carries masked previews and never values -- a trace is exactly
  what somebody pastes into a bug report, and a test pins it.

### Fixed

`mamori audit` found these on its first run, which is the point of it.

- **Three credential rules shipped in 0.10 had never been measured.** The prose
  password rules -- `the password is X`, `パスワードは X`, `密码是 X` -- had no
  dataset sample in any language. Credential detection, added without
  evaluation coverage, in the release that was about not trusting unmeasured
  things. Samples added in all three languages, including the negatives that
  matter more: "my password is fine" must not stop a request.

- **A UK-shaped phone rule had never fired**, for the same reason. Sample
  added.

- **A stale published figure.** The `ja-docs` leak rate given in 0.9 was
  measured before a fix that landed in the same release: published at 2.49%,
  actually 1.83%. `SECURITY.md` and the READMEs carry the corrected tables.

### Changed

- The remaining ten never-fired rules are the vendor-prefixed credential rules,
  which cannot have samples -- a literal key in a file that ships inside the
  wheel trips the secret scanner of everyone who clones the repository.
  `audit` says so rather than listing them beside genuine findings, and a test
  pins that nothing *else* is dead, so the next unexplained one is visible.

- The roadmap is revised in
  [proposal 0002](docs/proposals/0002-the-road-to-1-0-revised.md), against a
  set of proposals from the project owner: traceability brought forward to
  here, Japanese and Chinese precision next, multi-turn consistency after that,
  and a fail-closed stance and CI linter before 1.0. A `mamori.yml` is declined
  and [ADR 0012](docs/adr/0012-configuration-without-a-format.md) says why;
  Markdown and JSON structure preservation was investigated and found to be
  largely unnecessary already.

## [0.11.0] - 2026-08-29

Surrogate values: `山田一郎` instead of `<PERSON_001>`, off by default. On the
roadmap since 0.4 and deferred four times, because it is an answer-quality
feature and everything above it was a correctness one.

### Added

- **Surrogates, as a policy option.** Some models reason visibly worse about a
  page of tokens -- they lose track of who is who, they occasionally refuse to
  draft a reply *to* a placeholder, and they sometimes describe the token
  instead of using it. A readable value usually gets a better answer.

  ```json
  {"surrogates": ["PERSON", "EMAIL", "PHONE"]}
  ```

  ```text
  you wrote   Dear Jane Doe, reach me at jane.doe@example.com or 415-555-0198.
  sent        Dear Alex Rivera, reach me at a.person@example.com or 415-555-0142.
  restored    Dear Jane Doe, reach me at jane.doe@example.com or 415-555-0198.
  ```

  See [ADR 0026](docs/adr/0026-surrogates-trade-obviousness-for-readability.md).

- **Reserved ranges wherever any exist.** Emails use `example.com` and
  `example.org` (RFC 2606), addresses use the TEST-NET blocks of RFC 5737,
  telephone numbers use the ranges kept aside for fiction. A structured
  surrogate that escapes is not only harmless but identifiable: somebody who
  finds `192.0.2.10` in a log can look it up and learn it means nothing
  anywhere. Each pool records why it is safe, and `mamori privacy` prints it --
  "reserved for documentation" and "a plausible name we invented" are very
  different promises.

- **`mamori demo --scenario surrogates`**, which shows the trade including the
  failure, not just the happy path.

### The reason it is off by default

**An unrestored placeholder is obvious. An unrestored surrogate is not.**
Somebody reading `<PERSON_001>さんへ` knows at once that something did not
finish; somebody reading `山田一郎さんへ` reads a sentence about a person and
has no way to tell it is the wrong one.

Restoration loses its tolerance, and that cannot be avoided. A placeholder is
recognised by shape, so the restorer copes with `PERSON_001`, `<person_001>`
and `＜PERSON_001＞`. A surrogate is a name: it matches exactly or it does not.

What mamori can do is say so. `RestorationResult.missing` lists every mapping
that did not come back, so the failure is detectable even when it is not
visible. `mamori privacy` warns whenever surrogates are on -- twice when an
invented pool is in use -- with a non-zero exit status, so a deployment check
can fail on it.

**Nothing is reserved for personal names**, and no design fixes that. It is
stated in the module, in the report, in the demo and in all three READMEs.

### Design notes

- **Chosen by allocation order, never derived from the value.** Hashing the
  original would be tidier and would open a correlation channel: the same real
  person would get the same fake name in every document, so an observer holding
  two protected documents could tell they concern the same individual. Order is
  what keeps a surrogate from carrying information about what it replaced.

- **A surrogate never collides with the text it enters.** If the pool's choice
  already appears in the document, the next one is used -- restoring the wrong
  occurrence would corrupt the caller's own words, which is the one hazard here
  that would do damage rather than merely fail.

- **An exhausted pool falls back to a placeholder**, which is always safe.

- **No pool covers a credential.** There is no plausible stand-in for a
  password, and credentials are blocked rather than substituted anyway.

- `Mapping` gains `surface`, empty for every mapping mamori makes by default.
  It is excluded from `repr` alongside the original value: a surrogate is not
  sensitive, but the *pair* is exactly the lookup table this library exists to
  keep off other machines.

## [0.10.0] - 2026-08-29

A demo you can actually run, a guide to measuring mamori on your own text, and
a bug in the measurement harness that had been quietly corrupting the model-tier
numbers since 0.7.0.

### Added

- **`mamori demo`, rebuilt.** Five short scenarios, each answering a question
  somebody actually has: what the model sees and whether you get your words
  back, what happens when a placeholder arrives split across streamed chunks,
  whether any of this survives a document rather than a sentence, what to do
  when it gets one wrong, and what happens when there is a password in the
  text.

  ```bash
  mamori demo                      # the tour
  mamori demo --file draft.txt     # on your own text
  mamori demo --scenario stream
  ```

  The round trip now names **what found each value** -- the rule set and its
  confidence -- so "why was this replaced?" has an answer.

- **`mamori demo --live`** sends the protected text to a model you name and
  restores the answer. The whole round trip, nothing simulated:

  ```bash
  mamori demo --live --model llama3.1:8b --api http://localhost:11434/v1/
  ```

  Any OpenAI-compatible endpoint, and `--api-key-env` for a hosted one. The
  trust boundary deliberately does not apply: it refuses an external
  *detector*, which sees text before it is protected, and this is the service
  you chose, which sees protected text only.

- **[docs/measuring-your-own-data.md](docs/measuring-your-own-data.md)**, which
  the 0.9 plan owed. How to build a labelled dataset, what to put in it
  (documents, not sentences), how to compare two configurations -- and, first,
  the warning that such a file is full of your real data and belongs in
  `.gitignore` before it exists.

- **A password written in prose is now detected.** `password: hunter2spring`
  was caught and `the password is hunter2spring` was not, in all three
  languages -- and prose is how somebody pastes a credential into a chat
  window. A validator keeps "my password is fine" from blocking a request:
  a prose match needs a digit, a capital, a symbol, or length no ordinary word
  reaches. A short all-lowercase password is missed by this, which is the right
  way round.

### Fixed

- **The evaluation harness left the co-occurrence pass out of every cached
  model run.** `mamori eval --cache` rebuilt the detection pipeline by hand,
  and `build_pipeline` defaults co-occurrence to off while
  `MamoriConfig.detectors()` passes one in. So the model was scored against a
  baseline that had a pass the candidate lacked, from 0.7.0 onwards.

  Found by a result that could not be true: adding a model *increased* the leak
  rate on a document, and three propagated detections had vanished. The
  regression check written in 0.7.0 -- "for a candidate that only adds, this
  must be empty, and it is worth checking rather than assuming" -- caught the
  harness rather than the library.

  Fixed by deleting the second assembly path, not by correcting it.
  `MamoriConfig.detectors(provider=...)` substitutes the provider and leaves
  everything else alone, so there is one place that knows how a pipeline is
  built. A test pins that co-occurrence survives the substitution.

  **The published conclusions survived re-measurement** -- at 8B the model
  raises English recall and does nothing for Japanese -- but the over-redaction
  figures moved and the comparison was not sound when it was published.
  `SECURITY.md` and the READMEs carry the corrected table and say why.

- **A measurement where every model call failed reported a clean zero delta.**
  A 12B model timed out on every request; the pass degraded to nothing exactly
  as designed, the comparison measured the rules against themselves, and the
  output said `+0.00%` on every line -- which reads as "the model had nothing
  to add", a conclusion it had not earned. `mamori eval` now counts provider
  failures and refuses to exit clean:

  ```text
  WARNING: the model failed on 4 of 4 request(s).
  A model that never answers produces exactly the numbers above.
  ```

### Changed

- **The open question from 0.7 is still open, and now has a reason.** Whether a
  model above 8B changes the model-tier table could not be measured here:
  `gemma4:12b` times out on this hardware, and a run of 49 samples does not
  complete. That is not evidence about the model, only about the machine, and
  it is recorded as such rather than as a result.

## [0.9.0] - 2026-08-29

Every quality number this project published came from 123 samples with a median
length of 28 to 44 characters. mamori is for documents. This release measures
it at the length people actually send things, and the rules did not survive
first contact.

### Added

- **`en-docs`, `ja-docs`, `zh-docs`: business documents at real length.** Reply
  chains with quoted blocks, meeting minutes with attendee lists, support
  tickets with log excerpts, a CV, a contract extract, a technical note with
  almost nothing to protect, and a document with an instruction to a model
  buried in it. The core sets are unchanged -- they are good regression guards
  and cheap to run -- and the floors now cover all six. See
  [ADR 0025](docs/adr/0025-measure-at-the-length-people-send.md).

- **An anchored katakana name rule**, at the *core* tier: a middle dot, an
  honorific, or a label. `ジョンさん` was not detected by any rule before this
  release, while `ホスト` was reported as a person.

- **A project name after `プロジェクト` without a colon**, which is how it is
  written in a heading.

### Fixed

Four detection bugs, every one of them invisible at 44 characters and serious
in prose:

- **A name spanned a blank line.** The wide English name rule joined its words
  with `\s+`, so a heading and the first word of the next paragraph became
  `Headcount\n\nOne` -- a person. Every document with headings in it.

- **A legal suffix read as a surname.** `Umbrella Ltd` matched the wide name
  rule and `Where Umbrella Ltd` matched it more widely still, so the anchored
  company rule lost the span to a shape guess: the value was protected under
  the wrong type, with the wrong placeholder, under a different policy
  category, and an ordinary word was redacted with it.

- **An address at the end of a sentence was missed.** The internal-IP rule
  refused any trailing dot, to avoid matching the first four parts of
  `1.2.3.4.5`. A full stop is also a trailing dot, so `on 10.0.4.31.` found
  nothing. An address is never followed by a full stop in a one-line sample and
  usually is in a document.

- **The Japanese wide name rule reported 37 loanwords as people** across eight
  documents -- ホスト, プール, ゲートウェイ, ノード, エンジニア -- and not one
  true positive the anchored rules did not already have. It was filtered by a
  stoplist whose own comment admitted it "will never be complete".

  It was fixed by deleting the rule, not by extending the list. Japanese
  business writing coins loanwords faster than anybody maintains a list, so
  such a list encodes one author's vocabulary and is wrong for the next
  document. **A bare katakana run is not weak evidence of a name; it is no
  evidence of one, and the wide tier is for weak evidence rather than for
  none.**

- **The proxy answered an unknown path without reading the request body**, so a
  client that sent one could see a reset connection instead of the 404 it was
  given.

### Changed

- **Nothing regressed and the fragment sets improved too:**

  | recall-first | leak | over-redaction | precision |
  |---|---|---|---|
  | `en-core` | 0.67% (unchanged) | 1.44% -> **0.78%** | 0.938 -> **0.979** |
  | `ja-core` | 0.00% (unchanged) | 3.11% -> **2.42%** | 0.908 -> **0.937** |
  | `ja-docs` | -- | 6.08% -> **1.06%** | 0.600 -> **0.934** |

- **Documents leak several times more than fragments, and it is published.** At
  the default stance `en-docs` leaks 3.55% against `en-core` at 0.67%, and
  `zh-docs` 6.11% against `zh-core` at 0.00%. The old figures were not wrong;
  read alone they described the library at its easiest.

- **At the balanced stance, `en-docs` leaks 20.29%** -- a fifth of the
  sensitive characters, because a document is full of names with nothing
  anchored beside them. It is pinned as a floor so it stays visible rather than
  being discovered by somebody's deployment, and it is the strongest evidence
  this project has for why recall-first is the default.

- The quality floors are keyed by dataset rather than by locale, and there are
  twelve. A rule change that helps sentences and hurts documents turns the
  build red, which nothing could do before.

## [0.8.0] - 2026-08-29

The operator gets the last word. Until now everything mamori did was decided by
mamori, and somebody watching `Dear Monday,` become a `<PERSON_001>` had no
recourse short of forking the rule set.

Borrowed, with thanks, from the sibling
[kiseki](https://github.com/Nananananana/kiseki) project's ADR-0044.

### Added

- **Corrections: an append-only log of values you have ruled on.**

  ```bash
  mamori correct Monday --never --note "a weekday, not a name"
  mamori correct Acme   --always COMPANY_NAME --note "trading name, no suffix"
  mamori corrections
  ```

  The latest word about a value wins, so undo is another correction and nothing
  is ever deleted. Applied at read time: nothing rewrites a rule, nothing edits
  a prompt, and removing the log restores exactly the previous behaviour. See
  [ADR 0024](docs/adr/0024-corrections-are-appended-applied-at-read.md).

  `--always` closes, for one organisation's data, a gap no pattern can close in
  general: a trading name with no legal suffix (`Acme`, `田中商事`), documented
  since 0.1.0. It carries `CERTAIN` confidence -- a rule is a guess about a
  shape and a model is a guess about a sentence, and an operator typing a value
  into a log is neither -- and adds only what nothing else already covers.

- **`--never` is the only thing in mamori that reduces what it protects**, so
  the exception is kept narrow. Every exclusion is named by `mamori privacy`
  and reported as a warning with a non-zero exit status, so a deployment check
  can fail on one nobody meant to ship.

- **A credential can never be ruled away.** Enforced in three independent
  places, because one is not enough: the domain refuses an exclusion naming a
  credential type; `CorrectionLog.excludes` refuses to apply one at read time
  whatever a hand-edited file says; and `mamori correct` runs the value through
  the detectors **before writing anything**. That last one exists because a
  `never` ruling names no type at all, and because appending first would leave
  the credential sitting in a file on disk -- the outcome this library exists
  to avoid.

- **`docs/proposals/`**, starting with
  [the road to 1.0](docs/proposals/0001-the-road-to-1-0.md). ADRs record
  decisions already made; a plan is neither, and a roadmap in a README is a
  list without its reasoning. The roadmap is revised there in light of what
  0.7 measured, and says what is deliberately *not* planned.

- **A promises test that a command which reads writes nothing.** `kiseki`'s
  ADR-0070 found a command in that project quietly keeping a snapshot every
  time somebody ran it to look at something, and no test caught it. Ten mamori
  commands are now checked for leaving the working directory untouched and for
  being safe to run twice. All of them already were; the point is that they
  stay that way.

### Changed

- `MamoriConfig` gains `corrections`, accepting either a path to a log or the
  entries themselves. A path is a log somebody appends to; entries in the
  settings are rulings that travel with the configuration and get reviewed
  alongside it.

- `PrivacySession` and `ProtectionService` accept a `CorrectionLog`. Exclusions
  are applied *before* overlap resolution, not after: a corrected-away value
  that could first win a span and then vanish would leave a hole where a real
  detection would have been.

### Fixed

- `MamoriConfig.from_mapping` silently dropped any key without an explicit
  converter, which is how the new `corrections` setting did nothing the first
  time it was tried. Found immediately, and worth recording: this is the exact
  failure the module's "unknown keys are refused rather than ignored" rule
  exists to prevent, arriving from the other direction.

## [0.7.0] - 2026-08-29

The model tier gets measured for the first time, and the numbers say it was
not doing what the documentation claimed. Both are fixed here: the contract
that was throwing its answers away, and the paragraph that described an
intention as a result.

### Fixed

- **A model reports values now, not character offsets.** Asked for offsets
  against 49 English samples, a local 8B model got **0 of 52 right** -- while
  51 of those 52 values were genuinely in the document, most off by a handful
  of characters. `'John Smith' said 4..13, actually 4..14`. The verification
  step then discarded them all, correctly and uselessly, which means **the
  model tier contributed essentially nothing from 0.4.0 through 0.6.0**.

  Character offsets are close to the one thing a tokeniser-based model cannot
  produce. The value is now the answer and mamori locates it -- at every
  occurrence, on word boundaries where the script has them. Offsets are still
  honoured when volunteered and already correct, which keeps the one case a
  search cannot resolve: the same value twice, only one meant.

  The guarantee is unchanged and stronger: mamori never creates a span it did
  not locate itself, so a hallucinated value is still dropped. See
  [ADR 0022](docs/adr/0022-a-model-reports-values-not-offsets.md).

  Measured effect at the balanced stance: English leak rate 2.01% to **0.67%**,
  closing `en-006`, the unanchored name that has been a documented gap since
  0.1.0.

- **`OTHER_SENSITIVE` was being used as a dustbin.** Every English false
  positive was that type -- a weekday, a public IP, an error code, a whole
  sentence about revenue. The default policy *blocks* it, so those would have
  stopped requests rather than replaced a value. A guidance rule saying what
  the type is for, what it is not for, and that it stops the request halved
  over-redaction from 8.80% to 4.43%.

- **`mamori eval` honoured no configuration.** It built a rules-only pipeline
  and ignored `--config` entirely, so the harness that existed since 0.2.0 had
  never been pointed at the thing it was most needed for.

### Added

- **`mamori eval --compare`** scores the rules alone alongside the configured
  run and prints the delta, naming the individual samples that changed. An
  aggregate says something moved; the list says what, and whether you believe
  it. Tuning against an aggregate fits a prompt to a number instead of to a
  language.

- **`mamori eval --cache`** remembers what the model answered, keyed on the
  model *and the prompt*, so re-running is free and rewriting one line of
  guidance invalidates exactly the answers that depended on the old wording.
  **It writes to disk**, which is why it lives in the evaluation package,
  is named by no configuration key, and has a test in `test_promises.py`
  pinning that -- the storage claim in `mamori privacy` stays true for every
  configuration a user can express.

- **`mamori eval --replay`** answers only from the cache, so a change to
  scoring can be checked without the model's variance in the way.

- **`domain/occurrences.py`**, shared with the co-occurrence pass, which was
  already locating known values for the same reason.

### Changed

- **The documentation says what was measured.** The README claimed the model
  tier reached "an English name in running prose, a Chinese given name, a
  codename". Measured, at 8B: it reaches the English name. It does nothing for
  Chinese, where the rules were already at 1.000 recall, and nothing for
  Japanese, while costing over-redaction in all three. At the recall-first
  default it does not move the leak rate at all and costs roughly six times the
  over-redaction. See [ADR 0023](docs/adr/0023-the-model-tier-is-measured.md).

  | balanced, `llama3.1:8b` | leak: rules -> +model | over-redaction | precision |
  |---|---|---|---|
  | `en-core` | 2.01% -> **0.67%** | 0.66% -> 4.43% | 1.000 -> 0.855 |
  | `ja-core` | 0.71% -> 0.71% | 0.00% -> 5.41% | 1.000 -> 0.868 |
  | `zh-core` | 0.00% -> 0.00% | 2.55% -> 10.18% | 0.964 -> 0.871 |

- **One model proposal can produce several detections**, since a value judged
  sensitive is sensitive wherever it appears. A behaviour change for anyone
  counting entities.

- The CI quality floors stay rules-only. Pinning one to a model's output would
  make the build depend on a model being installed and on it answering the same
  way twice.

## [0.6.0] - 2026-08-29

The proxy, and the machinery that says what it does. An application that
already talks to an OpenAI-compatible API now moves behind mamori by changing
one string -- and the privacy claims that makes reasonable are answerable from
the command line and checked by the test suite.

Several ideas in this release are borrowed, with thanks, from the sibling
[kiseki](https://github.com/Nananananana/kiseki) project.

### Added

- **`mamori serve`: an OpenAI-compatible proxy.** Point an existing
  application at it and change nothing else. Every message is protected on the
  way out, the reply is restored on the way back, and the briefing telling the
  model to leave placeholders alone is prepended automatically. See
  [ADR 0018](docs/adr/0018-a-proxy-on-the-standard-library.md).

  ```bash
  mamori serve --upstream https://api.openai.com/v1/
  ```

  Built on `http.server`, so the runtime dependencies stay zero. It binds to
  127.0.0.1 -- reaching it from another machine is a deliberate act and a
  warning at startup, because anything that can reach the port can send
  documents through it. Streaming is supported: a placeholder arriving as
  `<PER`, `SON_0`, `01>` is held and restored as it passes. The system prompt
  is protected too, since an organisation's briefing is exactly the context
  that should stay local. One mapping scope per request, discarded with it.

  It fails closed. A blocked credential, an unparsable body, or a path it does
  not recognise are errors returned to the caller, and none of them forward
  anything.

- **`mamori privacy`: what your configuration actually does.** Computed from
  the settings in front of it, not from the README -- which types are blocked
  and which are pseudonymized, where a detection model is and whether the trust
  boundary admits it, what is kept and where. Anything that widens exposure is
  a warning and a non-zero exit status. See
  [ADR 0019](docs/adr/0019-privacy-is-a-report-not-a-promise.md).

  It separates what is measured from what is true by construction from what
  mamori cannot check for you, and prints, beside each construction claim, the
  name of the test that fails if it stops being true.

- **`tests/test_promises.py`: those tests.** `socket.connect` and its
  neighbours are replaced with functions that raise, and the whole default path
  then has to run without them -- protection, restoration, every language pack,
  the evaluation harness, the command line, importing the package. A future
  dependency that dials out fails in a build rather than in a deployment. The
  guard has its own test that it can still trip. Mappings staying in memory,
  values staying out of diagnostics, scope-bound restoration, keys never in
  configuration, and the model-only-adds bound are each a class. A final class
  checks that every claim in the report names a test that exists. See
  [ADR 0020](docs/adr/0020-the-promises-are-checked-by-machine.md).

- **Optional batching on the provider port.** `BatchLLMProvider` is advertised
  by implementing it, the same shape as `supports_structured_output`. A shared
  model on another machine is dominated by round trips, and the windows of one
  document should not cost ten of them. Nothing existing changes.

### Changed

- **A long document is scanned in overlapping windows instead of being
  skipped.** This was a recall hole with a length threshold on it: over the
  limit, the model pass silently returned nothing, so the documents most likely
  to hold a name no rule can anchor -- a long thread, a contract, a transcript
  -- got patterns only, with nothing in the output to say so. Windows overlap
  by 400 characters, comfortably more than any entity this library detects, so
  an address cut by one boundary is whole inside its neighbour; cuts prefer a
  paragraph or sentence boundary, in the CJK forms as well as the ASCII ones.
  See [ADR 0021](docs/adr/0021-a-long-document-is-windowed.md).

  The offset arithmetic lives in one place in the domain layer, because a
  detection at position 12 of the third window is not at position 12 of the
  document and getting that wrong would cut characters out of the wrong
  sentence. Both of its properties -- every character appears in some window,
  every window is a real slice of the document -- are tested with Hypothesis
  over arbitrary text.

- **`Upstream` joins its base URL the way an OpenAI client does.** The path
  appended is relative to a base URL that already ends at the version segment,
  so `http://localhost:11434/v1/` no longer becomes `/v1/v1/`. A base URL with
  no path at all gets `/v1` added rather than producing a 404 for the caller to
  work out.

- **The `MAMORI_` prefix note now appears in `mamori privacy` too**, alongside
  everything else about where a key may live.

- **The privacy report describes a configuration it cannot build.** Counting
  the detectors is also what refuses an endpoint outside the trust boundary, so
  the report used to raise on exactly the settings somebody would run it to
  understand. It now reports the refusal as a warning and says the detector
  count is unknown rather than guessing one.

### Fixed

- A document over `max_input_characters` is no longer silently unscanned by the
  model tier. See above; this is the substance of the release for anybody who
  runs a model.

## [0.5.0] - 2026-08-29

The model tier stops assuming a laptop. Where the model runs, and which library
talks to it, are both configuration now -- and the layering that keeps all of
this from tangling is enforced by a test instead of a diagram.

### Added

- **A trust boundary, replacing the localhost check.** The realistic deployment
  is one high-specification machine the team shares, not a model on every
  laptop, and 0.4.0 made that impossible. A host is now classified by
  inspection -- `loopback`, `private`, `declared`, `external` -- and a boundary
  decides what is admitted. The default, `private_network`, accepts a model on
  this machine *and* a model at `http://llm01.corp:8000/v1/`, and refuses a
  public API. See
  [ADR 0015](docs/adr/0015-a-trust-boundary-not-a-localhost-check.md).

  ```json
  {"llm": {"model": "qwen2.5:72b", "base_url": "http://llm01.corp:8000/v1/"}}
  ```

  A refusal arrives when the provider is built, not on the first document, and
  the message says what was classified and which of the two remedies applies.
  `trusted_hosts` names an exception; `"trust": "anywhere"` removes the check
  and is visible to anyone reviewing the config.

- **A provider registry, a callable provider, and `LLMEndpoint`.** Switching
  models is a field. Switching the *client library* is one line, and adds no
  dependency here: `CallableProvider(fn)` wraps anything already loaded in the
  process, and `register_llm_provider(name, factory)` makes an alternative
  selectable from configuration. The bundled OpenAI-compatible provider still
  speaks `urllib`, so the runtime dependencies remain zero. See
  [ADR 0016](docs/adr/0016-the-model-and-the-client-are-both-replaceable.md).

- **`mamori llm`** -- where the model is, whether the boundary admits it, and
  with `--check`, whether it answers. Worth running once after pointing it at a
  machine down the hall. `mamori config` now shows the model too.

- **`LLMSettings`, and `MamoriConfig.session()`.** Settings assemble a session;
  a session never reads settings. A literal `api_key` in a config file is
  refused with a pointer to `api_key_env`, so a key cannot arrive by being
  committed.

- **Retries with backoff** on transient endpoint failures (408, 425, 429, and
  5xx). Deliberately not conditional on the endpoint being remote: a model on
  this machine is just as capable of being busy loading weights.

- **`tests/test_architecture.py`** -- the layer rules parsed out of the source
  with `ast` and asserted. Domain purity against a standard-library allowlist,
  an explicit table of permitted imports per layer, no cycles, and the one
  default-construction exception pinned to the file and symbols it covers. See
  [ADR 0017](docs/adr/0017-the-layering-is-a-test.md).

- **Tolerated spans in the evaluation format.** `[[?TYPE:value]]` marks a span
  as neither required nor wrong. Ten bare digits are an order number to the
  anchored rules and a possible phone number to the wide ones; scoring the wide
  reading as a mistake charged the recall-first stance for doing its job.

### Changed

- **Over-redaction figures fell by roughly half, with no rule changing.** The
  earlier numbers were an artefact of datasets written for the balanced stance.
  What the recall-first default actually costs:

  | | leak rate | over-redaction (was) |
  |---|---|---|
  | `ja-core` | 0.00% | **3.11%** (6.34%) |
  | `en-core` | 0.67% | **1.44%** (2.95%) |
  | `zh-core` | 0.00% | **4.00%** (11.71%) |

  Entity precision rose with it: `ja` 0.868 to 0.908, `en` 0.900 to 0.938, `zh`
  0.844 to 0.900. The quality floors were tightened to match.

- **`PrivacySession` no longer takes `config=`.** The architecture test found
  it: the application layer was reaching through configuration to every adapter
  in the project. Build a session from settings with `MamoriConfig.session()`,
  which is the direction the dependency was always supposed to run.

- **`OpenAICompatibleProvider` takes an `LLMEndpoint`** rather than loose
  keyword arguments, and gained `health_check()`. Errors still never repeat the
  prompt, the answer, or the server's response body.

- **`MAMORI_*` is reserved for settings, and the error now says so.** An unknown
  one is still refused -- that is what catches a misspelled privacy variable --
  but the message no longer leaves a reader wondering why their API key
  variable broke the CLI. The value is never echoed.

### Fixed

- The `docs/architecture.md` layer table now matches what the code does, and a
  test fails if it stops matching again.

## [0.4.0] - 2026-08-29

Two themes: lean harder towards catching everything, and build the prompt layer
the model tier will run on.

### Added

- **A recall-first stance, and it is the default.** Every rule now declares a
  tier -- `CORE` (anchored on a checksum, a prefix, an honorific, a label) or
  `WIDE` (shape alone) -- and the stance decides which run. See
  [ADR 0013](docs/adr/0013-recall-first-by-default.md).

  | | leak rate balanced | recall-first | over-redaction balanced | recall-first |
  |---|---|---|---|---|
  | `ja-core` | 0.71% | **0.00%** | 0.00% | 6.34% |
  | `en-core` | 2.01% | **0.67%** | 0.65% | 2.95% |
  | `zh-core` | 0.00% | **0.00%** | 2.34% | 11.71% |

  Wide rules close the documented gaps that could only be closed by accepting
  false positives: an unanchored English name, an unseparated phone number, a
  credential with no vendor prefix, a postal code with no marker. They are
  `LOW` confidence, so `min_confidence` switches them off without changing
  stance. The stance changes no security decision; it only proposes more.
- **A prompt architecture.** Guidance is a shared, addressable knowledge base
  carrying what the regex work taught -- that an honorific fixes the right edge
  of a Japanese name, that 森林 is a forest, that an English name in prose has
  no anchor. A prompt is a document of named sections plus selected guidance,
  rendered deterministically with a fingerprint. See
  [ADR 0014](docs/adr/0014-prompts-are-documents.md).
- **Prompt overlays**, so an organisation adds its own rules and drops what does
  not fit without forking anything:

  ```json
  {"prompts": {"detection": {
    "disable": ["en.person.unanchored"],
    "add": [{"id": "acme.case", "text": "Case numbers look like ACME-12345."}]
  }}}
  ```

  A disable that matches nothing is refused, and refused when the config is
  built rather than months later.
- **`session.external_system_prompt()`** -- what to tell the *service* model
  about the placeholders. Needs no local model and pays for itself immediately:
  every placeholder returned intact is one restoration does not have to recover
  from a mangled form.
- **`LLMProvider` port and `LLMDetectionPass`**, the tier that reaches what
  shape cannot. It only ever adds, its output is checked against the text so a
  hallucinated span is dropped, and a failing model degrades the detector rather
  than stopping the request. `require_model=True` inverts the last one.
- **`OpenAICompatibleProvider`**, for Ollama, llama.cpp, vLLM and LM Studio,
  written against `urllib` so the library still has no runtime dependencies. It
  refuses a non-local URL: the text reaches a detector *before* it is protected.
- **`mamori prompt`** shows exactly what would be sent, with version and
  fingerprint; `--guidance` lists the ids so they can be disabled, marking which
  came from an overlay.
- `--stance` on `inspect`, `protect`, `config` and `eval`, so the trade can be
  measured rather than assumed.
- `IDENTIFIER` and `OTHER_SENSITIVE` entity types, for a long digit run with no
  label and for a model saying "this matters and I cannot name it".

### Changed

- Quality floors are now per stance, and a new test asserts the property the
  default rests on: recall-first never leaks more than balanced.
- Rule-level tests pin the balanced stance, since they are specifications of
  individual core rules.

## [0.3.0] - 2026-08-29

Architecture: the last hardcoded stage of the pipeline became swappable, and
every switch moved onto one object.

### Added

- **Detection is a pipeline of passes.** A new `DetectionPass` port receives the
  text *and* what earlier passes found; `DetectionPipeline` runs passes in order
  and is itself a `Detector`, so nothing upstream changed. `DetectorPass` adapts
  an ordinary detector, which keeps the narrow contract the default. See
  [ADR 0011](docs/adr/0011-detection-as-a-pipeline.md).
- **Co-occurrence detection.** Once a value is confirmed above the seed
  threshold anywhere in a text, its other occurrences are found too. This is the
  first thing the new port made possible and it is the largest recall gain
  available without a model:

  | | leak rate before | after |
  |---|---|---|
  | `en-core` | 7.37% | **2.01%** |
  | `ja-core` | 1.43% | **0.71%** |
  | `zh-core` | 1.49% | **0.00%** |

  Precision and over-redaction are unchanged. Word boundaries are respected in
  Latin text, so seeding on `Ann` does not match inside `Announcement`.
- **`MamoriConfig`**, holding every switch, with no opinion about file formats.
  `from_mapping()` takes an already-parsed mapping so the caller keeps their
  parser; `from_env()` reads `MAMORI_*`; `load_config_file()` handles JSON
  everywhere and TOML from 3.11. Unknown keys are refused rather than ignored.
  See [ADR 0012](docs/adr/0012-configuration-without-a-format.md).
- **`PrivacyPolicy.min_confidence`**, a coverage/quality dial. Detections below
  it are discarded before anything else happens. Default `0.0`, and it stays
  there: reducing coverage is a decision, not an inherited default.
- **`mamori config`**, printing the effective settings and where the layers come
  from, plus `--config`, `--min-confidence` and `--no-co-occurrence` on
  `inspect` and `protect`.
- A conformance suite for `DetectionPass` in `tests/contracts.py`.

### Changed

- Quality floors raised across all three languages, following the co-occurrence
  gains. The old ones no longer defended anything.
- `PrivacySession` accepts `config=`; it supplies the defaults for every other
  argument, and an explicit argument still wins.

## [0.2.0] - 2026-08-29

### Added

- **Detector evaluation.** `mamori.evaluation` scores the detectors against
  labelled datasets, and `mamori eval` prints the result. Two metric families
  are reported: entity precision/recall/F1 per type, and the character-level
  pair that actually matters here — `leak_rate` (share of labelled sensitive
  characters no detection covered) and `over_redaction_rate` (share of ordinary
  text replaced anyway). See
  [ADR 0009](docs/adr/0009-measure-leaked-characters.md).
- **Labelled datasets** for Japanese, English and Chinese, shipped with the
  package. Samples are authored with inline `[[TYPE:value]]` markup and the
  loader computes the offsets, so nobody counts characters by hand. Labels
  record what a human redactor would remove, including cases the rules are
  known to miss; each of those carries a note saying why.
- **Quality floors in CI** (`tests/test_detection_quality.py`), so a rule change
  that improves one language and quietly wrecks another turns the build red.
- **Streaming restoration.** `session.stream_restore()` restores a response as
  it arrives, holding back only the shortest suffix that further input could
  still turn into a placeholder. For any chunking it emits exactly what
  `restore()` emits for the whole response — a Hypothesis property, not an
  aspiration. See [ADR 0010](docs/adr/0010-streaming-restoration.md).
- **Port conformance suites** (`tests/contracts.py`). A new `Detector` or
  `MappingStore` subclasses the matching mixin and inherits the contract instead
  of guessing at it.

### Fixed

Five bugs, all found by the new datasets within an hour of writing them, and all
producing wrong output on plausible input:

- The Japanese address rule stopped at the first hyphen, so
  `東京都千代田区千代田1-1` was replaced as far as `...千代田1` and the rest was
  sent on.
- The Japanese surname rule swallowed the honorific: `佐藤花子様` came back as a
  four-character name ending in `様`.
- `INTERNAL_URL` and `DATABASE_URL` matched anything up to whitespace, so a link
  followed by Japanese text took the sentence with it.
- `DATE_OF_BIRTH` captured a trailing space when the closing `日` was absent.
- A Japanese company name ran into the following clause
  (`有限会社みどりから見積`); the tempered character class now stops on
  multi-character particles as well as single ones.

### Added -- language packs

- **English and Chinese detection**, alongside Japanese. Rules are grouped into
  language packs and a pack runs when the text gives a reason to run it; all of
  them are enabled by default. See
  [ADR 0008](docs/adr/0008-language-packs.md).
  - English: NANP and UK phone numbers, SSN with range validation, ZIP+4, UK
    postcodes, street addresses, legal-suffix company names, labelled employee
    IDs and project codes, and personal names anchored on a title, salutation,
    sign-off or label.
  - Chinese: mainland mobile and landline numbers, 居民身份证 with its ISO 7064
    MOD 11-2 check character, labelled postcodes, addresses from province to
    street number, company suffixes, labelled employee IDs and project codes,
    and personal names anchored on a surname.
- `Script` and `scripts_in`, and `AdaptiveLocaleDetector` on top of them: the
  Chinese pack stands down when the text contains kana, because kana appear in
  Japanese and never in Chinese. Han-only text runs both CJK packs and
  over-detects, which is the safe direction.
- `PrivacySession(locales=[...])`, the `--locale/-l` flag on `inspect` and
  `protect`, and a `mamori locales` command showing each pack and when it runs.
- `register_locale`, for adding a language without touching the library.
- `SSN` and `RESIDENT_ID` entity types. National identifiers keep their local
  names rather than collapsing into one `NATIONAL_ID`: each has its own format
  and its own checksum.
- Stopword lists for the Japanese and Chinese surname rules, so 森林 and 高兴
  are no longer read as people.

### Changed

- Language-independent rules moved to `UNIVERSAL_RULES` and now run whatever the
  text looks like; `DEFAULT_RULES` and `NAME_RULES` are gone.
- The detector name recorded on an entity is now the pack code (`ja`, `en`,
  `zh`) or `universal`, so a report says which language's rules fired.
- The CLI moved under `src/mamori/interfaces/`, matching the prescribed layout.

## [0.1.0] - 2026-08-29

First release. The core round trip works end to end, in memory, with no
dependencies outside the standard library.

### Added

- `PrivacySession` — conversation-scoped `protect` / `restore`. The same value
  keeps the same placeholder for the life of the session, so a multi-turn
  conversation stays coherent and a response in turn five can be restored with
  a value from turn one.
- Offset-preserving NFKC normalization, so full-width Japanese text matches the
  same rules as its half-width form while replacement still happens in the
  original string.
- Pattern detectors for email, Japanese phone numbers, postal codes and
  addresses, dates of birth, credit cards (Luhn), Individual Numbers
  (check digit), vendor-prefixed API keys and tokens, PEM private keys,
  database URLs, keyword-assigned passwords, private IPs, internal URLs,
  Japanese and English company names, employee IDs and project codes.
- Japanese personal-name detection, honorific-anchored and surname-dictionary
  anchored, with rejection of organisation and place suffixes.
- `PrivacyPolicy` with `ALLOW` / `ANONYMIZE` / `MASK` / `BLOCK`, resolved by
  type, then category, then a fail-closed default. Credentials are blocked
  rather than pseudonymized.
- Deterministic overlap resolution: widest span first, then severity,
  confidence and offset.
- Tamper-tolerant restoration, recovering `PERSON_001`, `<PERSON_1>`,
  `<person_001>`, `[PERSON_001]` and `＜PERSON_001＞`, while resolving only
  identities allocated in the same scope.
- Placeholder-shaped text in the *input* is itself re-mapped, so it cannot
  collide with a real placeholder during restoration.
- `InMemoryMappingStore`, the default. Nothing is written to disk unless asked.
- CLI: `inspect`, `protect`, `restore`, `policy`, `demo`.
- Optional plaintext mapping export for a two-process round trip, which warns
  every time it is used.

### Security

- Original values are excluded from every `repr`, so tracebacks and log lines
  that format the objects show types and offsets only.
- Exception messages carry entity types and offsets, never values.
- The library emits no log records.
- A detector that raises stops the request; no partial protected text is ever
  produced.
- Restoration resolves only placeholders allocated in the calling scope, so a
  response cannot read values out of the mapping table by guessing.

[Unreleased]: https://github.com/Nananananana/mamori/compare/v0.27.0...HEAD
[0.27.0]: https://github.com/Nananananana/mamori/compare/v0.26.0...v0.27.0
[0.26.0]: https://github.com/Nananananana/mamori/compare/v0.25.0...v0.26.0
[0.25.0]: https://github.com/Nananananana/mamori/compare/v0.24.0...v0.25.0
[0.24.0]: https://github.com/Nananananana/mamori/compare/v0.23.0...v0.24.0
[0.23.0]: https://github.com/Nananananana/mamori/compare/v0.22.0...v0.23.0
[0.22.0]: https://github.com/Nananananana/mamori/compare/v0.21.0...v0.22.0
[0.21.0]: https://github.com/Nananananana/mamori/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/Nananananana/mamori/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/Nananananana/mamori/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/Nananananana/mamori/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/Nananananana/mamori/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/Nananananana/mamori/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/Nananananana/mamori/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/Nananananana/mamori/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/Nananananana/mamori/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/Nananananana/mamori/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/Nananananana/mamori/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/Nananananana/mamori/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/Nananananana/mamori/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/Nananananana/mamori/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Nananananana/mamori/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Nananananana/mamori/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Nananananana/mamori/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Nananananana/mamori/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Nananananana/mamori/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Nananananana/mamori/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Nananananana/mamori/releases/tag/v0.1.0
