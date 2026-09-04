# Open questions

An ADR records a decision that was made. This records a decision that is
**owed** — something known, unresolved, and not yet argued out. Without a file
like this the two get confused, and a question nobody has answered starts
looking like a question somebody answered quietly.

**Every entry names what would settle it.** A concern with no settling
condition is a worry, and a file of worries is a graveyard: nothing ever leaves
it, so after a while nobody reads it, and then it is worse than not having one.
An entry that cannot say what would close it does not belong here — it belongs
in a commit message, or nowhere.

---

## A Chinese mobile number leaks at the balanced stance

`Call me on 13812345678 tomorrow.` has no Chinese in it, so the `zh` pack never
runs. At the default recall-first stance the wide digit-run rule covers it as
an `IDENTIFIER` — the wrong type, but not a leak. At **balanced**, the wide tier
is off and the number leaves the machine.

This is the same shape as the Japanese mobile number fixed in `0.27`, and the
fix that worked there does not transfer. `070|080|090` followed by four and
four, with separators, is a shape that means one thing. `1[3-9]` followed by
nine digits is eleven bare digits, and promoting it to the universal rules
redacts `Order 13812345678` and `Ref 15000000000` — measured, both of them.

The cost falls precisely on what the balanced stance is for. So the honest
statement is that the gap is real and the obvious fix is worse than the gap,
not that there is nothing here.

**Settled by** any of: a `zh` mobile pattern with an anchor cheap enough to run
universally; evidence from a real corpus that eleven-digit identifiers starting
`1[3-9]` are rare enough that the trade flips; or a decision that the balanced
stance does not promise national formats outside their own script, written down
as an ADR so that it is a decision instead of a gap.

---

## Nothing here was written by anybody else

