# 16. The model and the client are both replaceable

**Status:** accepted

## Context

0.4.0 could talk to one thing: an OpenAI-compatible HTTP endpoint, reached with
`urllib`, configured by three constructor arguments. Changing the model meant
changing a string. Changing *how* the model is reached meant editing the
adapter.

Those are two different axes and they were welded together.

- **Which model** is a routine decision. A team tries `qwen2.5:7b`, finds it
  misses Japanese company names, moves to a 72B on the shared server. Nothing
  structural changed.
- **Which client** is not routine, but it is inevitable. Someone will want
  `llama-cpp-python` in-process with no HTTP at all. Someone will have a vLLM
  deployment behind an in-house gateway with its own authentication. Someone
  will have a `transformers` pipeline already loaded in the same process and no
  desire to serve it over a socket just to satisfy an adapter.

Meanwhile the library ships with **zero runtime dependencies**, and that is not
an aesthetic position — it is what makes a privacy tool auditable. Vendoring an
SDK for every backend anyone might use would end that immediately.

## Decision

Separate the three concerns that were one.

**`LLMEndpoint`** (a port-layer value) says *where and how*: model, base URL,
key environment variable, timeout, retries, backoff, trust policy, extra
options. It is a frozen dataclass with no behaviour beyond `with_policy()` and
reading its key from the environment. Switching models is a field.

**`LLMProvider`** (the existing port) stays the only thing the detection pass
knows about. It has one required method.

**A provider registry** maps a name to a factory:

```python
register_llm_provider("vllm", lambda endpoint: MyVLLMProvider(endpoint))
```

Configuration then names it — `{"llm": {"provider": "vllm", ...}}` — and
nothing else in the library changes. `available_providers()` lists what is
registered, so a typo produces a list of the alternatives rather than an
`ImportError` from somewhere unrelated.

**`CallableProvider`** wraps any function of `(prompt) -> str`:

```python
session_llm = CallableProvider(my_pipeline, name="local-transformers")
```

This is the escape hatch that makes the whole scheme cheap. Anyone with a model
already in their process — any library, any framework, loaded any way — has a
working provider in one line and needs no adapter, no registration and no
change here.

The bundled `openai_compatible` provider remains the default, still on
`urllib`, still zero-dependency.

## Consequences

**No dependency is added for any of it.** The registry is a dict. The callable
provider is a wrapper. The dependency an alternative backend needs is installed
by the person who wants that backend, in their own project.

**The two axes move independently.** Changing the model is configuration.
Changing the client is one registration. Neither requires touching detection,
policy, or anything in the domain layer.

**The trust boundary applies to the transport, not the provider interface.** A
custom provider that opens its own socket is outside what the library can
check — it is the author's own code, and mamori cannot audit it. The bundled
HTTP provider enforces the boundary; a registered one is responsible for its
own. `mamori llm` reports which provider is in use, so a reviewer can see when
that responsibility has moved.

**`LLMEndpoint` accumulates fields over time.** A frozen dataclass with a dozen
optional fields is not elegant. The alternative — a `dict` of options — moves
every mistake from import time to request time, in the one place where a
mistake sends data somewhere unintended. The verbosity is the cheaper cost.
