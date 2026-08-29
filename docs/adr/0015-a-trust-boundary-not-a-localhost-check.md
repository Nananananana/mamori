# 15. A trust boundary, not a localhost check

**Status:** accepted

**Supersedes** the `localhost`-only rule introduced with the LLM detection pass
in 0.4.0.

## Context

The model pass sends text to an LLM **before** that text is protected. That is
unavoidable — a detector that only saw the redacted text would have nothing to
find — and it makes the endpoint the single most dangerous piece of
configuration in the library. Point it at a public API and every document goes
out in the clear, with no error, no warning, and a `mamori` logo on it.

0.4.0 guarded that with the simplest rule available: the endpoint must be
`localhost`. It was safe, and it was wrong about how the software is used.

The realistic deployment is not a laptop running a 7B model. It is one
high-specification machine — a GPU box in a server room — running a model the
whole team shares, reached at `http://llm01.corp:8000/v1/`. Under the localhost
rule, that deployment is impossible. Every team that has one would have to
either tunnel the port to make a remote host look local, or set some
`--i-know-what-i-am-doing` flag, and both of those defeat the check while
leaving it in place to feel reassuring.

A rule people route around is worse than no rule, because it stops being
information.

## Decision

Replace the host check with an explicit, configurable **trust boundary**.

A host is classified, by inspection only, into one of four kinds:

| Kind | Meaning |
|---|---|
| `loopback` | `localhost`, `127.0.0.0/8`, `::1` — this machine |
| `private` | RFC 1918 / RFC 4193 addresses, and unqualified or `.internal` / `.local` / `.corp` names — plausibly the network you control |
| `declared` | Named in `trusted_hosts` by the operator |
| `external` | Everything else |

A boundary decides which kinds are admitted:

| Boundary | Admits |
|---|---|
| `same_host` | `loopback`, `declared` |
| `private_network` (**default**) | `loopback`, `private`, `declared` |
| `anywhere` | everything |

The default admits both deployments the user actually has — the model on this
machine and the model on the server down the hall — and refuses a public API.
`declared` is admitted under every boundary, because an operator naming a host
is making a decision, and the library's job is to make that decision explicit
rather than to overrule it.

The check happens when the provider is constructed, so a refusal arrives at
startup rather than on the first document. `mamori llm` reports the verdict
before anything is sent at all.

## Consequences

**The in-house server case works, and it is the default.** No flag, no tunnel,
no opt-out ceremony. This is the point.

**The classification is heuristic, and it is honest about that.** An
unqualified name resolving to a private address is the overwhelmingly common
case, so it is classified `private` without a DNS lookup. Split-horizon DNS
could in principle make `llm01` resolve to something public. mamori does not
resolve names — resolution is neither stable nor safe to do at configuration
time — so an operator in that situation must use `same_host` or name the host
explicitly.

**A public endpoint is still reachable, deliberately.** Setting `anywhere` is
one line of configuration. Somebody running mamori inside a VPN whose exit
looks external needs it. What changed is that they now say so, and the string
`"trust": "anywhere"` is visible in the config and in `mamori llm` output for
anyone who reviews it.

**Refusal messages explain the rule.** An error that says only "refused" gets
worked around with whatever flag makes it stop. One that says what was
classified, why, and which of the two remedies applies gets read. The cost is a
long error message, which is the correct thing to be long.

**The classification lives in the domain layer** (`domain/trust.py`) with no
network access of any kind — it is pure inspection of a string, so it is
exhaustively testable and cannot itself leak anything by being called.
