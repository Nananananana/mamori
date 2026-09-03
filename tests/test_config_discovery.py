"""Finding the settings file the way every other tool in the ecosystem does.

`ruff`, `mypy`, `pytest` and `black` all walk up from the working directory
looking for their own file and then for a `[tool.<name>]` table in
`pyproject.toml`. Until 0.32 mamori did none of that: `--config` or nothing,
which meant a repository with settings had to repeat the flag on every command
and a CI job that forgot it ran with different protection than the developer.

One thing here is deliberately **not** what the other tools do, and it is the
part worth testing hardest: the walk stops at the repository root. A
`mamori.toml` in a home directory would apply `default_action = "allow"` to
every project on the machine, and nobody it applied to would have a reason to
look for it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mamori import MamoriConfig, load_config_file
from mamori.config import CONFIG_FILENAMES, discover_config
from mamori.errors import ConfigurationError
from mamori.interfaces.cli.main import main

TOML = pytest.mark.skipif(
    __import__("sys").version_info < (3, 11), reason="tomllib arrived in 3.11"
)


def repo(root: Path) -> Path:
    """A directory that looks like a repository root."""
    (root / ".git").mkdir(parents=True, exist_ok=True)
    return root


class TestDiscovery:
    @TOML
    def test_it_finds_a_file_in_the_same_directory(self, tmp_path: Path) -> None:
        (repo(tmp_path) / "mamori.toml").write_text('stance = "balanced"\n', encoding="utf-8")
        assert discover_config(tmp_path) == tmp_path / "mamori.toml"

    @TOML
    def test_it_walks_up_from_a_deep_subdirectory(self, tmp_path: Path) -> None:
        """The case the feature exists for: one file at the root, every command
        anywhere inside the project finds it."""
        (repo(tmp_path) / "mamori.toml").write_text('stance = "balanced"\n', encoding="utf-8")
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        assert discover_config(deep) == tmp_path / "mamori.toml"

    def test_finding_nothing_is_not_an_error(self, tmp_path: Path) -> None:
        """No config is a complete configuration, and the defaults are the safe
        ones. A tool that refused to run without a file would be worse."""
        assert discover_config(repo(tmp_path)) is None

    def test_json_is_found_too(self, tmp_path: Path) -> None:
        (repo(tmp_path) / "mamori.json").write_text('{"stance": "balanced"}', encoding="utf-8")
        assert discover_config(tmp_path) == tmp_path / "mamori.json"

    @TOML
    def test_a_dedicated_file_beats_pyproject(self, tmp_path: Path) -> None:
        """A file whose whole purpose is this tool is a more deliberate
        statement than a table inside a build file."""
        root = repo(tmp_path)
        (root / "mamori.toml").write_text('stance = "balanced"\n', encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[tool.mamori]\nstance = "recall_first"\n', encoding="utf-8"
        )
        assert discover_config(root) == root / "mamori.toml"

    @TOML
    def test_the_nearest_file_wins(self, tmp_path: Path) -> None:
        root = repo(tmp_path)
        (root / "mamori.toml").write_text('stance = "recall_first"\n', encoding="utf-8")
        nested = root / "service"
        nested.mkdir()
        (nested / "mamori.toml").write_text('stance = "balanced"\n', encoding="utf-8")
        assert discover_config(nested) == nested / "mamori.toml"

    def test_the_filename_order_is_the_documented_one(self) -> None:
        assert CONFIG_FILENAMES[0] == "mamori.toml"
        assert CONFIG_FILENAMES[-1] == "pyproject.toml"


class TestThePyprojectTable:
    @TOML
    def test_a_pyproject_with_the_table_is_found(self, tmp_path: Path) -> None:
        root = repo(tmp_path)
        (root / "pyproject.toml").write_text(
            '[project]\nname = "x"\n\n[tool.mamori]\nstance = "balanced"\n', encoding="utf-8"
        )
        assert discover_config(root) == root / "pyproject.toml"
        assert load_config_file(root / "pyproject.toml").stance.value == "balanced"

    @TOML
    def test_a_pyproject_without_the_table_is_skipped_not_stopped_at(self, tmp_path: Path) -> None:
        """Somebody else's build file said nothing to us. Treating it as an
        empty config would stop the walk and silently discard the settings one
        directory up -- this repository's own pyproject.toml is exactly such a
        file."""
        root = repo(tmp_path)
        (root / "mamori.toml").write_text('stance = "balanced"\n', encoding="utf-8")
        nested = root / "package"
        nested.mkdir()
        (nested / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
        assert discover_config(nested) == root / "mamori.toml"

    @TOML
    def test_a_broken_pyproject_does_not_stop_the_search(self, tmp_path: Path) -> None:
        """Refusing to run because another tool's TOML is malformed would be
        this library failing over a file that is not its own."""
        root = repo(tmp_path)
        (root / "mamori.toml").write_text('stance = "balanced"\n', encoding="utf-8")
        nested = root / "package"
        nested.mkdir()
        (nested / "pyproject.toml").write_text("this is not [ valid toml", encoding="utf-8")
        assert discover_config(nested) == root / "mamori.toml"

    @TOML
    def test_naming_a_tableless_pyproject_explicitly_is_an_error(self, tmp_path: Path) -> None:
        """Discovery skips it; `--config` cannot. The caller said they meant
        this file, so silence would be the wrong answer."""
        path = tmp_path / "pyproject.toml"
        path.write_text('[project]\nname = "x"\n', encoding="utf-8")
        with pytest.raises(ConfigurationError, match=r"no \[tool.mamori\]"):
            load_config_file(path)

    @TOML
    def test_a_dedicated_file_is_read_from_the_top_level(self, tmp_path: Path) -> None:
        """`mamori.toml` says `stance = ...`, not `[tool.mamori]` above it."""
        path = tmp_path / "mamori.toml"
        path.write_text('stance = "balanced"\n', encoding="utf-8")
        assert load_config_file(path).stance.value == "balanced"


class TestTheRepositoryBoundary:
    """The one place this deliberately differs from `ruff` and `mypy`."""

    @TOML
    def test_a_config_above_the_repository_root_does_not_apply(self, tmp_path: Path) -> None:
        (tmp_path / "mamori.toml").write_text('stance = "balanced"\n', encoding="utf-8")
        inside = repo(tmp_path / "project")
        assert discover_config(inside) is None

    @TOML
    def test_the_root_itself_is_still_searched(self, tmp_path: Path) -> None:
        """Stopping *at* the root means the root's own file counts. Off by one
        here would make the common layout -- `mamori.toml` beside `.git` --
        the one case that does not work."""
        root = repo(tmp_path / "project")
        (root / "mamori.toml").write_text('stance = "balanced"\n', encoding="utf-8")
        assert discover_config(root) == root / "mamori.toml"

    @TOML
    def test_a_file_between_the_cwd_and_the_root_still_applies(self, tmp_path: Path) -> None:
        root = repo(tmp_path / "project")
        middle = root / "services"
        deep = middle / "billing"
        deep.mkdir(parents=True)
        (middle / "mamori.toml").write_text('stance = "balanced"\n', encoding="utf-8")
        assert discover_config(deep) == middle / "mamori.toml"


class TestTheCommandLine:
    def settings_file(self, tmp_path: Path, body: dict[str, object]) -> Path:
        path = repo(tmp_path) / "mamori.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        return path

    def test_a_discovered_file_changes_what_a_command_does(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The point of the whole feature, checked through the command line
        rather than through the discovery function: a file nobody named has to
        reach the settings a command runs with."""
        self.settings_file(tmp_path, {"stance": "balanced"})
        monkeypatch.chdir(tmp_path)
        assert main(["config"]) == 0
        assert "balanced" in capsys.readouterr().out

    def test_no_config_ignores_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self.settings_file(tmp_path, {"stance": "balanced"})
        monkeypatch.chdir(tmp_path)
        assert main(["config", "--no-config"]) == 0
        out = capsys.readouterr().out
        assert "recall_first" in out
        assert "(none found)" in out

    def test_an_explicit_config_beats_a_discovered_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self.settings_file(tmp_path, {"stance": "balanced"})
        named = tmp_path / "other.json"
        named.write_text(json.dumps({"stance": "recall_first"}), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert main(["config", "--config", str(named)]) == 0
        out = capsys.readouterr().out
        assert "recall_first" in out
        assert "named with --config" in out

    def test_the_report_says_which_file_it_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A setting that came from a file nobody typed has to be traceable to
        that file, or the discovery is the surprise it was meant not to be."""
        path = self.settings_file(tmp_path, {"stance": "balanced"})
        monkeypatch.chdir(tmp_path)
        main(["config"])
        out = capsys.readouterr().out
        assert path.name in out
        assert "discovered" in out

    def test_a_named_file_that_is_missing_is_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(repo(tmp_path))
        assert main(["config", "--config", str(tmp_path / "nope.json")]) != 0

    def test_environment_still_beats_the_discovered_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The layering order is unchanged; discovery only fills the slot
        `--config` used to be the only way to fill."""
        self.settings_file(tmp_path, {"stance": "balanced"})
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("MAMORI_STANCE", "recall_first")
        main(["config"])
        assert "recall_first" in capsys.readouterr().out


class TestTheLibraryDoesNotDiscover:
    """An application embedding mamori must not have its protection changed by
    a file somebody added to the repository it happens to run in."""

    def test_a_session_built_in_python_ignores_a_discovered_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (repo(tmp_path) / "mamori.json").write_text(
            json.dumps({"stance": "balanced"}), encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        assert MamoriConfig().stance.value == "recall_first"

    def test_discovery_is_something_a_caller_asks_for(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It is available -- just never implicit."""
        (repo(tmp_path) / "mamori.json").write_text(
            json.dumps({"stance": "balanced"}), encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        found = discover_config()
        assert found is not None
        assert load_config_file(found).stance.value == "balanced"
