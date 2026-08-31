"""RED tests for tools/settings.py — `default_search_roots()` (file-search
change) and the walk/bridge config readers (file-search-resilience change).

Covers the fallback roots resolved when `file_search_allowed_roots` is
absent/empty in `config/settings.yaml`: ordered candidates `%USERPROFILE%`,
`%OneDrive%`, `%OneDriveCommercial%`, `%OneDriveConsumer%`, whichever are
set in the environment, resolved at call time (never hardcoded) — see
design.md's "Default roots when unconfigured" decision. A later candidate
nested inside an earlier one (case-insensitive, separator-normalized) is
dropped, so a plain OneDrive-under-profile setup collapses to just
`%USERPROFILE%`, while a KFM-redirected OneDrive on another drive stays as
an extra root.

Also covers the file-search-resilience change's Phase 1 config readers:
`file_search_walk_time_budget_seconds()` (default 5),
`file_search_walk_max_dirs()` (default 5000), and
`file_search_ps_bridge_timeout_seconds()` (default 10) — each read live
from `config/settings.yaml` (mocked here via `load_settings`), applying
the documented default when the key is absent, mirroring the
`load_settings()`-per-call discipline `local_timezone()` already
established (never cached, per design.md).
"""
import json

import pytest

from tools.settings import (
    default_search_roots,
    file_search_ps_bridge_timeout_seconds,
    file_search_walk_max_dirs,
    file_search_walk_time_budget_seconds,
    installed_tools,
    onenote_ps_bridge_timeout_seconds,
    onenote_search_max_results,
    onenote_writable_notebooks,
    resolve_search_limit,
    shipped_tools,
)

_ENV_VARS = ("USERPROFILE", "OneDrive", "OneDriveCommercial", "OneDriveConsumer")


