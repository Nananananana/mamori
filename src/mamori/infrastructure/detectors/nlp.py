"""The detection pass that asks a recogniser, and the spaCy adapter.

Two pieces, kept apart because they fail for different reasons. `NlpPass` turns
a recogniser's labels into mamori's entity types and is pure bookkeeping;
`SpacyRecognizer` loads a model and is where every environment problem lives.

**Off unless asked for**, `MamoriConfig(nlp="spacy")`, and the reason is not
caution about quality. A model is a dependency with a download, a version and a
few hundred megabytes of memory, and this library's promise of zero
unconditional runtime dependencies is what lets it be installed anywhere. The
model is an extra: `pip install "mamori[nlp]"`.

**What it buys, measured on the sentences the English rules are measured on.**
`SECURITY.md` calls an unanchored English name the largest single gap here, and
the recall-first stance closes it by accepting false positives -- 20.02% leak
down to 3.50% on `en-docs`, bought with over-redaction. A recogniser closes
part of the same gap without that trade:

    "I spoke to Sarah Okonkwo yesterday"          balanced: missed   spaCy: found
    "Attendees: Yuki Tanaka, Marcus Lindqvist"    balanced: missed   spaCy: found
    "Reported by: Nguyen Thi Hoa"                 balanced: missed   spaCy: found
    "The Quarterly Business Review is Monday"     balanced: clean    spaCy: clean
    "Social Security Number is required"          balanced: clean    spaCy: clean

It is not a replacement for the rules and is not offered as one. It missed
`Aleksandr Volkov` in a sentence it had every reason to get, which is what a
statistical recogniser is: better on average and worse to rely on. It runs
*after* the rules and only claims what nothing anchored has claimed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ...domain import entity_types as t
from ...domain.confidence import Confidence
from ...domain.entity_types import EntityType
from ...domain.sensitive_entity import SensitiveEntity
from ...domain.span import Span
from ...errors import ConfigurationError, DetectionError
from ...ports.detection_pass import DetectionContext
from ...ports.nlp_recognizer import NlpRecognizer, RecognizedEntity

__all__ = ["DEFAULT_LABELS", "NlpPass", "SpacyRecognizer"]

#: Which of a recogniser's labels become which entity type.
#:
#: **`PERSON` only**, and the two things left out were both measured rather
#: than assumed.
#:
#: `ORG` was in this map for one afternoon. `en_core_web_sm` tags *"The
#: Quarterly Business Review"* and *"Social Security Number"* as organisations
#: -- the exact two phrases the English stoplist exists to reject -- so the map
#: turned the model into a source of the false positives the rules had already
#: paid to remove. The company rules are anchored on a legal suffix and are
#: right about what they claim; a model guessing at organisations is not an
#: improvement on them.
#:
#: `GPE` and `LOC` were the obvious next line and are wrong for a different
#: reason: a city is not an address, and replacing every place name costs far
#: more answer quality than it buys.
#:
#: Both are one argument away, as a mapping somebody passes -- which is a
#: decision they have made rather than one they inherited.
DEFAULT_LABELS: Mapping[str, EntityType] = {
    "PERSON": t.PERSON,
    "PER": t.PERSON,  # what the CoNLL-style transformer models call it
}

#: What a model's opinion is worth. `MEDIUM`, deliberately: a checksum is
#: `CERTAIN` and an anchor is `HIGH`, and a recogniser is neither. Sitting at
#: `MEDIUM` means `min_confidence=0.8` drops it and `uncertain="refuse"` can be
#: made to stop on it, which is the point of having the dial.
DEFAULT_CONFIDENCE = Confidence(0.7)


class NlpPass:
    """Report what a recogniser sees, where nothing anchored already has.

    Args:
        recognizer: What actually reads the text.
        labels: Recogniser label -> entity type. Anything not in the map is
            ignored, so a model that grows a new label does not start
            producing entities nobody decided about.
        min_score: Recogniser scores below this are dropped before mamori's
            own confidence is applied. Separate from `min_confidence` because
            they are different questions: one is how sure the model is, the
            other is how much this library trusts a model.
        confidence: What every entity from this pass is worth.
        name: Recorded on each entity, so a report says a detection came from
            a model rather than a rule.
    """

    def __init__(
        self,
        recognizer: NlpRecognizer,
        *,
        labels: Mapping[str, EntityType] = DEFAULT_LABELS,
        min_score: float = 0.0,
        confidence: Confidence = DEFAULT_CONFIDENCE,
        name: str = "",
    ) -> None:
        if not 0.0 <= min_score <= 1.0:
            raise ValueError(f"min_score out of range: {min_score}")
        self._recognizer = recognizer
        self._labels = dict(labels)
        self._min_score = min_score
        self._confidence = confidence
        self._name = name or f"nlp:{recognizer.name}"

    @property
    def name(self) -> str:
        return self._name

    def run(self, context: DetectionContext) -> Sequence[SensitiveEntity]:
        text = context.text
        if not text:
            return []

        try:
            seen = self._recognizer.entities(text)
        except Exception as exc:
            # Fail closed. A model that did not load, ran out of memory or hit
            # a version mismatch must stop the request, not quietly report
            # nothing -- the caller cannot tell that from a clean document.
            raise DetectionError(f"{self._name} failed: {exc}") from exc

        covered = context.covered()
        found: list[SensitiveEntity] = []
        for entity in seen:
            entity_type = self._resolve(entity, text)
            if entity_type is None:
                continue
            if any(index in covered for index in range(entity.span.start, entity.span.end)):
                # A rule with an anchor already claimed it. An anchor beats a
                # model, and reporting the same span twice is noise the
                # resolver would have to settle anyway.
                continue
            found.append(
                SensitiveEntity(
                    entity_type=entity_type,
                    span=entity.span,
                    value=text[entity.span.start : entity.span.end],
                    confidence=self._confidence,
                    source=self._name,
                )
            )
            covered |= set(range(entity.span.start, entity.span.end))
        return found

    def _resolve(self, entity: RecognizedEntity, text: str) -> EntityType | None:
        """The entity type for one recognised span, or ``None`` to ignore it.

        Also where a recogniser that reports a span outside the text is caught.
        A model is untrusted input in the same sense a response is: it was not
        written by this library, and a span it invents would splice characters
        that are not there.
        """
        if entity.score < self._min_score:
            return None
        if not 0 <= entity.span.start < entity.span.end <= len(text):
            raise DetectionError(
                f"{self._name} reported a span outside the text; nothing was emitted"
            )
        # Labels arrive in the model's vocabulary, and a BIO-tagged model
        # prefixes them. `B-PER` is `PER`.
        label = entity.label.upper()
        if label[:2] in {"B-", "I-"}:
            label = label[2:]
        return self._labels.get(label)


class SpacyRecognizer:
    """spaCy, loaded once and asked per text.

    The model is not bundled and cannot be: it is a separate download with its
    own licence. `en_core_web_sm` is MIT, about 12 MB, and installed with
    ``python -m spacy download en_core_web_sm``.

    Only the entity recogniser runs. A spaCy pipeline also does tagging,
    parsing and lemmatisation, and none of that is read here -- disabling them
    is several times faster on the documents this library is measured on.
    """

    #: Pipeline components with nothing to contribute to named entities.
    DISABLED = ("tagger", "parser", "lemmatizer", "attribute_ruler", "textcat")

    def __init__(self, model: str = "en_core_web_sm", *, name: str = "") -> None:
        self._model_name = model
        self._name = name or f"spacy/{model}"
        self._nlp = self._load(model)

    @staticmethod
    def _load(model: str) -> object:
        try:
            import spacy
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on install
            raise ConfigurationError(
                'the spaCy recogniser needs the `spacy` package: pip install "mamori[nlp]". '
                "It is optional because the pattern rules need no model, and a model is a "
                "download, a version and a few hundred megabytes."
            ) from exc
        try:
            return spacy.load(model, disable=list(SpacyRecognizer.DISABLED))
        except OSError as exc:
            raise ConfigurationError(
                f"spaCy has no model named {model!r} installed. Fetch it with "
                f"`python -m spacy download {model}`. Raised here, when the session is "
                "built, rather than on the first document."
            ) from exc

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model_name

    def entities(self, text: str) -> Sequence[RecognizedEntity]:
        """What the model sees, in character offsets of ``text``.

        spaCy reports token offsets that are already character offsets into the
        string it was given, so nothing is remapped here -- and the pass checks
        every span against the text anyway, because a recogniser is not this
        library's code.
        """
        document = self._nlp(text)  # type: ignore[operator]
        return [
            RecognizedEntity(label=entity.label_, span=Span(entity.start_char, entity.end_char))
            for entity in document.ents
            if entity.end_char > entity.start_char
        ]
