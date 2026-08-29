# mamori 守り

**Use real data with an external LLM, without sending real data to it.**

日本語版は [README.ja.md](README.ja.md)、中文版在 [README.zh.md](README.zh.md)。

You have a customer email in front of you and a model that could draft the
reply in seconds. So you retype the message with the names removed, get the
placeholders inconsistent, miss the phone number in the signature, and end up
with a worse draft than if you had written it yourself.

`mamori` does that step for you, locally and consistently.

```text
you write                      the model sees                 you get back
─────────────────────────────  ─────────────────────────────  ─────────────────────────────
田中太郎さんへ                  <PERSON_001>さんへ              田中太郎さんへ
tanaka@example.com から        <EMAIL_001> から                tanaka@example.com から
メールが届きました。            メールが届きました。             メールが届きました。
```

The mapping from `<PERSON_001>` back to `田中太郎` never leaves your machine.

---

## Install

```bash
pip install mamori
```

No model, no GPU, no network. The default detectors are pattern rules that run
in microseconds.

## Use

```python
import mamori

with mamori.PrivacySession() as session:
    protected = session.protect("田中太郎さんに tanaka@example.com で連絡して")
    # -> '<PERSON_001>さんに <EMAIL_001> で連絡して'

    answer = call_your_favourite_llm(protected.protected_text)

    print(session.restore(answer).text)
```

A session is one conversation. The same value keeps the same placeholder for
its whole life, so a model can tell that two mentions are the same person, and
an answer in turn five can still be restored with a value from turn one.

### Streaming

An answer arrives token by token, and `<PERSON_001>` shows up as `<PER`,
`SON_0`, `01>`. Restore it as it comes:

```python
stream = session.stream_restore()
for chunk in llm_response_stream:
    print(stream.feed(chunk), end="", flush=True)
print(stream.finish())
```

Whatever the chunking, this emits exactly what `restore()` would emit for the
whole response — checked with Hypothesis over every split, because a streaming
path that *usually* agrees with the batch path breaks at whichever token
boundary the model happens to pick.

### From the shell

```bash
mamori inspect -f draft.txt
```

```text
4 detected:
      0:4     PERSON           <PERSON_001>       田***                (ja, 0.90)
     12:30    EMAIL            <EMAIL_001>        t*****************   (universal, 1.00)
     45:58    PHONE            <PHONE_001>        0************        (ja, 0.90)
     70:94    INTERNAL_URL     <INTERNAL_URL_001> h***********************  (universal, 0.90)
```

The last column is the rule set that fired, so you can see which language's
pack found what.

`mamori demo` runs a whole round trip, including a reply whose placeholders
have been mangled, so you can see what recovery looks like.

### Without changing your application

Nobody rewrites a working application to adopt a library. If yours already
talks to an OpenAI-compatible API, put mamori in front of it and change one
string:

```bash
mamori serve --upstream https://api.openai.com/v1/
```

```text
mamori proxy on http://127.0.0.1:8100/v1/
  upstream        https://api.openai.com/v1/
  detection       all locales, recall_first
  briefing        prepended
```

Point the application at `http://127.0.0.1:8100/v1/` and nothing else changes.
Every message is protected on the way out, the reply is restored on the way
back, and the proxy logs what it replaced without ever logging a value:

```text
  1 message(s), replaced EMAILx1, PERSONx1, PHONEx1
```

Streaming works: a placeholder arriving as `<PER`, `SON_0`, `01>` is held and
restored as it passes. A blocked credential stops the request instead of
forwarding it. It binds to this machine only unless you say otherwise, because
anything that can reach the port can send documents through it. See
[ADR 0018](docs/adr/0018-a-proxy-on-the-standard-library.md).


### What the model tier is actually worth

Measured, not asserted. `llama3.1:8b` running locally, balanced stance, against
the bundled sets:

