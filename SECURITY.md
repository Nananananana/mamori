# Security Policy

## Reporting a vulnerability

Please report security issues privately through
[GitHub Security Advisories](https://github.com/Nananananana/mamori/security/advisories/new)
rather than in a public issue.

Include what you did, what you expected, and what happened. If the issue is a
detection gap, a short example of text that slips through is the most useful
thing you can send. **Use invented data.** Do not send a real name, a real
address or a real key to demonstrate a bug in a privacy tool.

Expect an acknowledgement within a week. `mamori` is a young project maintained
in spare time; there is no paid response commitment and no bug bounty.

## What `mamori` is for

`mamori` reduces the chance that sensitive data reaches an external LLM when
somebody pastes real text into a prompt. It is a safety net for a mistake that
people make constantly and notice too late.

## What `mamori` does not do

This section is longer than the previous one on purpose. A privacy tool that is
trusted past its actual reach is worse than none at all, because it licenses
riskier behaviour than the behaviour it replaced.

### Detection is incomplete

The detectors are regular expressions, surname lists, and a pass that
propagates a value confirmed once to its other mentions. They are known to
miss:

Language-independent:

| Category | Known gaps |
|---|---|
| Secrets | Any credential without a recognisable vendor prefix, and any high-entropy string not written next to a keyword. Entropy-based detection is not implemented: it produces too many false positives on base64 payloads and hashes to be usable by default. |
| `PHONE` | Unseparated digit runs, which are deliberately not matched -- an order number looks identical. |
| Everything | Data that is only sensitive in context: a salary figure, an unreleased date, a headcount, who was in a meeting. |

Japanese (`ja`):

| Category | Known gaps |
|---|---|
| `PERSON` | Names with an uncommon surname and no honorific. Given names alone. Names inside compounds. Nicknames. Names written only in hiragana. |
| `ADDRESS` | Addresses with no prefecture. Building and room numbers written apart from the street. |
| `COMPANY_NAME` | Trading names with no legal suffix. Names containing の, which the rule truncates on purpose. Abbreviations and internal shorthand. |
| `PROJECT_NAME` | Internal codenames, which by construction look like ordinary words. |

English (`en`):

| Category | Known gaps |
|---|---|
| `PERSON` | **Any name not preceded by a title, salutation, sign-off or label.** Two capitalised words are also every product, city and department, so an unanchored rule would flag most of a business email. This is the largest single gap in the library. |
| `ADDRESS` | Addresses with no street type. Apartment and unit lines written separately. Non-US, non-UK formats. |
| `COMPANY_NAME` | Trading names with no legal suffix -- "the contract is with Acme" is not detected. |
| `SSN` | Nine bare digits, which are deliberately not matched without a label. |

Chinese (`zh`):

| Category | Known gaps |
|---|---|
| `PERSON` | Surnames outside the list. Also the reverse: a surname plus one or two characters is often an ordinary word, so this rule both misses names and invents them. It is `LOW` confidence for that reason. |
| `ADDRESS` | Addresses without a city or district marker. Traditional-character forms of the markers. |
| `POSTAL_CODE` | Six bare digits, which need a label to be matched at all. |
| Traditional Chinese | Rules keyed on characters use simplified forms. Identity numbers, phone numbers and email still match; company suffixes and surnames written only in traditional forms may not. |

Not covered at all: Korean, and every language with no pack. Universal rules
(email, credentials, card numbers, private addresses) still apply to text in
those languages; nothing else does.

### Checking it yourself

Two commands answer most of what this document asserts, against your own
configuration rather than the defaults described here:

```bash
mamori privacy
```

It reports what is detected, where text goes, what is kept, and -- separately
-- what is true however you configure it and what mamori cannot check for you.
Settings that widen exposure are warnings with a non-zero exit status.

Those construction claims are backed by `tests/test_promises.py`, which
replaces `socket.connect` with a function that raises and then runs the whole
default path. If a dependency ever starts contacting something, that suite
fails before a release does.

### What the numbers actually are

Detection is measured against bundled labelled datasets, at two scales. Run
`mamori eval` yourself; as of `0.18.0`, at the default recall-first stance:

| Set | Samples | Leak rate | Over-redaction | Entity P / R |
|---|---|---|---|---|
| `en-core` | 53 fragments | 0.62% | 0.71% | 0.980 / 0.980 |
| `ja-core` | 54 fragments | 0.00% | 2.44% | 0.955 / 1.000 |
| `zh-core` | 27 fragments | 0.00% | 2.94% | 0.875 / 1.000 |
| `en-docs` | 8 documents | **3.50%** | 0.90% | 0.946 / 0.883 |
| `ja-docs` | 8 documents | **0.33%** | 1.06% | 0.938 / 0.984 |
| `zh-docs` | 6 documents | **2.37%** | 1.12% | 0.900 / 0.978 |
| `en-context` | 2 packages | **6.31%** | 0.92% | 1.000 / 0.900 |
| `ja-context` | 2 packages | **0.00%** | 0.00% | 1.000 / 1.000 |
| `zh-context` | 1 package | **0.00%** | 0.53% | 0.889 / 1.000 |
| `en-agent` | 3 payloads | **0.00%** | 0.00% | 1.000 / 1.000 |
| `ja-agent` | 2 payloads | **0.00%** | 0.00% | 1.000 / 1.000 |
| `zh-agent` | 1 payload | **0.00%** | 0.00% | 1.000 / 1.000 |

A third corpus of a thousand generated documents across twelve genres is not
shipped -- it lives in the development repository, because the bundled sets are
the regression floor and that one is for finding bugs. It found five in its
first run, and four more in Chinese the run after that. See the 0.14.0 and
0.15.0 entries in `CHANGELOG.md`.

**The `-agent` rows are payloads rather than prose**: tool-call arguments and
tool definitions, where the label is a *key* rather than a word in a sentence.
They score perfectly because a key is a stronger anchor than any prose, which
is worth reading as "the rules read keys now" rather than as a claim about
agent payloads being easy -- before 0.18 the same rows would have been most of
the way to a total loss. See [ADR 0030](docs/adr/0030-a-tool-call-is-text.md).

**The `-context` rows are assembled prompts** -- what a retrieval layer or an
agent framework renders, rather than what a person typed. They leak more than
documents do at the balanced stance (46.85% against 20.02% in English) for a
reason worth stating: **selection strips anchors**. A passage chosen out of a
note arrives without the salutation, the signature block and the form label
that made its values detectable, because the anchor stayed behind in the part
that was not selected. See [ADR 0029](docs/adr/0029-a-prompt-nobody-typed.md).

**Read the document rows first.** The `-core` sets are sentence fragments with a
median length of 28 to 44 characters; the `-docs` sets are business documents at
the length people actually send. Documents leak several times more, because a
document is full of names with no anchor beside them. Every figure this project
published before `0.9.0` came from the fragment sets alone, which described
mamori at its easiest.

At `--stance balanced`, which runs only the anchored rules:

| Set | Leak rate | Over-redaction | Entity P / R |
|---|---|---|---|
| `en-core` | 1.93% | 0.00% | 1.000 / 0.960 |
| `ja-core` | 0.68% | 0.62% | 0.984 / 0.984 |
| `zh-core` | 0.00% | 1.63% | 0.933 / 1.000 |
| `en-docs` | **20.02%** | 0.03% | 1.000 / 0.700 |
| `ja-docs` | 0.33% | 0.18% | 0.968 / 0.984 |
| `zh-docs` | 2.37% | 0.40% | 0.957 / 0.978 |
| `en-context` | **46.85%** | 0.00% | 1.000 / 0.500 |
| `ja-context` | 0.00% | 0.00% | 1.000 / 1.000 |
| `zh-context` | 0.00% | 0.00% | 1.000 / 1.000 |

That 20.02% is not a typo. A fifth of the sensitive characters in an English
document have nothing anchored near them -- a name in an attendee list, a name
under a sign-off, a name after "Reported by:". It is the clearest reason the
recall-first stance is the default, and the clearest argument against turning it
off without measuring your own text first.

*Leak rate* is the share of labelled sensitive characters that no detection
covered — the part that would have left the machine. *Over-redaction* is the
share of ordinary characters replaced anyway.

**Read these as regression floors, not as a claim about your data.** The sets
are small and synthetic. They were written to cover the cases the rules are
meant to handle and the ones they are known to miss, which makes them good at
catching a change that breaks something and poor at estimating recall on a
corpus nobody has seen. A leak rate near zero on fifty invented
sentences says nothing about a real inbox.

The residual leak is one documented gap: a trading name with no legal suffix.

Two things closed the rest, and both cost something. A value confirmed once is
now protected everywhere it appears, which moved English from 7.4% to 2.0% at no
cost in precision. The recall-first stance then added rules that match on shape
alone, which took English to 0.67% and Japanese to zero and roughly doubled
over-redaction. **Read the two tables together.** A tool that redacts
everything has a perfect leak rate and destroys every answer.

The over-redaction figures fell in `0.5.0` without any rule changing. Some
labelled spans are genuinely ambiguous -- ten bare digits are an order number to
the anchored rules and a possible phone number to the wide ones -- and the
datasets previously scored the wide reading as a mistake. Those spans are now
marked *tolerated*: neither required nor wrong, excluded from both sides. The
earlier numbers charged the recall-first stance for doing exactly its job, and
overstated its cost by roughly half.

### The model tier, measured

Added in 0.4.0, measured for the first time in 0.7.0, and re-measured in 0.10.0
after a bug was found in the harness that produced those numbers. Balanced
stance, `llama3.1:8b` running locally, against the fragment sets:

| | leak: rules -> +model | over-redaction | precision |
|---|---|---|---|
| `en-core` | 2.01% -> 0.67% | 0.00% -> 3.77% | 1.000 -> 0.855 |
| `ja-core` | 0.71% -> 0.71% | 0.00% -> 5.41% | 1.000 -> 0.868 |

At this size the model raises English recall -- it closes `en-006`, a name in
running prose with nothing to anchor on -- and costs precision in both
languages. It does not improve Japanese. At the recall-first default it does
not move the leak rate at all, because the wide rules already reach those
values, and costs roughly six times the over-redaction.

**At 14B the answer is different, and 0.23 is where that was first measurable.**
`qwen2.5:14b-instruct-q4_K_M` against the document sets, which are documents
rather than fragments:

| set | leak: rules -> +model | over-redaction | recall |
|---|---|---|---|
| `en-docs`, balanced | 20.02% -> **1.69%** | 0.03% -> 0.03% | 0.700 -> 0.950 |
| `en-docs` | 3.50% -> **0.36%** | 0.90% -> 0.90% | 0.883 -> 0.967 |
| `ja-docs` | 0.33% -> **0.00%** | 1.06% -> 1.06% | 0.984 -> 1.000 |
| `zh-docs` | 2.37% -> **0.00%** | 1.20% -> 1.20% | 0.978 -> 0.978 |

Over-redaction does not move anywhere, which is what did not happen at 8B, and
two of the three languages reach zero. What closes in English is the anchorless
name, the largest measured gap in this project since 0.9. The Chinese row read
2.37% -> 2.37% until 0.24, when this library started accepting the type names
the model actually uses. The **345 seconds per document** this line used to
report has been withdrawn: an interrupted Ollama update had left no CUDA
library on the machine, so every run was CPU inference with a 16 GB card idle.
The accuracy above is unaffected **for these numbers**, and that is now
measured rather than assumed: changing only the device leaves the leak rate and
the entity recall byte-identical. It does not leave everything identical — one
model redacts 44% more on CPU than on GPU — so "the device cannot change what a
model returns" is not a claim this file makes. See
`docs/choosing-a-model.md`. The tier is off by default for a reason the stopwatch was never
carrying — it needs a model you have to run, on hardware that decides which
one — and "measure it on your own hardware" is still not a formality.

**Why this took sixteen releases.** Every attempt since 0.7 reported that the
model timed out, and every write-up repeated it. `LLMRequest.timeout` defaulted
to thirty seconds and the provider took the smaller of the request's and the
endpoint's, so `llm.timeout` above thirty did nothing -- three attempts plus
backoff is ninety-seven seconds, which looks exactly like hardware that is too
slow. The model pass degrades to nothing by design, so the symptom was silence.
If you ran a model tier before 0.23 with a timeout above thirty seconds, you
were not getting the timeout you configured.

**About the correction.** The 0.7.0 figures were produced by a harness that
rebuilt the detection pipeline by hand and left out the co-occurrence pass, so
the model was being scored against a baseline that had a pass it lacked. The
conclusions survived re-measurement -- the model is an English-recall tool at
8B and does nothing for Japanese -- but the over-redaction figures moved and
the comparison was not sound when it was published. The harness now has one
assembly path, and a test pins it.

Two things this measurement corrected in the library itself, worth knowing if
you ran an earlier version: the model was asked for character offsets and got
0 of 52 right, so its findings were being discarded almost entirely (0.4.0 to
0.6.0); and `OTHER_SENSITIVE`, which the default policy blocks, was being
proposed for weekdays and error codes. Both are fixed.

Run `mamori eval --compare` against your own data --
[docs/measuring-your-own-data.md](docs/measuring-your-own-data.md) says how,
and what to be careful about. These are two models on small synthetic sets and
they are a floor for judgement, not a substitute. The thing they do establish
is that "does a bigger model help" has a different answer at each size, which
is an argument for measuring rather than for either of the two conclusions.

### It is not a compliance control

Nothing here has been assessed against GDPR, HIPAA, APPI or any other regime.
Pseudonymized personal data remains personal data under most of them, and a
placeholder that a mapping can reverse is pseudonymization, not anonymization.

### It does not defend a compromised machine

Detection, the mapping table and restoration all run locally. Anything that can
read your process memory, your files or your keystrokes has already won. The
mapping table is the highest-value object in the system: it holds only the
values you were trying to protect.

### It is not automatic

`mamori` protects the text you pass to it. It cannot intercept a call that does
not go through it. The proxy planned for v0.5 narrows this gap; it does not
close it.

### It cannot control what the recipient does

Once the protected text is sent, it is out of scope. Placeholder structure
itself carries information -- that there were three people and two companies in
the message, and roughly where. If that fact is sensitive, do not send the
message.

## Threat model

The long form, including what is in and out of scope for each threat, is in
[docs/threat-model.md](docs/threat-model.md).

| Threat | Status |
|---|---|
| PII reaches the external service | Mitigated for what the detectors find |
| A credential reaches the external service | Blocked outright for recognised formats |
| The mapping table reaches the external service | Prevented structurally; the mapping never enters an outbound payload |
| A response reads values out of the mapping table | Prevented; only placeholders allocated in the same scope resolve |
| A detector fails and the request proceeds anyway | Prevented; a detector that raises stops the request |
| Sensitive values reach logs or tracebacks | Mitigated; values are excluded from every `repr`, and the library logs nothing |
| Prompt injection in the input steers a detector | Partly mitigated. Pattern rules and the co-occurrence pass cannot be argued with. The local-model pass can be, and the worst a successful injection achieves is silencing it: proposals only ever add, so the rules still run |
| A model hallucinates a span and the wrong text is replaced | Prevented. Offsets must lie inside the text and the reported value must be exactly the characters between them, or the candidate is dropped |
| A detector sends the unprotected text somewhere | Prevented by default. The model provider refuses a non-local URL unless explicitly overridden |
| An input crafted to be undetectable | **Not mitigated.** No detector set is complete |
| Local machine compromise | **Out of scope** |
| Re-identification from what remains | **Not mitigated.** Removing names does not remove a distinctive combination of facts |

## Data handling

- Mappings live in memory by default and are discarded when the session closes.
- Nothing is written to disk unless you ask for it. `--save-mapping` writes
  plaintext and says so on stderr every time.
- The library emits no log records, so there is nothing to configure away.
- No telemetry, no network calls, no model downloads.

## Supported versions

The latest `0.x` only, while the project is pre-1.0. Fixes land on `main`.
