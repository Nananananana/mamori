# Contributing

## Setup

[uv](https://docs.astral.sh/uv/) is the project standard.

```bash
git clone https://github.com/Nananananana/mamori.git
cd mamori
uv venv
uv pip install -e ".[dev]"
```

Plain `pip install -e ".[dev]"` into a virtualenv works too; `uv.lock` pins the
development toolchain.

Optionally, install the hooks:

```bash
pre-commit install
```

Before opening a pull request:

```bash
pytest && ruff check . && ruff format --check . && mypy
```

CI runs the same four on Python 3.10 through 3.13, on Linux and Windows, plus a
`pip-audit` pass and a job that installs the built wheel and uses it from
outside the source tree.

**Run them on `.`, not on the paths you touched.** `ruff` formats the Python
inside markdown fences too, so `ruff format --check src tests` passes while the
READMEs drift — which is exactly what happened, to two people on the same day,
and main was red for three commits before either noticed. The scope of a check
has to match the scope of what it protects, and a narrower spelling of it fails
silently by construction.

## The rules that are not negotiable

These come from what the library is, not from taste. A change that breaks one
of them needs to argue the case in an ADR first.

**`domain/` imports only the standard library.** No pydantic, no SQLAlchemy, no
LLM SDK. Every security-relevant decision lives there, and it stays testable
with no model, no network and no database. `mypy` will not catch a violation;
review will.

**Dependencies point inwards.** `interfaces → application → domain`, and
`infrastructure → ports`. `domain` knows about nothing else.

**Fail closed.** A new failure mode defaults to stopping the request. If you
find yourself writing `except ...: pass` in the protection path, that is the
bug.

**Nothing logs a value.** New fields holding original text get
`field(repr=False)`. Exception messages carry types and offsets, never values.
`tests/test_security_leakage.py` checks this by grepping real output — extend
it when you add a path that could leak.

**No dependencies without a reason.** v0.1 has none outside the test tooling,
and that is a feature: a privacy library nobody wants to audit is a privacy
library nobody uses.

## Tests first

The project is written test-first, and the tests are the specification. Write
the failing test, make it pass, then tidy.

Every detector rule needs three tests: something it catches, something it
deliberately does not catch, and the exact span it reports. The second is the
one that matters — a rule with no negative test is a rule nobody can safely
change later.

## Adding a detector rule

This is the most useful contribution, and the easiest to get subtly wrong.

1. Put it in the right place. If the format is the same in every language --
   an email address, a card number, a vendor-prefixed key -- it belongs in
   `detectors/patterns.py`. If it depends on the language, it belongs in that
   language's pack under `detectors/locales/`.
2. **Write a comment saying which way it leans.** Every rule is a
   precision/recall trade-off. `MY_NUMBER` uses a check digit because `\d{12}`
   would match every order number in the corpus; `POSTAL_CODE` requires 〒
   because `NNN-NNNN` is also a part number. Say what you chose and why.
3. Patterns run against NFKC-normalized text, so write them in ASCII and the
   full-width form matches for free.
4. **Do not use `\b` next to a rule that can touch Japanese text.** Kanji are
   word characters, so `\b\d{12}\b` never fires in `番号123456789012です`. Use
   explicit lookarounds: `(?<!\d)\d{12}(?!\d)`.
5. Beware greedy runs of kana. There is no word boundary to stop them, so a
   pattern that ends in `[一-鿿]{1,20}` will swallow the rest of the sentence.
   See `_COMPANY_BODY` for the tempered-class technique.
6. If the rule needs surrounding context to fire but the context is not itself
   sensitive, capture the value in a group and set `group=`. `password: hunter2`
   should redact `hunter2`, not the word `password`.
7. Add a `validator` when a checksum exists. It turns a hopeless pattern into a
   reliable one.

Then add the entity type to `docs/adr/` reasoning if it needs a new category,
and to the gap table in `SECURITY.md` if it has known blind spots.

## Adding an evaluation sample

The most useful thing after a rule. A sample is one line in
`src/mamori/evaluation/data/<locale>-core.json`, annotated inline:

```json
{"id": "ja-046", "annotated": "[[PERSON:田中太郎]]さんへ [[EMAIL:a@example.com]]"}
```

The loader strips the markup and computes the offsets, so you never count
characters.

Rules for samples:

- **Invent everything.** These files ship inside the wheel, so a real name or a
  real key here is published to everyone who installs mamori. A test refuses
  vendor-prefixed credentials outright; the rest is on you.
- **Label what a redactor would remove**, not what the rules currently find. A
  sample that leaks is a finding, not a bug in the sample.
- **A leaking sample needs a `note`** saying why, or the next reader will
  "fix" it by relabelling. A test enforces this.
- **Negative samples matter as much as positive ones.** Text with nothing
  sensitive is the only way over-redaction gets measured.

Then check what it did:

```bash
mamori eval --locale ja --show-leaks
```

If a change improves the numbers, raise the floors in
`tests/test_detection_quality.py`. That ratchet is the point. Never lower one to
make a change pass — if a change costs coverage, that is the finding.

## Adding an adapter

`tests/contracts.py` holds the conformance suites for `Detector`,
`DetectionPass` and `MappingStore`. Subclass the matching mixin and you inherit
the contract:

```python
class TestMyStore(MappingStoreContract):
    def make_store(self) -> MappingStore:
        return MyStore()
```

Scope isolation and index numbering are the two things store implementations get
wrong, and both are in the suite.

### Detector or pass?

Two ports, and the difference is one question: **does it need to see what else
was found?**

- **No** — write a `Detector`. Text in, findings out. Nearly everything belongs
  here, and the narrowness is deliberate: a rule set that cannot see the other
  rule sets' results cannot develop opinions about them.
- **Yes** — write a `DetectionPass`. It receives a `DetectionContext` carrying
  the text and everything earlier passes found. The co-occurrence pass is the
  example: it propagates a value confirmed by an honorific in one sentence to
  every other mention, which no rule looking at those mentions alone can do.

A pass goes at the end of the pipeline, after whatever produces the findings it
reasons over. Nothing enforces that ordering, because the pipeline cannot tell
the two kinds apart — a pass placed first simply sees nothing.

Do not deduplicate or resolve inside a pass. Report what you see, overlaps
included; `domain/resolution.py` settles conflicts once, in one place.

## Adding a rule to the wide tier

`RuleTier.WIDE` is for rules that match on shape alone: a run of digits, two
capitalised words, a long random-looking token. They find what nothing else can
and they also fire on order numbers and product names, so they run only under
the recall-first stance.

Before adding one, answer two questions in the comment above it:

1. **What does it find that no core rule can?** If the answer is "nothing", it
   belongs in the core tier with a proper anchor.
2. **What does it also fire on?** Say so plainly. A wide rule with no stated
   cost is a core rule somebody has not thought about hard enough.

Then measure. `mamori eval --stance balanced` and `mamori eval` are the two
halves of the trade, and a wide rule that raises over-redaction without lowering
the leak rate is not worth its noise.

Stoplists are the usual way to buy the precision back — `_KATAKANA_NOT_NAMES`
and `_NOT_NAME_WORDS` between them cut English over-redaction from 8.4% to 2.9%.
Neither will ever be complete, and neither has to be.

## Adding guidance

Guidance is what the rules taught, written for a model. It lives in
`src/mamori/prompts/guidance.py`, and each piece needs an id, because an id is
what lets somebody disable it without forking the library.

- **Namespace it**: `ja.person.honorific`, `en.company.no-suffix`.
- **Pick the right kind.** `FIND` is what counts as sensitive; `IGNORE` is what
  looks sensitive and is not; `BOUNDARY` is where a value starts and ends;
  `OUTPUT` is how to answer. They render as separate sections, because a model
  follows a short "find these" and a short "these are not those" far better than
  one long mixture.
- **`IGNORE` guidance is the valuable half.** Anything you had to add a stoplist
  for is knowledge a model needs too.
- **Give examples.** A model follows `田中さん -> 田中` more reliably than a
  sentence describing the same thing.

Check the result with `mamori prompt detection`, and remember that a locale-
tagged rule only reaches a prompt rendered for that locale.

## Adding a setting

A new switch goes on `MamoriConfig` as a field, gets coerced in `from_mapping`,
and is printed by `mamori config`. Three rules:

- **The default must be the fail-safe value.** `min_confidence` defaults to
  `0.0` and co-occurrence to on, because reducing coverage is a decision
  somebody makes, not one they inherit.
- **Document it as a trade, not an improvement.** Say what it costs as well as
  what it buys.
- **Unknown keys stay refused.** Do not add a lenient mode. A typo in a privacy
  setting that silently does nothing is the worst available outcome: the user
  believes they tightened something and did not.

## Adding a language

Create a module under `src/mamori/infrastructure/detectors/locales/`, export a
`LocalePack`, and register it in that package's `__init__.py`. Tests go in
`tests/test_detectors_<code>.py` and use `types_in(text, "<code>")` so they
exercise your pack alone.

The part that needs thought is `triggers` and `suppressed_by`. A pack runs when
the text contains one of its trigger scripts and none of its suppressing ones.
If your language shares a script with one already present, say what distinguishes
them — the Chinese pack stands down on kana for exactly that reason. If nothing
distinguishes them, let both run: over-detecting costs answer quality, and
missing a name costs what the library exists to prevent.

## Commits and pull requests

Small commits, one concern each. The subject line says what changed and why in
one line. Group unrelated changes into separate pull requests — a detector rule
and an architecture change reviewed together get reviewed badly.

Update `CHANGELOG.md` under `Unreleased` for anything a user would notice.

## Architecture decisions

Anything that changes a boundary, a default, or a security property gets an ADR
in `docs/adr/`. Copy the shape of an existing one: context, decision,
consequences, and — this is the part people skip — what the decision costs.

## Reporting a detection gap

Open an issue with an example of text that slips through. **Use invented data.**
Do not send a real name or a real key to report a bug in a privacy tool.

If the gap is in a category `SECURITY.md` already lists as a known blind spot,
say so — it is still worth filing, because a concrete example is what turns a
known gap into a fixed one.
