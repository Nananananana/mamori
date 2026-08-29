"""Remembering what a model answered, so a measurement can be repeated.

Measuring the model tier means asking a model about every sample in every
dataset. That is slow enough that nobody does it twice, and a number nobody
re-runs is a number nobody checks.

A cache fixes that, and it brings one property worth more than the speed: the
key includes the **prompt**. Ask the same model the same question and the
answer comes back instantly. Change one line of guidance and every affected
entry misses, because the same model under a rewritten prompt is a different
reader. So a prompt change can be measured against the samples it actually
touches, rather than against whatever the machine felt like re-running. That
framing is the sibling `kiseki` project's ADR-0051, applied to a cache key
instead of a database column.

**This writes to disk, and that is why it lives here rather than in
``infrastructure``.**

Everywhere else, mamori holds what it learned about a document in memory and
writes nothing (`ADR 0006`). A cache of model answers breaks that: an answer
names the spans it found, so the file is derived from the text. Keeping it in
the evaluation package, reachable only by passing a path in Python and named by
no configuration key, means the storage claim in ``mamori privacy`` stays true
for every configuration a user can express -- and `tests/test_promises.py`
checks exactly that.

Use it for measurement against data you are willing to have on disk. The
bundled datasets are invented, which is what makes them safe to cache.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from ..ports.llm import BatchLLMProvider, LLMProvider, LLMRequest, LLMResponse

__all__ = ["CachedProvider"]

_FORMAT_VERSION = 1


class CachedProvider:
    """Wraps a provider and remembers what it said.

    Args:
        inner: The provider that does the work on a miss.
        path: Where the cache lives. Created on first write.
        read_only: Answer from the cache and refuse to call the model on a
            miss. Turns a measurement into a replay of one, which is how a
            scoring change is checked without the model's variance in the way.

    Raises:
        LookupError: ``read_only`` and the answer is not cached.
    """

    def __init__(self, inner: LLMProvider, path: Path, *, read_only: bool = False) -> None:
        self._inner = inner
        self._path = Path(path)
        self._read_only = read_only
        self._entries: dict[str, str] = _load(self._path)
        self._dirty = False
        self.hits = 0
        self.misses = 0
        #: Requests the inner provider could not answer. Counted because a run
        #: where every call failed reports a clean zero delta and looks exactly
        #: like a run where the model had nothing to add.
        self.failures = 0

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def supports_structured_output(self) -> bool:
        return self._inner.supports_structured_output

    @property
    def path(self) -> Path:
        return self._path

    def generate(self, request: LLMRequest) -> LLMResponse:
        key = _key(self.name, request)
        cached = self._entries.get(key)
        if cached is not None:
            self.hits += 1
            return LLMResponse(text=cached, model=self.name)
        if self._read_only:
            raise LookupError(
                "no cached answer for this request, and the cache is read-only. "
                "The prompt or the model changed, so the answer this run needs "
                "was never recorded."
            )
        self.misses += 1
        try:
            response = self._inner.generate(request)
        except Exception:
            self.failures += 1
            raise
        self._entries[key] = response.text
        self._dirty = True
        return response

    def generate_batch(self, requests: Sequence[LLMRequest]) -> Sequence[LLMResponse]:
        """Answer the cached ones from here and batch only what is missing.

        A run that is half cached should send half a batch, not all of it and
        not one request at a time.
        """
        answers: list[LLMResponse | None] = []
        pending: list[tuple[int, LLMRequest]] = []
        for index, request in enumerate(requests):
            cached = self._entries.get(_key(self.name, request))
            if cached is not None:
                self.hits += 1
                answers.append(LLMResponse(text=cached, model=self.name))
            else:
                answers.append(None)
                pending.append((index, request))

        if pending:
            if self._read_only:
                raise LookupError(f"{len(pending)} of {len(requests)} answers are not cached")
            self.misses += len(pending)
            try:
                fresh = self._ask(tuple(request for _, request in pending))
            except Exception:
                self.failures += len(pending)
                raise
            for (index, request), response in zip(pending, fresh, strict=True):
                answers[index] = response
                self._entries[_key(self.name, request)] = response.text
            self._dirty = True

        return [answer for answer in answers if answer is not None]

    def _ask(self, requests: Sequence[LLMRequest]) -> Sequence[LLMResponse]:
        if isinstance(self._inner, BatchLLMProvider):
            return self._inner.generate_batch(requests)
        return [self._inner.generate(request) for request in requests]

    def save(self) -> None:
        """Write the cache out. A no-op when nothing was added."""
        if not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"format_version": _FORMAT_VERSION, "entries": self._entries}
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        self._dirty = False

    def __enter__(self) -> CachedProvider:
        return self

    def __exit__(self, *exc: object) -> None:
        self.save()

    def __len__(self) -> int:
        return len(self._entries)


def _key(model: str, request: LLMRequest) -> str:
    """Identity of one question.

    The system prompt is part of it, so rewriting the guidance invalidates
    exactly the answers that depended on the old wording and nothing else.
    """
    digest = hashlib.sha256()
    for part in (model, request.system, request.user):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _load(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A corrupt cache is a slow run, not a failed one. It is derived data
        # and can always be rebuilt by asking again.
        return {}
    if not isinstance(payload, dict) or payload.get("format_version") != _FORMAT_VERSION:
        return {}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return {}
    return {str(k): str(v) for k, v in entries.items()}
