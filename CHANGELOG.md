# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the version is below `1.0.0`, the public API may change in a minor release.

## [Unreleased]

## [0.13.0] - 2026-08-30

Japanese and Chinese, which the document sets have said are the weakest since
0.9. Four rule changes were tried; two are kept, two were measured out again
the same day, and the two that failed are the more interesting half.

### Added

- **A Japanese label anchor for Han names.** `差出人: 横山` was missed because
  the label rule added in 0.9 reached katakana and stopped there, so `ja-doc-006`
  leaked the same name twice for four releases.

- **`項目X` / `项目X` without a colon**, in Chinese. The Japanese equivalent
  landed in 0.9 and the Chinese one did not, so `zh-doc-002` leaked a codename
  for two releases because only one of the two languages got the fix.

- **Customer-facing identifier labels** in both languages -- `お客様番号`,
  `客户编号`, `受理号` and the rest. The employee-id rules had the internal
  labels only.

- **Two more Chinese documents**, one of which exists specifically to catch the
  mistake described below.

### Measured out again

Both of these looked right, improved the numbers, and were reverted.

- **A "not preceded by a Han character" guard**, to stop `里程碑` being read as
  a person called `程碑`. It lifted `zh-core` precision from 0.903 to 0.933 and
  cost nothing measurable on any of the six sets.

  It was reverted because a probe *outside* the corpus lost names entirely:
  `这是张伟。` and `昨天和王强，我们谈过。` both came back untouched. Chinese has
  no spaces, so a name is usually preceded by a Han character, and the datasets
  happened to place all of theirs after punctuation. Trading a visible false
  positive for invisible misses is the wrong direction for this library, and
  the corpus was not able to say so. `zh-doc-005` exists so that the next
  attempt is measurable.

  This is the case regular expressions cannot settle, and it is now the
  concrete argument for the optional morphological adapter rather than a
  general one.

- **A Chinese `负责人：` label rule.** It changed neither the leak rate nor
  recall -- the surname rule already reaches every name a label introduces,
  because Chinese personal names begin with a character from a closed set --
  and it cost precision by reading `收件人：客服` as a person called "customer
  service". A label is weaker evidence than a surname dictionary here, which is
  the opposite of the Japanese case.

### Fixed

- `mamori audit` reported the two new identifier rules as never having fired,
  within minutes of them being written -- the same failure as 0.12, caught this
  time by the tool built for it rather than three releases later. Samples added
  in both languages.

### Changed

Every set is better or unchanged at the default stance, and the two document
sets that were weakest moved most:

| | leak before → after | recall |
|---|---|---|
| `ja-docs` | 1.83% → **1.50%** | 0.951 → **0.967** |
| `zh-docs` | 6.11% → **4.41%** | 0.903 → **0.913** |

`zh-docs` over-redaction rose from 0.78% to 1.84% and `ja-core` from 2.50% to
2.78%, because the new samples are harder than the ones they joined rather than
because anything got worse. That is what a corpus growing towards realism looks
like.

## [0.12.0] - 2026-08-30

Saying why. Every detection has recorded which rule found it since 0.1.0 and
almost nothing surfaced it, so "why was this redacted?" was awkward to answer
and "why was this **not** redacted?" was impossible.

### Added

- **`mamori trace`** -- every candidate the pipeline considered and what became
  of it: kept, below the confidence threshold, ruled away by a correction, or
  displaced by an overlapping detection that won. Each displacement says which
  preference decided it, which makes
  [ADR 0005](docs/adr/0005-overlap-resolution.md) inspectable rather than
  merely written down.

  ```text
  where     type            rules         conf  outcome
  5:11      PERSON          en            0.90  kept
  59:69     IDENTIFIER      universal     0.50  displaced -- lost to PHONE (higher severity)
  ```

  And then the harder half. It runs the *other* stance and says what the wider
  rules would have caught -- as a shape, never a value. When neither stance
  finds anything more it says so, and points at a correction or the model tier
  rather than leaving somebody guessing. See
  [ADR 0027](docs/adr/0027-say-why-and-say-why-not.md).

- **`mamori audit`** -- which rules carry the load over a corpus, and which
  have never fired once. Rules are run individually rather than through the
  pipeline: a rule that fires and always loses an overlap looks identical to
  one that never fires, and those are different problems. `--file` audits your
  own text, which is the more useful question.

- **Stable rule identifiers** (`en.PERSON.2`, `universal.EMAIL.1`), derived
  from pack, type and declaration order, with an explicit `name=` available
  where a rule deserves one.

- **`ProtectionResult.trace`**, off by default because it costs a list of every
  candidate. It carries masked previews and never values -- a trace is exactly
  what somebody pastes into a bug report, and a test pins it.

### Fixed

`mamori audit` found these on its first run, which is the point of it.

- **Three credential rules shipped in 0.10 had never been measured.** The prose
  password rules -- `the password is X`, `パスワードは X`, `密码是 X` -- had no
  dataset sample in any language. Credential detection, added without
  evaluation coverage, in the release that was about not trusting unmeasured
  things. Samples added in all three languages, including the negatives that
  matter more: "my password is fine" must not stop a request.

- **A UK-shaped phone rule had never fired**, for the same reason. Sample
  added.

- **A stale published figure.** The `ja-docs` leak rate given in 0.9 was
  measured before a fix that landed in the same release: published at 2.49%,
  actually 1.83%. `SECURITY.md` and the READMEs carry the corrected tables.

### Changed

- The remaining ten never-fired rules are the vendor-prefixed credential rules,
  which cannot have samples -- a literal key in a file that ships inside the
  wheel trips the secret scanner of everyone who clones the repository.
  `audit` says so rather than listing them beside genuine findings, and a test
  pins that nothing *else* is dead, so the next unexplained one is visible.

