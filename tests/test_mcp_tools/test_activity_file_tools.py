"""MCP activity file tool tests: download and upload, confined to GARMIN_MCP_FILE_ROOT."""
from __future__ import annotations

import importlib
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import require_mcp

require_mcp()

from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from garmin_cli.exceptions import GarminCliError  # noqa: E402
from garmin_cli.mcp_server import create_mcp_server  # noqa: E402
from tests.test_mcp_tools.support import _call, _config, _tool_annotations  # noqa: E402

_MODULE = "garmin_cli.mcp_tools.activities_write"
_GENERIC_UPLOAD_ERROR = "File not available under GARMIN_MCP_FILE_ROOT"
_needs_unprivileged_posix = pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="needs POSIX permissions enforced for a non-root user",
)
# An unknown ~user fails expanduser; a NUL byte cannot reach os.environ, so
# that case makes the root lookup itself raise.
_BAD_ROOTS = ["~no-such-user-garmin/x", "relative/dir", ValueError("embedded null byte")]


def _set_bad_root(mocker: Any, monkeypatch: Any, bad_root: str | Exception) -> None:
    if isinstance(bad_root, str):
        monkeypatch.setenv("GARMIN_MCP_FILE_ROOT", bad_root)
    else:
        mocker.patch(f"{_MODULE}._file_root", side_effect=bad_root)


def _set_home(monkeypatch: Any, home: Path) -> None:
    # expanduser reads HOME on POSIX and USERPROFILE on Windows.
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


