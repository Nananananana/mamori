# Which local model, and at what quantisation

The model tier is off by default and the README says to measure it on your own
hardware. This is that measurement, on a development machine with a **16 GB
RTX 4070 Ti SUPER**, where a model has to leave room for everything else.

The harness that produced it is not in this repository — it drives `mamori
eval --compare` over a list of models and is kept with the raw outputs. What is
here is what it found.

Every row below was taken with the device recorded beside it — `[100% GPU]` —
for reasons the last section explains.

## The table

Eight documents per language, `en-docs` and `ja-docs`, at the recall-first
default. "over" is the over-redaction the model **added** to the rules'.

| model | VRAM | s/doc en·ja | en leak | en over | ja leak | ja over |
|---|---|---|---|---|---|---|
| `qwen2.5:14b-instruct-q4_K_M` | 9.0 GB | 4.6 · 5.1 | 3.50 → **0.36%** | **±0.00** | 0.33 → **0.00%** | **±0.00** |
| `qwen2.5:7b-instruct-q8_0` | 8.1 GB | 3.6 · 4.1 | 3.50 → 1.21% | **±0.00** | 0.33 → **0.00%** | **±0.00** |
| `qwen2.5:7b-instruct-q4_K_M` | 4.7 GB | **3.2 · 3.5** | 3.50 → 1.21% | +0.20 | 0.33 → **0.00%** | +0.26 |
| `llama3.1:8b` (q4) | 4.9 GB | 6.9 · 6.0 | 3.50 → 0.84% | +0.44 | 0.33 → **0.00%** | +1.50 |
| `gemma4:12b` | 7.6 GB | 36.7 · 34.8 | **not measured** | — | **not measured** | — |

## The 14B does not find more things. It finds more of each thing.

This is the result worth taking away, and it is invisible in the leak column
alone.

**Entity recall is identical across the 14B and both 7Bs** — `+0.083` in
English, `+0.016` in Japanese, to three decimal places, for all three. They
detect the same entities. All three also close the same three documents
(`en-doc-002`, `-003`, `-007`) and the same one in Japanese (`ja-doc-006`).

What separates `0.36%` from `1.21%` is **characters, not entities**: the 14B
covers more of each span it finds. A name it gets whole, the 7B gets from the
surname to somewhere short of the end.

So "the 14B is more accurate" is true and says the wrong thing. It is not
seeing values the smaller model misses. It is drawing the boundaries better.

## What each one paid

A leak rate ordered on its own hides how it was bought. Every model here trades
against precision, and they do not trade the same way:

| model | recall gained | precision paid |
|---|---|---|
| `7b-q8_0` | +0.083 / +0.016 | **+0.004 / +0.001** — paid nothing, gained a little |
| `14b-q4_K_M` | +0.083 / +0.016 | −0.011 / +0.001 |
| `7b-q4_K_M` | +0.083 / +0.016 | −0.011 / −0.013 |
| `llama3.1:8b` | **+0.100** / +0.016 | **−0.025 / −0.027** |

`llama3.1:8b` has the best entity recall on the page and the worst precision by
a factor of two. Whether that is a good trade is a question about your stance,
not about the model, and the leak column does not ask it.

**Quantisation costs precision, not recall.** The two 7Bs have identical recall
and identical leak rates; q4 pays `−0.011 / −0.013` where q8 pays nothing. That
is the cheaper failure for this library and it is not free.

## The recommendation for 16 GB

**`qwen2.5:7b-instruct-q8_0`**, unless 9 GB is free.

It adds nothing wrong — the only model here with positive precision on both
languages — leaves 8 GB of the card, and answers in four seconds. It gives up
0.85 points of English leak against the 14B, and that 0.85 is span boundaries
on values it already found, not values it missed.

**`qwen2.5:14b-instruct-q4_K_M` when the card is otherwise idle.** Best leak
rate on the page, no added over-redaction, half a second slower than the 7B.
The 9 GB is the whole objection; on this machine it fits and on a shared one it
will not.

