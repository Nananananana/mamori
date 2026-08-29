# 18. A proxy, on the standard library

**Status:** accepted

## Context

Every release so far protected only code that was written to use it. That is a
narrow audience. The applications where this matters most already exist: an
internal tool that drafts replies, a script that summarises tickets, a desktop
client somebody in the team already likes. Nobody rewrites a working
application to adopt a library, and a privacy layer that only protects new code
protects very little.

All of them have one thing in common. They talk to an OpenAI-compatible API,
and the address is a single string in their configuration.

## Decision

`mamori serve` is an OpenAI-compatible endpoint. An application moves behind it
by changing its `base_url` and nothing else. The proxy protects every message,
forwards the result to the service the application was already using, and
restores the reply on the way back.

**Built on `http.server`.** No dependency is added, because the zero-dependency
rule is what makes this package auditable, and a privacy tool nobody audits is
a privacy tool nobody should trust. This is the same reasoning, and the same
tool, that the sibling `kiseki` project reached for in its ADR-0026.

That choice sets a ceiling, and the ceiling is stated rather than discovered:
this is sized for one team's traffic on one machine. If it ever needs
datacentre concurrency, the answer is a separate package with a real server in
it, not a rewrite of this one.

**It binds to 127.0.0.1.** Anything that can reach the port can send documents
through it and read the restored answers, which makes the bind address a
security control. `--host 0.0.0.0` is a deliberate act, warned about on
startup, and never a default.

**One mapping scope per request, discarded with it.** Nothing accumulates
between requests, so a proxy left running for a month holds exactly what one
started a second ago holds: nothing. Placeholder numbering therefore restarts
each request, which costs nothing in practice because a chat client resends the
whole conversation every turn — the same values meet the same allocator in the
same order and land on the same placeholders.

**It fails closed.** A blocked credential, a payload it cannot parse, a path it
does not recognise: all are errors returned to the caller, and none forward
anything. A path this proxy does not understand is a path whose payload it
cannot promise to have protected, so it is refused rather than passed through.

**It protects the system prompt too.** An organisation's briefing is exactly
the sort of context that should stay local. Treating it as trusted because a
developer wrote it rather than a user would protect the message and leak the
briefing.

**It prepends the placeholder briefing.** The library already knew how to tell
a model to leave placeholders alone; the proxy is the first thing in a position
to do it automatically.

## Consequences

**The audience stops being "code written after mamori existed".** This is the
whole point, and it is worth the surface area.

**A new place for text to flow, and therefore a new thing to audit.** That is
the reason [ADR 0019](0019-privacy-is-a-report-not-a-promise.md) and
[ADR 0020](0020-the-promises-are-checked-by-machine.md) land in the same
release rather than later: a proxy makes "what leaves this machine" a live
question, and answering it by hand does not scale.

**Streaming is supported and is the fiddly part.** A placeholder arrives as
`<PER`, `SON_0`, `01>`, and the restorer built in 0.2.0 for exactly this holds
back the shortest suffix that could still become one. Reading the whole body
first would restore perfectly and defeat the reason anybody streams.

**Only `/v1/chat/completions` is proxied.** Embeddings, audio and the rest are
refused. Each would need its own decision about what in its payload is text,
and a wrong guess there forwards a document nobody checked.

**The trust boundary does not apply to the upstream, deliberately.** It looks
like an omission and is the opposite. A *detector* endpoint sees the document
before protection, so an external one is the leak; the proxy upstream sees
protected text and is the external service the caller already chose. Applying a
boundary there would refuse the only destination that makes sense.
