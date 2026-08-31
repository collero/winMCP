# Design: Selective Tool Deployment

## Technical Approach

`tools/catalog.yaml` is the source of truth (family, tool, maturity, deps),
**never read at runtime** — it drives two derived artifacts:
`tools/shipped-tools.json` (built by `make-deploy-package.sh`, read by
`install.ps1`) and `config/installed-tools.yaml` (written by `install.ps1`,
read by `server.py`/`smoke_test.py`). `server.py`'s static imports stay
unchanged; only `@app.tool` registration is gated (Decision 2).

Two build modes: **full** (no flags — today's behavior, all tools; the
only mode `deploy-qa.sh`/`promote-pro.sh` invoke) and **share**
(`--share`), curating a *default selection* for distribution — seeded
from maturity, decided by the human running the build ("last word is
mine"). Both stage identical files (shipped-but-disabled); they differ
only in `shipped-tools.json`'s `default_enabled` flags, which the
installer trusts as-is — no installer-side maturity logic at all.

## Architecture Decisions

| # | Decision | Choice | Rejected | Rationale |
|---|---|---|---|---|
| 1 | catalog schema | `families:[{name, tools:[{name, maturity}], deps:{modules, ps1, config_keys}}]`. `tool.name` == `server.py` name (test-enforced). Assignment: onenote (4 tools) = `beta`; calendar/tasks/mail/files (9 tools) = `alpha` | Flat per-tool list | Family is the UI grouping unit at both prompts |
| 2 | Build-time selection | Shipped-but-disabled, both modes (files never omitted). Full: `default_enabled=true` for all. Share: seeded from maturity, then a bash `read -p` prompt overrides before writing the manifest. Non-TTY `--share` needs `--tools=a,b` (catalog-validated) or FAILS LOUDLY | Physically omit tools; non-TTY `--share` silently defaults to maturity | Same import-breakage risk otherwise. "Last word is mine" needs a human or an explicit list, not an unattended guess |
| 3 | Install UX (PS 5.1, ASCII) | Maturity-agnostic — reads only `default_enabled` (built at build time) + `maturity` for display. `-Preset <json>` > `IsInputRedirected` (no TTY) -> apply `default_enabled` as-is > interactive per-family Y/n seeded from it | Recomputing maturity defaults in `install.ps1` | Full installs everything unattended, share installs its curated set unattended — zero installer branching on build mode |
| 4 | `installed-tools.yaml` | `config/installed-tools.yaml`, installed tree, from `install.ps1`; one flat list under `tools:`. Absent->all; empty->none; unknown names ignored | JSON, despite recording tool state | Real YAML for `settings.py`; `smoke_test.py` regex-parses the same file, no `yaml` import (#6) |
| 5 | `server.py` registration | `create_server(..., installed: set[str]\|None=None)`; each `@app.tool` block wrapped `if _tool_enabled("x"):` | Name->function registrar table | Minimal diff over 13 blocks; the coded blocks are the "all tools" ground truth |
| 6 | `smoke_test.py` derivation | `EXPECTED_TOOLS` = regex-scraped from `installed-tools.yaml`, else hardcoded `_DEFAULT_ALL_TOOLS`. `FAMILIES` hand-authored; skips a family not in `EXPECTED_TOOLS` as `"skipped"` (verdict-neutral) | Vendoring a YAML parser | stdlib-only; auto-generated `FAMILIES` would wrongly script live tests for `onenote`, excluded today |
| 7 | Test strategy | New/updated pytest per row below. Gate 7 and build-mode/`--tools=` paths stay shell-only | pytest driving the bash script | Gate logic already bash+inline-python; a pytest wrapper adds no unit value |
| 8 | Maturity assignment | Only in `catalog.yaml`: onenote=`beta`, rest=`alpha` (sharing-readiness, not code quality). Seeds `--share`'s default only; full build ignores it; installer never re-derives it | Maturity gating the full build too | Would silently change QA/PRO's installed set on a maturity edit — breaks "identical to today" |

## Data Flow / Sequence (build -> install -> serve -> verify)

```
catalog.yaml --(build: full=all-true | share=maturity-seeded+builder's-last-word)--> shipped-tools.json
shipped-tools.json --(install.ps1: -Preset | IsInputRedirected->defaults | prompt)--> installed-tools.yaml
installed-tools.yaml --(settings.py)--> create_server(installed=None) --> gate --> registered tools
installed-tools.yaml --(smoke_test.py regex)--> EXPECTED_TOOLS/FAMILIES --> pass/warn/fail/skipped
```

## File Changes

| File | Action | Notes |
|---|---|---|
| `tools/catalog.yaml` | Create | source of truth |
| `make-deploy-package.sh` | Modify | `--share`/`--tools=`, two-mode `default_enabled`, emits `shipped-tools.json`; Gate 7 |
| `deploy/install.ps1` | Modify | reads `default_enabled`/`maturity`; `-Preset`, `IsInputRedirected` branch, prompts, writes `installed-tools.yaml` |
| `deploy/install.bat` | Modify | forward `%*` (for `-Preset`) |
| `tools/settings.py` | Modify | add `installed_tools() -> set[str] \| None` |
| `server.py` | Modify | `installed=` param, per-tool `_tool_enabled` gates |
| `deploy/smoke_test.py` | Modify | `_read_installed_tools()`, family-skip, `"skipped"` verdict |
| `tests/test_catalog.py` | Create | schema + name-consistency |
| `test_settings.py`, `test_server.py`, `test_smoke_test.py` | Modify | new cases; all-13 kept via `installed=None`/absent-file path |
| `deploy-qa.sh`, `promote-pro.sh` | Unmodified | `< /dev/null` already triggers "install all" |
| `README.md` | Modify | catalog, `--share`/`--tools=`, `-Preset` |

## Testing Strategy

| Layer | What | Approach |
|---|---|---|
| Unit | catalog parsing, name consistency | `test_catalog.py` |
| Unit | `installed_tools()` absent/empty/present | `test_settings.py`, tmp path |
| Unit | registration gating, all-13 back-compat | `test_server.py`, `create_server(installed=...)` |
| Unit | `_read_installed_tools`, skip verdicts | `test_smoke_test.py`, stub server |
| Gate (shell) | name equality: catalog/manifest/server.py | Gate 7 |
| Manual | interactive drill-down, both modes | QA `test.bat` |

Full `pytest -q` still runs on the whole repo regardless of selection.

## Migration / Rollout

Additive, config-gated: no flags + no `installed-tools.yaml` -> today's
behavior end to end. Rollback = delete `catalog.yaml`, revert the
modified files. No data migration.

## Open Questions

None — onenote's maturity split (beta) vs. everything else (alpha) is
resolved by the user (Decision 8), encoded in `tools/catalog.yaml`.
