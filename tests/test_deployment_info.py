"""Tests for tools/deployment_info.py — the `server_info` tool's helper
(add-server-info change, cowork mailbox `general/` request 2026-08-28).

The tool exists so the CLIENT side of a debugging round (a Claude Desktop /
Cowork session) can state exactly which build it is talking to, instead of
inferring it from behavioral tells. The build stamp (`build-info.json`) is
written by make-deploy-package.sh at package time; a deployment without one
(source checkout, or a package predating the stamp) must still answer, with
the stamp fields null and a note saying why.
"""
import json
from pathlib import Path

from tools.deployment_info import deployment_info


def _write_stamp(root: Path, **overrides) -> dict:
    stamp = {
        "package": "WinMCP-20260828.zip",
        "builtUtc": "2026-08-28T15:50:00Z",
        "buildId": "abc123def456",
        "buildMode": "full",
    }
    stamp.update(overrides)
    (root / "build-info.json").write_text(json.dumps(stamp), encoding="utf-8")
    return stamp


def test_stamped_deployment_reports_build_metadata(tmp_path):
    _write_stamp(tmp_path)

    info = deployment_info(["onenote_search", "calendar_search"], root=tmp_path)

    assert info.package == "WinMCP-20260828.zip"
    assert info.built_utc == "2026-08-28T15:50:00Z"
    assert info.build_id == "abc123def456"
    assert info.build_mode == "full"
    assert info.install_root == str(tmp_path)
    assert info.note is None


def test_unstamped_deployment_answers_with_nulls_and_a_note(tmp_path):
    info = deployment_info([], root=tmp_path)

    assert info.package is None
    assert info.build_id is None
    assert info.built_utc is None
    assert info.build_mode is None
    assert info.note is not None
    assert "build-info.json" in info.note


def test_corrupt_stamp_never_raises(tmp_path):
    (tmp_path / "build-info.json").write_text("{not json", encoding="utf-8")

    info = deployment_info([], root=tmp_path)

    assert info.package is None
    assert info.note is not None


def test_enabled_tools_are_sorted_and_python_version_present(tmp_path):
    info = deployment_info(["b_tool", "a_tool"], root=tmp_path)

    assert info.enabled_tools == ["a_tool", "b_tool"]
    assert info.python_version  # non-empty, e.g. "3.12.3"


def test_default_root_is_the_repo_root():
    info = deployment_info([])

    assert Path(info.install_root, "server.py").exists()
