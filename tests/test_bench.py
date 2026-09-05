"""`mamori bench`: a speed claim somebody else can reproduce.

Every throughput number in this repository's documents was typed in after a
script that did not ship. This command is the script, shipped, so a user
asking how long their document will take has something to run -- and so a
regression in the shapes 0.33 fixed shows up as a number in a terminal before
it shows up as a proxy timeout.
"""

from __future__ import annotations

import io
import json

from mamori import MamoriConfig
from mamori.interfaces.cli.bench import SHAPES, measure, run_bench
from mamori.interfaces.cli.main import main


class TestItMeasuresWhatItSaysItMeasures:
    def test_a_row_has_the_shape_it_was_asked_for(self) -> None:
        row = measure(MamoriConfig(), "english-prose", repeats=1)
        assert row.shape == "english-prose"
        assert row.characters == 100_000
        assert row.protect_ms > 0
        assert row.restore_ms > 0
        assert row.entities > 0, "a prose shape with nothing found measured nothing"

    def test_nothing_sensitive_finds_nothing(self) -> None:
        """The control row. A configuration that found things in this line
        would be reporting the cost of false positives as throughput."""
        assert measure(MamoriConfig(), "nothing-sensitive", repeats=1).entities == 0

    def test_the_shapes_that_were_quadratic_are_in_the_default_run(self) -> None:
        assert {"one-long-token", "base64-blob"} <= set(SHAPES)

    def test_growth_is_reported_and_linear_today(self) -> None:
        """The x4 column is the whole reason the command exists."""
        for shape in ("one-long-token", "base64-blob"):
            assert measure(MamoriConfig(), shape, repeats=1).growth < 8, shape


class TestTheCommandLine:
    def test_json_rows_are_the_dataclass(self, capsys: object) -> None:
        out = io.StringIO()
        assert (
            run_bench(MamoriConfig(), shapes=["json-payload"], repeats=1, as_json=True, out=out)
            == 0
        )
        rows = json.loads(out.getvalue())
        assert [row["shape"] for row in rows] == ["json-payload"]
        assert set(rows[0]) >= {"protect_ms", "restore_ms", "protect_chars_per_ms", "growth"}

    def test_the_table_names_the_number_to_compare(self) -> None:
        out = io.StringIO()
        run_bench(MamoriConfig(), shapes=["english-prose"], repeats=1, out=out)
        text = out.getvalue()
        assert "chars/ms" in text
        assert "english-prose" in text
        assert "mamori eval" in text, "the table must say it is not a leak measurement"

    def test_it_is_reachable_from_the_shell(self, capsys: object) -> None:
        assert main(["bench", "--shape", "nothing-sensitive", "--repeats", "1"]) == 0

    def test_repeats_must_be_positive(self) -> None:
        assert main(["bench", "--repeats", "0"]) == 1
