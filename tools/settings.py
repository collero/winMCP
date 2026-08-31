"""Shared settings/timezone helpers used by both the tool layer
(`tools/calendar.py`) and the real Outlook adapter (`tools/outlook_adapter.py`).

Extracted out of `tools/calendar.py` (Batch 2) so Phase 7's real adapter can
reuse the same local-timezone resolution concept instead of reimplementing
it — per the Batch 2 apply-progress handoff note. Living in its own module
(rather than importing from `tools/calendar.py` directly) avoids a circular
import, since `tools/calendar.py` imports `CalendarPort` from
`tools/outlook_adapter.py`.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"

# selective-tool-deployment: the installer's install-time output, distinct
# from `_SETTINGS_PATH` — never present in the repo itself, only written
# into a deployed/installed copy by `install.ps1` (design.md Decision 4).
_INSTALLED_TOOLS_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "installed-tools.yaml"
)

# Ordered fallback env vars for file-search's default roots (file-search
# change) — %USERPROFILE% first, then whichever OneDrive variants are set,
# per design.md's "Default roots when unconfigured" decision.
_ONEDRIVE_ENV_VARS = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")

# hard-tool-exclusion: the deployed location of the per-build manifest
# `make-deploy-package.sh` generates and stages as `tools/shipped-
# tools.json` — sitting inside the `tools/` package itself (unlike
# `_INSTALLED_TOOLS_PATH`, which lives under `config/`), so this is a
# plain sibling of this module, not a `.parent.parent` climb.
_SHIPPED_TOOLS_PATH = Path(__file__).resolve().parent / "shipped-tools.json"


def load_settings() -> dict[str, Any]:
    with _SETTINGS_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def settings_file_path() -> str:
    """Absolute path of this deployment's own `settings.yaml`, for
    error messages that tell the caller exactly which file to edit
    (e.g. the writable-notebook refusal in `tools/onenote.py`). On a
    deployed Windows install this resolves to the install tree
    (`C:\\usr\\WinMCP\\config\\settings.yaml`), not the repo copy."""
    return str(_SETTINGS_PATH)


def _load_installed_tools_yaml() -> dict[str, Any] | None:
    """Raw YAML load of `config/installed-tools.yaml`, or `None` if the
    file is absent — kept separate from `installed_tools()` so tests can
    mock this loader directly (mirroring `load_settings()`'s own
    mock-the-loader convention), rather than touching the real filesystem.
    """
    if not _INSTALLED_TOOLS_PATH.exists():
        return None
    with _INSTALLED_TOOLS_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def installed_tools() -> set[str] | None:
    """Which tools the installed copy has enabled — `config/installed-
    tools.yaml`'s `tools:` flat list (mcp-server-bootstrap/smoke-test-
    coverage deltas, design.md Decision 4).

    `None` when the file is absent — the back-compat sentinel meaning
    "everything" (pre-selective-deploy behavior: every catalog tool is
    registered/expected). `set()` when `tools:` is present but empty
    (nothing enabled). Otherwise the exact set of names listed. The
    file's shape is restricted to exactly that one flat list — any other
    top-level YAML key is ignored, never inspected.
    """
    raw = _load_installed_tools_yaml()
    if raw is None:
        return None
    return set(raw.get("tools") or [])


def _load_shipped_tools_json() -> dict[str, Any] | None:
    """Raw JSON load of `tools/shipped-tools.json`, or `None` if the file
    is absent — kept separate from `shipped_tools()` so tests can mock
    this loader directly, mirroring `_load_installed_tools_yaml()`'s own
    mock-the-loader convention, rather than touching the real filesystem.
    """
    if not _SHIPPED_TOOLS_PATH.exists():
        return None
    with _SHIPPED_TOOLS_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def shipped_tools() -> set[str] | None:
    """Which tool names this deployed package's build actually shipped —
    `tools/shipped-tools.json`'s family-nested manifest (`make-deploy-
    package.sh`'s Phase 2 generator: `{build_mode, families: [{name,
    tools: [{name, maturity, default_enabled}]}]}`), read live next to
    this module — the deployed location (hard-tool-exclusion change,
    design.md Decision 2).

    `None` when the file is absent — the back-compat sentinel meaning "no
    ceiling" (a legacy package predating hard-tool-exclusion), mirroring
    `installed_tools()`'s own absent-file/`None` convention. Otherwise the
    flat set of every tool `name` literally listed across every family's
    `tools[]` entries — presence in the manifest is the hard ceiling,
    independent of each entry's own `default_enabled` flag (that flag
    seeds `installed_tools()`'s install-time default; it is not what this
    function reports). A malformed manifest (invalid JSON) is NOT
    silently treated as absent — it propagates as a real
    `json.JSONDecodeError`, since swallowing it would fall back to "no
    ceiling" on a broken build artifact and defeat hard exclusion's whole
    purpose.
    """
    raw = _load_shipped_tools_json()
    if raw is None:
        return None
    return {
        tool["name"]
        for family in raw.get("families", [])
        for tool in family.get("tools", [])
    }


def local_timezone() -> Any:
    """Resolve the timezone used to attach an offset to a naive datetime.

    Uses `config/settings.yaml`'s `timezone_override` (an IANA name) when
    set, otherwise falls back to the host's local timezone, per design.md's
    "Datetime handling" decision.
    """
    override = load_settings().get("timezone_override")
    if override:
        from zoneinfo import ZoneInfo

        return ZoneInfo(override)
    return datetime.now().astimezone().tzinfo


def _casefold_normalized(path: str) -> str:
    """Case-insensitive, separator-normalized form of `path` for a
    containment comparison — NTFS paths are case-insensitive and mix `/`/
    `\\` in practice. Mirrors the normalization design.md's "Path
    normalization" decision calls for at the tool layer, scoped here only
    to `default_search_roots()`'s own dedupe step."""
    return path.replace("/", "\\").rstrip("\\").casefold()


def _is_nested_under(candidate_norm: str, root_norm: str) -> bool:
    """True if `candidate_norm` equals `root_norm` or is a subpath of it.
    Both arguments MUST already be normalized via `_casefold_normalized`.
    Boundary-aware (`root_norm + "\\"` prefix) so a sibling directory
    sharing a name prefix (e.g. `ana2` vs `ana`) is never mistaken for
    nested."""
    return candidate_norm == root_norm or candidate_norm.startswith(root_norm + "\\")


def file_search_walk_time_budget_seconds() -> float:
    """Wall-clock budget (seconds) the filesystem walk
    (`tools/file_search_walk.py`) may spend before stopping early and
    flagging `results_truncated=True` — `file_search_walk_time_budget_seconds`
    in `config/settings.yaml`, default `5` when absent, per the
    filesystem-walk-search spec's "Result and Resource Caps" requirement.
    Read live via `load_settings()` every call — never cached, mirroring
    `local_timezone()`'s discipline."""
    return float(load_settings().get("file_search_walk_time_budget_seconds", 5))


def file_search_walk_max_dirs() -> int:
    """Directory-count budget the filesystem walk may visit before
    stopping early and flagging `results_truncated=True` —
    `file_search_walk_max_dirs` in `config/settings.yaml`, default `5000`
    when absent, per the filesystem-walk-search spec's "Result and
    Resource Caps" requirement. Read live via `load_settings()` every
    call — never cached."""
    return int(load_settings().get("file_search_walk_max_dirs", 5000))


def file_search_ps_bridge_timeout_seconds() -> float:
    """Overall wall-clock deadline (seconds) `PowerShellSearchBridge._invoke()`
    allows its streaming read loop to run before killing the child and
    returning whatever rows already parsed as a truncated result —
    `file_search_ps_bridge_timeout_seconds` in `config/settings.yaml`,
    default `30` when absent (bridge-streaming-hotfix: bumped from `10` —
    a killed-at-the-deadline child now degrades to partial results
    instead of a hard failure, so a longer default budget costs less).
    Read live via `load_settings()` every call — never cached."""
    return float(load_settings().get("file_search_ps_bridge_timeout_seconds", 30))


def resolve_search_limit(limit: int | None) -> int:
    """Resolve the effective row cap for `mail_search`/`calendar_search`/
    `task_search` (BUG-002's search-result-caps change), per design.md's
    "limit default/max as config" decision.

    `limit=None` -> `config/settings.yaml`'s `search_default_limit`
    (default `50` when absent). A given `limit > search_max_limit`
    (default `200` when absent) is clamped down to `search_max_limit`,
    never rejected. A given `limit <= 0` raises `ValueError` before any
    adapter call. Read live via `load_settings()` every call — never
    cached, mirroring `local_timezone()`'s discipline."""
    settings = load_settings()
    max_limit = int(settings.get("search_max_limit", 200))
    if limit is None:
        return int(settings.get("search_default_limit", 50))
    if limit <= 0:
        raise ValueError(f"limit must be a positive integer, got {limit}")
    return min(limit, max_limit)


def calendar_subject_search_lookback_days() -> int:
    """Days to look back from "now" for the default window a subject-only
    `calendar_search` request (no explicit `from`/`to`) auto-applies —
    BUG-008 hotfix, 2026-08-26. Config key
    `calendar_subject_search_lookback_days` in `config/settings.yaml`,
    default `90` when absent. Read live via `load_settings()` every
    call — never cached, mirroring `local_timezone()`'s discipline."""
    return int(load_settings().get("calendar_subject_search_lookback_days", 90))


def file_search_bridge_debug_log() -> bool:
    """Whether every `PowerShellSearchBridge` invocation should append one
    diagnostic line to `bridge_invocations.log` beside the deployed
    install (BUG-006 volume-theory-dead hotfix,
    0061-cowork-bug006-volume-theory-dead-any-row-kills.md) —
    `file_search_bridge_debug_log` in `config/settings.yaml`, default
    `True` for this diagnostic build (set `False` once BUG-006 closes).
    Read live via `load_settings()` every call — never cached, mirroring
    `local_timezone()`'s discipline."""
    return bool(load_settings().get("file_search_bridge_debug_log", True))


def calendar_subject_search_lookahead_days() -> int:
    """Days to look ahead from "now" for the default window a subject-only
    `calendar_search` request (no explicit `from`/`to`) auto-applies —
    BUG-008 hotfix, 2026-08-26. Config key
    `calendar_subject_search_lookahead_days` in `config/settings.yaml`,
    default `365` when absent. Read live via `load_settings()` every
    call — never cached."""
    return int(load_settings().get("calendar_subject_search_lookahead_days", 365))


def onenote_writable_notebooks() -> list[str]:
    """`onenote_writable_notebooks` from `config/settings.yaml` — the list
    of notebook names `onenote_create_page`/`onenote_update_page` are
    allowed to write to. Checked in Python (`tools/onenote.py`) BEFORE any
    adapter/COM call — the onenote-write-page spec's "Writable Notebook
    Allowlist" requirement. Defaults to exactly `["z - Test Notebook"]`
    when the key is absent/empty, so an LLM-driven write can never land on
    one of the live Informa notebooks unless the allowlist is explicitly
    widened. Read live via `load_settings()` every call — never cached,
    mirroring `local_timezone()`'s discipline."""
    configured = load_settings().get("onenote_writable_notebooks")
    if configured:
        return list(configured)
    return ["z - Test Notebook"]


def onenote_search_max_results(limit: int | None) -> int:
    """Resolve the effective row cap for `onenote_search` (add-onenote-
    adapter change), mirroring `resolve_search_limit()`'s default/clamp/
    reject contract but scoped to OneNote's own config key rather than the
    shared `search_default_limit`/`search_max_limit` (mail/calendar/
    tasks) — design.md's File Changes table introduces exactly one new
    onenote-search settings key, `onenote_search_max_results` (default
    `50` when absent), which this function applies as the *default* used
    when `limit` is omitted. The hard ceiling (`200`, matching
    `mail_search`'s own convention per the onenote-search spec's "Result
    Limit Parameter" requirement) is a fixed constant here, not
    independently configurable in this change.

    `limit=None` -> the configured/default value. A given `limit > 200`
    is clamped down to `200`, never rejected. A given `limit <= 0` raises
    `ValueError` before any adapter call. Read live via `load_settings()`
    every call — never cached."""
    hard_max = 200
    default = int(load_settings().get("onenote_search_max_results", 50))
    if limit is None:
        return default
    if limit <= 0:
        raise ValueError(f"limit must be a positive integer, got {limit}")
    return min(limit, hard_max)


def onenote_ps_bridge_timeout_seconds() -> float:
    """Overall wall-clock deadline (seconds) `OneNoteAdapter._invoke()`
    allows `PsBridgeTransport.invoke()`'s streaming read loop to run
    before killing the child and raising `PsBridgeTransportError` —
    `onenote_ps_bridge_timeout_seconds` in `config/settings.yaml`, default
    `20` when absent (design.md's File Changes table). Read live via
    `load_settings()` every call — never cached. Replaces
    `tools/onenote_adapter.py`'s Batch 2 `_DEFAULT_TIMEOUT_SECONDS` module
    constant placeholder (this batch's Phase 7 wiring, per that module's
    own deviation note)."""
    return float(load_settings().get("onenote_ps_bridge_timeout_seconds", 20))


def default_search_roots() -> list[str]:
    """Resolve the fallback `file_search` roots used when
    `file_search_allowed_roots` is absent/empty in `config/settings.yaml`
    (file-search change).

    Ordered candidates: `%USERPROFILE%` first, then whichever of
    `%OneDrive%`, `%OneDriveCommercial%`, `%OneDriveConsumer%` are set in
    the environment — each resolved at call time, never hardcoded, per
    design.md's "Default roots when unconfigured" decision. A later
    candidate that is nested inside (or identical to) an earlier, already-
    kept root is dropped: a plain OneDrive-under-profile setup collapses
    to just `%USERPROFILE%`, while a KFM-redirected OneDrive on another
    drive stays as an extra root. Returns `[]` when none of the env vars
    are set.
    """
    candidates: list[str] = []
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        candidates.append(userprofile)
    for var in _ONEDRIVE_ENV_VARS:
        value = os.environ.get(var)
        if value:
            candidates.append(value)

    roots: list[str] = []
    for candidate in candidates:
        candidate_norm = _casefold_normalized(candidate)
        if any(
            _is_nested_under(candidate_norm, _casefold_normalized(kept))
            for kept in roots
        ):
            continue
        roots.append(candidate)
    return roots