def _clear_env(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_default_search_roots_returns_userprofile_only_when_no_onedrive_env(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\ana")

    roots = default_search_roots()

    assert roots == ["C:\\Users\\ana"]


def test_default_search_roots_returns_empty_list_when_no_env_vars_set(monkeypatch):
    _clear_env(monkeypatch)

    roots = default_search_roots()

    assert roots == []


def test_default_search_roots_dedupes_onedrive_nested_under_userprofile(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\ana")
    monkeypatch.setenv("OneDrive", "C:\\Users\\ana\\OneDrive")

    roots = default_search_roots()

    assert roots == ["C:\\Users\\ana"]


def test_default_search_roots_dedupe_is_case_and_separator_insensitive(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\ana")
    monkeypatch.setenv("OneDrive", "c:/users/ana/OneDrive")

    roots = default_search_roots()

    assert roots == ["C:\\Users\\ana"]


def test_default_search_roots_keeps_kfm_redirected_onedrive_as_extra_root(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\ana")
    monkeypatch.setenv("OneDrive", "D:\\OneDriveRedirect")

    roots = default_search_roots()

    assert roots == ["C:\\Users\\ana", "D:\\OneDriveRedirect"]


def test_default_search_roots_includes_commercial_and_consumer_variants_in_order(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\ana")
    monkeypatch.setenv("OneDriveCommercial", "D:\\Work")
    monkeypatch.setenv("OneDriveConsumer", "E:\\Personal")

    roots = default_search_roots()

    assert roots == ["C:\\Users\\ana", "D:\\Work", "E:\\Personal"]


# ---------------------------------------------------------------------------
# file-search-resilience: walk/bridge config readers
# ---------------------------------------------------------------------------


def test_walk_time_budget_seconds_defaults_to_5_when_unconfigured(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})

    assert file_search_walk_time_budget_seconds() == 5


def test_walk_time_budget_seconds_returns_configured_value(mocker):
    mocker.patch(
        "tools.settings.load_settings",
        return_value={"file_search_walk_time_budget_seconds": 2},
    )

    assert file_search_walk_time_budget_seconds() == 2


def test_walk_max_dirs_defaults_to_5000_when_unconfigured(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})

    assert file_search_walk_max_dirs() == 5000


def test_walk_max_dirs_returns_configured_value(mocker):
    mocker.patch(
        "tools.settings.load_settings",
        return_value={"file_search_walk_max_dirs": 100},
    )

    assert file_search_walk_max_dirs() == 100


def test_ps_bridge_timeout_seconds_defaults_to_30_when_unconfigured(mocker):
    """bridge-streaming-hotfix: default bumped 10 -> 30 -- the streaming
    `_invoke()` rewrite (tools/file_search_adapter.py) now returns
    partial, truncated results instead of raising when the deadline hits
    mid-stream, so a longer default budget costs less (a slow-but-alive
    query gets more time to finish cleanly) instead of just producing a
    hard failure sooner."""
    mocker.patch("tools.settings.load_settings", return_value={})

    assert file_search_ps_bridge_timeout_seconds() == 30


def test_ps_bridge_timeout_seconds_returns_configured_value(mocker):
    mocker.patch(
        "tools.settings.load_settings",
        return_value={"file_search_ps_bridge_timeout_seconds": 30},
    )

    assert file_search_ps_bridge_timeout_seconds() == 30


# ---------------------------------------------------------------------------
# search-result-caps: resolve_search_limit() — shared limit
# default/clamp/reject helper for mail_search/calendar_search/task_search
# (BUG-002). See design.md's "limit default/max as config" decision:
# search_default_limit (50) / search_max_limit (200) read live via
# load_settings(), never cached — mirrors local_timezone()'s discipline.
# ---------------------------------------------------------------------------


def test_resolve_search_limit_defaults_to_50_when_limit_none_and_unconfigured(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})

    assert resolve_search_limit(None) == 50


def test_resolve_search_limit_reads_configured_default_when_limit_none(mocker):
    mocker.patch(
        "tools.settings.load_settings",
        return_value={"search_default_limit": 25},
    )

    assert resolve_search_limit(None) == 25


def test_resolve_search_limit_returns_given_value_unchanged_when_under_max(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})

    assert resolve_search_limit(120) == 120


def test_resolve_search_limit_clamps_to_200_when_over_hard_max_and_unconfigured(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})

    assert resolve_search_limit(10000) == 200


def test_resolve_search_limit_clamps_to_configured_max(mocker):
    mocker.patch(
        "tools.settings.load_settings",
        return_value={"search_max_limit": 75},
    )

    assert resolve_search_limit(1000) == 75


def test_resolve_search_limit_rejects_zero(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})

    with pytest.raises(ValueError):
        resolve_search_limit(0)


def test_resolve_search_limit_rejects_negative(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})

    with pytest.raises(ValueError):
        resolve_search_limit(-5)


def test_resolve_search_limit_configured_default_used_when_limit_omitted_and_over_max(mocker):
    """Triangulation: a configured `search_default_limit` that itself
    exceeds `search_max_limit` is not this helper's concern to reconcile —
    both are read independently. This test exercises reading both keys
    together from the same settings dict, distinct from the single-key
    tests above."""
    mocker.patch(
        "tools.settings.load_settings",
        return_value={"search_default_limit": 25, "search_max_limit": 75},
    )

    assert resolve_search_limit(None) == 25
    assert resolve_search_limit(1000) == 75


# ---------------------------------------------------------------------------
# add-onenote-adapter: onenote_writable_notebooks() / onenote_search_max_results()
# / onenote_ps_bridge_timeout_seconds()
# ---------------------------------------------------------------------------


def test_onenote_writable_notebooks_defaults_to_test_notebook_when_unconfigured(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})

    assert onenote_writable_notebooks() == ["z - Test Notebook"]


def test_onenote_writable_notebooks_reads_configured_list(mocker):
    mocker.patch(
        "tools.settings.load_settings",
        return_value={"onenote_writable_notebooks": ["z - Test Notebook", "Sandbox"]},
    )

    assert onenote_writable_notebooks() == ["z - Test Notebook", "Sandbox"]


def test_onenote_search_max_results_defaults_to_50_when_limit_none_and_unconfigured(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})

    assert onenote_search_max_results(None) == 50


