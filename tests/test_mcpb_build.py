"""Tests for scripts/build_mcpb.py — the Claude Desktop bundle builder."""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import zipfile
import tomllib
from pathlib import Path
from typing import Any

import pytest

from garmin_cli import __version__

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_mcpb.py"
_spec = importlib.util.spec_from_file_location("build_mcpb", _SCRIPT)
assert _spec is not None and _spec.loader is not None
build_mcpb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_mcpb)

_LAUNCHER = build_mcpb.REPO_ROOT / "mcpb" / "main.py"
_launcher_spec = importlib.util.spec_from_file_location("mcpb_main", _LAUNCHER)
assert _launcher_spec is not None and _launcher_spec.loader is not None
launcher = importlib.util.module_from_spec(_launcher_spec)
_launcher_spec.loader.exec_module(launcher)


class TestBuildMcpb:

    def test_bundle_contents_and_version_stamp(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(build_mcpb, "constraints", lambda project: "click==8.1.0\n")  # no network
        bundle_path = build_mcpb.build(tmp_path)

        assert bundle_path == tmp_path / f"garmin-py-{__version__}.mcpb"
        with zipfile.ZipFile(bundle_path) as bundle:
            assert set(bundle.namelist()) == {"manifest.json", "server/main.py", "server/constraints.txt"}
            manifest = json.loads(bundle.read("manifest.json"))
            main_py = bundle.read("server/main.py").decode()
            assert bundle.read("server/constraints.txt").decode() == "click==8.1.0\n"

        assert manifest["version"] == __version__
        # Security drift guard: the password must stay keychain-stored.
        assert manifest["user_config"]["garmin_password"]["sensitive"] is True
        assert f'VERSION = "{__version__}"' in main_py
        # Python minimum is stamped from pyproject's requires-python.
        requires = tomllib.loads((build_mcpb.REPO_ROOT / "pyproject.toml").read_text())["project"]["requires-python"]
        minimum = requires.removeprefix(">=")
        assert requires == f">={minimum}"
        # Claude Desktop checks this against python3 on PATH, so it is the
        # launcher's own floor (see the 3.8 parse test), not requires-python.
        assert manifest["compatibility"]["runtimes"]["python"] == ">=3.8"
        assert f"Requires Python {minimum}+" in manifest["long_description"]
        assert f'MIN_PYTHON = "{minimum}"' in main_py
        assert "__GARMIN_PY_" not in json.dumps(manifest) + main_py

    def test_constraints_pins_the_resolved_runtime_and_mcp_dependencies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[list[str], dict[str, Any]]] = []

        def fake_run(cmd: list[str], **kwargs: Any) -> None:
            calls.append((cmd, kwargs))
            report = {"install": [
                {"metadata": {"name": "pydantic_core", "version": "2.1.0", "summary": "Kern für Pydantic"}},
                {"metadata": {"name": "Click", "version": "8.1.0"}},
            ]}
            report_path = Path(cmd[cmd.index("--report") + 1])
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")  # pip writes UTF-8

        monkeypatch.setattr(build_mcpb.subprocess, "run", fake_run)
        monkeypatch.setattr(build_mcpb.importlib.util, "find_spec", lambda name: object())  # pip "present"
        monkeypatch.setenv("PIP_INDEX_URL", "https://mirror.invalid/simple")
        monkeypatch.setenv("PIP_CONFIG_FILE", "/etc/custom-pip.conf")
        project = {"dependencies": ["click>=8.0"], "optional-dependencies": {"mcp": ["mcp[cli]>=2.2.0,<3"]}}

        assert build_mcpb.constraints(project) == "Click==8.1.0\npydantic_core==2.1.0\n"
        [(cmd, kwargs)] = calls
        assert cmd[-2:] == ["click>=8.0", "mcp[cli]>=2.2.0,<3"]
        assert {"--dry-run", "--ignore-installed", "--isolated", "--only-binary=:all:"} <= set(cmd)
        assert kwargs["env"]["PIP_CONFIG_FILE"] == build_mcpb.os.devnull
        assert "PIP_INDEX_URL" not in kwargs["env"]

    def test_constraints_needs_pip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(build_mcpb.importlib.util, "find_spec", lambda name: None)
        with pytest.raises(SystemExit, match="needs pip"):
            build_mcpb.constraints({"dependencies": [], "optional-dependencies": {"mcp": []}})

    def test_read_only_toggle_is_wired_with_a_false_default(self) -> None:
        manifest = json.loads((build_mcpb.REPO_ROOT / "mcpb" / "manifest.json").read_text())
        setting = manifest["user_config"]["garmin_read_only"]
        assert setting["type"] == "boolean" and setting["default"] is False
        env = manifest["server"]["mcp_config"]["env"]
        assert env["GARMIN_MCP_READ_ONLY"] == launcher._READ_ONLY_PLACEHOLDER

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("${user_config.garmin_read_only}", "false"),
            ("true", "true"),
            ("${user_config.other}", "${user_config.other}"),  # the server refuses this
        ],
    )
    def test_launcher_defaults_only_the_unfilled_read_only_placeholder(
        self, capsys: pytest.CaptureFixture[str], value: str, expected: str
    ) -> None:
        environ = {"GARMIN_MCP_READ_ONLY": value}
        launcher._resolve_read_only_setting(environ)
        assert environ["GARMIN_MCP_READ_ONLY"] == expected
        assert ("not filled in" in capsys.readouterr().err) is (value == launcher._READ_ONLY_PLACEHOLDER)

    def test_min_python_parses_lower_bound(self) -> None:
        assert build_mcpb.min_python(">=3.12") == "3.12"

    @pytest.mark.parametrize("spec", [">=3.12,<4", "~=3.12", ">=3", ">= 3.12"])
    def test_min_python_rejects_specifiers_main_py_cannot_parse(self, spec: str) -> None:
        with pytest.raises(SystemExit, match="requires-python"):
            build_mcpb.min_python(spec)