| | leak: rules → +model | over-redaction | precision |
|---|---|---|---|
| `en-core` | 2.01% → **0.67%** | 0.66% → 4.43% | 1.000 → 0.855 |
| `ja-core` | 0.71% → 0.71% | 0.00% → 5.41% | 1.000 → 0.868 |
| `zh-core` | 0.00% → 0.00% | 2.55% → 10.18% | 0.964 → 0.871 |

**At this size it is an English-recall tool.** It closes `en-006` — a name in
running prose with nothing to anchor on, the gap it was built for — and does
nothing measurable for Japanese or Chinese while costing over-redaction in all
three. Earlier versions of this README claimed it reached Chinese given names.
It does not; the Chinese rules were already at 1.000 recall on that set.

At the **recall-first default** it is worse than useless: the wide rules already
reach those values, so the leak rate does not move and over-redaction goes from
1.44% to 9.58%. Leave it off until you have measured it on your own data.

Measure it yourself — the delta is the only thing worth reading:

```bash
mamori eval --compare --stance balanced -c mamori.json --cache answers.json
```

`--compare` names the individual samples that changed, because an aggregate
tells you something moved and not what. `--cache` keys on the model *and the
prompt*, so re-running is free and rewriting one line of guidance invalidates
exactly the answers that depended on it.

Two findings from doing this came back into the code. The model was being asked
for character offsets and got **0 of 52** right while 51 of those values were
really in the document — so it now reports values and mamori locates them
([ADR 0022](docs/adr/0022-a-model-reports-values-not-offsets.md)). And every
English false positive was `OTHER_SENSITIVE` used as a dustbin; one guidance
rule about what that type is for halved over-redaction from 8.80% to 4.43%.


## When it gets something wrong

It will. A salutation anchor is right far more often than it is wrong, and
`Dear Monday,` is when it is wrong. Say so:

```bash
mamori correct Monday --never --note "a weekday, not a name"
mamori correct Acme   --always COMPANY_NAME --note "trading name, no suffix"
```

The second closes a gap documented since `v0.1` — a trading name with no legal
suffix, which no pattern can reach in general and any operator can settle for
their own data.

The log is append-only and the latest word about a value wins, so undo is
another correction and nothing is deleted. Rules are not rewritten and prompts
are not edited; remove the log and you are exactly back where you were.

```bash
mamori corrections     # what has been ruled on, and what it costs
```

**`--never` is the only thing in mamori that reduces what it protects**, so it
is kept narrow. Every exclusion is named by `mamori privacy` and reported as a
warning with a non-zero exit status, so a deployment check can fail on one
nobody meant to ship. And a credential can never be ruled away:

```text
error: that value looks like a credential (API_KEY), and a credential cannot
be ruled 'never'. Nothing was written -- recording it would have put the
credential in a file on disk. Rotate it instead.
```

That refusal happens *before* anything is appended, in three independent
places. See [ADR 0024](docs/adr/0024-corrections-are-appended-applied-at-read.md).

---

## What is this actually doing with my data?

Ask it:

```bash
mamori privacy
```

The answer is computed from **your** configuration, not from this README: which
types are blocked and which are pseudonymized, where a detection model is and
whether the trust boundary admits it, what is kept and where. Anything that
widens exposure is a warning and a non-zero exit status, so a deployment check
can fail on it.

Under that, the claims that hold however you configure it — each printed with
the name of the test that fails if it stops being true:

```text
  - Pattern detection contacts nothing. No socket is opened to protect a
    document with the default detectors.
    checked by test_promises.py::TestNothingLeavesTheMachine
```

Those tests are real. `tests/test_promises.py` replaces `socket.connect` with a
function that raises and then runs the whole default path — every language
pack, the evaluation harness, the command line — so a future dependency that
dials out fails in a build rather than in your deployment. The README claims
are a specification, not a description. See
[ADR 0019](docs/adr/0019-privacy-is-a-report-not-a-promise.md) and
[ADR 0020](docs/adr/0020-the-promises-are-checked-by-machine.md).