def test_onenote_search_max_results_reads_configured_default_when_limit_none(mocker):
    mocker.patch(
        "tools.settings.load_settings",
        return_value={"onenote_search_max_results": 25},
    )

    assert onenote_search_max_results(None) == 25


def test_onenote_search_max_results_clamps_to_200_when_over_hard_max(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})

    assert onenote_search_max_results(10000) == 200


def test_onenote_search_max_results_returns_given_value_unchanged_when_under_max(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})

    assert onenote_search_max_results(120) == 120


def test_onenote_search_max_results_rejects_zero(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})

    with pytest.raises(ValueError):
        onenote_search_max_results(0)


def test_onenote_search_max_results_rejects_negative(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})

    with pytest.raises(ValueError):
        onenote_search_max_results(-5)


def test_onenote_ps_bridge_timeout_seconds_defaults_to_20_when_unconfigured(mocker):
    mocker.patch("tools.settings.load_settings", return_value={})

    assert onenote_ps_bridge_timeout_seconds() == 20


def test_onenote_ps_bridge_timeout_seconds_returns_configured_value(mocker):
    mocker.patch(
        "tools.settings.load_settings",
        return_value={"onenote_ps_bridge_timeout_seconds": 45},
    )

    assert onenote_ps_bridge_timeout_seconds() == 45


# ---------------------------------------------------------------------------
# selective-tool-deployment Phase 3: installed_tools() — reads
# `config/installed-tools.yaml` (shape-restricted: only its `tools:` flat
# list is meaningful), NOT `config/settings.yaml` — a separate loader,
# `_load_installed_tools_yaml()`, is mocked here rather than
# `load_settings()`, mirroring that function's own mock-the-loader
# convention above.
#
# Absent file -> None (sentinel for "everything" — exact back-compat with
# pre-selective-deploy behavior, since server.py/smoke_test.py treat a
# None/absent config as "register/expect every catalog tool"). Empty
# `tools:` -> set() (nothing enabled). Populated -> the exact name set.
# Any top-level YAML keys other than `tools:` are ignored — the file's
# shape is restricted to exactly that one flat list per design.md's
# Decision 4.
# ---------------------------------------------------------------------------


def test_installed_tools_returns_none_when_file_absent(mocker):
    mocker.patch("tools.settings._load_installed_tools_yaml", return_value=None)

    assert installed_tools() is None


def test_installed_tools_returns_empty_set_for_empty_tools_list(mocker):
    mocker.patch(
        "tools.settings._load_installed_tools_yaml",
        return_value={"tools": []},
    )

    assert installed_tools() == set()


def test_installed_tools_returns_exact_name_set_when_populated(mocker):
    mocker.patch(
        "tools.settings._load_installed_tools_yaml",
        return_value={"tools": ["calendar_search", "mail_search"]},
    )

    assert installed_tools() == {"calendar_search", "mail_search"}


def test_installed_tools_ignores_unknown_top_level_keys(mocker):
    """Triangulation: a file whose shape carries an extra, unrecognized
    top-level key alongside `tools:` must still resolve correctly — only
    `tools:` is read, per the shape-restricted-flat-YAML design decision."""
    mocker.patch(
        "tools.settings._load_installed_tools_yaml",
        return_value={"tools": ["file_search"], "generated_by": "install.ps1"},
    )

    assert installed_tools() == {"file_search"}


# ---------------------------------------------------------------------------
# hard-tool-exclusion: shipped_tools() -- reads `tools/shipped-tools.json`
# (make-deploy-package.sh's family-nested manifest generator: `{build_mode,
# families: [{name, tools: [{name, maturity, default_enabled}]}]}`), next
# to this module -- the deployed location. `None` when absent (legacy
# package predating hard-tool-exclusion -> no ceiling, mirrors
# `installed_tools()`'s own absent-file/`None` convention). Otherwise the
# flat set of every tool NAME literally listed across every family's
# `tools[]`, regardless of each entry's own `default_enabled` flag --
# presence in the manifest is the hard ceiling (design.md Decision 2), not
# whether the build pre-selected it as default-enabled.
#
# Mirrors installed_tools()'s split: a private loader
# (`_load_shipped_tools_json()`) is mocked for the shape-parsing tests
# below; a couple of tmp-path tests exercise the loader's own real-
# filesystem/JSON-parsing path via the `_SHIPPED_TOOLS_PATH` module
# constant, the way `_INSTALLED_TOOLS_PATH` is never mocked directly but
# its consuming loader is testable via monkeypatching the path constant.
# ---------------------------------------------------------------------------


