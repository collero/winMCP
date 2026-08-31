"""RED/GREEN tests for `tools/catalog.py` — the parser/accessors for
`tools/catalog.yaml` (selective-tool-deployment change, tool-catalog
spec's "Catalog Structure", "Maturity Drives the Share Build's
Pre-Selection Only, Never a Hard Exclusion", "Loadable Without Windows or
COM", and "Consistent Family Grouping" requirements).

Covers: WSL2-safe parsing (`win32com` is not installed in this venv, so
any accidental import surfaces as a real `ModuleNotFoundError` here, not
a mocked assertion), exact name-set consistency against `server.py`'s
registered `@app.tool` names (the runtime counterpart to Gate 7's
build-time check), a tool's bridge dependency, family grouping, and
`share_preselection()`'s maturity-driven default selection.
"""
import re
from pathlib import Path

from tools.catalog import excluded_files, families, load_catalog, share_preselection

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "tools" / "catalog.yaml"
_SERVER_PATH = Path(__file__).resolve().parent.parent / "server.py"

_ONENOTE_TOOLS = (
    "onenote_search",
    "onenote_get_page",
    "onenote_list_sections",
    "onenote_create_page",
    "onenote_update_page",
)
_ALPHA_TOOLS = ("calendar_search", "task_search", "mail_search", "file_search")


def _server_tool_names() -> list[str]:
    """Every `@app.tool(name="...")` name declared in `server.py`, in file
    order — the ground truth `catalog.yaml` must match exactly (name,
    count, no extras/omissions)."""
    source = _SERVER_PATH.read_text(encoding="utf-8")
    return re.findall(r'@app\.tool\(name="([^"]+)"\)', source)


def test_load_catalog_parses_on_wsl2_without_win32com():
    catalog = load_catalog(_CATALOG_PATH)

    assert isinstance(catalog, list)
    assert len(catalog) == 15


def test_load_catalog_matches_server_py_tool_names_exactly():
    catalog = load_catalog(_CATALOG_PATH)
    catalog_names = [entry["name"] for entry in catalog]
    server_names = _server_tool_names()

    assert len(server_names) == 15
    assert sorted(catalog_names) == sorted(server_names)
    assert len(catalog_names) == len(set(catalog_names))


def test_onenote_search_declares_its_bridge_dependency():
    catalog = load_catalog(_CATALOG_PATH)
    entry = next(e for e in catalog if e["name"] == "onenote_search")

    assert "tools/onenote_adapter.py" in entry["deps"]["modules"]
    assert "tools/ps_bridge_onenote.ps1" in entry["deps"]["ps1"]


def test_calendar_search_declares_outlook_adapter_dependency_no_bridge():
    """Triangulates the deps scenario with a non-bridge tool: a calendar
    tool depends on the Outlook adapter module but has no `.ps1` bridge
    dependency at all."""
    catalog = load_catalog(_CATALOG_PATH)
    entry = next(e for e in catalog if e["name"] == "calendar_search")

    assert "tools/outlook_adapter.py" in entry["deps"]["modules"]
    assert entry["deps"]["ps1"] == []


def test_families_groups_tools_by_consistent_family_string():
    catalog = load_catalog(_CATALOG_PATH)
    grouped = families(catalog)

    assert grouped["onenote"] == list(_ONENOTE_TOOLS)
    assert grouped["calendar"] == ["calendar_search", "calendar_get_event", "calendar_get_notes"]
    # Every entry's family value must be one of families()'s keys, spelled
    # identically (no casing/spacing variant slipping through).
    entry_families = {entry["family"] for entry in catalog}
    assert entry_families == set(grouped.keys())


def test_share_preselection_selects_beta_leaves_alpha_unselected_but_present():
    catalog = load_catalog(_CATALOG_PATH)
    preselected = share_preselection(catalog)
    catalog_names = {entry["name"] for entry in catalog}

    assert set(_ONENOTE_TOOLS) <= preselected
    assert not (set(_ALPHA_TOOLS) & preselected)
    # Alpha tools are unselected but still present in the full catalog.
    assert set(_ALPHA_TOOLS) <= catalog_names


