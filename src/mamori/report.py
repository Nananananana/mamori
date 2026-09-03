"""What this configuration actually does, read out of the configuration.

Every privacy claim in the README is enforced somewhere in code: credentials
are blocked rather than pseudonymized, mappings are held in memory unless a
caller says otherwise, a detector endpoint outside your network is refused,
keys are read from the environment and never from a file. What was missing was
one place to see all of it **against your own settings**, so that "trust the
documentation" becomes "run the command and read the answer".

The distinction this module draws, and the reason it is worth having, is
between three different kinds of statement:

**Measured** -- computed from the settings in front of it. How many rules are
active, which categories are blocked, where the model is. Change the config and
these change.

**By construction** -- true because of how the code is built, not because of a
setting. A protected value never appears in a log line because nothing ever
writes one. These cannot be switched off, and each is paired with the test that
would fail if it stopped being true.

**Your responsibility** -- things this library cannot check. Whether the
upstream service you chose retains your prompts is not knowable from here, and
a report that implied otherwise would be worse than silent.

Nothing here reads a document, contacts anything, or writes what it found.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import MamoriConfig
from .domain.entity_types import BUILTIN_TYPES
from .domain.policy import Uncertain
from .domain.retention import Retention
from .errors import MamoriError

__all__ = ["Claim", "PrivacyReport", "build_report"]


@dataclass(frozen=True, slots=True)
class Claim:
    """One statement, and what backs it."""

    text: str
    #: The test that fails if this stops being true. Empty for measured facts,
    #: which are backed by the number beside them rather than by a test.
    checked_by: str = ""

    def as_mapping(self) -> dict[str, str]:
        return {"claim": self.text, "checked_by": self.checked_by}


@dataclass(frozen=True, slots=True)
class PrivacyReport:
    """The answer to "what does this configuration do with my data"."""

    detection: dict[str, Any] = field(default_factory=dict)
    storage: dict[str, Any] = field(default_factory=dict)
    #: Where text goes, and whether it is protected first.
    destinations: list[dict[str, Any]] = field(default_factory=list)
    #: True regardless of settings, each paired with its test.
    by_construction: tuple[Claim, ...] = ()
    #: What this library cannot check on your behalf.
    your_responsibility: tuple[Claim, ...] = ()
    #: Settings that widen exposure. Empty is the healthy state.
    warnings: tuple[str, ...] = ()

    def as_mapping(self) -> dict[str, Any]:
        return {
            "detection": self.detection,
            "storage": self.storage,
            "destinations": self.destinations,
            "by_construction": [c.as_mapping() for c in self.by_construction],
            "your_responsibility": [c.as_mapping() for c in self.your_responsibility],
            "warnings": list(self.warnings),
        }


#: True however mamori is configured. Each names the test that would fail.
#: Adding a line here without adding its test is the one way to make this
#: module dishonest, so ``tests/test_promises.py`` checks the pairing.
_BY_CONSTRUCTION = (
    Claim(
        "Pattern detection contacts nothing. No socket is opened to protect a "
        "document with the default detectors.",
        "test_promises.py::TestNothingLeavesTheMachine",
    ),
    Claim(
        "The mapping from a placeholder back to a value is held in memory and "
        "written nowhere unless a caller passes a store that writes.",
        "test_promises.py::TestMappingsStayInMemory",
    ),
    Claim(
        "A protected value never appears in an error, a log line or a repr. "
        "The fields that hold one are excluded from every representation.",
        "test_promises.py::TestValuesStayOutOfDiagnostics",
    ),
    Claim(
        "Restoration resolves only placeholders allocated in the calling "
        "scope, so a reply cannot read values back by guessing at names.",
        "test_promises.py::TestRestorationIsScopeBound",
    ),
    Claim(
        "An API key is read from an environment variable you name. A literal "
        "key in a configuration file is refused rather than used.",
        "test_promises.py::TestKeysAreNeverInConfiguration",
    ),
    Claim(
        "A model asked to help with detection may only add candidates. It "
        "cannot remove a rule's finding, veto a policy decision, or alter a "
        "placeholder.",
        "test_promises.py::TestTheModelOnlyAdds",
    ),
    Claim(
        "A correction can never rule a credential to be not sensitive. The "
        "refusal is mechanical, at the moment one is recorded and again when "
        "one is applied.",
        "test_corrections.py::TestACredentialCannotBeCorrectedAway",
    ),
    Claim(
        "The bundled evaluation data is invented. No real name, address or "
        "credential ships inside the package.",
        "test_detection_quality.py::TestDatasetHygiene",
    ),
)

_YOUR_RESPONSIBILITY = (
    Claim("Whether the service you send protected text to retains it."),
    Claim("Whether a value this library has no rule for is sensitive to you."),
    Claim("Who can reach a proxy you have bound to a public address."),
)


def build_report(config: MamoriConfig, *, upstream: str | None = None) -> PrivacyReport:
    """Describe what ``config`` does, without doing any of it.

    Args:
        config: The settings to describe.
        upstream: A proxy destination, if one is configured. Named separately
            because it is a property of a running proxy rather than of the
            settings, and leaving it out of the destinations would hide the
            one place protected text is meant to go.
    """
    policy = config.policy()

    # Building the detectors is how the number below is obtained, and it is
    # also what refuses an endpoint outside the trust boundary. A report that
    # raised there would be useless in the one situation it exists for: a
    # configuration that is wrong, being examined to find out how.
    try:
        detector_count: int | None = len(list(config.detectors()))
        build_error = ""
    except MamoriError as exc:
        detector_count = None
        build_error = str(exc).splitlines()[0]

    # Resolved per type rather than per category, because a rule naming one
    # type overrides its category and a report that showed the category would
    # then be describing settings the user does not have.
    by_action: dict[str, list[str]] = {}
    for entity_type in BUILTIN_TYPES.values():
        action = policy.action_for(entity_type)
        by_action.setdefault(action.value, []).append(entity_type.name)
    for names in by_action.values():
        names.sort()

    detection: dict[str, Any] = {
        "locales": list(config.locales) if config.locales else "all",
        "stance": config.stance.value,
        "detectors": detector_count,
        "minimum_confidence": config.min_confidence,
        # What happens *at* that threshold, which is half of what it means. A
        # report that gives the number and not the behaviour describes a dial
        # without saying which way it turns.
        "uncertain": config.uncertain,
        "co_occurrence": config.co_occurrence,
        "placeholder_style": config.placeholder_style,
        # Which algorithm looks for the credentials the patterns cannot name.
        # Reported because it changes what *blocks*: with "entropy" a content
        # hash can stop a request, and an operator reading this to decide
        # whether to trust the configuration needs to know that before the
        # first refused document tells them.
        "secrets": config.secrets,
        "by_action": by_action,
    }
    if config.secrets != "patterns":
        detection["secrets_note"] = (
            f'secrets="{config.secrets}" runs a measurement after the pattern rules. '
            "It finds credentials with no vendor prefix and no keyword, and it also "
            "flags commit ids, content hashes and base64 payloads as API_KEY -- "
            "which the default policy blocks. Set min_confidence to 0.6 or above "
            "to keep only the candidates that had a keyword beside them."
        )

    # The default store's retention, read from the default rather than named
    # here, so this report cannot drift from what a session actually gets.
    default_retention = Retention.forever()
    storage = {
        "mappings": "memory only, for the life of one session",
        "written_to_disk": False,
        "retention": default_retention.describe(),
        "note": (
            "A JSON store exists and must be passed to a session explicitly in "
            "Python. There is no setting that turns on writing to disk, so a "
            "configuration file cannot start it by accident. A store may be "
            "given a retention period, in which case it stops answering for "
            "what it has forgotten -- expiry happens when the store is used "
            "and nothing here starts a thread."
        ),
    }

    destinations, warnings = _destinations(config, upstream)

    warnings_from_settings: list[str] = []
    if config.uncertainty() is Uncertain.REFUSE:
        detection["uncertain_note"] = (
            f"a detection below {config.min_confidence} stops the text rather than "
            "being discarded; nothing is sent and the refusal names types, never values"
        )
        if config.min_confidence <= 0.0:
            warnings_from_settings.append(
                'uncertain="refuse" does nothing at min_confidence 0.0: nothing is '
                "below zero, so no detection is ever uncertain. Set a threshold as well."
            )

    surrogate_types = sorted(config.surrogate_types())
    if surrogate_types:
        from .domain.surrogate import pool_for

        bases: dict[str, str] = {}
        for name in surrogate_types:
            for locale in ("*", "en", "ja", "zh"):
                pool = pool_for(name, locale)
                if pool is not None:
                    bases[name] = pool.basis
                    break
        detection["surrogates"] = bases
        invented = [name for name, basis in detection["surrogates"].items() if "invented" in basis]
        warnings.append(
            "surrogate values are substituted for "
            + ", ".join(surrogate_types)
            + ". An unrestored placeholder is obvious; an unrestored surrogate "
            "reads as a fact about the wrong person"
        )
        if invented:
            warnings.append(
                "nothing is reserved for " + ", ".join(invented) + ", so those "
                "surrogates are plausible rather than identifiable. Check "
                "RestorationResult.missing on every answer"
            )
    else:
        detection["surrogates"] = {}

    log = config.correction_log()
    corrections = {
        "rulings": len(log),
        "excluded": [c.value for c in log.excluded()],
        "added": [c.value for c in log.added()],
    }
    if log.excluded():
        warnings.append(
            f"{len(log.excluded())} value(s) are ruled not sensitive and are no "
            "longer protected: " + ", ".join(sorted(c.value for c in log.excluded()))
        )
    if build_error:
        warnings.append(f"this configuration cannot be used as it stands: {build_error}")

    detection["corrections"] = corrections

    return PrivacyReport(
        detection=detection,
        storage=storage,
        destinations=destinations,
        by_construction=_BY_CONSTRUCTION,
        your_responsibility=_YOUR_RESPONSIBILITY,
        warnings=(*warnings, *warnings_from_settings),
    )


def _destinations(
    config: MamoriConfig, upstream: str | None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Every place text can travel, and whether it was protected first."""
    destinations: list[dict[str, Any]] = []
    warnings: list[str] = []

    llm = config.llm
    if llm is not None and llm.model:
        endpoint = llm.endpoint()
        kind = endpoint.policy.classify(llm.base_url)
        admitted = endpoint.policy.admits(llm.base_url)
        destinations.append(
            {
                "what": "detection model",
                "where": llm.base_url,
                "host": kind.value,
                "sees": "UNPROTECTED TEXT",
                "why": (
                    "A detector is asked what is sensitive, so it is shown the "
                    "document before anything is replaced."
                ),
                "admitted": admitted,
                "trust_boundary": llm.trust.value,
            }
        )
        if not admitted:
            warnings.append(
                f"the detection model at {llm.base_url} is outside the "
                f"{llm.trust.value} boundary and will be refused"
            )
        elif llm.trust.value == "anywhere":
            warnings.append(
                "the trust boundary is set to 'anywhere', so unprotected text "
                "may be sent to a detection model on any host"
            )
    else:
        destinations.append(
            {
                "what": "detection model",
                "where": None,
                "sees": "nothing",
                "why": "No model is configured. Detection is pattern rules only.",
            }
        )

    if upstream is not None:
        destinations.append(
            {
                "what": "proxy upstream",
                "where": upstream,
                "sees": "protected text",
                "why": (
                    "The service you already chose. What reaches it has been "
                    "through detection and replacement, which is the point."
                ),
            }
        )

    return destinations, warnings
