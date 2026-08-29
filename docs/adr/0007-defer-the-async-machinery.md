# 7. Defer the async, event and envelope machinery

**Status:** accepted

## Context

The design charter specifies a JSON envelope with correlation and causation ids,
separated commands and events, six distinct id types, a ten-state request
machine, a seven-state processing-run machine, and eleven repository ports.

Every one of those has a real use. An asynchronous pipeline that dispatches a
request, waits, and reconciles a response arriving minutes later needs most of
them.

v0.1 has no such pipeline. `protect` and `restore` are two synchronous calls,
and the caller owns the LLM request in between.

Building the machinery first would mean writing correlation ids that nothing
correlates and state transitions that nothing transitions. The risk is not
theoretical: a project can spend its entire initial energy on scaffolding and
ship nothing that does the thing it was for.

## Decision

v0.1 ships the transformation core and nothing else. One scope identifier
instead of six id types. No envelope, no event bus, no state machine, no
persistence layer.

The extension points that *are* built are the ones with a second implementation
already in view: `Detector`, because a local model is coming, and `MappingStore`,
because an encrypted store is coming. A port with no second implementation in
sight is a guess about the future dressed as architecture.

## Consequences

The library does one thing, and the whole of it fits in one reading. Coverage
sits high because there is no speculative code to leave untested.

Roadmap ordering changed to match: the OpenAI-compatible proxy moves to v0.2,
ahead of the async work. Nobody rewrites a working application to adopt a
library, so the proxy — a one-line `base_url` change — is the adoption path.
Asynchrony can wait until something is actually asynchronous.

## What it costs

If asynchronous processing arrives later, correlation has to be retrofitted, and
retrofitting is more work than building it in from the start. That is accepted:
this cost is paid only if the feature turns out to be needed, whereas building
it now is paid for certain.

The charter's design is not rejected. It is scheduled. This ADR is the record
that deferring it was a decision.
