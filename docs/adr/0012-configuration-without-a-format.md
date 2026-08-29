# 12. One configuration object, no configuration format

**Status:** accepted

## Context

Every part of the library was already swappable — detectors, policy, store,
language packs, and now detection passes — but only from Python, one keyword
argument at a time. A team that wants the same settings in a script, in a CLI
invocation and (next) in a proxy had nowhere to put them, so the settings got
copied, and copies drift.

The obvious answer is a config file, and the obvious file format brings a
parser. YAML is what the original design charter sketched, and `pyyaml` would be
a runtime dependency for every user of a library whose selling point is that it
has none. TOML is in the standard library — from 3.11, which is not the floor
this project supports.

## Decision

`MamoriConfig` is a frozen dataclass holding every switch. It has no opinion
about where the values came from: `from_mapping()` takes an already-parsed
mapping, so the caller chooses JSON, TOML, YAML, a database row or a dict
literal and keeps their parser to themselves.

```python
MamoriConfig.from_mapping(yaml.safe_load(text))  # their dependency, not ours
```

`from_env()` reads `MAMORI_*` variables. `load_config_file()` is a convenience
over the two formats the standard library can already read — JSON everywhere,
TOML from 3.11, with an error on 3.10 that says to use JSON rather than failing
obscurely.

Settings layer, later winning: built-in defaults, then `--config`, then the
environment, then command-line flags. `mamori config` prints the result and says
where the layers come from, because a configuration system whose effective state
cannot be inspected is a configuration system nobody trusts.

**Unknown keys are refused, not ignored.** A typo in a privacy setting that
silently does nothing is the worst available outcome: the user believes they
tightened something and did not. The error lists the keys that do exist.

Two switches are new and both are documented as trades rather than improvements:

- `min_confidence` discards detections below a threshold. Raising it buys fewer
  spurious placeholders and costs coverage.
- `co_occurrence` toggles the propagation pass. Off costs recall on repeated
  values and never costs safety.

Their defaults — `0.0` and `on` — are the fail-safe ones and must stay there.
Reducing coverage is a decision for whoever is handling the data, not a default
they inherit without being asked.

## Consequences

One object to pass around, and it is what the proxy will be configured with.
`PrivacySession(config=...)` supplies defaults for every other argument, and an
explicit argument still wins, so a caller can load a shared config and override
one thing.

Still no runtime dependencies.

## What it costs

`load_config_file` supports two formats and neither is the one the charter
sketched. A team standardised on YAML writes one line to parse it, which is a
real if small inconvenience, paid by them rather than by everyone.

`from_env` refuses unknown `MAMORI_*` variables. That catches typos and will
also reject an unrelated variable somebody puts in that namespace. Owning the
prefix is the assumption; the alternative is silently ignoring a misspelled
privacy setting, which is worse.

Config is not yet a place to define detectors or stores — only to switch the
built-in ones. Registering a custom detector is still Python. That is the right
boundary for now: a config format that can name arbitrary code is a config
format that can load arbitrary code.