And the last section says what mamori *cannot* check for you — whether the
service you chose retains your prompts, for one — because a report that implied
otherwise would be worse than one that stayed quiet.

---

## Languages

Japanese, English and Chinese, in one document if that is what you have:

```text
田中太郎さんへ                        ->  <PERSON_001>さんへ
CC: Mr. John Smith (Acme Inc.)       ->  CC: Mr. <PERSON_003> (<COMPANY_NAME_002>)
张伟先生，请拨打 13812345678          ->  <PERSON_004>先生，请拨打 <PHONE_003>
```

Rules are grouped into language packs, and a pack runs when the text gives a
reason to run it. All of them are enabled by default — an unexpected language in
a document is exactly the case nobody redacted by hand — and `locales=` narrows
it when you know better:

```python
mamori.PrivacySession(locales=["ja", "en"])
```

```bash
mamori locales
```

```text
  en  English     16 rules  runs on: latin
  ja  Japanese    11 rules  runs on: han, kana
  zh  Chinese     11 rules  runs on: han  (not when: kana)
```

That last line is the whole trick. Chinese and Japanese share Han characters, so
the two surname lists fire on each other's text and turn ordinary words into
people. Kana settle it: they appear in Japanese and never in Chinese, so kana in
the text stands the Chinese rules down. Text in Han alone could be either, so
both run and over-detect — the safe direction.

Email, credentials, card numbers and private addresses are language-independent
and always run. Adding a language is one module and one registry entry; see
`register_locale`.

---

## Switching things

Detection is a pipeline of passes, not a fixed procedure. Each pass sees the
text and what earlier passes found:

```text
rules            universal patterns + whichever language packs apply
  ↓
co-occurrence    values confirmed above the seed threshold, found again
                 wherever else they appear in the same text
```

The second pass is why the first is not enough. Once a name is settled by an
honorific in one sentence, every other mention of it is the same person — and no
rule looking at those mentions alone can tell:

```text
尊敬的张伟先生：              ← an honorific settles it
本次评审由张伟主持。           ← nothing here says this is a name
请张伟在周五前回复。           ← nor here
```

All three are protected. In Chinese this is not an optimisation; there is
nothing else to anchor on.

Everything switchable lives on one object:

```python
mamori.PrivacySession(
    config=mamori.MamoriConfig(
        locales=["ja", "en"],
        min_confidence=0.7,  # ignore shaky detections: fewer placeholders, less coverage
        co_occurrence=True,
    )
)
```

`MamoriConfig` has no opinion about file formats. `from_mapping()` takes an
already-parsed mapping, so you pick JSON, TOML, YAML or a dict literal and keep
your parser to yourself — the library still has no runtime dependencies.

```bash
mamori config                       # what would be used, and where each layer came from
mamori protect --min-confidence 0.7 -f draft.txt
```

Settings layer, later winning: defaults, `--config`, `MAMORI_*` environment
variables, then flags. Unknown keys are refused rather than ignored — a typo in
a privacy setting that silently does nothing is the worst available outcome.

### The recall dial

Every rule declares a tier. **Core** rules are anchored on something rarely
anything else: a checksum, a vendor prefix, an honorific, a label. **Wide** rules
match on shape alone — ten bare digits, two capitalised words, a long
random-looking token. The stance decides which run, and **recall-first is the
default**:

| | leak rate | | over-redaction | |
|---|---|---|---|---|
| | balanced | **recall-first** | balanced | **recall-first** |
| `ja-core` | 0.71% | **0.00%** | 0.00% | **3.11%** |
| `en-core` | 2.01% | **0.67%** | 0.66% | **1.44%** |
| `zh-core` | 0.00% | **0.00%** | 2.55% | **4.00%** |

That is the trade, stated rather than buried. A miss is silent and permanent; a
false positive is a word visibly replaced that should not have been. Somebody
reading a protected prompt notices the second. Nobody notices the first.