def test_share_preselection_also_selects_a_synthetic_stable_tool(tmp_path):
    """Triangulates maturity handling beyond the real catalog's
    beta/alpha split — a synthetic `stable` entry must default
    pre-selected too, proving `share_preselection()` branches on the
    `maturity` value itself (beta OR stable), not on tool identity."""
    synthetic = tmp_path / "synthetic_catalog.yaml"
    synthetic.write_text(
        """
families:
  - name: demo
    tools:
      - name: demo_alpha_tool
        maturity: alpha
        deps: {modules: [], ps1: [], config_keys: []}
      - name: demo_stable_tool
        maturity: stable
        deps: {modules: [], ps1: [], config_keys: []}
""".strip(),
        encoding="utf-8",
    )

    catalog = load_catalog(synthetic)
    preselected = share_preselection(catalog)

    assert preselected == {"demo_stable_tool"}


# ---------------------------------------------------------------------------
# hard-tool-exclusion: excluded_files() -- owner-set based file exclusion
# for a share build's staging step (design.md Decision 3, hard-tool-
# exclusion spec's "Dependency File's Retention Is Owner-Set Based"
# requirement). `tools/ps_bridge_transport.py` is the real catalog's own
# cross-family shared file (declared by both the `onenote` and `file`
# families since the 2026-08-28 data fix) -- used below to triangulate
# the owner-set union behavior without a synthetic catalog.
# ---------------------------------------------------------------------------


def _all_tool_names(catalog):
    return {entry["name"] for entry in catalog}


def test_excluded_files_drops_a_zero_selected_familys_modules_and_bridge():
    catalog = load_catalog(_CATALOG_PATH)
    selected = _all_tool_names(catalog) - set(_ONENOTE_TOOLS)

    excluded = excluded_files(catalog, selected)

    assert "tools/onenote.py" in excluded
    assert "tools/onenote_adapter.py" in excluded
    assert "tools/ps_bridge_onenote.ps1" in excluded


def test_excluded_files_cross_family_shared_file_survives_either_family_selected():
    catalog = load_catalog(_CATALOG_PATH)
    # Only one onenote tool selected; the whole file family is unselected.
    selected = {"onenote_search"}

    excluded = excluded_files(catalog, selected)

    assert "tools/ps_bridge_transport.py" not in excluded
    # file-only deps ARE excluded since no file tool is selected.
    assert "tools/file_search.py" in excluded
    assert "tools/ps_bridge_search.ps1" in excluded


def test_excluded_files_shared_file_excluded_when_both_owning_families_unselected():
    catalog = load_catalog(_CATALOG_PATH)
    selected = _all_tool_names(catalog) - set(_ONENOTE_TOOLS) - {"file_search", "file_get_info"}

    excluded = excluded_files(catalog, selected)

    assert "tools/ps_bridge_transport.py" in excluded


def test_excluded_files_empty_selection_excludes_every_declared_dep_file():
    catalog = load_catalog(_CATALOG_PATH)

    excluded = excluded_files(catalog, set())

    all_declared = {f for e in catalog for f in e["deps"]["modules"] + e["deps"]["ps1"]}
    assert excluded == all_declared
    assert "tools/ps_bridge_transport.py" in excluded


def test_excluded_files_unknown_names_in_selected_have_no_retention_effect():
    catalog = load_catalog(_CATALOG_PATH)

    excluded_with_garbage = excluded_files(catalog, {"not_a_real_tool_name"})
    excluded_empty = excluded_files(catalog, set())

    assert excluded_with_garbage == excluded_empty


def test_excluded_files_full_selection_excludes_nothing():
    catalog = load_catalog(_CATALOG_PATH)

    excluded = excluded_files(catalog, _all_tool_names(catalog))

    assert excluded == set()
