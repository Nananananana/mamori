# Architecture decision records

One file per decision that changed a boundary, a default, or a security
property. Each says what the situation was, what was chosen, what follows from
it, and — the part that is usually missing — what it costs.

| # | Decision |
|---|---|
| [0001](0001-domain-depends-on-nothing.md) | The domain layer imports only the standard library |
| [0002](0002-fail-closed.md) | Fail closed, and block credentials rather than pseudonymize them |
| [0003](0003-readable-placeholders.md) | Placeholders are readable tokens, not random strings |
| [0004](0004-offset-preserving-normalization.md) | Normalize with an offset map instead of normalizing the text |
| [0005](0005-overlap-resolution.md) | Resolve overlapping detections by width first |
| [0006](0006-mappings-live-in-memory.md) | Mappings live in memory by default |
| [0007](0007-defer-the-async-machinery.md) | Defer the async, event and envelope machinery |
| [0008](0008-language-packs.md) | Language packs, selected by script |
| [0009](0009-measure-leaked-characters.md) | Measure leaked characters, not just entity F1 |
| [0010](0010-streaming-restoration.md) | Restore streamed responses by holding the shortest unsafe suffix |
| [0011](0011-detection-as-a-pipeline.md) | Detection is a pipeline of passes |
| [0012](0012-configuration-without-a-format.md) | One configuration object, no configuration format |
| [0013](0013-recall-first-by-default.md) | Recall first, by default |
| [0014](0014-prompts-are-documents.md) | Prompts are documents with addressable parts |
