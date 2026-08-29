# Security Policy

## Reporting a vulnerability

Please report security issues privately through
[GitHub Security Advisories](https://github.com/Nananananana/mamori/security/advisories/new)
rather than in a public issue.

Include what you did, what you expected, and what happened. If the issue is a
detection gap, a short example of text that slips through is the most useful
thing you can send. **Use invented data.** Do not send a real name, a real
address or a real key to demonstrate a bug in a privacy tool.

Expect an acknowledgement within a week. `mamori` is a young project maintained
in spare time; there is no paid response commitment and no bug bounty.

## What `mamori` is for

`mamori` reduces the chance that sensitive data reaches an external LLM when
somebody pastes real text into a prompt. It is a safety net for a mistake that
people make constantly and notice too late.

## What `mamori` does not do

This section is longer than the previous one on purpose. A privacy tool that is
trusted past its actual reach is worse than none at all, because it licenses
riskier behaviour than the behaviour it replaced.

### Detection is incomplete

The v0.1 detectors are regular expressions and a surname list. They are known
to miss:

| Category | Known gaps |
|---|---|
| `PERSON` | Names with an uncommon surname and no honorific. Given names alone. Names inside compounds. Nicknames. Names written only in hiragana. |
| `ADDRESS` | Addresses with no prefecture. Building and room numbers when written apart from the street. Non-Japanese addresses. |
| `PHONE` | Unseparated digit runs, which are deliberately not matched -- an order number looks identical. |
| `COMPANY_NAME` | Trading names with no legal suffix. Names containing の, which the rule truncates on purpose. Abbreviations and internal shorthand. |
| `PROJECT_NAME` | Internal codenames, which by construction look like ordinary words. |
| Secrets | Any credential without a recognisable vendor prefix, and any high-entropy string not written next to a keyword. |
| Everything | Data that is only sensitive in context: a salary figure, an unreleased date, a headcount, who was in a meeting. |

Detector quality is not yet measured. There is no labelled evaluation set, so
nobody -- including the maintainers -- can currently state a recall figure.
Building one is a v0.2 goal.

### It is not a compliance control

Nothing here has been assessed against GDPR, HIPAA, APPI or any other regime.
Pseudonymized personal data remains personal data under most of them, and a
placeholder that a mapping can reverse is pseudonymization, not anonymization.

### It does not defend a compromised machine

Detection, the mapping table and restoration all run locally. Anything that can
read your process memory, your files or your keystrokes has already won. The
mapping table is the highest-value object in the system: it holds only the
values you were trying to protect.

### It is not automatic

`mamori` protects the text you pass to it. It cannot intercept a call that does
not go through it. The proxy planned for v0.2 narrows this gap; it does not
close it.

### It cannot control what the recipient does

Once the protected text is sent, it is out of scope. Placeholder structure
itself carries information -- that there were three people and two companies in
the message, and roughly where. If that fact is sensitive, do not send the
message.

## Threat model

The long form, including what is in and out of scope for each threat, is in
[docs/threat-model.md](docs/threat-model.md).

| Threat | v0.1 status |
|---|---|
| PII reaches the external service | Mitigated for what the detectors find |
| A credential reaches the external service | Blocked outright for recognised formats |
| The mapping table reaches the external service | Prevented structurally; the mapping never enters an outbound payload |
| A response reads values out of the mapping table | Prevented; only placeholders allocated in the same scope resolve |
| A detector fails and the request proceeds anyway | Prevented; a detector that raises stops the request |
| Sensitive values reach logs or tracebacks | Mitigated; values are excluded from every `repr`, and the library logs nothing |
| Prompt injection in the input steers a detector | Not applicable in v0.1 -- pattern rules cannot be argued with. Becomes a live threat with the v0.4 local-model detector |
| An input crafted to be undetectable | **Not mitigated.** No detector set is complete |
| Local machine compromise | **Out of scope** |
| Re-identification from what remains | **Not mitigated.** Removing names does not remove a distinctive combination of facts |

## Data handling

- Mappings live in memory by default and are discarded when the session closes.
- Nothing is written to disk unless you ask for it. `--save-mapping` writes
  plaintext and says so on stderr every time.
- The library emits no log records, so there is nothing to configure away.
- No telemetry, no network calls, no model downloads.

## Supported versions

`0.1.x` only, while the project is pre-1.0. Fixes land on `main`.
