# 6. Mappings live in memory by default

**Status:** accepted

## Context

The mapping table is not a cache. It is a list containing only the values
somebody was trying to keep off other machines, indexed and deduplicated.

Persisting it by default would be convenient: protect in one process, restore in
another; survive a restart; audit later. It would also create a file that did
not exist before — one that gets backed up, synced and forgotten.

That trades a transmission risk for a storage risk, and making that trade
silently is not the library's call.

## Decision

`InMemoryMappingStore` is the default. Nothing reaches disk unless asked.

`PrivacySession.close()` purges the scope, and the session is a context manager,
so the common shape discards mappings on the way out.

`--save-mapping` exists for a two-process CLI round trip. It writes plaintext,
says so on stderr every time it runs, embeds the warning in the file itself, and
the usual filenames are in `.gitignore`.

An encrypted persistent store is roadmap work, not v0.1.

## Consequences

The default configuration leaves nothing behind. No file to encrypt, no key to
manage, no retention policy to get wrong.

Scopes partition the store, so one session cannot resolve another session's
placeholders even when both share a store instance.

## What it costs

Multi-process and long-lived workflows need the plaintext export until the
encrypted store lands, and that export is genuinely dangerous. Making it loud
rather than removing it is the compromise: the workflow is real, and somebody
who needs it will otherwise reimplement it worse.

`purge()` drops references. Python cannot guarantee the strings are gone from
memory, so this is not a secure wipe. `docs/threat-model.md` says so plainly.
