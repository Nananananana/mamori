# Architecture

## The path a prompt takes

```text
                    your text
                        │
   ┌────────────────────▼────────────────────┐
   │ normalize          NFKC + offset map    │  domain/normalization
   ├─────────────────────────────────────────┤
   │ detect             ordered passes,      │  infrastructure/detectors
   │                    freely overlapping   │
   ├─────────────────────────────────────────┤
   │ map back           normalized span ->   │  application/protection
   │                    original span+value  │
   ├─────────────────────────────────────────┤
   │ filter             confidence floor     │  domain/policy
   ├─────────────────────────────────────────┤
   │ resolve            one winner per       │  domain/resolution
   │                    character            │
   ├─────────────────────────────────────────┤
   │ decide             ALLOW / ANONYMIZE /  │  domain/policy
   │                    MASK / BLOCK         │
   ├─────────────────────────────────────────┤
   │ allocate           stable placeholder   │  domain/placeholder
   │                    per identity, scoped │  ports/mapping_store
   ├─────────────────────────────────────────┤
   │ splice             right to left, into  │  application/protection
   │                    the ORIGINAL text    │
   └────────────────────┬────────────────────┘
                        │
                 protected text ────────────> external LLM
                                                    │
   ┌────────────────────────────────────────┐       │
   │ scan               tamper-tolerant,    │  <────┘  response
   │                    identity-strict     │  domain/placeholder_matching
   ├────────────────────────────────────────┤
   │ substitute         known placeholders  │  application/restoration
   │                    only; report others │
   └────────────────────┬───────────────────┘
                        │
                   your answer
```

The order is not arbitrary. Detection has to see normalized text; replacement
has to touch original text; the confidence floor applies before resolution, so a
detection the policy will not consider cannot win a span from one it would have;
resolution has to happen after every pass has spoken and before anything is
replaced; and the policy has to decide before a single placeholder is allocated,
so a blocked request leaves no trace in the store.

## Layers

```text
interfaces ──> application ──> domain
                    │              ▲
                    │              │
                    └──> ports <───┴── infrastructure
```

| Layer | Holds | May import |
|---|---|---|
| `domain/` | Value objects, entities, policy, resolution, normalization, placeholder identity, host trust, corrections, surrogates | stdlib only |
| `ports/` | `Detector`, `DetectionPass`, `MappingStore`, `LLMProvider` protocols, `LLMEndpoint`, `AuditSink` | `domain` |
| `prompts/` | Guidance, prompt definitions, overlays, response parsing | `domain` |
| `application/` | `ProtectionService`, `RestorationService`, `PrivacySession`, result DTOs | `domain`, `ports`, `prompts`, and `infrastructure` for default construction only |
| `infrastructure/` | Regex detectors, language packs, in-memory store, JSON mapping file, encrypted mapping file, JSONL audit sink, LLM providers | `domain`, `ports`, `prompts` |
| `evaluation/` | Labelled datasets, scoring, quality metrics | `domain`, `ports`, `application`, `infrastructure` |
| `llm_settings.py` | Model settings, and the endpoint they build | `domain`, `ports` |
| `config.py` | Every switch, and the factories that assemble them | everything above |
| `report.py` | What a configuration does with your data | `domain`, `config` |
| `provenance.py` | What one protected text had done to it, as a document, and the ledger that hands it to a sink | `domain`, `ports`, `application` |
| `interop/` | Presidio-shaped input and output, so trying this costs an import | `domain`, `ports`, `config`, `application` |
| `schemas/` | Frozen contract documents, shipped as package data | nothing; there is no code in it |
| `interfaces/cli/` | Argument parsing, output formatting | everything above |
| `interfaces/proxy/` | The OpenAI-compatible endpoint: payload walk, exchange, upstream | everything above |

`domain` imports nothing else, including nothing outside the standard library.
See [ADR 0001](adr/0001-domain-depends-on-nothing.md).

**This table is executable.** `tests/test_architecture.py` parses every module
and asserts these rules, so a diagram that stops matching the code turns the
build red instead of quietly becoming fiction. The `ALLOWED` table in that file
is the authority; this one describes it. See
[ADR 0017](adr/0017-the-layering-is-a-test.md).

The one deliberate exception is marked above: `application/session.py` imports
`default_detectors` and `InMemoryMappingStore` so that `PrivacySession()` works
with no arguments at all. The test pins that to those two symbols in that one
file. Settings assemble a session -- `MamoriConfig.session()` -- and a session
never reads settings, which is what keeps the rest of the application layer
clear of the adapters a configuration happens to name.

## Where the security decisions live

All of them are in `domain/`, and none of them are in a swappable component:

| Decision | Module |
|---|---|
| Which overlapping detection survives | `resolution.py` |
| What happens to a detected entity | `policy.py` |
| Which value gets which placeholder | `placeholder.py` + `sensitive_entity.identity_key` |
| Whether a run of response text resolves to a value | `placeholder_matching.py` |
| Whether a span maps back to the right original characters | `normalization.py` |

