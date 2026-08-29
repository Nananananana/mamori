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
`pip-audit` pass.

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
