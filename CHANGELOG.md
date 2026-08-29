# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the version is below `1.0.0`, the public API may change in a minor release.

## [Unreleased]

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

[Unreleased]: https://github.com/Nananananana/mamori/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/Nananananana/mamori/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Nananananana/mamori/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Nananananana/mamori/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Nananananana/mamori/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Nananananana/mamori/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Nananananana/mamori/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Nananananana/mamori/releases/tag/v0.1.0
