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

## The model tier has never been timed on a GPU

Every per-document figure this project ever published for the model tier was
CPU inference, because an interrupted Ollama update had left no CUDA library on
the machine. The numbers are withdrawn rather than corrected
([ADR 0025](adr/0025-measure-at-the-length-people-send.md) carries the lesson).

The accuracy figures are unaffected — the device does not change what a model
returns — so what is missing is only the cost side of the trade the README asks
readers to make.

**Settled by** repairing the install and re-running the benchmark, which is
somebody's decision to run an installer and not a code change.

---

## `pip install mamori` still does not work

The README now says so and gives the install that does. The package has never
been published, and there has never been a job that would publish one.

**Settled by** the owner deciding whether the name should be claimed. Not a
defect to fix: publishing to a public index is a decision, and the CI job that
builds and checks the artifact is already in place either way.
