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
ja-core  (ja, 45 samples)
  leak rate             0.75%   (4/531 sensitive chars left uncovered)
  over-redaction        0.00%   (0/803 ordinary chars replaced)
  entity P / R / F1   1.000 / 0.981 / 0.990   (match: overlap)
  clean samples       44/45
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

Quality floors run in CI, so a rule change that improves one language and
quietly wrecks another turns the build red. Writing the first datasets found
five real bugs within an hour — read
[ADR 0009](docs/adr/0009-measure-leaked-characters.md) for what they were.

Treat the numbers as regression floors, not as a claim about your data: the
datasets are small and synthetic, and a leak rate near zero on 45 invented
sentences says nothing about a real inbox.

---

## What this does not do

Read this part. A security tool that is trusted past its actual reach is worse
than no tool, because the behaviour it licenses is riskier than the behaviour
it replaced.

- **Detection is not complete and never will be.** The default rules are
  regular expressions. They will miss a name written with an uncommon surname
  and no honorific, an English name with nothing in front of it to mark it as
  one, an address with no prefecture or street type, an internal codename that
  looks like an ordinary word, and anything sensitive only in context.
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

`v0.2` added the measurement harness, streaming restoration, and English and
Chinese language packs.

| | |
|---|---|
| **v0.3** | An OpenAI-compatible local proxy, so an existing app moves over by changing `base_url` and nothing else. Same-document co-occurrence: once a name is confirmed anywhere with high confidence, every later mention of it is too. |
| **v0.4** | A Presidio adapter, an opt-in encrypted persistent store, and a confidence floor so answer quality can be traded against coverage. |
| **v0.5** | Local-model detection as an opt-in deep-scan tier, for the cases patterns cannot reach — unanchored English names and Chinese given names above all. |
| **v0.6** | Surrogate values (`田中太郎` → `山田一郎`) as a policy option, for prompts where an opaque token costs too much answer quality. |

The proxy is next on purpose. Nobody rewrites a working application to adopt a
library, and a privacy layer that only protects new code protects very little.

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