A detector is a *proposer*. Swapping it, or adding a local model in v0.4,
cannot change any of the above. That separation is the reason a hallucinating
model cannot become a security incident: the worst it can do is propose or
withhold a candidate.

## Key types

**`SensitiveEntity`** — one detection. Carries the entity type, a span, the
value, a confidence and the detector that found it. `value` is excluded from
`repr` so a traceback cannot print it.

**`Placeholder`** — a `(type name, index)` pair. `token` renders `<PERSON_001>`;
`parse` reads the canonical form back. Tolerant reading of mangled forms is
`placeholder_matching.scan_placeholders`, kept separate because it is the part
that handles untrusted input.

**`Mapping`** — placeholder ↔ original value, within a scope. The highest-value
object in the system.

**`PrivacyPolicy`** — type rules, then category defaults, then a fail-closed
fallback.

**`NormalizedText`** — normalized string plus the offset map back to the
original.

## Scopes

A scope is one conversation. It partitions the mapping store, so:

- the same value keeps its placeholder across every `protect` in the session;
- a response in a later turn restores with a value from an earlier one;
- one session cannot resolve another session's placeholders, even sharing a
  store.

`PrivacySession` creates a scope, and `close()` purges it.

## Language packs

Rules are grouped by language. A pack declares its rules plus the scripts that
make it worth running, and the scripts that mean it is not:

```text
                        scripts in the text
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
     latin?                  kana?                    han?
        │                       │                       │
        ▼                       ▼                       ▼
      en pack              ja pack, and           ja pack, and
                           zh pack stands          zh pack too
                              down                (ambiguous)
```

Kana are the one decisive signal: they appear in Japanese and never in Chinese.
Han alone could be either, so both CJK packs run and over-detect — the safe
direction. Language-independent rules (email, card numbers, credentials, private
addresses) sit outside the packs and always run.

Every pack is enabled unless `locales=` narrows it. `mamori locales` prints what
is registered and when each one fires. See
[ADR 0008](adr/0008-language-packs.md).

## Detection is a pipeline

Detection is assembled from ordered passes rather than hardcoded. Each pass sees
the text **and** what earlier passes found:

```text
   ┌── DetectionPipeline (itself a Detector) ──────────────────┐
   │                                                           │
   │  rules            universal patterns + language packs,    │
   │    │              core tier always, wide tier under the   │
   │    │              recall-first stance                     │
   │    ▼                                                      │
   │  co-occurrence    values confirmed above the seed         │
   │    │              threshold, found again elsewhere        │
   │    ▼                                                      │
   │  llm (optional)   a local model, proposing what shape     │
   │                   alone cannot settle                     │
   └───────────────────────────────────────────────────────────┘
```

The second pass is why the port exists: once a name is confirmed by an honorific
in one sentence, every other mention of it in the document is the same person,
and no rule looking at those mentions alone can tell. See
[ADR 0011](adr/0011-detection-as-a-pipeline.md).

Passes may report overlapping spans. Nothing is resolved here — that still
happens once, in `domain/resolution.py`.

## Stance

Every rule declares a tier, and the stance decides which run:

| Tier | Anchored on | Example |
|---|---|---|
| `CORE` | Something rarely anything else | a checksum, an honorific, a label |
| `WIDE` | Shape alone | ten bare digits, two capitalised words |

`RECALL_FIRST` runs both and is the default; `BALANCED` runs core only. The
stance changes **no security decision** — it only proposes more candidates,
which is why "recall-first never leaks more than balanced" is a test. See
[ADR 0013](adr/0013-recall-first-by-default.md).

## Prompts

Two, facing opposite directions:

```text
  detection  ──> a local model, asked to FIND what shape cannot settle
  external   ──> the service model, told to leave the placeholders alone
```

A prompt is a document of named sections plus guidance selected from a shared
knowledge base — everything the regex work taught, written for a model. An
organisation adds and disables guidance by id through an overlay, without
forking anything.

```text
  BUILTIN_GUIDANCE ──┐
                     ├──> PromptDefinition ──> PromptOverlay ──> RenderedPrompt
  sections ──────────┘                          (org rules)      (+ fingerprint)
```

Nothing a model returns is trusted: `prompts/parsing.py` checks every candidate
against the text it claims to describe, and a mismatch is dropped. See
[ADR 0014](adr/0014-prompts-are-documents.md).

## Configuration

Every switch lives on one frozen object:

```python
MamoriConfig(locales=["ja", "en"], min_confidence=0.7, co_occurrence=True)
```

It has no opinion about file formats. `from_mapping()` takes an already-parsed
mapping, so the caller picks JSON, TOML, YAML or a dict literal and keeps their
parser to themselves. `from_env()` reads `MAMORI_*`. Layers, later winning:

```text
built-in defaults  ->  --config file  ->  MAMORI_* env  ->  command-line flags
```

`mamori config` prints the effective result. Unknown keys are refused rather
than ignored: a typo in a privacy setting that silently does nothing is the
worst available outcome. See
[ADR 0012](adr/0012-configuration-without-a-format.md).