class TestLauncher:

    def test_launcher_parses_on_python_3_8(self) -> None:
        # macOS /usr/bin/python3 must get far enough to re-exec a newer Python.
        ast.parse(_LAUNCHER.read_text(), feature_version=(3, 8))

    @staticmethod
    def _executables(monkeypatch: pytest.MonkeyPatch, paths: set[str]) -> None:
        monkeypatch.setattr(launcher.os.path, "isfile", lambda path: path in paths)
        monkeypatch.setattr(launcher.os, "access", lambda path, mode: path in paths)

    def test_python_candidates_lowest_qualifying_minor_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        framework = "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
        self._executables(monkeypatch, {
            "/opt/homebrew/bin/python3.11", "/usr/bin/python3",  # too old / unversioned: ignored
            "/opt/homebrew/bin/python3.14", "/usr/local/bin/python3.13", framework,
        })
        assert launcher._python_candidates((3, 12)) == [
            framework, "/usr/local/bin/python3.13", "/opt/homebrew/bin/python3.14",
        ]

    _HOMEBREW, _USR_LOCAL = "/opt/homebrew/bin/python3.100", "/usr/local/bin/python3.101"

    def _too_old(
        self, monkeypatch: pytest.MonkeyPatch, guard: str, versions: dict[str, str] | None = None
    ) -> list[tuple[str, list[str]]]:
        """Running Python is below a 3.99 minimum; ``versions`` maps candidate -> its real version output."""
        monkeypatch.setattr(launcher, "VERSION", "9.9.9")
        monkeypatch.setattr(launcher, "MIN_PYTHON", "3.99")
        monkeypatch.setenv(launcher._REEXEC_ENV, guard)
        self._executables(monkeypatch, {self._HOMEBREW, self._USR_LOCAL})
        if versions is None:
            versions = {self._HOMEBREW: "3 100\n", self._USR_LOCAL: "3 101\n"}

        def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            assert kwargs["timeout"] == 10 and kwargs["stdin"] == subprocess.DEVNULL  # never reads MCP stdin
            if cmd[0] not in versions:
                raise OSError("bad interpreter")
            return subprocess.CompletedProcess(cmd, 0, stdout=versions[cmd[0]])

        monkeypatch.setattr(launcher.subprocess, "run", fake_run)
        calls: list[tuple[str, list[str]]] = []

        def fake_execv(path: str, argv: list[str]) -> None:
            calls.append((path, argv))
            raise OSError("exec failed")

        monkeypatch.setattr(launcher.os, "execv", fake_execv)
        return calls

    def test_too_old_python_tries_each_newer_one_then_explains(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        calls = self._too_old(monkeypatch, guard="")
        assert launcher.main() == 1  # every exec "failed", so it falls back to the error
        script_args = [launcher.os.path.abspath(launcher.__file__), *launcher.sys.argv[1:]]
        assert calls == [(path, [path, *script_args]) for path in (self._HOMEBREW, self._USR_LOCAL)]
        assert launcher.os.environ[launcher._REEXEC_ENV] == "1"
        assert "needs Python 3.99" in capsys.readouterr().err

    @pytest.mark.parametrize("homebrew_output", ["3 9\n", None, "not a version\n"])  # lies, won't run, garbage
    def test_candidate_whose_real_version_is_too_old_or_broken_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch, homebrew_output: str | None
    ) -> None:
        versions = {self._USR_LOCAL: "3 101\n"}
        if homebrew_output is not None:
            versions[self._HOMEBREW] = homebrew_output
        calls = self._too_old(monkeypatch, guard="", versions=versions)
        assert launcher.main() == 1
        assert [path for path, _ in calls] == [self._USR_LOCAL]

    def test_reexec_guard_stops_a_second_switch(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        calls = self._too_old(monkeypatch, guard="1")
        assert launcher.main() == 1
        assert calls == []
        assert "needs Python 3.99" in capsys.readouterr().err

    @staticmethod
    def _fake_install(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run: Any,
        pinned: bool = True, clock: list[float] | None = None,
    ) -> Path:
        """Fake venv + pip (+ monotonic clock); returns the venv dir under a pre-existing 0755 root."""
        monkeypatch.setattr(launcher, "VERSION", "9.9.9")
        constraints_file = tmp_path / "constraints.txt"
        if pinned:
            constraints_file.write_text("click==8.1.0\n")
        monkeypatch.setattr(launcher, "_CONSTRAINTS", constraints_file)
        monkeypatch.setattr(
            launcher.venv, "EnvBuilder", lambda with_pip: type("B", (), {"create": lambda self, d: Path(d).mkdir()})()
        )
        monkeypatch.setattr(launcher.subprocess, "run", run)
        ticks = iter(clock or [0.0, 0.0, 0.0])
        monkeypatch.setattr(launcher, "time", type("Clock", (), {"monotonic": staticmethod(lambda: next(ticks))}))
        root = tmp_path / "mcpb"
        root.mkdir()
        root.chmod(0o755)  # as left by an older release
        return root / "venv-9.9.9-py3.12"

    @pytest.mark.skipif(launcher.os.name == "nt", reason="POSIX permissions and flock")
    def test_install_is_private_isolated_pinned_and_time_limited(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        for name, value in [
            ("GARMIN_PASSWORD", "hunter2"), ("GARMIN_EMAIL", "a@b.c"),
            ("PIP_INDEX_URL", "https://mirror.invalid/simple"), ("PIP_CONFIG_FILE", "/etc/custom-pip.conf"),
        ]:
            monkeypatch.setenv(name, value)
        runs: list[tuple[list[str], dict[str, Any]]] = []
        venv_dir = self._fake_install(monkeypatch, tmp_path, lambda cmd, **kwargs: runs.append((cmd, kwargs)))

        launcher._ensure_install(venv_dir)

        assert venv_dir.parent.stat().st_mode & 0o777 == 0o700
        [(cmd, kwargs)] = runs
        assert {"--isolated", "--disable-pip-version-check", "--only-binary=:all:"} <= set(cmd)
        assert cmd[cmd.index("--constraint") + 1] == str(tmp_path / "constraints.txt")
        assert cmd[cmd.index("--timeout") + 1] == "60"
        assert cmd[-1] == "garmin-py[mcp]==9.9.9"
        assert kwargs["timeout"] == launcher._PIP_TIMEOUT_SECONDS
        env = kwargs["env"]
        assert not {"GARMIN_PASSWORD", "GARMIN_EMAIL", "PIP_INDEX_URL"} & set(env)
        assert env["PIP_CONFIG_FILE"] == launcher.os.devnull
        assert (venv_dir / ".install-ok").exists()

    @pytest.mark.skipif(launcher.os.name == "nt", reason="POSIX flock")
    def test_failed_pinned_install_retries_once_without_pins_in_a_fresh_venv(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        runs: list[tuple[list[str], float, bool]] = []

        def run(cmd: list[str], **kwargs: Any) -> None:
            runs.append((cmd, kwargs["timeout"], (venv_dir / "partial").exists()))
            if "--constraint" in cmd:
                (venv_dir / "partial").touch()  # half-installed packages
                raise subprocess.CalledProcessError(1, cmd)

        venv_dir = self._fake_install(monkeypatch, tmp_path, run, clock=[0.0, 100.0, 300.0])
        launcher._ensure_install(venv_dir)

        # One 900 s budget across both attempts; the retry starts from an empty venv.
        assert [("--constraint" in cmd, timeout, partial) for cmd, timeout, partial in runs] == [
            (True, 800.0, False), (False, 600.0, False),
        ]
        assert "retrying without version pins" in capsys.readouterr().err
        assert (venv_dir / ".install-ok").exists()

    @pytest.mark.skipif(launcher.os.name == "nt", reason="POSIX flock")
    @pytest.mark.parametrize(
        ("pinned", "clock", "error", "attempts"),
        [
            (True, None, subprocess.CalledProcessError, 2),  # both attempts fail
            (False, None, subprocess.CalledProcessError, 1),  # no pins: nothing to retry without
            (True, [0.0, 0.0, 900.0], subprocess.TimeoutExpired, 1),  # budget spent: no retry
        ],
    )
    def test_failed_install_propagates_without_marker(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
        pinned: bool, clock: list[float] | None, error: type[Exception], attempts: int,
    ) -> None:
        runs: list[list[str]] = []

        def run(cmd: list[str], **kwargs: Any) -> None:
            runs.append(cmd)
            raise subprocess.CalledProcessError(1, cmd)

        venv_dir = self._fake_install(monkeypatch, tmp_path, run, pinned=pinned, clock=clock)
        with pytest.raises(error):
            launcher._ensure_install(venv_dir)
        assert len(runs) == attempts
        assert ("retrying without version pins" in capsys.readouterr().err) is pinned
        assert not (venv_dir / ".install-ok").exists()

    @pytest.mark.skipif(launcher.os.name == "nt", reason="POSIX flock")
    def test_install_timeout_is_not_retried_and_leaves_no_marker(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        runs: list[list[str]] = []

        def run(cmd: list[str], **kwargs: Any) -> None:
            runs.append(cmd)
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

        venv_dir = self._fake_install(monkeypatch, tmp_path, run)
        with pytest.raises(subprocess.TimeoutExpired):
            launcher._ensure_install(venv_dir)
        assert len(runs) == 1
        assert not (venv_dir / ".install-ok").exists()

    def test_pip_command_skips_constraints_missing_from_an_unbuilt_tree(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(launcher, "_CONSTRAINTS", tmp_path / "absent.txt")
        assert "--constraint" not in launcher._pip_install_command(tmp_path)

    @pytest.mark.parametrize(
        ("error", "message"),
        [
            (subprocess.TimeoutExpired("pip", 900), "timed out after 15 minutes"),
            (subprocess.CalledProcessError(2, "pip"), "pip exited with status 2; see the pip output above"),
        ],
    )
    def test_install_failure_messages(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        error: subprocess.SubprocessError, message: str,
    ) -> None:
        monkeypatch.setattr(launcher, "VERSION", "9.9.9")
        monkeypatch.setattr(launcher, "MIN_PYTHON", "3.0")

        def fail(venv_dir: Path) -> None:
            raise error

        monkeypatch.setattr(launcher, "_ensure_install", fail)
        assert launcher.main() == 1
        assert message in capsys.readouterr().err
