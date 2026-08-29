# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the version is below `1.0.0`, the public API may change in a minor release.

## [Unreleased]

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

[Unreleased]: https://github.com/Nananananana/mamori/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/Nananananana/mamori/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Nananananana/mamori/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Nananananana/mamori/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Nananananana/mamori/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Nananananana/mamori/releases/tag/v0.1.0