`q4_K_M` if 4.7 GB matters more than a fifth of a point of over-redaction.

**Not `gemma4:12b`, and not for the reason the table first suggested.**

## The row that was not measured

`gemma4:12b` cost 35 seconds a document and moved nothing. That reads as a
model with nothing to add, and it is not one.

It is a **reasoning model**. Given mamori's 7,552-character detection prompt it
writes 7,387 characters into a `reasoning` field and returns `content: ""` —
the token budget is gone before it begins answering. mamori read the empty
answer, the parse failed, and the run recorded a model that contributed
nothing.

The detection pass had recorded the failure the whole time, on `last_outcome`.
**Nothing above it was looking.** `EvaluationReport.unanswered_samples` and a
`MODEL UNREAD` line in `mamori eval` exist now because of this row.

Two things to keep from it:

**A model can fail in a way that looks like a measurement.** Every other kind
of failure here is loud — a timeout, a refused endpoint, a parse error on a
malformed answer. This one produced a well-formed table with a plausible number
in it.

**Raising `llm.max_tokens` may make it work.** It has not been tried. A
reasoning model needs room for the reasoning *and* the answer, and 2048 was
sized for models that only produce the second.

## Every second on this page is a GPU second, and that is checked

The previous version of this file had no seconds at all. The ones before that —
20 to 345 a document — were **CPU inference on a machine with an idle GPU**: an
interrupted Ollama update had left no `ggml-cuda.dll`, so GPU discovery failed
in 0.19 seconds instead of the 6.7 it takes when it works, and every run for
six days went to the processor.

The 345 seconds had an explanation, too. It was attributed to VRAM contention
between resident models — a story that fit the effect, was checkable, and was
not checked. The real figure is **4.6**.

The check that stops it happening again is in the harness, and it is worth
reading because the first version of it was also wrong. It printed the third
field from the end of `ollama ps`, which is the `UNTIL` column: every row of
that run recorded its device as **`[minutes]`** — not an error, a word, printed
in the same brackets a real device would use, and identical whether the work
ran on the GPU or the CPU. The line existed *because* six days of timings had
been taken without anybody reading the log that said so, and then it printed
something unreadable in the place reserved for the thing nobody was reading.

It now finds the field ending in `%` and takes the word after it, and **raises
rather than returning a fallback string**. Verified against five formats,
including `51%/49% CPU/GPU` — a partially offloaded model, which on a 16 GB
card running a 9 GB model is not a hypothetical, and which the position-counting
version could never have produced.

## An open question about these numbers

**Whether the device changes the accuracy figures is not settled.**

This page's earlier CPU run and this GPU run disagree on two rows —
`7b-q4_K_M` Japanese over-redaction (+0.84 against +0.26) and `llama3.1:8b`
English leak (1.21% against 0.84%) — while the other rows match. Sampling is
ruled out: at `temperature=0.0` the same prompt returns a byte-identical answer
three times on one device.

What is not ruled out is that mamori changed between the two runs. The morning's
per-model outputs were overwritten by the evening's, so the surviving artifacts
cannot separate the two explanations.

Until it is settled, **"the device does not change what a model returns" is not
a claim this page makes.** It was made, repeatedly, as the reason the accuracy
figures survived the CPU/GPU mix-up — asserted rather than measured, which is
the same shape as the 345 seconds it was used to excuse.

## Anything OpenAI-compatible

mamori speaks the OpenAI chat API and nothing else, so the server is a `base_url`:

```json
{"llm": {"model": "qwen2.5-7b-instruct", "base_url": "http://localhost:8000/v1/"}}
```

That is Ollama above, and it is equally **vLLM** (`vllm serve
Qwen/Qwen2.5-7B-Instruct`), llama.cpp's server, LM Studio, TGI, or a shared
model on a company machine — the trust boundary admits anything on the private
network and refuses a public API endpoint
([ADR 0015](adr/0015-a-trust-boundary-not-a-localhost-check.md)).

vLLM is worth the setup where throughput matters: it batches, and this
measurement is eight documents one at a time, which is the case it is worst at.
