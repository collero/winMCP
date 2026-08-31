"""Helper for the `server_info` MCP tool (add-server-info change).

Requested from the cowork debugging mailbox (2026-08-28): during the
BUG-009 round the client side could only infer WHICH build it was talking
to from behavioral tells ("does get_page report the page-XML timestamp
yet?"), because a promote without a Claude Desktop restart leaves the old
server running and nothing on the tool surface said so. `server_info`
makes the deployment self-identifying: the build stamp
(`build-info.json`, written by make-deploy-package.sh at package time),
the install root (distinguishes PRO / QA / a source checkout), and the
tool names this server actually registered.

A deployment WITHOUT a stamp — a source checkout, or a package built
before the stamp existed — must still answer: stamp fields come back
null with a `note` saying why, never an error.
"""
import json
import sys
from pathlib import Path

from models.schemas import DeploymentInfo

# Resolved next to this module's parent (the install root, where
# server.py and build-info.json live) — never the process CWD, mirroring
# `_PS_BRIDGE_ONENOTE_SCRIPT`'s absolute-path discipline.
_INSTALL_ROOT = Path(__file__).resolve().parent.parent

_STAMP_NAME = "build-info.json"


def deployment_info(enabled_tools: list[str], root: Path | None = None) -> DeploymentInfo:
    """Build the `server_info` response. `enabled_tools` is the list of
    tool names the server actually registered for this process (computed
    by server.py, which owns the gating); `root` is injectable for
    tests and defaults to the real install root."""
    root = _INSTALL_ROOT if root is None else root
    package = built_utc = build_id = build_mode = note = None

    stamp_path = root / _STAMP_NAME
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
        package = stamp.get("package")
        built_utc = stamp.get("builtUtc")
        build_id = stamp.get("buildId")
        build_mode = stamp.get("buildMode")
    except FileNotFoundError:
        note = (
            f"no {_STAMP_NAME} in {root} — this is a source checkout or a "
            f"package built before build stamping existed; identify it by "
            f"installRoot and enabledTools instead."
        )
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        note = f"{_STAMP_NAME} present but unreadable ({exc}) — stamp fields omitted."

    return DeploymentInfo(
        package=package,
        built_utc=built_utc,
        build_id=build_id,
        build_mode=build_mode,
        install_root=str(root),
        python_version=".".join(str(part) for part in sys.version_info[:3]),
        enabled_tools=sorted(enabled_tools),
        note=note,
    )
