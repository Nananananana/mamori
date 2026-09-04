"""The figures in SECURITY.md are the ones `mamori eval` prints today.

Proposal 0002 makes this a condition of 1.0: *the figures in SECURITY.md have
data behind them worth the word "measured"*. Two clauses of that are met and
the third has a part that does not wait on anybody -- **the numbers in the
document have to still be the numbers**.

They were not. Three of the twelve rows had drifted, and the sample counts on
three rows with them, because the table is written by hand and the corpus and
the rules keep moving. The worst was `ja-core`: over-redaction 2.78% against a
real 2.44%, precision 0.925 against 0.955. Nothing was wrong except that the
document had stopped being true, quietly, at some release nobody can name.

A published number that no longer holds is the same defect as a check that
cannot fail. It reads as evidence and is a memory of evidence.
"""

from __future__ import annotations

import pathlib
import re
from typing import ClassVar

import pytest

from mamori.evaluation import Dataset, bundled_datasets, evaluate

SECURITY = pathlib.Path(__file__).resolve().parent.parent / "SECURITY.md"

#: `| `en-core` | 53 fragments | 0.62% | 0.71% | 0.980 / 0.980 |`
ROW = re.compile(
    r"^\| `(?P<set>[a-z]{2}-\w+)` \| (?P<count>\d+) \w+ \| "
    r"\*{0,2}(?P<leak>[\d.]+)%\*{0,2} \| "
    r"(?P<over>[\d.]+)% \| "
    r"(?P<precision>[\d.]+) / (?P<recall>[\d.]+) \|$",
    re.MULTILINE,
)


def published() -> dict[str, dict[str, float]]:
    text = SECURITY.read_text(encoding="utf-8")
    return {
        match["set"]: {
            "count": float(match["count"]),
            "leak": float(match["leak"]),
            "over": float(match["over"]),
            "precision": float(match["precision"]),
            "recall": float(match["recall"]),
        }
        for match in ROW.finditer(text)
    }


def test_the_table_was_found_at_all() -> None:
    """A regex that silently matches nothing would make every check below pass.

    The count is not pinned to twelve: adding a dataset should not fail here,
    it should fail in the row-by-row test, which says which set is missing.
    """
    rows = published()
    assert rows, "no figures parsed out of SECURITY.md -- has the table changed shape?"


def test_every_bundled_dataset_has_a_row() -> None:
    missing = sorted({dataset.name for dataset in bundled_datasets()} - set(published()))
    assert not missing, f"measured but not published in SECURITY.md: {missing}"


@pytest.mark.parametrize("dataset", bundled_datasets(), ids=lambda d: d.name)
def test_the_published_figures_are_the_measured_ones(dataset: Dataset) -> None:
    row = published().get(dataset.name)
    assert row is not None, f"{dataset.name} is measured and not in SECURITY.md"

    report = evaluate(dataset)
    measured = {
        "count": float(len(dataset.samples)),
        "leak": round(report.leak_rate * 100, 2),
        "over": round(report.over_redaction_rate * 100, 2),
        "precision": round(report.overall.precision, 3),
        "recall": round(report.overall.recall, 3),
    }

    wrong = {k: (row[k], v) for k, v in measured.items() if abs(row[k] - v) > 1e-9}
    assert not wrong, (
        f"SECURITY.md is out of date for {dataset.name}: "
        + ", ".join(f"{k} says {a} and measures {b}" for k, (a, b) in sorted(wrong.items()))
        + ". Run `mamori eval` and copy the numbers, or explain in the document "
        "why the published figure differs from what the tool reports."
    )


