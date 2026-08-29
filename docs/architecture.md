# Architecture

## The pipeline

```text
                    your text
                        │
   ┌────────────────────▼────────────────────┐
   │ normalize          NFKC + offset map    │  domain/normalization
   ├─────────────────────────────────────────┤
   │ detect             many rules, freely   │  infrastructure/detectors
   │                    overlapping          │
   ├─────────────────────────────────────────┤
   │ map back           normalized span ->   │  application/protection
   │                    original span+value  │
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
has to touch original text; resolution has to happen after every detector has
spoken and before anything is replaced; and the policy has to run before a
single placeholder is allocated, so a blocked request leaves no trace in the
store.

## Layers

```text
interfaces ──> application ──> domain
                    │              ▲
                    │              │
                    └──> ports <───┴── infrastructure
```

| Layer | Holds | May import |
|---|---|---|
| `domain/` | Value objects, entities, policy, resolution, normalization, placeholder identity | stdlib only |
| `ports/` | `Detector`, `MappingStore` protocols | `domain` |
| `application/` | `ProtectionService`, `RestorationService`, `PrivacySession`, result DTOs | `domain`, `ports` |
| `infrastructure/` | Regex detectors, in-memory store, JSON mapping file | `domain`, `ports` |
| `interfaces/cli/` | Argument parsing, output formatting | `application`, `domain` |

`domain` imports nothing else, including nothing outside the standard library.
See [ADR 0001](adr/0001-domain-depends-on-nothing.md).

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

## Extension points

Two, both with a second implementation already in view:

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

Custom entity types register with `mamori.register_type`. Note that a type
whose category has no policy default falls through to `BLOCK` — deliberately,
so a new detector stops a request rather than quietly shipping what it found.

## Testing

| File | Covers |
|---|---|
| `test_domain_values.py` | Value object invariants |
| `test_normalization.py` | The offset map, including length-changing normalization |
| `test_resolution_and_policy.py` | Overlap resolution and policy precedence |
| `test_detectors.py` | Every rule: what it catches, what it deliberately does not, exact spans |
| `test_placeholder_matching.py` | Tamper tolerance and the precision guards against it |
| `test_session.py` | Round trips, fail-closed behaviour, scope isolation, placeholder collision |
| `test_security_leakage.py` | Greps real logs, reprs, tracebacks and payloads for the values |
| `test_roundtrip_properties.py` | Hypothesis: restore undoes protect, protect is idempotent, nothing crashes |
| `test_cli_and_storage.py` | The shell interface and the JSON mapping file |

The round-trip property is scoped to `ANONYMIZE`. It cannot hold for `MASK` or
`BLOCK`, which destroy information on purpose — a global assertion would be
asserting that the security features do not work.
