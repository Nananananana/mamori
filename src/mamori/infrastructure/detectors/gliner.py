"""GLiNER: a recogniser you tell what to look for, in words.

`SpacyRecognizer` finds what its model was trained to find, and that list is
fixed at training time -- `PERSON`, `ORG`, `GPE`, and nothing else, ever. A
deployment that needs *"medication"* or *"internal case reference"* has to
train a model or write a rule, and `SECURITY.md` is explicit that a rule
cannot find what has no shape.

GLiNER (Zaratiana et al., 2024, Apache-2.0) takes the entity types as **text**
and scores spans against them, so a new category is a string in a
configuration::

    MamoriConfig(nlp="gliner")                       # personal names
    GlinerRecognizer(labels=("person", "medication", "medical condition"))

**Measured, on 2026-09-04, on the sentences the English rules are measured
on.** Numbers, not adjectives, because a model is where a library is most
tempted to describe instead of measure::

    English, urchade/gliner_multi-v2.1, threshold 0.5
      Sarah Okonkwo / Yuki Tanaka / Marcus Lindqvist / Priya Raman
      / Nguyen Thi Hoa / Aleksandr Volkov            6 of 6, 0.96-0.98
      "The Quarterly Business Review is Monday."     nothing  (correct)
      "Social Security Number is required..."        nothing  (correct)

The balanced stance finds none of those six. spaCy `en_core_web_sm` finds
five: it misses `Aleksandr Volkov`, which this gets at 0.96::

    New categories, given only as words
      "chest pain" as medical condition              0.90
      "metoprolol" as medication                     0.91
      "42%" as financial figure                      0.72
      "The weather is nice and the build is green."  nothing  (correct)

    And what it does not do
      "Ship Project Nightingale to the Osaka plant"  nothing, at any threshold,
        as internal project codename                 on either model

So it generalises to categories that resemble ones it has seen, and not to
ones invented on the spot. The internal-codename gap `SECURITY.md` describes
is still open, and this does not close it.

**Japanese: do not use this for it.** Also measured, same run::

    Sentence with 田中太郎さん
        gliner_multi-v2.1    nothing
        gliner_multi_pii-v1  seventeen characters at 0.57 -- the name plus
                             most of the clause after it
    Sentence listing 佐藤花子, 鈴木一郎, 山田
        both                 missed 佐藤花子; took 山田です with the copula
    Sentence with 担当は高橋。
        both                 nothing

Wrong spans, not just low recall, and a wrong span is worse than a miss: it
replaces a clause with a placeholder and the answer comes back about nothing.
The Japanese rules -- honorifics, the 様/さん/氏 anchors, the surname list --
find these, and this pass runs after them and skips what they claimed, so the
damage is bounded. It is still the wrong tool for Japanese. Chinese: found
nothing at all in the same run.

**Cost.** ``pip install "mamori[gliner]"`` pulls torch and transformers,
several hundred megabytes, plus a model download of about the same. Roughly
90ms per short sentence on a CPU, against 4ms for the whole rule pipeline.
That is a deployment decision, which is why it is a name in a configuration
and not a default.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from typing import Any

from ...domain.span import Span
from ...domain.windowing import LONGEST_ENTITY, longest_whole, windows
from ...errors import ConfigurationError, DetectionError
from ...ports.nlp_recognizer import RecognizedEntity

__all__ = [
    "DEFAULT_GLINER_LABELS",
    "DEFAULT_GLINER_MODEL",
    "DEFAULT_THRESHOLD",
    "GlinerRecognizer",
]

#: Multilingual, Apache-2.0, and the one measured above. Not the PII-tuned
#: `gliner_multi_pii-v1`: on the same English sentences the two are equal, and
#: on Japanese the PII model is the one that produced the seventeen-character
#: span. A model fine-tuned on synthetic PII is more confident, not more right.
DEFAULT_GLINER_MODEL = "urchade/gliner_multi-v2.1"

#: What to look for, in the words the model reads. `person` only, matching
#: `DEFAULT_LABELS` in `nlp.py` and for the same measured reasons:
#: organisations and places cost more answer quality than they buy, and the map
#: from these strings to entity types is `NlpPass`'s to make.
DEFAULT_GLINER_LABELS: tuple[str, ...] = ("person",)

#: Below this the model is guessing. GLiNER's own examples use 0.5; at 0.3 the
#: only thing that moved in the measurements above was `42%`, and the false
#: positives stayed empty -- so this is the published default rather than one
#: tuned on six sentences.
DEFAULT_THRESHOLD = 0.5

#: Characters per window. The model truncates its input silently, which is the
#: fail-open failure this library exists to avoid: a long document would come
#: back clean because the end of it was never read. DeBERTa-v3's 512 positions
#: are roughly 1000 characters of mixed script, with room to spare.
_WINDOW = 1000

#: Repeated between windows, so a name on a cut is whole in one of them.
#: `longest_whole` turns this into the promise that is actually kept, and the
#: constructor checks that against `LONGEST_ENTITY` rather than trusting it.
_OVERLAP = 128


class GlinerRecognizer:
    """GLiNER, loaded once and asked per text.

    Args:
        model: A GLiNER checkpoint -- anything ``GLiNER.from_pretrained``
            accepts, including a local directory.
        labels: Entity types, as the words the model reads. These are also what
            arrives at `NlpPass`'s label map, upper-cased: ``"person"`` reaches
            it as ``PERSON``.
        threshold: Scores below this are not reported.
        name: Recorded on every entity, so ``mamori trace`` says which model.

    Raises:
        ConfigurationError: the package is missing, or the model will not load.
            Raised when the session is built, not on the first document.
    """

    def __init__(
        self,
        model: str = DEFAULT_GLINER_MODEL,
        *,
        labels: Sequence[str] = DEFAULT_GLINER_LABELS,
        threshold: float = DEFAULT_THRESHOLD,
        name: str = "",
    ) -> None:
        if not labels:
            raise ConfigurationError(
                "GlinerRecognizer needs at least one label: it is told what to look "
                "for rather than trained on it, and an empty list looks for nothing."
            )
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold out of range: {threshold}")
        whole = longest_whole(_WINDOW, _OVERLAP)
        if whole < LONGEST_ENTITY:  # pragma: no cover - both are constants here
            raise ValueError(
                f"windows of {_WINDOW} overlapping {_OVERLAP} keep only {whole} "
                f"characters whole; entities up to {LONGEST_ENTITY} are expected"
            )
        self._labels = list(labels)
        self._threshold = threshold
        self._model_name = model
        self._name = name or f"gliner/{model.rsplit('/', 1)[-1]}"
        # One model, one lock. Torch modules hold buffers across a forward pass
        # and this library is used from threads -- the proxy serves concurrent
        # conversations. Serialising inference is the boring answer and the
        # only one that does not depend on a version's internals.
        self._lock = threading.Lock()
        self._model = self._load(model)

    @staticmethod
    def _load(model: str) -> object:
        try:
            from gliner import GLiNER
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on install
            raise ConfigurationError(
                "the GLiNER recogniser needs the `gliner` package: "
                'pip install "mamori[gliner]". It is optional because it pulls '
                "torch and transformers -- several hundred megabytes for a library "
                "whose rules need no model at all."
            ) from exc
        try:
            return GLiNER.from_pretrained(model)
        except Exception as exc:
            raise ConfigurationError(
                f"could not load the GLiNER model {model!r}: {exc}. The first load "
                "downloads it; check the name and that the machine can reach the "
                "hub, or point this at a local directory."
            ) from exc

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(self._labels)

    def entities(self, text: str) -> Sequence[RecognizedEntity]:
        """What the model sees, in character offsets of ``text``.

        Windowed, because the model truncates a long input without saying so.
        The same span found in two overlapping windows is reported once, at the
        better score.
        """
        best: dict[tuple[int, int, str], RecognizedEntity] = {}
        for window in windows(text, _WINDOW, _OVERLAP):
            for found in self._predict(window.text):
                start, end = window.locate(int(found["start"]), int(found["end"]))
                if not 0 <= start < end <= len(text):
                    raise DetectionError(
                        f"{self._name} reported a span outside the text; nothing was emitted"
                    )
                label = str(found["label"])
                score = float(found.get("score", 1.0))
                previous = best.get((start, end, label))
                if previous is None or previous.score < score:
                    best[start, end, label] = RecognizedEntity(
                        label=label, span=Span(start, end), score=score
                    )
        return sorted(best.values(), key=lambda entity: (entity.span.start, entity.span.end))

    def _predict(self, text: str) -> Sequence[Mapping[str, Any]]:
        """What GLiNER returns, unexamined.

        `Any` because this is the boundary: the dicts come from a library with
        no type information, and pretending otherwise would put the assertion
        in the annotation instead of in the code. Every field is checked where
        it is used -- the offsets against the text, the score by the pass.
        """
        with self._lock:
            return self._model.predict_entities(  # type: ignore[attr-defined,no-any-return]
                text, self._labels, threshold=self._threshold
            )
