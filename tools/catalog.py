"""Parser/accessors for `tools/catalog.yaml` — the single source of truth
enumerating every tool WinMCP ships (selective-tool-deployment change,
tool-catalog spec).

`tools/catalog.yaml` is never read at runtime by `server.py`/
`deploy/smoke_test.py` directly (design.md's "Technical Approach"); this
module is instead consumed by build-time tooling
(`make-deploy-package.sh`'s Phase 2 `--share` picker and Gate 7) that
still runs Python. Parsing is a plain PyYAML load with no `win32com`
dependency whatsoever, so it succeeds on this Linux dev/CI host exactly
as it will on the Windows build host (tool-catalog spec's "Loadable
Without Windows or COM" requirement).
"""
from pathlib import Path
from typing import Any

import yaml

#: Maturity values whose tools default to pre-selected in a `--share`
#: build's picker (tool-catalog spec's "Maturity Drives the Share Build's
#: Pre-Selection Only" requirement). `alpha` is deliberately absent —
#: alpha tools stay unselected by default but remain fully present and
#: selectable.
_SHARE_PRESELECTED_MATURITIES = frozenset({"beta", "stable"})


def load_catalog(path: str | Path) -> list[dict[str, Any]]:
    """Parse `tools/catalog.yaml` and flatten its `families[].tools[]`
    structure into one dict per tool: `name`, `family`, `maturity`,
    `deps` (the tool's own `{modules, ps1, config_keys}` dict, defaulting
    each key to `[]` when the YAML omits it).

    Returns entries in file order (family order, then tool order within
    each family) — callers relying on a stable order (e.g. `families()`,
    a build-time picker) get one for free.
    """
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    entries: list[dict[str, Any]] = []
    for family in raw.get("families", []):
        family_name = family["name"]
        for tool in family.get("tools", []):
            deps = tool.get("deps") or {}
            entries.append(
                {
                    "name": tool["name"],
                    "family": family_name,
                    "maturity": tool["maturity"],
                    "deps": {
                        "modules": deps.get("modules", []),
                        "ps1": deps.get("ps1", []),
                        "config_keys": deps.get("config_keys", []),
                    },
                }
            )
    return entries


def families(catalog: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Group a `load_catalog()` result by `family`, mapping each family
    name to its tool names in catalog order — the shape a family->tool
    hierarchical selection prompt (build-time `--share` picker,
    install-time `install.ps1` prompt) iterates directly."""
    grouped: dict[str, list[str]] = {}
    for entry in catalog:
        grouped.setdefault(entry["family"], []).append(entry["name"])
    return grouped


def share_preselection(catalog: list[dict[str, Any]]) -> set[str]:
    """Tool names that default to pre-selected in a `--share` build's
    picker: every tool whose `maturity` is `beta` or `stable`. Alpha
    tools are omitted from the returned set — unselected by default —
    but remain present in `catalog` itself and fully selectable; nothing
    here excludes a tool from the default/full build, which ignores
    maturity entirely (tool-catalog spec's "Maturity Drives the Share
    Build's Pre-Selection Only, Never a Hard Exclusion" requirement)."""
    return {entry["name"] for entry in catalog if entry["maturity"] in _SHARE_PRESELECTED_MATURITIES}


def excluded_files(catalog: list[dict[str, Any]], selected: set[str]) -> set[str]:
    """Which catalog-declared dependency files a `--share` build's staging
    step must OMIT for a given `selected` tool-name set — the build-side
    counterpart to `tools/settings.py::shipped_tools()`'s runtime ceiling
    (design.md Decision 3, hard-tool-exclusion spec's "Dependency File's
    Retention Is Owner-Set Based" requirement).

    Every `deps.modules`/`deps.ps1` file declared anywhere in `catalog` has
    an implicit *owner set*: every tool (of any family) whose entry
    declares it. A file is returned (excluded) iff its owner set has NO
    overlap with `selected` — every one of its owners is unselected. A
    file declared by at least one selected tool is always retained, even
    when other, unselected tools also declare it and even across family
    boundaries: a file shared by tools in two different families (e.g.
    `tools/ps_bridge_transport.py`, declared by both the `onenote` and
    `file` families) is retained if either family has a selected tool.

    A file that no catalog entry declares at all (shared infra like
    `models/schemas.py`, `settings.py`, `server.py`) never appears in the
    returned set — this function is scoped to catalog-declared deps only;
    `make-deploy-package.sh`'s MANIFEST array stages that shared infra
    unconditionally, independent of this function.
    """
    owners: dict[str, set[str]] = {}
    for entry in catalog:
        for f in entry["deps"]["modules"] + entry["deps"]["ps1"]:
            owners.setdefault(f, set()).add(entry["name"])
    return {f for f, names in owners.items() if not (names & selected)}
