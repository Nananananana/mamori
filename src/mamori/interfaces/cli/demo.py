"""A guided tour, and a way to try it on your own text.

Reading what a privacy layer claims is not the same as watching it happen to a
sentence you recognise. This module is the difference: five short scenarios
that need nothing installed, and a ``--live`` mode that sends a real request to
a real model so the whole round trip is visible rather than described.

Each scenario answers one question somebody actually has.

``roundtrip``   What does the model see, and do I get my words back?
``stream``      What happens when a placeholder arrives in pieces?
``document``    Does this work on something longer than a sentence?
``corrections`` It got one wrong. Now what?
``blocked``     What if there is a password in my text?
``surrogates``  Can I have readable values instead of tokens?

The demo text is invented, like everything else that ships in this package.
``--text`` and ``--file`` run the same tour on yours instead, which is the
point at which somebody finds out whether this is any use to them.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ...config import MamoriConfig
from ...domain.corrections import Correction, CorrectionLog, Verdict
from ...domain.script import scripts_in
from ...errors import PolicyViolationError
from ..proxy.upstream import Upstream, UpstreamError

__all__ = ["SCENARIOS", "run_demo"]

DEMO_TEXT = """田中太郎さんへ

株式会社さくら商事の佐藤花子です。先日の件、tanaka@example.com か
090-1234-5678 にご返信ください。社内Wikiは https://wiki.corp.local/project です。

CC: Mr. John Smith (Acme Inc.), 415-555-0198"""

DOCUMENT_TEXT = """Subject: Re: Migration window

Hi Priya Raman,

Thanks for the quick turnaround. I have copied Michael Chen so he can approve
it before he goes on leave.

One thing: the runbook still points at the old staging box. Could you update it
to 10.0.4.17 when you get a moment? Priya Raman mentioned the DNS entry moved.

If anything goes wrong overnight my mobile is 415-555-0198.