@pytest.fixture(autouse=True)
def _file_root(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("GARMIN_MCP_FILE_ROOT", str(tmp_path))


class TestMcpActivityDownload:

    def _download(self, mocker: Any, args: dict[str, Any]) -> tuple[dict[str, Any], Any]:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        download = mocker.patch(f"{_MODULE}.download_activity", return_value=b"new")
        mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())
        result = _call(server, "activity_download", {"activity_id": 1, "fmt": "gpx", **args})
        return result["rows"][0], download

    def test_writes_file_and_reports_path_not_bytes(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        download = mocker.patch(f"{_MODULE}.download_activity", return_value=b"FITDATA")
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        target = tmp_path / "ride.gpx"
        server = create_mcp_server(_config())

        result = _call(
            server,
            "activity_download",
            {"activity_id": 12345, "fmt": "gpx", "output_path": str(target)},
        )
        row = result["rows"][0]
        assert row["ok"] is True
        assert row["action"] == "downloaded"
        assert row["path"] == str(target)
        assert row["size_bytes"] == len(b"FITDATA")
        assert row["format"] == "gpx"
        # Never leak raw bytes into the envelope.
        assert "bytes" not in row and "content" not in row
        assert target.read_bytes() == b"FITDATA"
        download.assert_called_once_with(12345, "gpx")
        event = log.call_args.args[0]
        assert event.tool == "activity_download"
        assert event.outcome == "success"
        assert event.size_bytes == len(b"FITDATA")
        assert event.path_len == len(str(target))

    def test_disk_write_failure_is_audited_tool_error(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        # A post-validation disk failure (target raced into a directory) must
        # still emit exactly one audit event and surface as ToolError, not a
        # raw OSError.
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        mocker.patch(f"{_MODULE}.download_activity", return_value=b"FITDATA")
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        target = tmp_path / "ride.gpx"
        target.mkdir()
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="Failed to write output file"):
            _call(
                server,
                "activity_download",
                {
                    "activity_id": 1,
                    "fmt": "gpx",
                    "output_path": str(target),
                    "overwrite": True,
                },
            )
        assert log.call_count == 1
        event = log.call_args.args[0]
        assert event.outcome == "failed-upstream"

    def test_refuses_overwrite_without_flag(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        download = mocker.patch(f"{_MODULE}.download_activity")
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        existing = tmp_path / "ride.gpx"
        existing.write_bytes(b"old")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "activity_download",
            {"activity_id": 1, "fmt": "gpx", "output_path": str(existing)},
        )
        row = result["rows"][0]
        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        assert any("already exists" in e for e in row["errors"])
        download.assert_not_called()
        assert existing.read_bytes() == b"old"
        event = log.call_args.args[0]
        assert event.outcome == "failed-validation"

    def test_overwrite_true_replaces(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        mocker.patch(f"{_MODULE}.download_activity", return_value=b"new")
        mocker.patch(f"{_MODULE}._emit_write_log")
        existing = tmp_path / "ride.gpx"
        existing.write_bytes(b"old")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "activity_download",
            {"activity_id": 1, "fmt": "gpx", "output_path": str(existing), "overwrite": True},
        )
        assert result["rows"][0]["ok"] is True
        assert existing.read_bytes() == b"new"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["ride.gpx"]

    def test_rejects_output_path_outside_root(
        self, mocker: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("GARMIN_MCP_FILE_ROOT", str(tmp_path / "root"))
        outside = tmp_path / "outside.gpx"

        row, download = self._download(mocker, {"output_path": str(outside)})

        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        assert any("GARMIN_MCP_FILE_ROOT" in e for e in row["errors"])
        download.assert_not_called()
        assert not outside.exists()

    @pytest.mark.parametrize("output_path", ["../escape.gpx", "sub/../ride.gpx"])
    def test_rejects_dotdot(self, mocker: Any, tmp_path: Path, output_path: str) -> None:
        (tmp_path / "sub").mkdir()

        row, download = self._download(mocker, {"output_path": output_path})

        assert row["ok"] is False
        assert any("GARMIN_MCP_FILE_ROOT" in e for e in row["errors"])
        download.assert_not_called()

    @pytest.mark.parametrize("overwrite", [False, True])
    def test_rejects_symlink_target(
        self, mocker: Any, tmp_path: Path, monkeypatch: Any, overwrite: bool
    ) -> None:
        root = tmp_path / "root"
        root.mkdir()
        monkeypatch.setenv("GARMIN_MCP_FILE_ROOT", str(root))
        victim = tmp_path / "victim.txt"
        victim.write_bytes(b"keep")
        (root / "link.gpx").symlink_to(victim)
        (root / "dangling.gpx").symlink_to(tmp_path / "missing.txt")

        for name in ("link.gpx", "dangling.gpx"):
            row, download = self._download(
                mocker, {"output_path": name, "overwrite": overwrite}
            )
            assert row["ok"] is False, name
            download.assert_not_called()
        assert victim.read_bytes() == b"keep"
        assert not (tmp_path / "missing.txt").exists()

    @pytest.mark.parametrize("output_path", [".", ""])
    def test_rejects_root_itself_as_target(
        self, mocker: Any, tmp_path: Path, monkeypatch: Any, output_path: str
    ) -> None:
        root = tmp_path / "root"
        root.mkdir()
        monkeypatch.setenv("GARMIN_MCP_FILE_ROOT", str(root))

        row, download = self._download(
            mocker, {"output_path": output_path or str(root), "overwrite": True}
        )

        assert row["ok"] is False
        download.assert_not_called()
        assert [p.name for p in tmp_path.iterdir()] == ["root"]
        assert list(root.iterdir()) == []

    def test_unusable_root_fails_before_auth(
        self, mocker: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        blocker = tmp_path / "file"
        blocker.write_bytes(b"x")
        monkeypatch.setenv("GARMIN_MCP_FILE_ROOT", str(blocker / "root"))

        row, download = self._download(mocker, {})

        assert row["ok"] is False
        assert any("not a writable directory" in e for e in row["errors"])
        importlib.import_module(_MODULE).ensure_authenticated.assert_not_called()
        download.assert_not_called()

    @_needs_unprivileged_posix
    def test_permission_error_is_reported_not_called_outside_root(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        locked = tmp_path / "locked"
        locked.mkdir(mode=0o000)
        try:
            row, download = self._download(mocker, {"output_path": "locked/ride.gpx"})
        finally:
            locked.chmod(0o700)

        assert row["ok"] is False
        assert any("Permission denied" in e for e in row["errors"])
        assert not any("must resolve inside" in e for e in row["errors"])
        download.assert_not_called()

    def test_unexpanded_placeholder_root_falls_back_to_default(
        self, mocker: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("GARMIN_MCP_FILE_ROOT", "${HOME}/Downloads/garmin-py")
        _set_home(monkeypatch, tmp_path)

        row, _ = self._download(mocker, {})

        assert row["ok"] is True
        assert row["path"] == str(tmp_path / "Downloads" / "garmin-py" / "activity_1.gpx")

    def test_relative_output_path_resolves_under_root(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        row, _ = self._download(mocker, {"output_path": "ride.gpx"})

        assert row["ok"] is True
        assert row["path"] == str(tmp_path / "ride.gpx")
        assert (tmp_path / "ride.gpx").read_bytes() == b"new"

    @pytest.mark.parametrize("link_target", ["outside", "inside"])
    def test_rejects_symlinked_parent_dir(
        self, mocker: Any, tmp_path: Path, monkeypatch: Any, link_target: str
    ) -> None:
        root = tmp_path / "root"
        real = (tmp_path / "elsewhere") if link_target == "outside" else (root / "real")
        real.mkdir(parents=True)
        root.mkdir(exist_ok=True)
        monkeypatch.setenv("GARMIN_MCP_FILE_ROOT", str(root))
        (root / "linkdir").symlink_to(real, target_is_directory=True)

        row, download = self._download(mocker, {"output_path": "linkdir/ride.gpx"})

        assert row["ok"] is False
        download.assert_not_called()
        assert list(real.iterdir()) == []

    @pytest.mark.parametrize("bad_root", _BAD_ROOTS)
    def test_unusable_root_value_is_validation_error(
        self, mocker: Any, monkeypatch: Any, bad_root: str | Exception
    ) -> None:
        _set_bad_root(mocker, monkeypatch, bad_root)

        row, download = self._download(mocker, {})

        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        download.assert_not_called()
        log = importlib.import_module(_MODULE)._emit_write_log
        assert log.call_args.args[0].outcome == "failed-validation"

    def test_relative_root_must_be_absolute(self, mocker: Any, monkeypatch: Any) -> None:
        monkeypatch.setenv("GARMIN_MCP_FILE_ROOT", "relative/dir")

        row, _ = self._download(mocker, {})

        assert any("must be an absolute path" in e for e in row["errors"])

    def test_invalid_format_does_not_create_root(
        self, mocker: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        root = tmp_path / "root"
        monkeypatch.setenv("GARMIN_MCP_FILE_ROOT", str(root))

        with pytest.raises(ToolError, match="Input should be 'original'"):
            self._download(mocker, {"fmt": "pdf"})

        assert not root.exists()

    def test_failed_exclusive_write_leaves_no_partial_file(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        real_fdopen = os.fdopen

        def failing_fdopen(fd: int, *args: Any, **kwargs: Any) -> Any:
            os.close(fd)
            raise OSError("disk full")

        patch = mocker.patch(f"{_MODULE}.os.fdopen", side_effect=failing_fdopen)
        with pytest.raises(ToolError, match="disk full"):
            self._download(mocker, {"output_path": "ride.gpx"})
        assert not (tmp_path / "ride.gpx").exists()

        patch.side_effect = real_fdopen
        row, _ = self._download(mocker, {"output_path": "ride.gpx"})
        assert row["ok"] is True
        assert (tmp_path / "ride.gpx").read_bytes() == b"new"

    def test_file_planted_during_download_is_not_clobbered(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        target = tmp_path / "ride.gpx"

        def plant(*_args: Any) -> bytes:
            target.write_bytes(b"planted")
            return b"new"

        mocker.patch(f"{_MODULE}.ensure_authenticated")
        mocker.patch(f"{_MODULE}.download_activity", side_effect=plant)
        mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="Failed to write output file"):
            _call(server, "activity_download", {"activity_id": 1, "fmt": "gpx",
                                                "output_path": "ride.gpx"})
        assert target.read_bytes() == b"planted"

    def test_symlink_planted_during_download_is_refused_on_overwrite(
        self, mocker: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        root = tmp_path / "root"
        root.mkdir()
        monkeypatch.setenv("GARMIN_MCP_FILE_ROOT", str(root))
        victim = tmp_path / "victim.txt"
        victim.write_bytes(b"keep")

        def plant(*_args: Any) -> bytes:
            (root / "ride.gpx").symlink_to(victim)
            return b"new"

        mocker.patch(f"{_MODULE}.ensure_authenticated")
        mocker.patch(f"{_MODULE}.download_activity", side_effect=plant)
        mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="symlink"):
            _call(server, "activity_download", {"activity_id": 1, "fmt": "gpx",
                                                "output_path": "ride.gpx", "overwrite": True})
        assert victim.read_bytes() == b"keep"
        assert (root / "ride.gpx").is_symlink()

    def test_default_root_is_created_private(
        self, mocker: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        monkeypatch.delenv("GARMIN_MCP_FILE_ROOT")
        _set_home(monkeypatch, tmp_path)
        root = tmp_path / "Downloads" / "garmin-py"

        row, _ = self._download(mocker, {})

        assert row["ok"] is True
        target = root / "activity_1.gpx"
        assert row["path"] == str(target)
        assert target.read_bytes() == b"new"
        if os.name == "posix":
            assert stat.S_IMODE(root.stat().st_mode) == 0o700
            assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_unknown_format_is_rejected_by_the_input_schema(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        download = mocker.patch(f"{_MODULE}.download_activity")
        mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="fmt"):
            _call(
                server,
                "activity_download",
                {"activity_id": 1, "fmt": "pdf", "output_path": str(tmp_path / "x.pdf")},
            )
        download.assert_not_called()

    def test_download_formats_match_the_endpoint_table(self) -> None:
        from typing import get_args

        from garmin_cli.endpoints.activities import _DOWNLOAD_FORMAT_MAP
        from garmin_cli.mcp_tools.activities_write import DownloadFormat

        assert set(get_args(DownloadFormat)) == set(_DOWNLOAD_FORMAT_MAP)

    def test_missing_output_dir_returns_validation_envelope(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        download = mocker.patch(f"{_MODULE}.download_activity")
        mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(
            server,
            "activity_download",
            {"activity_id": 1, "fmt": "gpx", "output_path": str(tmp_path / "nope" / "x.gpx")},
        )
        row = result["rows"][0]
        assert row["ok"] is False
        assert any("directory does not exist" in e for e in row["errors"])
        download.assert_not_called()

    def test_invalid_activity_id(self) -> None:
        server = create_mcp_server(_config())
        with pytest.raises(ToolError, match="positive"):
            _call(server, "activity_download", {"activity_id": 0})

    def test_destructive_annotation(self) -> None:
        server = create_mcp_server(_config())
        ann = _tool_annotations(server, "activity_download")
        # overwrite=True can replace a local file, so clients must prompt.
        assert ann is not None
        assert ann.read_only_hint is False
        assert ann.destructive_hint is True
        assert ann.idempotent_hint is None


def _uploaded_copy(upload: Any, original: Path) -> Path:
    """The private copy handed to Garmin: same name and bytes, never the original."""
    sent = Path(upload.call_args.args[0])
    assert sent != original and sent.name == original.name
    return sent


class TestMcpActivityUpload:

    def _upload(self, mocker: Any, file_path: str) -> tuple[dict[str, Any], Any]:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        upload = mocker.patch(f"{_MODULE}.upload_activity", return_value={})
        mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())
        result = _call(server, "activity_upload", {"file_path": file_path})
        return result["rows"][0], upload

    def test_happy_path_reports_activity_id(self, mocker: Any, tmp_path: Path) -> None:
        f = tmp_path / "ride.fit"
        f.write_bytes(b"fit")
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        seen: dict[str, Any] = {}

        def _upload(path: str) -> dict[str, Any]:
            seen["bytes"] = Path(path).read_bytes()
            seen["mode"] = stat.S_IMODE(Path(path).parent.stat().st_mode)
            return {"detailedImportResult": {"successes": [{"internalId": 99}]}}

        upload = mocker.patch(f"{_MODULE}.upload_activity", side_effect=_upload)
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "activity_upload", {"file_path": str(f)})
        row = result["rows"][0]
        assert row == {"ok": True, "action": "uploaded", "status": "uploaded", "activity_id": 99}
        sent = _uploaded_copy(upload, f)
        assert seen == {"bytes": b"fit", "mode": 0o700}
        assert not sent.exists()  # the private copy is always removed
        event = log.call_args.args[0]
        assert event.tool == "activity_upload"
        assert event.outcome == "success"
        assert event.activity_id == 99
        # Path reduced to length only -- no PII in logs.
        assert event.path_len == len(str(f))

    def test_missing_file_returns_validation_envelope(self, mocker: Any, tmp_path: Path) -> None:
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        upload = mocker.patch(f"{_MODULE}.upload_activity")
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "activity_upload", {"file_path": str(tmp_path / "nope.fit")})
        row = result["rows"][0]
        assert row["ok"] is False
        assert row["error_code"] == "INVALID_INPUT"
        assert row["errors"] == [_GENERIC_UPLOAD_ERROR]
        upload.assert_not_called()
        event = log.call_args.args[0]
        assert event.outcome == "failed-validation"

    def test_unavailable_paths_share_one_generic_error(
        self, mocker: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        root = tmp_path / "root"
        (root / "dir.fit").mkdir(parents=True)
        monkeypatch.setenv("GARMIN_MCP_FILE_ROOT", str(root))
        outside = tmp_path / "outside.fit"
        outside.write_bytes(b"fit")
        (root / "link.fit").symlink_to(outside)

        for path in (str(outside), "../outside.fit", "link.fit", "dir.fit", "missing.fit"):
            row, upload = self._upload(mocker, path)
            assert row["errors"] == [_GENERIC_UPLOAD_ERROR], path
            upload.assert_not_called()

    @_needs_unprivileged_posix
    def test_permission_error_returns_generic_error(self, mocker: Any, tmp_path: Path) -> None:
        locked = tmp_path / "locked"
        locked.mkdir(mode=0o000)
        try:
            row, upload = self._upload(mocker, "locked/ride.fit")
        finally:
            locked.chmod(0o700)

        assert row["errors"] == [_GENERIC_UPLOAD_ERROR]
        upload.assert_not_called()

    @pytest.mark.parametrize("link_target", ["outside", "inside"])
    def test_symlinked_parent_dir_returns_generic_error(
        self, mocker: Any, tmp_path: Path, monkeypatch: Any, link_target: str
    ) -> None:
        root = tmp_path / "root"
        real = (tmp_path / "elsewhere") if link_target == "outside" else (root / "real")
        real.mkdir(parents=True)
        root.mkdir(exist_ok=True)
        (real / "ride.fit").write_bytes(b"fit")
        monkeypatch.setenv("GARMIN_MCP_FILE_ROOT", str(root))
        (root / "linkdir").symlink_to(real, target_is_directory=True)

        row, upload = self._upload(mocker, "linkdir/ride.fit")

        assert row["errors"] == [_GENERIC_UPLOAD_ERROR]
        upload.assert_not_called()

    @pytest.mark.parametrize("bad_root", _BAD_ROOTS)
    def test_unusable_root_value_returns_generic_error(
        self, mocker: Any, monkeypatch: Any, bad_root: str | Exception
    ) -> None:
        _set_bad_root(mocker, monkeypatch, bad_root)

        row, upload = self._upload(mocker, "ride.fit")

        assert row["errors"] == [_GENERIC_UPLOAD_ERROR]
        upload.assert_not_called()

    def test_junction_component_returns_generic_error(
        self, mocker: Any, tmp_path: Path
    ) -> None:
        (tmp_path / "junction").mkdir()
        (tmp_path / "junction" / "ride.fit").write_bytes(b"fit")
        mocker.patch(
            f"{_MODULE}.os.path.isjunction", side_effect=lambda p: Path(p).name == "junction"
        )

        row, upload = self._upload(mocker, "junction/ride.fit")

        assert row["errors"] == [_GENERIC_UPLOAD_ERROR]
        upload.assert_not_called()

    def test_relative_path_resolves_under_root(self, mocker: Any, tmp_path: Path) -> None:
        (tmp_path / "ride.fit").write_bytes(b"fit")

        _, upload = self._upload(mocker, "ride.fit")

        _uploaded_copy(upload, tmp_path / "ride.fit")

    def test_symlink_swapped_in_after_the_check_is_not_followed(
        self, mocker: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        root = tmp_path / "root"
        root.mkdir()
        monkeypatch.setenv("GARMIN_MCP_FILE_ROOT", str(root))
        secret = tmp_path / "secret.fit"
        secret.write_bytes(b"secret")
        swapped = root / "ride.fit"
        swapped.symlink_to(secret)
        # _confine saw a regular file; the symlink appeared before the open.
        mocker.patch(f"{_MODULE}._confine", return_value=swapped)

        row, upload = self._upload(mocker, "ride.fit")

        assert row["errors"] == [_GENERIC_UPLOAD_ERROR]
        upload.assert_not_called()

    def test_rejected_import_reports_rejected(self, mocker: Any, tmp_path: Path) -> None:
        f = tmp_path / "dup.fit"
        f.write_bytes(b"fit")
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        mocker.patch(
            f"{_MODULE}.upload_activity",
            return_value={"detailedImportResult": {"successes": [], "failures": [{"m": "dup"}]}},
        )
        mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        result = _call(server, "activity_upload", {"file_path": str(f)})
        row = result["rows"][0]
        assert row["ok"] is True
        assert row["status"] == "rejected"
        assert row["activity_id"] is None

    def test_upstream_failure(self, mocker: Any, tmp_path: Path) -> None:
        f = tmp_path / "ride.fit"
        f.write_bytes(b"fit")
        mocker.patch(f"{_MODULE}.ensure_authenticated")
        upload = mocker.patch(
            f"{_MODULE}.upload_activity",
            side_effect=GarminCliError(error="Internal server error.", error_code="SERVER_ERROR"),
        )
        log = mocker.patch(f"{_MODULE}._emit_write_log")
        server = create_mcp_server(_config())

        with pytest.raises(ToolError, match="Internal server error"):
            _call(server, "activity_upload", {"file_path": str(f)})
        event = log.call_args.args[0]
        assert event.outcome == "failed-upstream"
        assert not _uploaded_copy(upload, f).exists()
