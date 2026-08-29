# 0002. The road to 1.0, revised

**Status:** current plan. Supersedes
[proposal 0001](0001-the-road-to-1-0.md), which stands as the record of what
was planned after 0.7 and what came of it.

Revised after eleven releases and a set of proposals from the project owner.
This document says which of those are adopted, which are adapted, which are
declined and why, and where the accumulated known problems land.

## What the eleven releases actually taught

Three things, and they shape everything below.

**A component can be correct in every line and contribute nothing.** The model
tier asked for character offsets for three releases and threw away 98% of what
it was given. The evaluation harness compared against the wrong baseline for
two. A 12B measurement reported a perfect zero delta that was every request
timing out. Three instances in four releases is not bad luck; it is what this
kind of software does, and the answer each time was to *count* rather than to
reason.

**The numbers changed when the scale did.** 123 sentence fragments said one
thing; twenty documents said something several times worse and found four
detection bugs in the first run. Anything measured at the wrong scale is not
measured.

**The remaining weaknesses are concentrated and known.** Japanese is the
weakest language at document scale. Names without an anchor are the weakest
type. Neither is a surprise and neither has been attacked directly yet.

## The open problems, collected

Written down here because a problem in a changelog is a problem nobody finds.

| | where it hurts | lands in |
|---|---|---|
| A trading name with no legal suffix (`Acme`, `田中商事`) | `en-027`, `ja-020` leak | partly solved by corrections in 0.8; the rest needs context |
| Chinese personal names are weak by design | `zh-docs` leaks 6.11%, the worst of the six sets | 0.13 |
| A name with nothing anchored near it | `en-docs` leaks 20.29% at the balanced stance | 0.12, 0.13 |
| `mamori` cannot say *why* something was, or was not, redacted | every user's first question | **0.12** |
| Placeholders restart per request, so a stateful client loses them | the proxy, documented in ADR 0018 | **0.14** |
| Overlap resolution prefers severity over confidence | a low-confidence guess can outrank an anchored rule of another type | 0.12, as part of the trace work |
| The datasets are twenty documents | every published figure | continuous |
| Whether a model above 8B changes the model tier | unanswered; the hardware here times out | when hardware allows |
| `<PERSON_001>` inside HTML looks like a tag | anyone protecting an HTML payload | 0.15 |
| A name split across JSON keys is not detected | structured payloads | 0.15 |

## The owner's proposals, assessed

### Adopted, with the version changed

**Traceability and decision audit** — proposed for 0.14, moved to **0.12** and
made the next release. It is the single most valuable thing on the list, it
needs no dependency, and it answers the question every user actually has. It
is also `kiseki` ADR-0063 ("evidence names its source"), which proposal 0001
listed as still open. Bringing it forward means every later decision is
inspectable while it is being made rather than afterwards.

**Multi-turn consistency** — adopted for **0.14**, with one change. The
proposal is a salted hash seed per session, and 0.11 deliberately chose
*allocation order* over hashing for surrogates, because deriving a stand-in
from the value it replaces lets somebody holding two protected documents tell
they concern the same individual. A **per-session salt removes that objection**:
the hash is stable inside a conversation and unrelated across conversations,
which is exactly the property multi-turn work needs and the one order cannot
provide across process boundaries. Adopted as specified, with the reasoning
recorded so nobody re-opens it.

**Japanese precision, and lightweight context** — adopted for **0.13**, and
this is the right target: `ja-docs` and `zh-docs` are the weakest measured
sets, and "川 as a surname versus 川 as a noun" is precisely the case anchored
rules cannot reach.

Morphological analysis means a tokenizer, and a tokenizer is a runtime
dependency. The core stays dependency-free — that is what makes it auditable —
so it arrives the way the model provider did in 0.5: an **optional adapter**
behind the existing port, installed as `mamori[ja]` by whoever wants it, with
the measured difference published. If it does not beat the rules on `ja-docs`,
it does not ship as a default, and that is a measurement rather than a
preference.

**Fail-closed guard** — adopted for **0.15**, narrowed. mamori already fails
closed on credentials, and "block anything uncertain" as stated would block
most documents. What is worth building is a **stance** where a detection below
a confidence threshold escalates to `BLOCK` rather than being dropped, so a
deployment that cannot tolerate a miss can choose to stop instead. That is a
policy setting with a measurable cost, which is the shape everything else in
this library takes.

