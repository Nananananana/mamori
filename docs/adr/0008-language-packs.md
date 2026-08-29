# 8. Language packs, selected by script

**Status:** accepted

## Context

v0.1 shipped one set of rules, Japanese-first with a few English patterns mixed
in. Supporting more languages by adding to that set does not work, for two
separate reasons.

The first is precision. A rule that is right in one language is noise in
another. `Dear ...` anchors an English name and means nothing in Japanese. A
five-digit run is a US ZIP code, a Chinese postcode prefix, and an order number.
Mixing them means every document is scanned with rules that cannot fire and can
only produce false positives.

The second is specific and worse. Chinese and Japanese share Han characters. The
Chinese surname list contains 林, 森, 高, 田; so does the Japanese one. Run both
over Japanese prose and ordinary words come back as people. There is no way to
tell them apart character by character.

## Decision

Rules are grouped into **language packs**. A pack declares its rules plus the
evidence for running it:

- `triggers`: scripts whose presence makes the pack worth running.
- `suppressed_by`: scripts whose presence means it is not, whatever the triggers
  say.

`AdaptiveLocaleDetector` computes which scripts a text uses and runs the packs
that apply. Language-independent rules -- email, card numbers, credentials,
private addresses -- live outside the packs and always run.

The Chinese pack is `suppressed_by` kana. That is the one decisive piece of
evidence available: kana appear in Japanese and never in Chinese. Text
containing kana is Japanese, so the Chinese rules stand down.

Text written purely in Han could be either, and both packs run.

**Every pack is enabled by default.** `locales=["ja"]` narrows it; nothing
narrows it automatically. An unexpected language in a document is exactly the
case nobody redacted by hand, so the default errs towards running too much.

## Consequences

Adding a language is adding one module and one registry entry, with no risk to
the languages already there — each pack's rules are tested against its own
language.

`mamori locales` prints the packs, their rule counts and when each runs, so the
selection is inspectable rather than magic. The detector name recorded on every
entity is the pack code, so a report says which language's rules fired.

Han-only text is scanned by both CJK packs and over-detects. That is the
intended direction: a spurious placeholder costs answer quality, and a missed
name costs the thing the library exists to prevent.

## What it costs

Script detection is not language identification, and does not pretend to be. It
cannot tell Chinese from Japanese in a Han-only sentence, so it does not try —
it runs both. A real language classifier would be more precise and would also be
a model, a dependency, and a component that can be wrong in ways nobody can
predict from the source. The rule as written can be read in one sitting and
reasoned about exactly.

Chinese personal names are the least precise rule in the library. Chinese has no
word boundary and no honorific requirement, so a surname followed by one or two
characters is often an ordinary word — 高兴 is *happy*, not a person named Gao.
A stopword list covers the common collisions and will never cover all of them.
The rule is `LOW` confidence and is documented as such; closing this properly
needs a model.

English personal names have the opposite problem. Two capitalised words are also
every product, city and department, so each English name rule is anchored on a
title, a salutation, a sign-off or a label. A name in the middle of a sentence
with no marker is not detected, and no regex will fix it.
