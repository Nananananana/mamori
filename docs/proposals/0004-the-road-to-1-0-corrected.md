# 0004. The road to 1.0, corrected

**Status:** proposed, 2026-09-01. Supersedes the plan in
[0002](0002-the-road-to-1-0-revised.md) from `0.15` onward; everything that
document says about `0.12` through `0.14` still holds.

## Why there is a third one

Proposal 0002 was read as saying that everything up to `0.15` had shipped and
only `1.0` remained. That reading was reported to the project's owner, by this
project, on 2026-08-31. It was wrong, and the way it was arrived at is the
reason this document exists.

The check was `grep -rlq "encrypt" src/mamori/`, which returns files. Three
files mention encryption. **All three mention it as future work:**

```
jsonfile.py     "A future release will add an encrypted store; until then this
                 module refuses to..."
memory.py       "...no file to encrypt and no file to forget to delete."
mapping_store.py "implementations that persist to disk must encrypt"
```

A grep for a word finds the word. It cannot tell a feature from a promise to
build one, and the promise is where the word gets used most.

So `0.15` has six items and **four of them shipped**:

| item | state |
|---|---|
| The fail-closed stance | shipped — `require_model` |
| The CI linter | shipped — `mamori lint` |
| The HTML placeholder shape | shipped — `PlaceholderStyle.SQUARE` |
| Names split across structured fields | shipped — `_STRUCTURED_KEYS` |
| **The opt-in encrypted store** | **not built** |
| **Retention as a stated rule** | **not built** |

## What is actually missing, measured rather than listed

Three of these were found by looking for them today. None is a new idea; two
are promises this project has already published.

### The mapping file is plaintext, and the threat model says so

`--save-mapping` writes every original value in the clear. That is
[T10](../threat-model.md), which calls it *your responsibility* and says
"an encrypted store is on the roadmap". It has been on the roadmap since
proposal 0001.

The mapping table is the one asset in this system that is worth more than the
document it came from: it holds the values **and** their positions, for
everything protected in a scope. In memory, which is the default, there is no
file to leak. The moment somebody runs `protect --save-mapping` to hand work to
a second process — which is the only reason that flag exists — there is.

### Nothing expires

`ConversationRegistry` has an idle TTL and a size bound, which is retention for
*conversations*. A `MappingStore` has none. Values live until `purge()` is
called, and nothing calls it on a timer, because there is no timer.

Proposal 0002 asked for "retention as a **stated rule** rather than a
background process", borrowing `kiseki` ADR-0062. That distinction is the whole
design: a rule the caller can read and act on beats a thread they cannot see.

### ~~The proxy can be bound to the network and says nothing~~

**Withdrawn before this document was committed, and left here because how it
got in matters more than the claim.**

It was reported that `ProxySettings.remote_binding` describes a risk and is
never called. `remote_binding` does not exist. The property is `is_public`, it
is called at `interfaces/cli/main.py:883`, and a non-loopback binding prints:

```text
WARNING: this is bound to a public address. Anything that can reach
this port can send documents through it and read the restored answers.
```

The search was for the name that was handed over, and the absence of that name
read as the absence of the thing. **That is the same mistake as the `encrypt`
grep at the top of this document, run in the opposite direction**: one found a
word and concluded a feature existed, the other missed a word and concluded a
feature did not. Neither read the code.

There is still no authentication, and that stays deliberate — see the closing
section. What was wrong was the claim that nothing says so.

### There is no record that a protection ever happened

This one is a consequence of a good decision, which is why it needs saying
rather than fixing carelessly.

**This library has no logging.** Not a quiet logger, not a disabled one:
`import logging` appears nowhere in `src/`. That is what makes the claim in
`mamori privacy` — *a protected value never appears in a log line because
nothing ever writes one* — true by construction rather than by discipline.

The cost is that **nothing survives the process**. `DecisionTrace` answers
"why was this redacted" for a request that is still in hand. `mamori audit`
summarises a corpus. `mamori.protection-scope/1` states what one protection
did, carries no values, and is handed to the caller — who has nowhere to put
it.

An operator asking "what left this machine last Tuesday, and under which
policy" has no answer, and the honest reason is that answering would mean
writing something down.

## The plan

### 0.29 — The mapping at rest

The two items `0.15` promised and did not deliver, together because they are
the same asset.

- **An encrypted mapping store**, opt-in, behind the existing `MappingStore`
  port. The key comes from the environment or a caller-supplied callable, never
  from the config file — the rule `api_key_env` already follows.
- **Retention as a rule the caller can read.** A `MappingStore` states how long
  it keeps what it keeps, `mamori privacy` prints it, and expiry happens when
  the store is used rather than on a thread. A background sweeper is what
  proposal 0002 said not to build, and the reason holds: a caller cannot reason
  about a thread they did not start.
- T10 in the threat model changes from *your responsibility* to a statement of
  what the encrypted store does and does not protect against. **It does not
  protect against a compromised machine**, which is already out of scope, and
  saying that plainly matters more than shipping the feature.

### 0.30 — Saying what happened, without saying what it was

The traceability gap, built so that it cannot become the logging this project
refuses.

- **An audit sink**: an opt-in port that receives `protection-scope` records —
  the document that already exists, already carries no values, and already has
  a schema and a conformance suite. A file writer, and nothing else, in this
  package.
- **The invariant is the point**: what reaches the sink is exactly what
  [ADR 0032](../adr/0032-state-the-protection-without-importing-it.md) permits
  — anything derivable from the protected artifact, and nothing else. The
  record inherits the classification of the text it describes, and the sink
  documentation says so, because "it contains no values" is the sentence that
  gets a file written to a log directory at the wrong classification.

### 1.0 — The contract

Unchanged from 0002, restated with what each clause needs:

| clause | state |
|---|---|
| The public API is stable | **met** — `tests/test_api.py`, since `0.25` |
| `test_promises.py` is the specification | **met** — green |
| The figures in `SECURITY.md` are worth the word "measured" | **not met** |

The third has two halves and only one of them ever waited on anybody.

**The half that did not**: the figures have to be the figures. Three of twelve
rows had drifted and the version stamp was nine releases old, until
`tests/test_security_figures.py` made that a build failure. The population, the
device and the label set are stated now.

**The half that does**: a corpus written by somebody who has not read these
rules. Commissioned, approved by the owner on 2026-08-31, not yet delivered.
[docs/open-questions.md](../open-questions.md) carries what would settle it and
the three ways of getting it wrong.

## Not planned, restated

Unchanged from 0002 and repeated because a refusal nobody writes down gets
added later by somebody meaning well: **a sensitive-words list, async
machinery, and a web framework in the core.**

Two more, earned today:

**Logging.** Not "logging that redacts", not "logging behind a flag". The audit
sink in `0.30` takes a document that provably carries no values; a logger takes
whatever a caller passes it. The first can be checked and the second is a
promise about everybody's future code.

**Authentication in the proxy.** A service that needs authenticating is a
service that should not be bound to the network, and the answer to `--host
0.0.0.0` is to say what it costs rather than to make it safe. mamori's trust
boundary is the machine.
