# Design: Hard Tool Exclusion

## Technical Approach

`selective-tool-deployment` (unarchived; this change builds directly on
its shipped code) gates *default-enablement* only — every tool's files
always ship. This change makes the **share build's existing picker also
control physical presence and enableability**, resolving the proposal's
DECISION FORK with neither Model A nor B verbatim but a tool-granular
hybrid: **presence in `tools/shipped-tools.json` is the single hard
ceiling** — checked = shipped + `default_enabled=true`; unchecked = absent
from the manifest, and therefore un-enableable, whether or not its family
still ships code for a sibling tool. No `catalog.yaml` schema change is
needed — exclusion is *derived* from the selection already made at build
time, not separately declared.

## Architecture Decisions

| # | Problem | Choice | Rejected | Rationale |
|---|---|---|---|---|
| 1 | Import safety | `importlib.util.find_spec("tools.X")` presence check per family, guarding the existing column-0 `from tools.X import ...` block; the real `import` runs unguarded once presence is confirmed | Blind `except ImportError` (masks a genuine bug inside a present module as "absent"); build-time code stripping (fragile, untestable) | `find_spec` only asks "is the module discoverable", never executes it — a `SyntaxError`/`NameError` inside a present module still propagates. Monkeypatching `importlib.util.find_spec` is the Linux test seam |
| 2 | Registration allowlist | `settings.shipped_tools()` (new) returns the flat name set literally listed in `tools/shipped-tools.json`, or `None` if the file is absent (pre-selective-tool-deployment legacy package). `_tool_enabled(name)` in `server.py` now requires `name` in `shipped_tools() ∪ {ceiling absent}` **and** in `installed_tools() ∪ {installed absent}` | Re-deriving allowlist from `catalog.yaml` at runtime | `catalog.yaml` never ships (design precedent); the manifest is already staged and is the build's own record of what shipped |
| 3 | Build-side omission | File-granular, not family-granular: `tools/catalog.py::excluded_files(catalog, selected)` returns every declared dep file whose *entire* owner set (across all families) is outside `selected`. `make-deploy-package.sh --share` subtracts this set from `MANIFEST` before staging; `shipped-tools.json` share mode lists only selected tools, omitting any family with zero selections entirely | Family-level omission flag | Owner-set-based exclusion auto-generalizes to a file shared by two families (kept if either has a selected tool) with no special case |
| 4 | Installer | **No code change.** `install.ps1` already iterates `manifest.families`/`$fam.tools`; an omitted family/tool never renders, and `-Preset` naming a name absent from the manifest already fails with the existing "unknown tool name" error | New PS validation logic | The manifest-driven design already treats "absent from manifest" == "unknown", which is exactly the desired hard-fail |
| 5 | Wheels | No change | Per-family optional wheel sets | `pyproject.toml`'s deps are project-wide (pywin32, pyyaml, fastmcp); no family declares its own extra; Gate 6 is unaffected |
| 6 | Test strategy | Unit: `excluded_files()` (pure, no FS), `shipped_tools()` (tmp-path JSON), `_tool_enabled()` ceiling logic, import-guard via monkeypatched `find_spec`. Shell: build a `--tools=` share zip on WSL2, `unzip -l` asserts excluded deps absent + selected deps present, extend Gate 7 | pytest wrapper around bash | Matches predecessor's Decision 7 exactly |
| 7 | Sequencing | Predecessor stays unarchived; this change touches the same files (`server.py`, `make-deploy-package.sh`, `tools/catalog.py`, `tools/settings.py`) it shipped — apply must rebase on top of its landed code, not race it | Archiving first, blind | Avoids two batches editing the same `_tool_enabled` block from stale copies |

## Data Flow

```
Build:  catalog.yaml --load--> ALL_TOOL_NAMES --(picker: same as today)--> selected
        excluded_files(catalog, selected) --> MANIFEST -= excluded_files
        shipped-tools.json (share) = {families: [f for f in families if any tool in selected],
                                       tools: [t for t in f.tools if t in selected], default_enabled=true}
        Gate 7 (extended): unzip -l OUT | assert none of excluded_files present
                                          | assert every selected tool's deps present

Runtime: server.py import  --find_spec per family--> _FAMILY_PRESENT[fam]
         create_server()   --settings.shipped_tools() ∩ settings.installed_tools()--> _tool_enabled(name)
         _tool_enabled(name) = _FAMILY_PRESENT[family_of(name)]
                                and (shipped is None or name in shipped)
                                and (installed is None or name in installed)
```

## Interfaces / Contracts

```python
# tools/catalog.py
def excluded_files(catalog: list[dict], selected: set[str]) -> set[str]:
    owners: dict[str, set[str]] = {}
    for e in catalog:
        for f in e["deps"]["modules"] + e["deps"]["ps1"]:
            owners.setdefault(f, set()).add(e["name"])
    return {f for f, names in owners.items() if not (names & selected)}

# tools/settings.py
def shipped_tools() -> set[str] | None:
    """None = legacy package, no ceiling. Else exact manifest tool-name set."""

# server.py (per-family, repeated for calendar/task/mail/file/onenote)
_ONENOTE_PRESENT = all(importlib.util.find_spec(m) is not None
                        for m in ("tools.onenote", "tools.onenote_adapter"))
if _ONENOTE_PRESENT:
    from tools.onenote import onenote_create_page, onenote_get_page, onenote_search, onenote_update_page
else:
    onenote_create_page = onenote_get_page = onenote_search = onenote_update_page = None
```

## File Changes

| File | Action | Notes |
|---|---|---|
| `tools/catalog.py` | Modify | add `excluded_files()` |
| `tools/settings.py` | Modify | add `shipped_tools()`, reading `tools/shipped-tools.json` next to it |
| `server.py` | Modify | per-family `find_spec` guard + `_tool_enabled()` ceiling |
| `make-deploy-package.sh` | Modify | subtract `excluded_files()` from staged `MANIFEST` in share mode; manifest omits unselected tools/empty families; Gate 7 negative-assert |
| `deploy/install.ps1`, `deploy/smoke_test.py` | Unmodified | already correct (Decisions 4, out-of-scope) |
| `README.md` | Modify | document exclusion + explicit protection limits (readability, no signing/sandboxing) |

## Testing Strategy

| Layer | What | Approach |
|---|---|---|
| Unit | `excluded_files()`, `shipped_tools()`, `_tool_enabled()` ceiling, import guard | pytest, `find_spec` monkeypatch, tmp-path JSON |
| Shell | Manifest omission, Gate 7 negative check | build `--tools=` share zip, `unzip -l` |
| Manual | Recipient install/enable-attempt experience | Windows host, deferred (COM) |

## Migration / Rollout

Additive: full/default build's `selected == ALL_TOOL_NAMES`, so
`excluded_files()` returns `∅` and every guard/ceiling is a no-op —
byte-identical to pre-change output. Rollback = revert the four modified
files; no data migration.

## Open Questions

None — the DECISION FORK is resolved by the user's two-tier model above.