def test_shipped_tools_returns_none_when_file_absent(mocker):
    mocker.patch("tools.settings._load_shipped_tools_json", return_value=None)

    assert shipped_tools() is None


def test_shipped_tools_returns_every_name_from_a_full_manifest(mocker):
    mocker.patch(
        "tools.settings._load_shipped_tools_json",
        return_value={
            "build_mode": "full",
            "families": [
                {
                    "name": "calendar",
                    "tools": [
                        {"name": "calendar_search", "maturity": "alpha", "default_enabled": True},
                        {"name": "calendar_get_event", "maturity": "alpha", "default_enabled": True},
                        {"name": "calendar_get_notes", "maturity": "alpha", "default_enabled": True},
                    ],
                },
                {
                    "name": "onenote",
                    "tools": [
                        {"name": "onenote_search", "maturity": "beta", "default_enabled": True},
                        {"name": "onenote_get_page", "maturity": "beta", "default_enabled": True},
                    ],
                },
            ],
        },
    )

    assert shipped_tools() == {
        "calendar_search",
        "calendar_get_event",
        "calendar_get_notes",
        "onenote_search",
        "onenote_get_page",
    }


def test_shipped_tools_returns_exact_subset_regardless_of_default_enabled_flag(mocker):
    """Triangulation: membership in the manifest is the ceiling, not the
    per-tool `default_enabled` flag -- an entry present but
    `default_enabled: False` still counts as shipped."""
    mocker.patch(
        "tools.settings._load_shipped_tools_json",
        return_value={
            "build_mode": "share",
            "families": [
                {
                    "name": "onenote",
                    "tools": [
                        {"name": "onenote_search", "maturity": "beta", "default_enabled": True},
                        {"name": "onenote_get_page", "maturity": "beta", "default_enabled": False},
                    ],
                },
            ],
        },
    )

    assert shipped_tools() == {"onenote_search", "onenote_get_page"}


def test_shipped_tools_reads_real_json_file_via_tmp_path(tmp_path, mocker):
    manifest_path = tmp_path / "shipped-tools.json"
    manifest_path.write_text(
        json.dumps(
            {
                "build_mode": "full",
                "families": [
                    {
                        "name": "task",
                        "tools": [
                            {"name": "task_search", "maturity": "alpha", "default_enabled": True},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    mocker.patch("tools.settings._SHIPPED_TOOLS_PATH", manifest_path)

    assert shipped_tools() == {"task_search"}


def test_shipped_tools_returns_none_when_real_file_absent_via_tmp_path(tmp_path, mocker):
    mocker.patch("tools.settings._SHIPPED_TOOLS_PATH", tmp_path / "does-not-exist.json")

    assert shipped_tools() is None


def test_shipped_tools_raises_on_malformed_json(tmp_path, mocker):
    """Malformed-manifest choice (documented per design.md's Decision 2):
    a corrupt `shipped-tools.json` is NOT silently treated as "absent" (no
    ceiling) -- that would defeat hard exclusion's entire purpose by
    falling back to "everything allowed" on a broken build artifact.
    Invalid JSON syntax propagates as a real `json.JSONDecodeError`."""
    manifest_path = tmp_path / "shipped-tools.json"
    manifest_path.write_text("{not valid json", encoding="utf-8")
    mocker.patch("tools.settings._SHIPPED_TOOLS_PATH", manifest_path)

    with pytest.raises(json.JSONDecodeError):
        shipped_tools()