## Extension points

Three, each with a second implementation already in the tree:

`LocalePack` is a fourth: registering one with `register_locale` adds a language
without touching the library.

```python
class Detector(Protocol):
    @property
    def name(self) -> str: ...
    def detect(self, text: str) -> Sequence[SensitiveEntity]: ...
```

Receives normalized text, returns spans in that text's coordinates. **Raises on
failure** — returning nothing would be indistinguishable from finding nothing,
which is a fail-open bug.

```python
class MappingStore(Protocol):
    def find_by_identity(self, scope: str, identity_key: str) -> Mapping | None: ...
    def find_by_placeholder(self, scope: str, placeholder: Placeholder) -> Mapping | None: ...
    def put(self, mapping: Mapping) -> None: ...
    def next_index(self, scope: str, entity_type_name: str) -> int: ...
    def list_scope(self, scope: str) -> Sequence[Mapping]: ...
    def purge(self, scope: str) -> None: ...
```

```python
class DetectionPass(Protocol):
    @property
    def name(self) -> str: ...
    def run(self, context: DetectionContext) -> Sequence[SensitiveEntity]: ...
```

The wider contract, for detection that needs to know what else was found.
`DetectionContext` carries the normalized text and the findings so far.

```python
class LLMProvider(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def supports_structured_output(self) -> bool: ...
    def generate(self, request: LLMRequest) -> LLMResponse: ...
```

Deliberately the smallest interface that does the job. A provider is asked for
text and never for a decision, which is what keeps a model outside every
security judgement.

Custom entity types register with `mamori.register_type`, and custom guidance
with a `PromptOverlay`. Note that a type
whose category has no policy default falls through to `BLOCK` — deliberately,
so a new detector stops a request rather than quietly shipping what it found.

## Streaming

An answer arrives token by token, and `<PERSON_001>` shows up as `<PER`, `SON_0`,
`01>`. `session.stream_restore()` holds back the shortest suffix that further
input could still turn into a placeholder and emits the rest, restored:

```python
stream = session.stream_restore()
for chunk in llm_response_stream:
    print(stream.feed(chunk), end="")
print(stream.finish())
```

The invariant, checked with Hypothesis over every chunking: streaming emits
exactly what `restore()` emits for the whole response. See
[ADR 0010](adr/0010-streaming-restoration.md).

## Measuring detection

`mamori.evaluation` scores the detectors against labelled data. Two metric
families, because neither is honest alone:

| Metric | Question it answers |
|---|---|
| `leak_rate` | What share of the sensitive characters would have left the machine |
| `over_redaction_rate` | What share of ordinary text was destroyed getting there |
| entity P / R / F1 | Which rule is missing, per type |

```bash
mamori eval --locale ja --show-leaks
```

Datasets are authored with inline markup — `[[PERSON:田中太郎]]さんへ` — and the
loader computes the offsets, so nobody counts characters by hand. Quality floors
run in CI. See [ADR 0009](adr/0009-measure-leaked-characters.md).

## Testing

| File | Covers |
|---|---|
| `test_domain_values.py` | Value object invariants |
| `test_normalization.py` | The offset map, including length-changing normalization |
| `test_resolution_and_policy.py` | Overlap resolution and policy precedence |
| `test_detectors.py` | Universal and Japanese rules: what each catches, what it deliberately does not, exact spans |
| `test_detectors_en.py` | English rules, and the names they are known to miss |
| `test_detectors_zh.py` | Chinese rules, including the resident-ID check character |
| `test_locales.py` | Script detection, pack selection, cross-language behaviour |
| `test_placeholder_matching.py` | Tamper tolerance and the precision guards against it |
| `test_session.py` | Round trips, fail-closed behaviour, scope isolation, placeholder collision |
| `test_security_leakage.py` | Greps real logs, reprs, tracebacks and payloads for the values |
| `test_roundtrip_properties.py` | Hypothesis: restore undoes protect, protect is idempotent, nothing crashes |
| `test_cli_and_storage.py` | The shell interface and the JSON mapping file |
| `test_streaming.py` | Incremental restoration; Hypothesis over every chunking |
| `test_evaluation.py` | The scoring harness and the dataset parser |
| `test_detection_quality.py` | Quality floors per language, run in CI |
| `test_port_contracts.py` | Every bundled adapter against the port conformance suites |
| `test_detection_pipeline.py` | The pipeline, and the co-occurrence pass on top of it |
| `test_config.py` | Settings, their layering, and what a bad one does |
| `test_stance.py` | Both halves of the recall/precision trade, per language |
| `test_prompts.py` | Composition, overlays, and refusing to trust a model |
| `test_llm_provider.py` | The HTTP adapter, against a real local server |

`tests/contracts.py` holds the conformance suites for `Detector` and
`MappingStore`. A new adapter subclasses the matching mixin and inherits the
contract rather than guessing at it.

The round-trip property is scoped to `ANONYMIZE`. It cannot hold for `MASK` or
`BLOCK`, which destroy information on purpose — a global assertion would be
asserting that the security features do not work.