```bash
mamori protect --stance balanced -f draft.txt   # fewer stray placeholders
mamori eval --stance balanced                   # measure either one
```

The stance changes no security decision — policy still decides what leaves,
resolution still picks one detection per character, credentials are still
blocked. It only proposes more, which is why "recall-first never leaks more than
balanced" is a test rather than a hope.

---

## Prompts

Two models are involved, facing opposite directions, and both get a prompt you
can read and change.

**The service model** is told to leave the placeholders alone. This needs no
local model and pays for itself immediately:

```python
system = session.external_system_prompt() + "

" + your_own_system_prompt
```

Every placeholder that comes back intact is one restoration does not have to
recover from a mangled form.

**A local model** is asked to find what patterns cannot reach. As of `v0.7`
that claim comes with numbers instead of an intention — see
[what the model tier is actually worth](#what-the-model-tier-is-actually-worth)
below, which is less than this README used to imply. Its prompt carries
everything the regex work taught —

```bash
mamori prompt detection
```

```text
## What looks sensitive and is not

- Many ordinary words begin with a character that is also a surname. 森林 is a
  forest, not 森 and 林. 原因, 金額, 石油, 田舎 and 林檎 are words.
- Two capitalised words are usually not a name. Headings, products, departments,
  weekdays and sentence openers all look identical.
```

— because that knowledge is about *languages*, not about regular expressions.

### Your rules, not ours

Guidance is addressable, so an organisation adds what the library cannot know
and drops what does not fit, without forking anything:

```json
{"prompts": {"detection": {
  "disable": ["en.person.unanchored"],
  "add": [{"id": "acme.case", "text": "Case numbers look like ACME-12345."}]
}}}
```

```bash
mamori prompt detection --guidance   # list the ids, so they can be disabled
```

A disable that matches nothing is refused, when the config is loaded rather than
months later.

### Wiring up a model, wherever it runs

The realistic deployment is not a laptop. It is one GPU machine the team shares:

```json
{"llm": {"model": "qwen2.5:72b", "base_url": "http://llm01.corp:8000/v1/"}}
```

```bash
mamori llm --check     # where it is, whether it is allowed, whether it answers
```

```text
  model           qwen2.5:72b
  endpoint        http://llm01.corp:8000/v1/
  host            private (another machine)
  trust boundary  private_network
  reachable       yes
```

The same file with no `base_url` uses a model on this machine. Nothing else
changes.

What is refused is a **public** endpoint. A detector is sent the text *before*
it is protected, so an endpoint outside your network is the leak, and mamori
says so at startup rather than on the first document:

```text
REFUSED. This model will not be used:
  'api.openai.com' looks external, which is outside the private_network trust
  boundary.
```

Three boundaries: `same_host`, `private_network` (the default), `anywhere`. A
host named in `trusted_hosts` is admitted under all of them, because an
operator naming a host is making a decision. See
[ADR 0015](docs/adr/0015-a-trust-boundary-not-a-localhost-check.md).

### Any model, any client library

Switching models is a field. Switching *how* the model is reached is one line,
and needs no dependency here:

```python
from mamori.infrastructure.llm import CallableProvider, register_llm_provider

# A model already loaded in this process -- any library, no HTTP at all.
provider = CallableProvider(my_pipeline, name="local-transformers")

# Or make it selectable by name from configuration.
register_llm_provider("vllm", lambda endpoint: MyVLLMProvider(endpoint))
```

```python
from mamori import MamoriConfig

session = MamoriConfig.from_mapping(settings).session()
```

The bundled provider speaks OpenAI-compatible HTTP over `urllib`, so the zero
runtime dependencies stay zero. See
[ADR 0016](docs/adr/0016-the-model-and-the-client-are-both-replaceable.md).

Three properties hold whatever the model does:

- **It only ever adds.** Text that talks it out of reporting anything gets you
  back to the rules, which is where every earlier release already was.
- **Its output is checked against the text.** Offsets must lie inside it and the
  reported value must be exactly the characters between them, so a hallucinated
  span is dropped rather than spliced out of your document.
- **Its failure is not your request's failure.** A missing model is a weaker
  detector, not a stopped pipeline. Set `require_model` to invert that.

Keys are read from an environment variable you name, never from the config file:
`{"api_key_env": "LLM_API_KEY"}`. A literal `api_key` is refused.

---

## The three things that make this hard

Most of the work in `mamori` is in the parts that a first implementation gets
wrong.

**A model will not give your placeholders back unchanged.** `<PERSON_001>`
comes home as `PERSON_001`, `<PERSON_1>`, `<person_001>` or `＜PERSON_001＞`.
Restoration is tolerant about the surface form and strict about identity: a run
of text is only substituted when its canonical `(TYPE, index)` pair was
actually allocated in this session. Anything else is reported, never resolved —
a response is untrusted input, and a lookup driven by text the responder chose
is how a mapping table gets read out one guess at a time.

**Japanese has no word boundaries, and normalizing it moves every offset.**
`ｔａｎａｋａ＠ｅｘａｍｐｌｅ．ｃｏｍ` has to match the same rule as its
half-width form, but replacement has to happen in the *original* string or the
user gets back mangled input. `mamori` normalizes with a character-level offset
map, so a span found in normalized coordinates maps back exactly.

**Detectors disagree, and overlapping replacements corrupt text.**
`田中太郎(tanaka@example.com)` produces overlapping spans from three rules. One
detection per character has to win, and the rule has to be written down rather
than left to dictionary order: widest span first, then entity severity, then
confidence, then offset. Replacing a wider span also removes everything inside
it, which is why width comes first.

---

## How well does it work?

Ask it:

```bash
mamori eval
```

```text
ja-core  (ja, 49 samples)
  leak rate             0.00%   (0/561 sensitive chars left uncovered)
  over-redaction        3.11%   (27/869 ordinary chars replaced)
  entity P / R / F1   0.868 / 0.983 / 0.922   (match: overlap)
  clean samples       49/49
```

**Leak rate** is the share of labelled sensitive characters that no detection
covered — the part that would have left the machine. **Over-redaction** is what
it cost in ordinary text. Neither number means anything alone: a tool that
redacts everything has a perfect leak rate and destroys every answer, and a
privacy layer people stop using has a real-world leak rate of 1.0.

Entity-level precision and recall are reported too, per type, because they are
how you find a rule that is missing rather than merely imprecise. But they are
not the headline. A detector that finds `田中` inside `田中太郎` scores as a hit
under overlap matching and a miss under exact matching; neither says the thing
that matters, which is that two characters of somebody's name were sent to a
third party.

Quality floors run in CI — per stance, so neither half of the trade can rot —
and a rule change that improves one language while quietly wrecking another
turns the build red. Writing the first datasets found five real bugs within an
hour; read [ADR 0009](docs/adr/0009-measure-leaked-characters.md) for what they
were.

The numbers are also what justified each subsequent change rather than an
opinion about it:

| leak rate | v0.2 | + co-occurrence | + recall-first |
|---|---|---|---|
| `en-core` | 7.37% | 2.01% | **0.67%** |
| `ja-core` | 1.43% | 0.71% | **0.00%** |
| `zh-core` | 1.49% | 0.00% | **0.00%** |

Treat the numbers as regression floors, not as a claim about your data: the
datasets are small and synthetic, and a leak rate near zero on fifty invented
sentences says nothing about a real inbox.

---

## What this does not do

Read this part. A security tool that is trusted past its actual reach is worse
than no tool, because the behaviour it licenses is riskier than the behaviour
it replaced.

- **Detection is not complete and never will be.** The default rules are
  regular expressions, and the recall-first stance widens them rather than
  finishing them. They will miss a name written with an uncommon surname in a
  sentence that gives no clue, an address with no prefecture or street type, an
  internal codename that looks like an ordinary word, and anything sensitive
  only in context. A local model narrows this; it does not close it.
- **`mamori` reduces the chance of a leak. It does not eliminate it.** If your
  team's rule was "never paste customer data into a chat window", `mamori` is
  not a reason to change that rule. It is a safety net for the times someone
  does it anyway.
- **It is not a compliance control.** Nothing here has been assessed against
  GDPR, HIPAA, APPI or any other regime, and pseudonymized personal data is
  still personal data under most of them.
- **It does not protect a machine that is already compromised.** The mapping
  table holds exactly the values you were trying to protect. Keeping it in
  memory, which is the default, is the whole reason it is not a file.
- **It does not stop you from sending an unprotected prompt.** `mamori` sits
  where you put it. It cannot intercept a call that does not go through it.

`docs/threat-model.md` has the long version, including what each detector
class is known to miss.

---

## Design

Four rules shape everything else:

**The external model is outside the trust boundary.** Detection, mapping,
policy and restoration are local and deterministic. Nothing about deciding what
is safe to send depends on a service you are trying to protect data from.

**A model is never the security mechanism.** Later versions will use a local
model to *find* candidates, which is a job models are good at. Deciding what to
do with a candidate, allocating placeholders, and putting values back stays in
code you can read and test.

**Fail closed.** A detector that raises stops the request. A policy that blocks
stops the request. There is no partial result, because at the call site a
partial result is indistinguishable from a safe one.

**Credentials are blocked, not pseudonymized.** There is no legitimate reason
to send an API key to a third party — not even a placeholder-shaped one, which
still tells the recipient that one exists.

```text
interfaces ──> application ──> domain
                    │
infrastructure ──> ports
```

`domain/` imports nothing but the Python standard library. Every
security-relevant decision lives there, so it is testable with no model, no
network and no database.

---

## Roadmap

`v0.1` is the core: detect, decide, pseudonymize, restore, in memory, from
Python or the shell.

`v0.2` added the measurement harness and streaming restoration. `v0.3` made
detection a pipeline and collected every switch onto one configuration object.
`v0.4` leaned the default towards catching everything, and built the prompt
layer. `v0.5` made the model's location and its client library both
configuration, and made the layering a test rather than a diagram. `v0.6`
delivered the proxy, and made the privacy claims answerable and machine-checked.
`v0.7` measured the model tier for the first time and found it had been
discarding almost everything the model got right. `v0.8` gave the operator the
last word.

| | |
|---|---|
| **v0.9** | The evidence under the numbers: larger and harder datasets, a documented way to measure mamori on your own labelled text, and the open question from `v0.7` answered — does a model above 8B change the table? |
| **v0.10** | Surrogate values (`田中太郎` → `山田一郎`) as a policy option, for prompts where an opaque token costs too much answer quality. |
| **v0.11** | An opt-in encrypted store with retention as a stated rule, and a Presidio adapter. |
| **v1.0** | Not a feature: a stable API, the promises suite as the specification, and numbers with data behind them worth the word "measured". |

The reasoning behind that table — and what is deliberately *not* planned — is
in [docs/proposals/0001](docs/proposals/0001-the-road-to-1-0.md).

A Presidio adapter is next, and an encrypted store for the deployments that
cannot hold mappings in memory alone. The larger open question is whether a
model above 8B changes the table above; the harness to settle that now exists
and takes one command.

Language priority is Japanese and English first, Chinese second. The Chinese
rules exist and are measured; the design for making them good is written up in
`docs/adr/0008-language-packs.md` and is honest that regular expressions cannot
finish the job.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Detector rules are the most useful
thing to send: every rule is a precision/recall trade-off, and the ones in
`src/mamori/infrastructure/detectors/patterns.py` each carry a comment saying
which way they lean and why.

Security issues: [SECURITY.md](SECURITY.md). Please do not open a public issue.

## License

Apache-2.0. See [LICENSE](LICENSE).