Stated in the README, under [Who wrote the documents these numbers come
from](../README.md#who-wrote-the-documents-these-numbers-come-from). What the
README does not say is what would fix it, which is why it is also here.

Twelve bundled datasets, three adversarial sets, six generated corpora — one
hand, all of them. Borrowing a corpus from a sibling project does not help: a
sibling reused this one's and reported a miss rate its own unseen data did not
support, which is how this became a known problem rather than a suspected one.

**Settled by** a corpus of documents with values in them, labelled by somebody
who has not read these rules, which nobody has yet commissioned. Not by another
generator, however adversarial: three of the five findings from the 900-document
adversarial corpus were resolved by deciding what its generator should have
been able to write, which is what a corpus refuting only its author's
imagination looks like from the inside.

Three things about commissioning it that are easy to get wrong:

**The values do not have to be real, and must not be.** What has to be
independent is the hand, not the data. An outside writer using invented values
in real formats satisfies every constraint at once — redistributable under a
licence they can grant, free of anybody's actual details, and written by
somebody who has not seen these rules. The bundled corpora already meet the
first two: all 34 addresses in them use RFC 2606 reserved domains and the
telephone numbers use ranges kept aside for fiction. What is missing is only
the third.

**The labels have to come from the same outside hand as the text.** A document
somebody else wrote and we annotated leaves the classification ours, which is
the half that decides what counts as a value. `Provenance` records the two
separately for exactly this reason.

**Record the date it was published.** Commissioned text is unpublished, so a
model cannot have memorised it — until it is committed here under Apache-2.0,
at which point it becomes training data for whatever comes next. The rule-tier
figures are unaffected, being deterministic. The **model-tier** figures decay
from the day of publication, so the date is the floor under any claim they
support.

---

## Identity folds width but not case, and nobody decided that

`Ｙ0@a.example.com` and `Y0@a.example.com` share a placeholder. `Y0@…` and
`y0@…` do not. That looks like two decisions disagreeing and it is not: identity
is keyed on the same NFKC form the detectors already run on
([ADR 0004](adr/0004-offset-preserving-normalization.md)), so width folding is
**inherited**, and case folding is a decision nobody has ever made.

It probably should not be made globally — a mailbox is case-insensitive in
practice, and `AB-123` and `ab-123` can be two different assets. Which means
the answer, if there is one, is per entity type, and that is a bigger change
than it looks.

**Settled by** either an ADR saying identity folding is inherited from
detection and will never be extended, or a per-type folding rule with the
`EMAIL` case measured against the corpora.

---

## When does `mamori.protection-scope/1` freeze?

Three sibling projects read it. One has it implemented and verified against
real emitted bytes. Nobody has asked for it to be frozen, which under the
family's own rule — *a contract freezes because a consumer needed it to, not
because we want to freeze it* — is already an answer.

What stops it being frozen anyway is that **it changed twice on the day it was
written, and both changes came from the producer side**: the mixed mode, found
by writing the emitter and discovering that surrogates are enabled per entity
type; and the split contract identifier, found by realising a rule for
consumers could be carried by a name instead. Neither was visible while it was
only a design.

**The first condition proposed for it was wrong, and it is worth saying why.**

It was: *another project produces these records, and it works.* The reasoning
was sound — a contract with one producer has not finished finding out what
producers need. The problem is that no such project exists or is likely to.
`iriguchi`, `akashi` and `tsumugi` all consume; `musubi` was the one candidate
on anybody's roadmap and it turns out to be outside the contract entirely,
because it does not protect anything, so it never has a scope to describe.

A condition nothing can satisfy is a refusal wearing a condition's clothes —
which is this file's own rule about settling conditions, applied to a decision
instead of to a concern.

**Settled by** somebody writing a second emitter **from the document alone**,
without reading `mamori.provenance`, and its output validating against the
shipped schema in all three modes. That tests the thing the original condition
was reaching for — whether the document says enough to produce from — without
requiring anybody to have a reason to adopt it. It is an afternoon's work for
whoever does it, and it can be anybody.

Until then the contract is versioned, published, and free to change with a
version bump.

---

## `pip install mamori` still does not work

The README now says so and gives the install that does. The package has never
been published, and there has never been a job that would publish one.

**Settled by** the owner deciding whether the name should be claimed. Not a
defect to fix: publishing to a public index is a decision, and the CI job that
builds and checks the artifact is already in place either way.

---

## The entropy pass has no corpus to measure its cost on

`MamoriConfig(secrets="entropy")` runs the detector every secret scanner runs,
and the documentation says what it costs: a commit id, a content hash or a
base64 payload in a prompt becomes a refused request. That cost is stated from
synthetic cases -- `tests/test_entropy.py` holds a commit id, an encoded
sentence and a pangram -- and not from a corpus, because the corpora cannot
show it.

Twelve bundled datasets, 167 samples, both stances: every published figure is
identical with the pass on. Not because it is free. Between them the samples
hold eight runs of twenty or more key-shaped characters and none is generated.
An instrument that reports zero change is not evidence of zero cost; it is
evidence about the range it was given, and this is the same finding the
detection figures carry under
[nothing here was written by anybody else](#nothing-here-was-written-by-anybody-else),
arrived at from the secrets side.

The measure's own limits are known and pinned -- a UUID can never clear the
threshold, a pangram always does -- but a limit demonstrated on one string is
not a rate.

**Settled by** a corpus of documents that carry real secrets *and* real
checksums, commit ids, signed URLs and base64 payloads, labelled by somebody
who has not read the thresholds, with the over-redaction and leak rates of the
pass published against it at both stances and at `min_confidence` 0.0 and
0.6. The commissioned corpus already approved for the detection figures is the
natural place for it, if its brief is widened to include a code review and a
deployment ticket -- the two documents where a hash and a key sit in the same
paragraph.


## Should a policy know where the text is going?

An external review asked for `type x confidence x context x destination` as the
unit of decision: the same value allowed to a model on this machine and refused
to one across the internet.

The argument for it is real — those *are* different risks, and a deployment
running both endpoints currently has to hold two configurations and remember
which is which.

The argument against is that it doubles the states a deployment has to reason
about, and every one of them is a state where a value might be sent. A policy
with one axis is a table somebody can read; a policy with two is a table
somebody skims. Two configurations, chosen by whichever endpoint is being
called, expresses the same thing with the same number of decisions and no new
mechanism — and if that is genuinely worse, the way to show it is a deployment
that tried and found what it could not say.

**What would settle it:** one concrete case that per-type actions plus a second
configuration cannot express. Not a scenario — a configuration somebody tried
to write and could not.

## Should there be a privacy budget?

The same review proposed a sensitivity budget per conversation or destination:
this much may leave, and no more.

Two problems, and the second is the one that matters. First, nobody has a
number: there is no measurement in this project or outside it that says what a
sensible budget would be for a conversation, and a limit picked to feel careful
is a limit that gets raised the first time it fires.

Second, **a budget spent is a value sent.** The counter becomes a fact about
what has already left, which makes it worth reading and worth attacking, and it
has to live somewhere — which is a new thing to protect, in a library whose
argument is that it holds as little as possible. `mamori inspect` answers the
same question without keeping anything: ask before you send, and decide.

**What would settle it:** a measurement that says what a budget should be, and
a place to keep the counter that is not worse than what it protects.


## Two scopes both mint `<EMAIL_001>`

Placeholder numbering restarts per scope. So two independent sessions -- two
`mamori.protect()` calls, two conversations on a proxy -- both give their first
address the token `<EMAIL_001>`, and feeding one session's answer to the
other's `restore` returns *the other value*, silently: `unknown` is empty,
`is_clean` is true, and the restoration record says `clean`. The token is
perfectly well known. It just means somebody else.

Measured, and pinned in `tests/test_quickstart.py` so it is a stated property
rather than a surprise. An external review raised the same thing independently,
which is how it got written down here instead of only in a docstring.

**Why it is not fixed.** The only actual fix is distinct token names across
scopes, and every way of getting them costs something worse:

- A **process-wide counter** makes `<EMAIL_1043>` tell the external model
  roughly how many addresses this process has protected. That is metadata,
  leaked to exactly the party the library exists to keep things from, and in a
  long-running proxy it also walks towards the six-digit ceiling on a
  placeholder index.
- **The scope in the token** -- `<EMAIL_a3f9_001>` -- makes every placeholder
  longer and uglier in text a model has to read and reproduce intact, which is
  the thing tamper-tolerance already struggles with.
- **Detecting the crossing at restore time** is impossible from inside a scope:
  a token another scope also minted is indistinguishable from one's own.

So the rule is the boring one -- restore the text with the session that
protected it -- and it is stated in `SECURITY.md`, in
`mamori.quickstart`'s docstring, and in the test.

**What would settle it:** a case where the crossing happens without a caller
mixing up two sessions. The proxy binds a response to its conversation by
token, and `mamori.protect` hands back the session that made the placeholders;
if there is a path where the two get crossed without somebody passing the wrong
object, that is a defect in the path rather than in the numbering, and it
changes this answer.