- The roadmap is revised in
  [proposal 0002](docs/proposals/0002-the-road-to-1-0-revised.md), against a
  set of proposals from the project owner: traceability brought forward to
  here, Japanese and Chinese precision next, multi-turn consistency after that,
  and a fail-closed stance and CI linter before 1.0. A `mamori.yml` is declined
  and [ADR 0012](docs/adr/0012-configuration-without-a-format.md) says why;
  Markdown and JSON structure preservation was investigated and found to be
  largely unnecessary already.

## [0.11.0] - 2026-08-29

Surrogate values: `山田一郎` instead of `<PERSON_001>`, off by default. On the
roadmap since 0.4 and deferred four times, because it is an answer-quality
feature and everything above it was a correctness one.

### Added

- **Surrogates, as a policy option.** Some models reason visibly worse about a
  page of tokens -- they lose track of who is who, they occasionally refuse to
  draft a reply *to* a placeholder, and they sometimes describe the token
  instead of using it. A readable value usually gets a better answer.

  ```json
  {"surrogates": ["PERSON", "EMAIL", "PHONE"]}
  ```

  ```text
  you wrote   Dear Jane Doe, reach me at jane.doe@example.com or 415-555-0198.
  sent        Dear Alex Rivera, reach me at a.person@example.com or 415-555-0142.
  restored    Dear Jane Doe, reach me at jane.doe@example.com or 415-555-0198.
  ```

  See [ADR 0026](docs/adr/0026-surrogates-trade-obviousness-for-readability.md).

- **Reserved ranges wherever any exist.** Emails use `example.com` and
  `example.org` (RFC 2606), addresses use the TEST-NET blocks of RFC 5737,
  telephone numbers use the ranges kept aside for fiction. A structured
  surrogate that escapes is not only harmless but identifiable: somebody who
  finds `192.0.2.10` in a log can look it up and learn it means nothing
  anywhere. Each pool records why it is safe, and `mamori privacy` prints it --
  "reserved for documentation" and "a plausible name we invented" are very
  different promises.

- **`mamori demo --scenario surrogates`**, which shows the trade including the
  failure, not just the happy path.

### The reason it is off by default

**An unrestored placeholder is obvious. An unrestored surrogate is not.**
Somebody reading `<PERSON_001>さんへ` knows at once that something did not
finish; somebody reading `山田一郎さんへ` reads a sentence about a person and
has no way to tell it is the wrong one.

Restoration loses its tolerance, and that cannot be avoided. A placeholder is
recognised by shape, so the restorer copes with `PERSON_001`, `<person_001>`
and `＜PERSON_001＞`. A surrogate is a name: it matches exactly or it does not.

What mamori can do is say so. `RestorationResult.missing` lists every mapping
that did not come back, so the failure is detectable even when it is not
visible. `mamori privacy` warns whenever surrogates are on -- twice when an
invented pool is in use -- with a non-zero exit status, so a deployment check
can fail on it.

**Nothing is reserved for personal names**, and no design fixes that. It is
stated in the module, in the report, in the demo and in all three READMEs.

### Design notes

- **Chosen by allocation order, never derived from the value.** Hashing the
  original would be tidier and would open a correlation channel: the same real
  person would get the same fake name in every document, so an observer holding
  two protected documents could tell they concern the same individual. Order is
  what keeps a surrogate from carrying information about what it replaced.

- **A surrogate never collides with the text it enters.** If the pool's choice
  already appears in the document, the next one is used -- restoring the wrong
  occurrence would corrupt the caller's own words, which is the one hazard here
  that would do damage rather than merely fail.

- **An exhausted pool falls back to a placeholder**, which is always safe.

- **No pool covers a credential.** There is no plausible stand-in for a
  password, and credentials are blocked rather than substituted anyway.

- `Mapping` gains `surface`, empty for every mapping mamori makes by default.
  It is excluded from `repr` alongside the original value: a surrogate is not
  sensitive, but the *pair* is exactly the lookup table this library exists to
  keep off other machines.

## [0.10.0] - 2026-08-29

A demo you can actually run, a guide to measuring mamori on your own text, and
a bug in the measurement harness that had been quietly corrupting the model-tier
numbers since 0.7.0.

### Added

- **`mamori demo`, rebuilt.** Five short scenarios, each answering a question
  somebody actually has: what the model sees and whether you get your words
  back, what happens when a placeholder arrives split across streamed chunks,
  whether any of this survives a document rather than a sentence, what to do
  when it gets one wrong, and what happens when there is a password in the
  text.

  ```bash
  mamori demo                      # the tour
  mamori demo --file draft.txt     # on your own text
  mamori demo --scenario stream
  ```

  The round trip now names **what found each value** -- the rule set and its
  confidence -- so "why was this replaced?" has an answer.

- **`mamori demo --live`** sends the protected text to a model you name and
  restores the answer. The whole round trip, nothing simulated:

  ```bash
  mamori demo --live --model llama3.1:8b --api http://localhost:11434/v1/
  ```

  Any OpenAI-compatible endpoint, and `--api-key-env` for a hosted one. The
  trust boundary deliberately does not apply: it refuses an external
  *detector*, which sees text before it is protected, and this is the service
  you chose, which sees protected text only.

- **[docs/measuring-your-own-data.md](docs/measuring-your-own-data.md)**, which
  the 0.9 plan owed. How to build a labelled dataset, what to put in it
  (documents, not sentences), how to compare two configurations -- and, first,
  the warning that such a file is full of your real data and belongs in
  `.gitignore` before it exists.

