# Running `mamori serve` from another program

For the layer that starts the proxy as a child process, routes conversations
through it, and needs to know -- without parsing prose -- what happened to
each one. Everything here is pinned by `tests/test_proxy_orchestration.py`, so
a row that stops being true fails the build rather than the orchestrator.

## Starting it

```bash
mamori serve --upstream https://api.openai.com/v1/ --port 0 --conversations --audit audit.jsonl
```

- **`--port 0`** takes a free port. The first line of stdout is the address,
  and it is the port the kernel chose, not the zero that was asked for:
  `mamori proxy on http://127.0.0.1:53412/v1/`. Read that line; do not guess.
- **`GET /health`** answers `200 {"status": "ok", ...}` as soon as the socket
  is bound, before any request has been served. Poll it for readiness. It
  says whether conversations are kept, never how many or for whom.
- **`--host`** stays unset. The proxy binds `127.0.0.1` and refuses to be
  anything else without an explicit override.
- The upstream URL lives here, in this flag, and nowhere in the orchestrator.

## What every reply carries

| header | when | what |
|---|---|---|
| `X-Mamori-Scope` | every reply that had a session, refusals included | the scope this request's placeholders were allocated in. **Minted here**; a value sent in is ignored |
| `X-Mamori-Session` | with `--conversations` | the conversation token to echo on the next turn. Minted here; a value sent in that nothing minted starts a fresh conversation |
| `X-Mamori-Replaced` | when anything was replaced | `KIND=count` pairs, `EMAIL=2,PERSON=1` -- occurrences, never values |

The scope is the join key to the audit file. Without `--conversations` a
scope lives for one request; with it, for the conversation, so the lines in
the file carrying one scope are that conversation's turns in order.

## The audit file

`--audit PATH` appends one `mamori.audit-line/1` envelope per **message slot**
protected -- a request with three messages writes three lines, all carrying
the scope the reply names. Each holds a `mamori.protection-scope/1` record
(or `/1+surrogate` when surrogates are on, which a consumer written for
placeholders refuses through the contract check it already has). No value is
in it; the file inherits the classification of the traffic it describes.

A request the policy refuses writes **nothing**: a record says a protection
happened, and a refused request is one where it did not leave. A sink that
cannot be written stops the request with a `500` rather than answering with a
hole in the trail.

## Statuses

| status | meaning | nothing was forwarded? |
|---|---|---|
| `422` | **blocked by policy** -- a credential, or a type the policy blocks. Map this to *refused*; do not retry | yes |
| `502` | the upstream failed or could not be reached | it was attempted |
| `500` | detection or the audit sink failed | yes |
| `400` | the body was not JSON, was empty, or was over 8 MB | yes |
| `404` | a path this does not proxy (only `/v1/chat/completions`) | yes |

Error bodies are `{"error": {"message", "type": "mamori_error", "code"}}` and
never carry a value. A `422` still names its scope in `X-Mamori-Scope`.

## Ending a conversation

Send `X-Mamori-Session-End: true` with the last turn. The scope is purged when
that reply is sent, and *"the mapping is gone"* is then true rather than
scheduled. Otherwise a conversation is purged after `--conversation-idle`
minutes untouched (30 by default), when it grows past 5,000 mappings, or when
more than `--max-conversations` (64) are live and it is the least recently
used idle one. **These are flags, not `MAMORI_*` environment variables.**

## Time

Measured with `mamori bench` on the machine in the README's cost table --
run it on yours:

| shape | `protect`, 100,000 chars | throughput |
|---|---|---|
| English prose | ~160 ms | ~630 chars/ms |
| Japanese prose | ~470 ms | ~215 chars/ms |
| a rendered mixed prompt | ~330 ms | ~300 chars/ms |

So a rendered prompt of a few thousand characters costs single-digit
milliseconds in English and tens in Japanese, and the proxy's own overhead on
a 3.5 KB three-message request measured 17 ms end to end, upstream excluded.
Cost is linear in length -- `bench`'s `x4 growth` column is the check.

**Streaming holds back at most 266 characters.** A placeholder can arrive
split across chunks, so the restorer keeps the shortest suffix that could
still become one and releases it the moment it cannot. The bound is the
longest placeholder that can exist (a 63-character type name, four bytes a
character, brackets and a six-digit index), which is what makes the hold a
number rather than a wait. On screen: the last few words of a sentence land
together rather than one by one, and a name never appears as `<PER` first.

## Detections without importing this library

```bash
mamori inspect --presidio "Review notes for E-45033 -- Priya Raman"
```

prints a JSON array of `{"entity_type", "start", "end", "score"}` -- Presidio's
`RecognizerResult`, for a consumer that already reads that shape. Nothing
else is in it: no preview, no placeholder, no character of any value.
Offsets index the text as given.

## Surrogates

Off unless the configuration says `surrogates = ...`. When on, the audit
records declare `mamori.protection-scope/1+surrogate`, and a consumer that
refuses unknown contracts refuses them -- which is the intended way to opt in:
knowing they exist is what makes them safe to read.
