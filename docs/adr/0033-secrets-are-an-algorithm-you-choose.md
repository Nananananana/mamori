# 33. Secrets are an algorithm you choose

**Status:** accepted, implemented in 0.31.

## Context

A credential with no vendor prefix and no keyword beside it has been the
documented gap in secret detection since 0.1. `SECURITY.md` and the threat
model both said why nothing closed it:

> Entropy-based detection is not implemented: it produces too many false
> positives on base64 payloads and hashes to be usable by default.

That sentence contains its own answer. *By default* is the qualifier, and the
library already has a dial whose entire purpose is a trade the default should
not make for everybody — the stance. What the sentence describes is not an
algorithm that does not work; it is an algorithm whose cost the deployment has
to be the one to accept.

The algorithm is not in dispute. Shannon entropy over a run of key-shaped
characters, with two thresholds because the ceiling depends on the alphabet
(3.0 bits per character for hex, 4.5 for base64), and a keyword window that
says whether the number beside the word *key* or the word *commit* — this is
what `detect-secrets`, `gitleaks` and `trufflehog` all run, and they run it
because it is the only detector for the secrets that look like nothing.

## Decision

**The secret-detection algorithm is a named choice, defaulting to what shipped
before.**

```python
MamoriConfig(secrets="patterns")  # the default: the rules, and nothing more
MamoriConfig(secrets="entropy")  # the rules, then the entropy pass
```

Three things follow from *named*:

**It is a registry.** `register_secret_algorithm("name", factory)` makes a
fourth algorithm — a local model asked one question per candidate, a filter of
known-leaked keys — a call and a config value, not an edit to this package.
The same shape the language packs have, for the same reason: the library
should not have to be patched to be extended.

**A misspelling is refused when the file is read.** `secrets="entrpy"` fails
at startup. The alternative — falling back to patterns — produces a config file
that says it is looking for bare keys and a scanner that is not, which is the
outcome this project calls the worst available.

**`mamori privacy` reports it, with what it means for what blocks.** Because
that is the part that matters: the entropy pass reports `API_KEY`, and the
default policy blocks a credential rather than pseudonymising it. A false
positive is not a stray placeholder; it is a refused request. A commit id in a
prompt becomes a document that does not go out.

## What was found building it

**The corpora cannot measure this.** Twelve bundled datasets, 167 samples,
both stances: every figure is identical with the pass on. Not because the pass
is free — because the samples hold eight runs of twenty or more key-shaped
characters between them and none is generated. The false-positive cost is
stated from synthetic cases (`tests/test_entropy.py`: a commit id, a base64
payload, a pangram) and not from a corpus, and the open questions file says
what would settle it. An instrument that reports zero change is not evidence
of zero cost; it is evidence about the range it was given.

**Three claims in the first tests were wrong, and calibration said so.** A
pangram clears the base64 threshold at 4.54 — so the detector requires a mix
of character classes before believing the number, the same guard the wide-tier
secret rule has. A short base64 payload sits at 4.48, two hundredths under. A
UUID cannot be flagged at all: hyphens put it in the base64 class, and sixteen
hex digits plus a hyphen is seventeen symbols with a ceiling of log2(17), about
4.09. That last one is a miss for a UUID-shaped key and it is also what keeps
every request id in an agent payload from becoming a refused request, so it
is kept and stated.

**`api_key = X` is not the gap.** The first tests used it as the "bare" sample
and the keyword-assignment rule blocked it as `PASSWORD` before the pass ever
ran. Measured against the default rules at both stances, the phrasings the
rules actually miss are `Authorization: Bearer X`, *the new staging key is
X*, 鍵は X です, 密钥：X — and those are what the tests use now. The pass
defers to anything with an anchor; it speaks only for spans nothing has
claimed.

## Consequences

- The default detector is byte-for-byte what it was. Every published number
  holds, and `test_the_default_session_does_not_find_a_bare_key` pins that a
  bare key is still missed unless somebody asks.
- A deployment that turns it on gets the gap closed for hex keys, random
  session tokens and bearer headers, and gets commit ids and base64 payloads
  refused unless it also raises `min_confidence` to `0.6`, which keeps only the
  candidates that had a keyword beside them.
- A corpus of real secrets and real hashes, written by somebody who has not
  read this, is now owed. It is the same debt the detection figures carry and
  it is recorded in the same place.
- Nothing about the trust boundary, the policy or the layering moved. The
  measure is a domain function on one token; the tokeniser and the keyword
  window are infrastructure; the switch is configuration.

## Cost

One more setting to get wrong, refused loudly when it is. One more thing
`mamori privacy` has to say. And a false-positive class that was previously
impossible by construction — a refused request over a checksum — is now
possible by choice.