class TestTheLabelSetTheFiguresAreARateAgainst:
    """`SECURITY.md`: *a leak rate is a rate against a label set, and this one
    is ours*. The document is explicit that `0.00%` means the rules cover
    everything **mamori's own type system knows how to mark** -- so the type
    system is the unit those figures are quoted in.

    That set was pinned nowhere. Adding a type was measured, and it turned
    **zero** mechanisms red: a type with no rule behind it produces no
    detections, so every number in the table stays exactly where it was while
    the sentence explaining what the numbers mean quietly starts meaning
    something else. The published claim goes on being literally true and stops
    being the same claim.

    A sibling put the general form of this well: *adding a member to a set --
    how many mechanisms does that turn red? If zero, the set will be silent for
    the next member too.*

    The direction that motivates it is the opposite one, and was settled
    earlier in this project: a proposal to exclude a type from the rate by
    declaring it out of scope was refused, because *a declaration adjusts a
    reader's expectations and is not authority to change the denominator* --
    otherwise the cheapest way to improve a rate is to rewrite the scope
    narrower. Adding a type moves the same denominator the other way, and it
    should be no quieter.
    """

    #: Every type the published figures are a rate against, as of `0.30.0`.
    #: Not a count: a count survives one type being swapped for another, which
    #: is the change most likely to happen by accident.
    PUBLISHED_LABEL_SET: ClassVar[frozenset[str]] = frozenset(
        {
            "PERSON",
            "EMAIL",
            "PHONE",
            "ADDRESS",
            "POSTAL_CODE",
            "DATE_OF_BIRTH",
            "CREDIT_CARD",
            "MY_NUMBER",
            "SSN",
            "RESIDENT_ID",
            "IDENTIFIER",
            "API_KEY",
            "ACCESS_TOKEN",
            "PASSWORD",
            "PRIVATE_KEY",
            "DATABASE_URL",
            "COMPANY_NAME",
            "EMPLOYEE_ID",
            "PROJECT_NAME",
            "INTERNAL_IP",
            "INTERNAL_URL",
            # Registered as `TEXT`. The Python constant is
            # `PLACEHOLDER_LITERAL`, which is what the first version of
            # this set said -- a set written from the source rather than
            # from the registry, and the check caught it immediately.
            "TEXT",
        }
    )

    def test_the_set_is_the_one_the_figures_were_measured_against(self) -> None:
        from mamori.domain.entity_types import BUILTIN_TYPES

        current = set(BUILTIN_TYPES)
        # The wording below avoids "update ... table", which ruff's S608 rule
        # reads as SQL construction inside an f-string.
        assert current == self.PUBLISHED_LABEL_SET, (
            f"added: {sorted(current - self.PUBLISHED_LABEL_SET)}; "
            f"removed: {sorted(self.PUBLISHED_LABEL_SET - current)}.\n\n"
            "The label set the figures in SECURITY.md are a rate against has "
            "changed. That is allowed and is not a defect -- but it is a "
            "decision, and this is the only place that makes it one. Change "
            "this set in the same commit, re-run `mamori eval`, and if the "
            "figures moved, correct them too. If the new type has no rule "
            "behind it "
            "the numbers will not move, which is exactly why nothing else here "
            "would have told you."
        )

    def test_the_document_still_says_the_figures_are_a_rate_against_it(self) -> None:
        """Pinning a set whose published meaning has been withdrawn would leave
        a check with nothing behind it."""
        assert "a rate against a label set" in SECURITY.read_text(encoding="utf-8")

    def test_the_business_confidential_types_named_in_the_document_are_real(self) -> None:
        """`SECURITY.md` names three types to argue that this is not only a PII
        tool. A renamed type would leave the argument standing on nothing."""
        from mamori.domain.entity_types import BUILTIN_TYPES

        for name in ("COMPANY_NAME", "EMPLOYEE_ID", "PROJECT_NAME"):
            assert name in BUILTIN_TYPES
            assert f"`{name}`" in SECURITY.read_text(encoding="utf-8")


#: `| `en-docs` | 2.65% | **0.00%** | 0.90% | 1.56% |`
GLINER_ROW = re.compile(
    r"^\| `(?P<set>[a-z]{2}-\w+)` \| "
    r"\*{0,2}(?P<rules_leak>[\d.]+)%\*{0,2} \| "
    r"\*{0,2}(?P<gliner_leak>[\d.]+)%\*{0,2} \| "
    r"\*{0,2}(?P<rules_over>[\d.]+)%\*{0,2} \| "
    r"\*{0,2}(?P<gliner_over>[\d.]+)%\*{0,2} \|$",
    re.MULTILINE,
)