**Privacy linter for CI** — adopted for **0.15**. `mamori privacy` already
exits non-zero on a warning. The missing piece is scanning *files* — prompt
templates, fixtures, notebooks — for values that should not be committed, which
is a small command over machinery that exists.

### Adapted

**Attribute-preserving tokenizer** — mostly delivered in 0.11. Surrogates keep
the shape of what they replace and draw from reserved ranges where any exist.
What is left is finer grain: preserving the *format* of a value so a
`03-1234-5678` becomes another Tokyo-shaped number rather than a mobile one.
Folded into **0.13** with the Japanese work, where it belongs.

**Markdown and JSON structure preservation** — **investigated and largely
unnecessary**, which is worth stating rather than planning around. Markdown
links, tables, JSON bodies, YAML, CSV, code and HTML attributes all survive a
round trip today, and no detection span crosses a structural boundary. The
`[^\S\r\n]+` fix in 0.9 removed the one rule that did.

Two real gaps remain and are smaller than the proposal implies: `<PERSON_001>`
inside an HTML document reads as an unknown tag, and a name split across two
JSON keys is not detected. Both go to **0.15**, and neither needs a parser.

### Declined

**`mamori.yml`** — declined, and the reason is
[ADR 0012](../adr/0012-configuration-without-a-format.md). mamori has no
configuration format on purpose: the moment this package imports a YAML parser,
every user of the library inherits it, and a privacy tool nobody wants to audit
is a privacy tool nobody uses. `load_config_file` already reads JSON, and TOML
on 3.11 and later, both from the standard library.

The ergonomic need behind the proposal is real and is met a different way: the
policy *engine* — per-type rules, category defaults, prompt overlays,
corrections, surrogates — already exists and is configured by an ordinary
mapping. Anyone who wants YAML can pass `yaml.safe_load(...)` to
`MamoriConfig.from_mapping`, in their own project, with their own dependency.
That is the whole of what a `mamori.yml` would have added.

## The plan

### 0.12 — Say why *(next)*

Every detection already records which rule found it and how confident it was.
Nothing surfaces that consistently, so "why was this redacted?" has no answer
and "why was this **not** redacted?" has none at all. The second question is
the one that matters, and it is the harder one.

- A trace on every result: rule, tier, confidence, and what it beat in overlap
  resolution.
- `mamori trace <text>` — what fired, what was considered and discarded, and
  what a *near miss* was: the rules that almost matched and the character that
  stopped them.
- `mamori audit` — a file or a dataset, summarised: which rules carry the load,
  which never fire at all, which types never appear.
- The overlap-resolution question, settled with evidence rather than argument:
  a wide-tier guess can currently take a span from an anchored rule of another
  type because it is wider. The trace makes that visible; the datasets say
  whether fixing it helps.

### 0.13 — The weakest languages

Japanese and Chinese at document scale, attacked directly and measured.

- Context rules that anchored patterns cannot express, with the optional
  morphological adapter behind the port, `mamori[ja]`, published against
  `ja-docs` — and dropped if it does not win.
- Format-preserving surrogates, folded in from the proposal.
- More document-scale Chinese data, which is currently four documents.

### 0.14 — Conversations

- A session identity that survives a process, with a per-session salt, so a
  stateful client keeps its placeholders across turns.
- The proxy stops being one-scope-per-request when a client asks for
  continuity, and keeps being it when they do not, because the current
  behaviour is what makes "the proxy remembers nothing" true.

### 0.15 — Deployment

- The fail-closed stance.
- The CI linter.
- The HTML placeholder shape, and names split across structured fields.
- The opt-in encrypted store with **retention as a stated rule rather than a
  background process** (`kiseki` ADR-0062), carried over from proposal 0001.

### 1.0 — The contract

Unchanged from proposal 0001, and worth repeating. Not a feature: the public
API is stable, `test_promises.py` is the specification of what this library
will not do, and the figures in `SECURITY.md` have data behind them worth the
word "measured".

A Presidio adapter is dropped from the plan. Nobody has asked for it, and the
provider registry means anybody who wants one can write it without this project
carrying it.

## Still deliberately not planned

Unchanged, and restated because a refusal nobody wrote down gets added later by
somebody meaning well: a sensitive-words list, async machinery, and a web
framework in the core.
