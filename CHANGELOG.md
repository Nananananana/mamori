# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the version is below `1.0.0`, the public API may change in a minor release.

## [Unreleased]

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

[Unreleased]: https://github.com/Nananananana/mamori/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Nananananana/mamori/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Nananananana/mamori/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Nananananana/mamori/releases/tag/v0.1.0