class TestTheRecogniserTableIsAlsoTheMeasuredOne:
    """The second table in SECURITY.md, under the same rule as the first.

    It arrived in 0.33 and the regex for the first table does not match its
    shape, so publishing it added six rows of numbers that nothing checked --
    the exact defect the module docstring above is about, reintroduced by the
    change that documented a fix. This is that gap closed in the same commit.

    Skipped without `gliner` and the model. A check that cannot run in CI is
    weaker than one that can, and is not nothing: it runs wherever the
    configuration it describes is actually installed, which is the only place
    the numbers mean anything.
    """

    def published(self) -> dict[str, dict[str, float]]:
        text = SECURITY.read_text(encoding="utf-8")
        return {
            match["set"]: {
                "rules_leak": float(match["rules_leak"]),
                "gliner_leak": float(match["gliner_leak"]),
                "rules_over": float(match["rules_over"]),
                "gliner_over": float(match["gliner_over"]),
            }
            for match in GLINER_ROW.finditer(text)
        }

    def test_the_table_was_found_at_all(self) -> None:
        rows = self.published()
        assert len(rows) >= 6, f"found {sorted(rows)}; the recogniser table is not being read"

    @pytest.mark.parametrize(
        "name", ["en-core", "en-docs", "ja-core", "ja-docs", "zh-core", "zh-docs"]
    )
    def test_the_published_figures_are_the_measured_ones(self, name: str) -> None:
        pytest.importorskip("gliner")
        from mamori import MamoriConfig
        from mamori.errors import ConfigurationError

        try:
            config = MamoriConfig(nlp="gliner")
            detectors = config.detectors()
        except ConfigurationError as exc:  # no model on this machine
            pytest.skip(str(exc))

        dataset = next(one for one in bundled_datasets() if one.name == name)
        report = evaluate(dataset, detectors=detectors)
        row = self.published()[name]
        assert round(report.leak_rate * 100, 2) == row["gliner_leak"], (
            f"{name}: SECURITY.md says {row['gliner_leak']}% leaked with the "
            f"recogniser on; `mamori eval` says {report.leak_rate * 100:.2f}%"
        )
        assert round(report.over_redaction_rate * 100, 2) == row["gliner_over"], (
            f"{name}: SECURITY.md says {row['gliner_over']}% over-redacted with the "
            f"recogniser on; `mamori eval` says {report.over_redaction_rate * 100:.2f}%"
        )


class TestTheMappingLifecycleTableIsTrue:
    """`SECURITY.md` now states how long a mapping lives, in a table with
    numbers in it. A number in a security document that has drifted is the
    same defect as a check that cannot fail: it reads as evidence and is a
    memory of evidence.

    The defaults are the ones that could move without anybody noticing --
    somebody tuning a proxy for throughput would change all three.
    """

    def test_the_defaults_named_in_the_table_are_the_defaults(self) -> None:
        from mamori.application.conversations import (
            DEFAULT_IDLE_SECONDS,
            DEFAULT_MAX_CONVERSATIONS,
            DEFAULT_MAX_MAPPINGS,
        )

        text = SECURITY.read_text(encoding="utf-8")
        assert f"({DEFAULT_IDLE_SECONDS // 60} minutes by default)" in text
        assert f"`--max-conversations` ({DEFAULT_MAX_CONVERSATIONS})" in text
        assert f"`max_mappings` ({DEFAULT_MAX_MAPPINGS:,})" in text

    def test_closing_a_session_really_purges_the_scope(self) -> None:
        """The first row of the table, which every other row rests on."""
        from mamori import PrivacySession
        from mamori.infrastructure.storage import InMemoryMappingStore

        store = InMemoryMappingStore()
        with PrivacySession(store=store, scope="x") as session:
            session.protect("mail tanaka@example.com")
            assert store.list_scope("x"), "nothing was stored, so the purge proved nothing"
        assert store.list_scope("x") == ()

    def test_the_document_still_says_retention_is_a_rule_and_not_a_thread(self) -> None:
        """A claim withdrawn from the document would leave this checking a
        sentence nobody makes any more."""
        text = SECURITY.read_text(encoding="utf-8")
        assert "not a thread you cannot see" in text
        assert "on every read and write of the store rather than by a sweeper" in text