- **A password written in prose is now detected.** `password: hunter2spring`
  was caught and `the password is hunter2spring` was not, in all three
  languages -- and prose is how somebody pastes a credential into a chat
  window. A validator keeps "my password is fine" from blocking a request:
  a prose match needs a digit, a capital, a symbol, or length no ordinary word
  reaches. A short all-lowercase password is missed by this, which is the right
  way round.

### Fixed

- **The evaluation harness left the co-occurrence pass out of every cached
  model run.** `mamori eval --cache` rebuilt the detection pipeline by hand,
  and `build_pipeline` defaults co-occurrence to off while
  `MamoriConfig.detectors()` passes one in. So the model was scored against a
  baseline that had a pass the candidate lacked, from 0.7.0 onwards.

  Found by a result that could not be true: adding a model *increased* the leak
  rate on a document, and three propagated detections had vanished. The
  regression check written in 0.7.0 -- "for a candidate that only adds, this
  must be empty, and it is worth checking rather than assuming" -- caught the
  harness rather than the library.

  Fixed by deleting the second assembly path, not by correcting it.
  `MamoriConfig.detectors(provider=...)` substitutes the provider and leaves
  everything else alone, so there is one place that knows how a pipeline is
  built. A test pins that co-occurrence survives the substitution.

  **The published conclusions survived re-measurement** -- at 8B the model
  raises English recall and does nothing for Japanese -- but the over-redaction
  figures moved and the comparison was not sound when it was published.
  `SECURITY.md` and the READMEs carry the corrected table and say why.

- **A measurement where every model call failed reported a clean zero delta.**
  A 12B model timed out on every request; the pass degraded to nothing exactly
  as designed, the comparison measured the rules against themselves, and the
  output said `+0.00%` on every line -- which reads as "the model had nothing
  to add", a conclusion it had not earned. `mamori eval` now counts provider
  failures and refuses to exit clean:

  ```text
  WARNING: the model failed on 4 of 4 request(s).
  A model that never answers produces exactly the numbers above.
  ```

### Changed

- **The open question from 0.7 is still open, and now has a reason.** Whether a
  model above 8B changes the model-tier table could not be measured here:
  `gemma4:12b` times out on this hardware, and a run of 49 samples does not
  complete. That is not evidence about the model, only about the machine, and
  it is recorded as such rather than as a result.

## [0.9.0] - 2026-08-29

Every quality number this project published came from 123 samples with a median
length of 28 to 44 characters. mamori is for documents. This release measures
it at the length people actually send things, and the rules did not survive
first contact.

### Added

- **`en-docs`, `ja-docs`, `zh-docs`: business documents at real length.** Reply
  chains with quoted blocks, meeting minutes with attendee lists, support
  tickets with log excerpts, a CV, a contract extract, a technical note with
  almost nothing to protect, and a document with an instruction to a model
  buried in it. The core sets are unchanged -- they are good regression guards
  and cheap to run -- and the floors now cover all six. See
  [ADR 0025](docs/adr/0025-measure-at-the-length-people-send.md).

- **An anchored katakana name rule**, at the *core* tier: a middle dot, an
  honorific, or a label. `ジョンさん` was not detected by any rule before this
  release, while `ホスト` was reported as a person.

- **A project name after `プロジェクト` without a colon**, which is how it is
  written in a heading.

### Fixed

Four detection bugs, every one of them invisible at 44 characters and serious
in prose:

- **A name spanned a blank line.** The wide English name rule joined its words
  with `\s+`, so a heading and the first word of the next paragraph became
  `Headcount\n\nOne` -- a person. Every document with headings in it.

- **A legal suffix read as a surname.** `Umbrella Ltd` matched the wide name
  rule and `Where Umbrella Ltd` matched it more widely still, so the anchored
  company rule lost the span to a shape guess: the value was protected under
  the wrong type, with the wrong placeholder, under a different policy
  category, and an ordinary word was redacted with it.

- **An address at the end of a sentence was missed.** The internal-IP rule
  refused any trailing dot, to avoid matching the first four parts of
  `1.2.3.4.5`. A full stop is also a trailing dot, so `on 10.0.4.31.` found
  nothing. An address is never followed by a full stop in a one-line sample and
  usually is in a document.

- **The Japanese wide name rule reported 37 loanwords as people** across eight
  documents -- ホスト, プール, ゲートウェイ, ノード, エンジニア -- and not one
  true positive the anchored rules did not already have. It was filtered by a
  stoplist whose own comment admitted it "will never be complete".

  It was fixed by deleting the rule, not by extending the list. Japanese
  business writing coins loanwords faster than anybody maintains a list, so
  such a list encodes one author's vocabulary and is wrong for the next
  document. **A bare katakana run is not weak evidence of a name; it is no
  evidence of one, and the wide tier is for weak evidence rather than for
  none.**

- **The proxy answered an unknown path without reading the request body**, so a
  client that sent one could see a reset connection instead of the 404 it was
  given.

### Changed

- **Nothing regressed and the fragment sets improved too:**

  | recall-first | leak | over-redaction | precision |
  |---|---|---|---|
  | `en-core` | 0.67% (unchanged) | 1.44% -> **0.78%** | 0.938 -> **0.979** |
  | `ja-core` | 0.00% (unchanged) | 3.11% -> **2.42%** | 0.908 -> **0.937** |
  | `ja-docs` | -- | 6.08% -> **1.06%** | 0.600 -> **0.934** |

- **Documents leak several times more than fragments, and it is published.** At
  the default stance `en-docs` leaks 3.55% against `en-core` at 0.67%, and
  `zh-docs` 6.11% against `zh-core` at 0.00%. The old figures were not wrong;
  read alone they described the library at its easiest.

- **At the balanced stance, `en-docs` leaks 20.29%** -- a fifth of the
  sensitive characters, because a document is full of names with nothing
  anchored beside them. It is pinned as a floor so it stays visible rather than
  being discovered by somebody's deployment, and it is the strongest evidence
  this project has for why recall-first is the default.