Best,
Robert Lang
Platform Engineering"""

_RULE = "─" * 68


def _heading(text: str) -> None:
    print()
    print(text)
    print(_RULE)


def _block(label: str, body: str) -> None:
    print(f"\n{label}")
    for line in body.splitlines() or [""]:
        print(f"  {line}")


# -- the scenarios -----------------------------------------------------------


def _roundtrip(config: MamoriConfig, text: str) -> None:
    _heading("1. A round trip")
    print("Your text is protected here, the model sees placeholders, and the")
    print("answer is put back into your own words. The mapping never leaves.")

    with config.session() as session:
        result = session.protect(text)
        _block("you wrote", text)
        _block("the model sees", result.protected_text)

        print(f"\nreplaced {result.entity_count} value(s), and what found each one:")
        for entity in result.entities:
            target = entity.placeholder or entity.action.value
            print(
                f"  {target:<20}{entity.entity_type:<14}{entity.source:<12}{entity.confidence:.2f}"
            )
        print("\nThe last two columns are the rule set that fired and how sure it")
        print("was, so 'why was this replaced?' has an answer.")
        print(f"scripts found: {', '.join(sorted(s.value for s in scripts_in(text)))}")

        reply = _pretend_reply(result.protected_text)
        _block("a reply comes back", reply)
        _block("restored, locally", session.restore(reply).text)


def _stream(config: MamoriConfig, text: str) -> None:
    _heading("2. A streamed answer")
    print("An answer arrives token by token, so <PERSON_001> shows up as")
    print("'<PER', 'SON_0', '01>'. The restorer holds back the shortest suffix")
    print("that could still become a placeholder, and releases the rest.")

    with config.session() as session:
        session.protect(text)
        chunks = ["こんにちは、", "<PER", "SON_0", "01>", "さん。", "ご連絡は<EMAIL_0", "01>まで。"]
        stream = session.stream_restore()

        print()
        for chunk in chunks:
            out = stream.feed(chunk)
            held = "…" if not out else ""
            print(f"  chunk {chunk!r:<18} -> {out!r}{held}")
        tail = stream.finish()
        if tail:
            print(f"  {'(end)':<24} -> {tail!r}")


def _document(config: MamoriConfig, text: str) -> None:
    _heading("3. Something longer than a sentence")
    print("Documents are where this gets hard: a name introduced once and")
    print("referred to four more times, a signature block, a quoted reply.")

    with config.session() as session:
        result = session.protect(text)
        _block("protected", result.protected_text)
        print(f"\n{result.entity_count} replacement(s) across {len(text)} characters.")
        print("The same value keeps the same placeholder wherever it appears,")
        print("so the model can tell that two mentions are the same person.")


def _corrections(config: MamoriConfig, text: str) -> None:
    _heading("4. When it gets one wrong")
    wrong = "Dear Monday, the contract is with Acme until March."
    print("A salutation is a strong anchor and it is right far more often than")
    print("it is wrong. 'Dear Monday,' is when it is wrong -- and 'Acme' is a")
    print("trading name with no legal suffix, which no pattern can reach.")

    with config.session() as session:
        _block("without corrections", session.protect(wrong).protected_text)

    log = CorrectionLog.of(
        [
            Correction("Monday", Verdict.NEVER, note="a weekday, not a name"),
            Correction("Acme", Verdict.ALWAYS, entity_type="COMPANY_NAME"),
        ]
    )
    corrected = MamoriConfig(corrections=[c.as_mapping() for c in log])
    with corrected.session() as session:
        _block("after two corrections", session.protect(wrong).protected_text)

    print("\n  mamori correct Monday --never --note 'a weekday, not a name'")
    print("  mamori correct Acme --always COMPANY_NAME")
    print("\nAppend-only: undo is another correction, and 'mamori privacy'")
    print("reports every value you have ruled out.")


def _blocked(config: MamoriConfig, text: str) -> None:
    _heading("5. When there is a credential in the text")
    print("A name is replaced. A password is not: there is no safe placeholder")
    print("for a credential, so the request stops instead.")

    with config.session() as session:
        try:
            session.protect("the staging password is hunter2spring, can you check?")
            print("\n  (not blocked -- this should not happen)")
        except PolicyViolationError as exc:
            _block("refused", str(exc))
            print("Nothing was sent. The credential is not quoted back, either.")


def _surrogates(config: MamoriConfig, text: str) -> None:
    _heading("6. Plausible values instead of tokens")
    print("Some models reason badly about a page of <PERSON_001>. Substituting")
    print("a readable name usually gets a better answer -- and gives up the")
    print("thing that makes a token safe.")

    sample = "Dear Jane Doe, reach me at jane.doe@example.com or 415-555-0198."
    with config.session() as session:
        _block("with tokens (the default)", session.protect(sample).protected_text)

    surrogate = MamoriConfig(surrogates=True)
    with surrogate.session() as session:
        result = session.protect(sample)
        _block("with surrogates", result.protected_text)
        _block("restored", session.restore(result.protected_text).text)

    print()
    print("The address and the number come from ranges reserved for")
    print("documentation, so one that escapes means nothing anywhere. Nothing")
    print("is reserved for personal names, which is the risk that stays.")

    with surrogate.session() as session:
        result = session.protect(sample)
        mangled = result.protected_text.replace("Alex Rivera", "Alex")
        _block("if the model rewrites one", mangled)
        answer = session.restore(mangled)
        _block("restored", answer.text)
        print()
        print(f"  missing: {[p.token for p in answer.missing]}")

    print()
    print("A token can be recognised by its shape, so restoration tolerates a")
    print("model that mangles it. A surrogate is just a name -- it either")
    print("matches or it does not. That is why this is off by default, and why")
    print("RestorationResult.missing is the thing to check when it is on.")


SCENARIOS: dict[str, Callable[[MamoriConfig, str], None]] = {
    "roundtrip": _roundtrip,
    "stream": _stream,
    "document": _document,
    "corrections": _corrections,
    "blocked": _blocked,
    "surrogates": _surrogates,
}


def _pretend_reply(protected: str) -> str:
    """A plausible answer, with the placeholders mangled the way models do."""
    reply = "\n<PERSON_001>様\n\nお世話になっております。PERSON_002です。\n"
    reply += "<EMAIL_1> 宛にご返信いたします。よろしくお願いいたします。"
    del protected
    return reply


# -- live mode ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiveSettings:
    """Where to send the protected prompt."""

    base_url: str
    model: str
    api_key: str = ""
    timeout: float = 180.0


def _live(config: MamoriConfig, text: str, live: LiveSettings) -> int:
    """Protect, ask a real model, restore its answer.

    The trust boundary deliberately does not apply here. It refuses an external
    *detector*, because a detector is shown the document before it is
    protected. This is the opposite case: the service the caller chose, which
    sees protected text only. Sending to it is the entire point.
    """
    _heading("Live: a real model, a real round trip")
    print(f"model     {live.model}")
    print(f"endpoint  {live.base_url}")

    upstream = Upstream(live.base_url, timeout=live.timeout)
    headers = {"Authorization": f"Bearer {live.api_key}"} if live.api_key else {}

    with config.session() as session:
        result = session.protect(text)
        _block("you wrote", text)
        _block("what actually goes over the wire", result.protected_text)

        if not result.entity_count:
            print("\n  (nothing was detected in this text)")

        payload = {
            "model": live.model,
            "messages": [
                {"role": "system", "content": session.external_system_prompt()},
                {"role": "user", "content": result.protected_text},
            ],
            "stream": False,
        }

        print("\nasking the model...")
        try:
            reply = upstream.send("chat/completions", payload, headers)
        except UpstreamError as exc:
            print(f"\n  {exc}")
            print("\n  Is the endpoint running? Try:  mamori llm --check")
            return 1

        answer = _answer_text(reply.json())
        if answer is None:
            print("\n  the reply had no message content")
            return 1

        _block("what the model said (placeholders intact)", answer)
        _block("restored into your own words", session.restore(answer).text)

    print("\nThe model never saw a name, an address or a number from your text.")
    print("The mapping back was held in memory here and is gone already.")
    return 0


def _answer_text(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    return content if isinstance(content, str) else None


# -- entry point -------------------------------------------------------------


def run_demo(
    config: MamoriConfig,
    *,
    text: str | None = None,
    scenarios: Sequence[str] | None = None,
    live: LiveSettings | None = None,
    as_json: bool = False,
) -> int:
    """Run the tour, or one scenario, or a live round trip."""
    subject = text if text is not None else DEMO_TEXT

    if as_json:
        with config.session() as session:
            result = session.protect(subject)
            print(
                json.dumps(
                    {
                        "original_characters": len(subject),
                        "protected": result.protected_text,
                        "replaced": result.counts_by_type(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 0

    if live is not None:
        return _live(config, subject, live)

    chosen = list(scenarios) if scenarios else list(SCENARIOS)
    for name in chosen:
        runner = SCENARIOS[name]
        # The document scenario has its own fixture unless you supplied one.
        material = subject
        if name == "document" and text is None:
            material = DOCUMENT_TEXT
        runner(config, material)

    print()
    print(_RULE)
    print("Try it on your own text:   mamori demo --file draft.txt")
    print("Against a real model:      mamori demo --live --model qwen3:8b \\")
    print("                             --api http://localhost:11434/v1/")
    print("In front of your app:      mamori serve --upstream <your api>")
    return 0
