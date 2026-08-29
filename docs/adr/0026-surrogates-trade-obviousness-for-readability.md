# 26. Surrogates trade obviousness for readability

**Status:** accepted

## Context

`<PERSON_001>さんへ` is unambiguous and it is not a sentence. Models reason
visibly worse about text full of tokens: they lose track of who is who across a
long thread, they occasionally refuse to draft a reply *to* a placeholder, and
they sometimes describe the token instead of using it. A prompt where every
name, address and number has become `<TYPE_NNN>` is a prompt that has lost most
of its shape, and the answer shows it.

Substituting a plausible value — `山田一郎` rather than `<PERSON_001>` — keeps
the text readable. This has been on the roadmap since 0.4 and deferred four
times, because it is an answer-quality feature and everything above it was a
correctness one.

## The reason it was hard to accept

**An unrestored placeholder is obvious. An unrestored surrogate is not.**

Somebody who reads `<PERSON_001>さんへ` knows instantly that something did not
finish. Somebody who reads `山田一郎さんへ` reads a sentence about a person, and
has no way to tell it is the wrong person. Every failure this feature can have
— restoration skipped, restoration failed, the text copied somewhere before
restoration — turns a loud error into a quiet, plausible wrong answer.

That is a worse failure mode than anything else in this library, and the design
is shaped entirely around narrowing it.

## Decision

Surrogates are a policy option, **off by default**, enabled per entity type.

**Reserved values wherever any exist.** Emails use `example.com` and
`example.org` (RFC 2606). Addresses use the TEST-NET blocks of RFC 5737.
Telephone numbers use the ranges kept aside for fiction. A surrogate that
escapes is then not only harmless but *identifiable*: somebody who finds
`192.0.2.10` in a log can look it up and learn it means nothing anywhere. Each
pool records its basis, and `mamori privacy` prints it, because "reserved for
documentation" and "a plausible name we invented" are very different promises.

**Names are the residual risk, and there is no fixing it.** No standards body
reserves personal names. The pools are invented and read naturally, which is
precisely what makes an unrestored one hard to spot. This is stated in the
module, warned about by `mamori privacy`, shown in the demo, and is the main
reason the feature is off by default.

**Chosen by allocation order, never derived from the value.** `PERSON_001`
takes the first name in the pool whatever it stands for. Deriving the surrogate
from the original — hashing it — would be tidier and would open a correlation
channel: the same real person would get the same fake name in every document,
so an observer holding two protected documents could tell they concern the same
individual. Order is what keeps a surrogate from carrying information about
what it replaced. The cost is that the same person gets different surrogates in
different documents, which is fine, because consistency is only needed *within*
a session and that is exactly where order provides it.

**A surrogate never collides with the text it enters.** If the pool's choice
already appears in the document, the next is used. Restoring the wrong
occurrence would corrupt the caller's own words, and this is the one hazard
that would do damage rather than merely fail.

**An exhausted pool falls back to a placeholder.** Running out is not an error;
a token is always safe.

**No pool covers a credential.** There is no plausible stand-in for a password,
and credentials are blocked rather than substituted anyway.

## Consequences

**Restoration loses its tolerance, and this is the honest cost.** A placeholder
can be recognised by shape, so 0.2's restorer copes with `PERSON_001`,
`<person_001>` and `＜PERSON_001＞`. A surrogate is a name: it matches exactly or
it does not. A model that writes `山田さん` where it was given `山田一郎` has
produced text mamori cannot restore.

What mamori can do is **say so**. `RestorationResult.missing` lists every
mapping that did not come back, so an unrestored surrogate is detectable even
though it is not visible. Anyone turning this on should check it on every
answer, and the demo shows exactly that case.

**The mapping gains a surface form.** `Mapping.surface` is empty for every
mapping mamori has made by default, and non-empty means a surrogate was used.
It is excluded from `repr` like the original value: a surrogate is not
sensitive, but the *pair* is precisely the lookup table this library exists to
keep off other machines.

**It is reported and it warns.** `mamori privacy` names the types, prints each
pool's basis, and raises a warning with a non-zero exit status — twice when
invented pools are in use. A deployment check can fail on it.

**It does not compose with the balanced/recall-first trade.** A wide-tier false
positive under surrogates replaces an ordinary word with a plausible name
rather than an obvious token, which is worse. Nothing in the code prevents that
combination and nothing should; it is a judgement about a deployment, and the
numbers to make it are in `mamori eval`.