- The quality floors are keyed by dataset rather than by locale, and there are
  twelve. A rule change that helps sentences and hurts documents turns the
  build red, which nothing could do before.

## [0.8.0] - 2026-08-29

The operator gets the last word. Until now everything mamori did was decided by
mamori, and somebody watching `Dear Monday,` become a `<PERSON_001>` had no
recourse short of forking the rule set.

Borrowed, with thanks, from the sibling
[kiseki](https://github.com/Nananananana/kiseki) project's ADR-0044.

### Added

- **Corrections: an append-only log of values you have ruled on.**

  ```bash
  mamori correct Monday --never --note "a weekday, not a name"
  mamori correct Acme   --always COMPANY_NAME --note "trading name, no suffix"
  mamori corrections
  ```

  The latest word about a value wins, so undo is another correction and nothing
  is ever deleted. Applied at read time: nothing rewrites a rule, nothing edits
  a prompt, and removing the log restores exactly the previous behaviour. See
  [ADR 0024](docs/adr/0024-corrections-are-appended-applied-at-read.md).

  `--always` closes, for one organisation's data, a gap no pattern can close in
  general: a trading name with no legal suffix (`Acme`, `田中商事`), documented
  since 0.1.0. It carries `CERTAIN` confidence -- a rule is a guess about a
  shape and a model is a guess about a sentence, and an operator typing a value
  into a log is neither -- and adds only what nothing else already covers.

- **`--never` is the only thing in mamori that reduces what it protects**, so
  the exception is kept narrow. Every exclusion is named by `mamori privacy`
  and reported as a warning with a non-zero exit status, so a deployment check
  can fail on one nobody meant to ship.

- **A credential can never be ruled away.** Enforced in three independent
  places, because one is not enough: the domain refuses an exclusion naming a
  credential type; `CorrectionLog.excludes` refuses to apply one at read time
  whatever a hand-edited file says; and `mamori correct` runs the value through
  the detectors **before writing anything**. That last one exists because a
  `never` ruling names no type at all, and because appending first would leave
  the credential sitting in a file on disk -- the outcome this library exists
  to avoid.

- **`docs/proposals/`**, starting with
  [the road to 1.0](docs/proposals/0001-the-road-to-1-0.md). ADRs record
  decisions already made; a plan is neither, and a roadmap in a README is a
  list without its reasoning. The roadmap is revised there in light of what
  0.7 measured, and says what is deliberately *not* planned.

- **A promises test that a command which reads writes nothing.** `kiseki`'s
  ADR-0070 found a command in that project quietly keeping a snapshot every
  time somebody ran it to look at something, and no test caught it. Ten mamori
  commands are now checked for leaving the working directory untouched and for
  being safe to run twice. All of them already were; the point is that they
  stay that way.

### Changed

- `MamoriConfig` gains `corrections`, accepting either a path to a log or the
  entries themselves. A path is a log somebody appends to; entries in the
  settings are rulings that travel with the configuration and get reviewed
  alongside it.

- `PrivacySession` and `ProtectionService` accept a `CorrectionLog`. Exclusions
  are applied *before* overlap resolution, not after: a corrected-away value
  that could first win a span and then vanish would leave a hole where a real
  detection would have been.

### Fixed

- `MamoriConfig.from_mapping` silently dropped any key without an explicit
  converter, which is how the new `corrections` setting did nothing the first
  time it was tried. Found immediately, and worth recording: this is the exact
  failure the module's "unknown keys are refused rather than ignored" rule
  exists to prevent, arriving from the other direction.

## [0.7.0] - 2026-08-29

The model tier gets measured for the first time, and the numbers say it was
not doing what the documentation claimed. Both are fixed here: the contract
that was throwing its answers away, and the paragraph that described an
intention as a result.

### Fixed

- **A model reports values now, not character offsets.** Asked for offsets
  against 49 English samples, a local 8B model got **0 of 52 right** -- while
  51 of those 52 values were genuinely in the document, most off by a handful
  of characters. `'John Smith' said 4..13, actually 4..14`. The verification
  step then discarded them all, correctly and uselessly, which means **the
  model tier contributed essentially nothing from 0.4.0 through 0.6.0**.

  Character offsets are close to the one thing a tokeniser-based model cannot
  produce. The value is now the answer and mamori locates it -- at every
  occurrence, on word boundaries where the script has them. Offsets are still
  honoured when volunteered and already correct, which keeps the one case a
  search cannot resolve: the same value twice, only one meant.

  The guarantee is unchanged and stronger: mamori never creates a span it did
  not locate itself, so a hallucinated value is still dropped. See
  [ADR 0022](docs/adr/0022-a-model-reports-values-not-offsets.md).

  Measured effect at the balanced stance: English leak rate 2.01% to **0.67%**,
  closing `en-006`, the unanchored name that has been a documented gap since
  0.1.0.

- **`OTHER_SENSITIVE` was being used as a dustbin.** Every English false
  positive was that type -- a weekday, a public IP, an error code, a whole
  sentence about revenue. The default policy *blocks* it, so those would have
  stopped requests rather than replaced a value. A guidance rule saying what
  the type is for, what it is not for, and that it stops the request halved
  over-redaction from 8.80% to 4.43%.

- **`mamori eval` honoured no configuration.** It built a rules-only pipeline
  and ignored `--config` entirely, so the harness that existed since 0.2.0 had
  never been pointed at the thing it was most needed for.

### Added

- **`mamori eval --compare`** scores the rules alone alongside the configured
  run and prints the delta, naming the individual samples that changed. An
  aggregate says something moved; the list says what, and whether you believe
  it. Tuning against an aggregate fits a prompt to a number instead of to a
  language.

- **`mamori eval --cache`** remembers what the model answered, keyed on the
  model *and the prompt*, so re-running is free and rewriting one line of
  guidance invalidates exactly the answers that depended on the old wording.
  **It writes to disk**, which is why it lives in the evaluation package,
  is named by no configuration key, and has a test in `test_promises.py`
  pinning that -- the storage claim in `mamori privacy` stays true for every
  configuration a user can express.

- **`mamori eval --replay`** answers only from the cache, so a change to
  scoring can be checked without the model's variance in the way.

- **`domain/occurrences.py`**, shared with the co-occurrence pass, which was
  already locating known values for the same reason.

### Changed

- **The documentation says what was measured.** The README claimed the model
  tier reached "an English name in running prose, a Chinese given name, a
  codename". Measured, at 8B: it reaches the English name. It does nothing for
  Chinese, where the rules were already at 1.000 recall, and nothing for
  Japanese, while costing over-redaction in all three. At the recall-first
  default it does not move the leak rate at all and costs roughly six times the
  over-redaction. See [ADR 0023](docs/adr/0023-the-model-tier-is-measured.md).

  | balanced, `llama3.1:8b` | leak: rules -> +model | over-redaction | precision |
  |---|---|---|---|
  | `en-core` | 2.01% -> **0.67%** | 0.66% -> 4.43% | 1.000 -> 0.855 |
  | `ja-core` | 0.71% -> 0.71% | 0.00% -> 5.41% | 1.000 -> 0.868 |
  | `zh-core` | 0.00% -> 0.00% | 2.55% -> 10.18% | 0.964 -> 0.871 |

- **One model proposal can produce several detections**, since a value judged
  sensitive is sensitive wherever it appears. A behaviour change for anyone
  counting entities.

- The CI quality floors stay rules-only. Pinning one to a model's output would
  make the build depend on a model being installed and on it answering the same
  way twice.

## [0.6.0] - 2026-08-29

The proxy, and the machinery that says what it does. An application that
already talks to an OpenAI-compatible API now moves behind mamori by changing
one string -- and the privacy claims that makes reasonable are answerable from
the command line and checked by the test suite.

Several ideas in this release are borrowed, with thanks, from the sibling
[kiseki](https://github.com/Nananananana/kiseki) project.

### Added

- **`mamori serve`: an OpenAI-compatible proxy.** Point an existing
  application at it and change nothing else. Every message is protected on the
  way out, the reply is restored on the way back, and the briefing telling the
  model to leave placeholders alone is prepended automatically. See
  [ADR 0018](docs/adr/0018-a-proxy-on-the-standard-library.md).

  ```bash
  mamori serve --upstream https://api.openai.com/v1/
  ```

  Built on `http.server`, so the runtime dependencies stay zero. It binds to
  127.0.0.1 -- reaching it from another machine is a deliberate act and a
  warning at startup, because anything that can reach the port can send
  documents through it. Streaming is supported: a placeholder arriving as
  `<PER`, `SON_0`, `01>` is held and restored as it passes. The system prompt
  is protected too, since an organisation's briefing is exactly the context
  that should stay local. One mapping scope per request, discarded with it.

  It fails closed. A blocked credential, an unparsable body, or a path it does
  not recognise are errors returned to the caller, and none of them forward
  anything.

- **`mamori privacy`: what your configuration actually does.** Computed from
  the settings in front of it, not from the README -- which types are blocked
  and which are pseudonymized, where a detection model is and whether the trust
  boundary admits it, what is kept and where. Anything that widens exposure is
  a warning and a non-zero exit status. See
  [ADR 0019](docs/adr/0019-privacy-is-a-report-not-a-promise.md).

  It separates what is measured from what is true by construction from what
  mamori cannot check for you, and prints, beside each construction claim, the
  name of the test that fails if it stops being true.

- **`tests/test_promises.py`: those tests.** `socket.connect` and its
  neighbours are replaced with functions that raise, and the whole default path
  then has to run without them -- protection, restoration, every language pack,
  the evaluation harness, the command line, importing the package. A future
  dependency that dials out fails in a build rather than in a deployment. The
  guard has its own test that it can still trip. Mappings staying in memory,
  values staying out of diagnostics, scope-bound restoration, keys never in
  configuration, and the model-only-adds bound are each a class. A final class
  checks that every claim in the report names a test that exists. See
  [ADR 0020](docs/adr/0020-the-promises-are-checked-by-machine.md).

- **Optional batching on the provider port.** `BatchLLMProvider` is advertised
  by implementing it, the same shape as `supports_structured_output`. A shared
  model on another machine is dominated by round trips, and the windows of one
  document should not cost ten of them. Nothing existing changes.

### Changed

- **A long document is scanned in overlapping windows instead of being
  skipped.** This was a recall hole with a length threshold on it: over the
  limit, the model pass silently returned nothing, so the documents most likely
  to hold a name no rule can anchor -- a long thread, a contract, a transcript
  -- got patterns only, with nothing in the output to say so. Windows overlap
  by 400 characters, comfortably more than any entity this library detects, so
  an address cut by one boundary is whole inside its neighbour; cuts prefer a
  paragraph or sentence boundary, in the CJK forms as well as the ASCII ones.
  See [ADR 0021](docs/adr/0021-a-long-document-is-windowed.md).

  The offset arithmetic lives in one place in the domain layer, because a
  detection at position 12 of the third window is not at position 12 of the
  document and getting that wrong would cut characters out of the wrong
  sentence. Both of its properties -- every character appears in some window,
  every window is a real slice of the document -- are tested with Hypothesis
  over arbitrary text.

- **`Upstream` joins its base URL the way an OpenAI client does.** The path
  appended is relative to a base URL that already ends at the version segment,
  so `http://localhost:11434/v1/` no longer becomes `/v1/v1/`. A base URL with
  no path at all gets `/v1` added rather than producing a 404 for the caller to
  work out.

- **The `MAMORI_` prefix note now appears in `mamori privacy` too**, alongside
  everything else about where a key may live.

- **The privacy report describes a configuration it cannot build.** Counting
  the detectors is also what refuses an endpoint outside the trust boundary, so
  the report used to raise on exactly the settings somebody would run it to
  understand. It now reports the refusal as a warning and says the detector
  count is unknown rather than guessing one.

### Fixed

- A document over `max_input_characters` is no longer silently unscanned by the
  model tier. See above; this is the substance of the release for anybody who
  runs a model.

## [0.5.0] - 2026-08-29

The model tier stops assuming a laptop. Where the model runs, and which library
talks to it, are both configuration now -- and the layering that keeps all of
this from tangling is enforced by a test instead of a diagram.

### Added

- **A trust boundary, replacing the localhost check.** The realistic deployment
  is one high-specification machine the team shares, not a model on every
  laptop, and 0.4.0 made that impossible. A host is now classified by
  inspection -- `loopback`, `private`, `declared`, `external` -- and a boundary
  decides what is admitted. The default, `private_network`, accepts a model on
  this machine *and* a model at `http://llm01.corp:8000/v1/`, and refuses a
  public API. See
  [ADR 0015](docs/adr/0015-a-trust-boundary-not-a-localhost-check.md).

  ```json
  {"llm": {"model": "qwen2.5:72b", "base_url": "http://llm01.corp:8000/v1/"}}
  ```

  A refusal arrives when the provider is built, not on the first document, and
  the message says what was classified and which of the two remedies applies.
  `trusted_hosts` names an exception; `"trust": "anywhere"` removes the check
  and is visible to anyone reviewing the config.

- **A provider registry, a callable provider, and `LLMEndpoint`.** Switching
  models is a field. Switching the *client library* is one line, and adds no
  dependency here: `CallableProvider(fn)` wraps anything already loaded in the
  process, and `register_llm_provider(name, factory)` makes an alternative
  selectable from configuration. The bundled OpenAI-compatible provider still
  speaks `urllib`, so the runtime dependencies remain zero. See
  [ADR 0016](docs/adr/0016-the-model-and-the-client-are-both-replaceable.md).

- **`mamori llm`** -- where the model is, whether the boundary admits it, and
  with `--check`, whether it answers. Worth running once after pointing it at a
  machine down the hall. `mamori config` now shows the model too.

- **`LLMSettings`, and `MamoriConfig.session()`.** Settings assemble a session;
  a session never reads settings. A literal `api_key` in a config file is
  refused with a pointer to `api_key_env`, so a key cannot arrive by being
  committed.

- **Retries with backoff** on transient endpoint failures (408, 425, 429, and
  5xx). Deliberately not conditional on the endpoint being remote: a model on
  this machine is just as capable of being busy loading weights.

- **`tests/test_architecture.py`** -- the layer rules parsed out of the source
  with `ast` and asserted. Domain purity against a standard-library allowlist,
  an explicit table of permitted imports per layer, no cycles, and the one
  default-construction exception pinned to the file and symbols it covers. See
  [ADR 0017](docs/adr/0017-the-layering-is-a-test.md).

- **Tolerated spans in the evaluation format.** `[[?TYPE:value]]` marks a span
  as neither required nor wrong. Ten bare digits are an order number to the
  anchored rules and a possible phone number to the wide ones; scoring the wide
  reading as a mistake charged the recall-first stance for doing its job.

### Changed

- **Over-redaction figures fell by roughly half, with no rule changing.** The
  earlier numbers were an artefact of datasets written for the balanced stance.
  What the recall-first default actually costs:

  | | leak rate | over-redaction (was) |
  |---|---|---|
  | `ja-core` | 0.00% | **3.11%** (6.34%) |
  | `en-core` | 0.67% | **1.44%** (2.95%) |
  | `zh-core` | 0.00% | **4.00%** (11.71%) |

  Entity precision rose with it: `ja` 0.868 to 0.908, `en` 0.900 to 0.938, `zh`
  0.844 to 0.900. The quality floors were tightened to match.

- **`PrivacySession` no longer takes `config=`.** The architecture test found
  it: the application layer was reaching through configuration to every adapter
  in the project. Build a session from settings with `MamoriConfig.session()`,
  which is the direction the dependency was always supposed to run.

- **`OpenAICompatibleProvider` takes an `LLMEndpoint`** rather than loose
  keyword arguments, and gained `health_check()`. Errors still never repeat the
  prompt, the answer, or the server's response body.

- **`MAMORI_*` is reserved for settings, and the error now says so.** An unknown
  one is still refused -- that is what catches a misspelled privacy variable --
  but the message no longer leaves a reader wondering why their API key
  variable broke the CLI. The value is never echoed.

### Fixed

- The `docs/architecture.md` layer table now matches what the code does, and a
  test fails if it stops matching again.

## [0.4.0] - 2026-08-29

Two themes: lean harder towards catching everything, and build the prompt layer
the model tier will run on.

### Added

- **A recall-first stance, and it is the default.** Every rule now declares a
  tier -- `CORE` (anchored on a checksum, a prefix, an honorific, a label) or
  `WIDE` (shape alone) -- and the stance decides which run. See
  [ADR 0013](docs/adr/0013-recall-first-by-default.md).

  | | leak rate balanced | recall-first | over-redaction balanced | recall-first |
  |---|---|---|---|---|
  | `ja-core` | 0.71% | **0.00%** | 0.00% | 6.34% |
  | `en-core` | 2.01% | **0.67%** | 0.65% | 2.95% |
  | `zh-core` | 0.00% | **0.00%** | 2.34% | 11.71% |

  Wide rules close the documented gaps that could only be closed by accepting
  false positives: an unanchored English name, an unseparated phone number, a
  credential with no vendor prefix, a postal code with no marker. They are
  `LOW` confidence, so `min_confidence` switches them off without changing
  stance. The stance changes no security decision; it only proposes more.
- **A prompt architecture.** Guidance is a shared, addressable knowledge base
  carrying what the regex work taught -- that an honorific fixes the right edge
  of a Japanese name, that 森林 is a forest, that an English name in prose has
  no anchor. A prompt is a document of named sections plus selected guidance,
  rendered deterministically with a fingerprint. See
  [ADR 0014](docs/adr/0014-prompts-are-documents.md).
- **Prompt overlays**, so an organisation adds its own rules and drops what does
  not fit without forking anything:

  ```json
  {"prompts": {"detection": {
    "disable": ["en.person.unanchored"],
    "add": [{"id": "acme.case", "text": "Case numbers look like ACME-12345."}]
  }}}
  ```

  A disable that matches nothing is refused, and refused when the config is
  built rather than months later.
- **`session.external_system_prompt()`** -- what to tell the *service* model
  about the placeholders. Needs no local model and pays for itself immediately:
  every placeholder returned intact is one restoration does not have to recover
  from a mangled form.
- **`LLMProvider` port and `LLMDetectionPass`**, the tier that reaches what
  shape cannot. It only ever adds, its output is checked against the text so a
  hallucinated span is dropped, and a failing model degrades the detector rather
  than stopping the request. `require_model=True` inverts the last one.
- **`OpenAICompatibleProvider`**, for Ollama, llama.cpp, vLLM and LM Studio,
  written against `urllib` so the library still has no runtime dependencies. It
  refuses a non-local URL: the text reaches a detector *before* it is protected.
- **`mamori prompt`** shows exactly what would be sent, with version and
  fingerprint; `--guidance` lists the ids so they can be disabled, marking which
  came from an overlay.
- `--stance` on `inspect`, `protect`, `config` and `eval`, so the trade can be
  measured rather than assumed.
- `IDENTIFIER` and `OTHER_SENSITIVE` entity types, for a long digit run with no
  label and for a model saying "this matters and I cannot name it".

### Changed

- Quality floors are now per stance, and a new test asserts the property the
  default rests on: recall-first never leaks more than balanced.
- Rule-level tests pin the balanced stance, since they are specifications of
  individual core rules.

## [0.3.0] - 2026-08-29

Architecture: the last hardcoded stage of the pipeline became swappable, and
every switch moved onto one object.

### Added

- **Detection is a pipeline of passes.** A new `DetectionPass` port receives the
  text *and* what earlier passes found; `DetectionPipeline` runs passes in order
  and is itself a `Detector`, so nothing upstream changed. `DetectorPass` adapts
  an ordinary detector, which keeps the narrow contract the default. See
  [ADR 0011](docs/adr/0011-detection-as-a-pipeline.md).
- **Co-occurrence detection.** Once a value is confirmed above the seed
  threshold anywhere in a text, its other occurrences are found too. This is the
  first thing the new port made possible and it is the largest recall gain
  available without a model:

  | | leak rate before | after |
  |---|---|---|
  | `en-core` | 7.37% | **2.01%** |
  | `ja-core` | 1.43% | **0.71%** |
  | `zh-core` | 1.49% | **0.00%** |

  Precision and over-redaction are unchanged. Word boundaries are respected in
  Latin text, so seeding on `Ann` does not match inside `Announcement`.
- **`MamoriConfig`**, holding every switch, with no opinion about file formats.
  `from_mapping()` takes an already-parsed mapping so the caller keeps their
  parser; `from_env()` reads `MAMORI_*`; `load_config_file()` handles JSON
  everywhere and TOML from 3.11. Unknown keys are refused rather than ignored.
  See [ADR 0012](docs/adr/0012-configuration-without-a-format.md).
- **`PrivacyPolicy.min_confidence`**, a coverage/quality dial. Detections below
  it are discarded before anything else happens. Default `0.0`, and it stays
  there: reducing coverage is a decision, not an inherited default.
- **`mamori config`**, printing the effective settings and where the layers come
  from, plus `--config`, `--min-confidence` and `--no-co-occurrence` on
  `inspect` and `protect`.
- A conformance suite for `DetectionPass` in `tests/contracts.py`.

### Changed

- Quality floors raised across all three languages, following the co-occurrence
  gains. The old ones no longer defended anything.
- `PrivacySession` accepts `config=`; it supplies the defaults for every other
  argument, and an explicit argument still wins.

## [0.2.0] - 2026-08-29

### Added

- **Detector evaluation.** `mamori.evaluation` scores the detectors against
  labelled datasets, and `mamori eval` prints the result. Two metric families
  are reported: entity precision/recall/F1 per type, and the character-level
  pair that actually matters here — `leak_rate` (share of labelled sensitive
  characters no detection covered) and `over_redaction_rate` (share of ordinary
  text replaced anyway). See
  [ADR 0009](docs/adr/0009-measure-leaked-characters.md).
- **Labelled datasets** for Japanese, English and Chinese, shipped with the
  package. Samples are authored with inline `[[TYPE:value]]` markup and the
  loader computes the offsets, so nobody counts characters by hand. Labels
  record what a human redactor would remove, including cases the rules are
  known to miss; each of those carries a note saying why.
- **Quality floors in CI** (`tests/test_detection_quality.py`), so a rule change
  that improves one language and quietly wrecks another turns the build red.
- **Streaming restoration.** `session.stream_restore()` restores a response as
  it arrives, holding back only the shortest suffix that further input could
  still turn into a placeholder. For any chunking it emits exactly what
  `restore()` emits for the whole response — a Hypothesis property, not an
  aspiration. See [ADR 0010](docs/adr/0010-streaming-restoration.md).
- **Port conformance suites** (`tests/contracts.py`). A new `Detector` or
  `MappingStore` subclasses the matching mixin and inherits the contract instead
  of guessing at it.

### Fixed

Five bugs, all found by the new datasets within an hour of writing them, and all
producing wrong output on plausible input:

- The Japanese address rule stopped at the first hyphen, so
  `東京都千代田区千代田1-1` was replaced as far as `...千代田1` and the rest was
  sent on.
- The Japanese surname rule swallowed the honorific: `佐藤花子様` came back as a
  four-character name ending in `様`.
- `INTERNAL_URL` and `DATABASE_URL` matched anything up to whitespace, so a link
  followed by Japanese text took the sentence with it.
- `DATE_OF_BIRTH` captured a trailing space when the closing `日` was absent.
- A Japanese company name ran into the following clause
  (`有限会社みどりから見積`); the tempered character class now stops on
  multi-character particles as well as single ones.

### Added -- language packs

- **English and Chinese detection**, alongside Japanese. Rules are grouped into
  language packs and a pack runs when the text gives a reason to run it; all of
  them are enabled by default. See
  [ADR 0008](docs/adr/0008-language-packs.md).
  - English: NANP and UK phone numbers, SSN with range validation, ZIP+4, UK
    postcodes, street addresses, legal-suffix company names, labelled employee
    IDs and project codes, and personal names anchored on a title, salutation,
    sign-off or label.
  - Chinese: mainland mobile and landline numbers, 居民身份证 with its ISO 7064
    MOD 11-2 check character, labelled postcodes, addresses from province to
    street number, company suffixes, labelled employee IDs and project codes,
    and personal names anchored on a surname.
- `Script` and `scripts_in`, and `AdaptiveLocaleDetector` on top of them: the
  Chinese pack stands down when the text contains kana, because kana appear in
  Japanese and never in Chinese. Han-only text runs both CJK packs and
  over-detects, which is the safe direction.
- `PrivacySession(locales=[...])`, the `--locale/-l` flag on `inspect` and
  `protect`, and a `mamori locales` command showing each pack and when it runs.
- `register_locale`, for adding a language without touching the library.
- `SSN` and `RESIDENT_ID` entity types. National identifiers keep their local
  names rather than collapsing into one `NATIONAL_ID`: each has its own format
  and its own checksum.
- Stopword lists for the Japanese and Chinese surname rules, so 森林 and 高兴
  are no longer read as people.

### Changed

- Language-independent rules moved to `UNIVERSAL_RULES` and now run whatever the
  text looks like; `DEFAULT_RULES` and `NAME_RULES` are gone.
- The detector name recorded on an entity is now the pack code (`ja`, `en`,
  `zh`) or `universal`, so a report says which language's rules fired.
- The CLI moved under `src/mamori/interfaces/`, matching the prescribed layout.

## [0.1.0] - 2026-08-29

First release. The core round trip works end to end, in memory, with no
dependencies outside the standard library.

### Added

- `PrivacySession` — conversation-scoped `protect` / `restore`. The same value
  keeps the same placeholder for the life of the session, so a multi-turn
  conversation stays coherent and a response in turn five can be restored with
  a value from turn one.
- Offset-preserving NFKC normalization, so full-width Japanese text matches the
  same rules as its half-width form while replacement still happens in the
  original string.
- Pattern detectors for email, Japanese phone numbers, postal codes and
  addresses, dates of birth, credit cards (Luhn), Individual Numbers
  (check digit), vendor-prefixed API keys and tokens, PEM private keys,
  database URLs, keyword-assigned passwords, private IPs, internal URLs,
  Japanese and English company names, employee IDs and project codes.
- Japanese personal-name detection, honorific-anchored and surname-dictionary
  anchored, with rejection of organisation and place suffixes.
- `PrivacyPolicy` with `ALLOW` / `ANONYMIZE` / `MASK` / `BLOCK`, resolved by
  type, then category, then a fail-closed default. Credentials are blocked
  rather than pseudonymized.
- Deterministic overlap resolution: widest span first, then severity,
  confidence and offset.
- Tamper-tolerant restoration, recovering `PERSON_001`, `<PERSON_1>`,
  `<person_001>`, `[PERSON_001]` and `＜PERSON_001＞`, while resolving only
  identities allocated in the same scope.
- Placeholder-shaped text in the *input* is itself re-mapped, so it cannot
  collide with a real placeholder during restoration.
- `InMemoryMappingStore`, the default. Nothing is written to disk unless asked.
- CLI: `inspect`, `protect`, `restore`, `policy`, `demo`.
- Optional plaintext mapping export for a two-process round trip, which warns
  every time it is used.

### Security

- Original values are excluded from every `repr`, so tracebacks and log lines
  that format the objects show types and offsets only.
- Exception messages carry entity types and offsets, never values.
- The library emits no log records.
- A detector that raises stops the request; no partial protected text is ever
  produced.
- Restoration resolves only placeholders allocated in the calling scope, so a
  response cannot read values out of the mapping table by guessing.

[Unreleased]: https://github.com/Nananananana/mamori/compare/v0.13.0...HEAD
[0.13.0]: https://github.com/Nananananana/mamori/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/Nananananana/mamori/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/Nananananana/mamori/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/Nananananana/mamori/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/Nananananana/mamori/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/Nananananana/mamori/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Nananananana/mamori/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Nananananana/mamori/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Nananananana/mamori/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Nananananana/mamori/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Nananananana/mamori/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Nananananana/mamori/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Nananananana/mamori/releases/tag/v0.1.0
