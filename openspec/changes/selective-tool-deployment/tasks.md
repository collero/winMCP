# Tasks: Selective Tool Deployment

## Phase 1: Catalog (Foundation)

- [x] 1.1 CREATE `tools/catalog.yaml`: 13 tools, families (calendar, task, mail, file, onenote); `maturity`: onenote's 4 tools=`beta`, the other 9 (calendar/task/mail/file)=`alpha`; `deps` per tool incl. `tools/ps_bridge_onenote.ps1` for both onenote bridge tools
- [x] 1.2 RED `tests/test_catalog.py`: parses on WSL2, no win32com import; every `server.py` `@app.tool` name appears exactly once; family strings identical across entries; `share_preselection()` pre-selects beta/stable, leaves alpha unselected but present
- [x] 1.3 GREEN `tools/catalog.py`: `load_catalog(path) -> list[dict]`, `share_preselection(catalog) -> set[str]`, `families(catalog) -> dict[str, list[str]]`

## Phase 2: Build-Time Selection (`make-deploy-package.sh`) — Two Modes

- [x] 2.1 MODIFY: default mode (no flags) — stage all 13 tools unconditionally, regardless of maturity; identical file selection to today's pipeline
- [x] 2.2 MODIFY: add `--share` flag — interactive family→tool prompt (bash `read -p`) seeded by `share_preselection()` (beta/stable pre-checked, alpha unchecked); builder's picks always win over maturity, either direction
- [x] 2.3 MODIFY: add `--tools=a,b` explicit override (catalog-name-validated); non-TTY `--share` with `--tools=` stages exactly that list, no prompt; non-TTY `--share` without `--tools=` FAILS LOUDLY, produces no package
- [x] 2.4 MODIFY: emit `tools/shipped-tools.json` with per-tool `default_enabled` — default build: `true` for all 13; share build: mirrors the final selection exactly (never a blanket flag)
- [x] 2.5 ADD Gate 7: name-set equality between `shipped-tools.json` and staged tool files' declared catalog `deps` — fail build if a shipped tool's dep is missing, or a manifest name is absent from the catalog
- [x] 2.6 VERIFY manually: default run stages all 13 incl. alpha; `--share` with no override pre-selects onenote's 4 beta tools only; `--share --tools=x,y` overrides regardless of maturity; non-TTY `--share` with no `--tools=` exits non-zero, no zip written; Gates 1-6 unaffected by mode

## Phase 3: `settings.py` — installed_tools() accessor

- [x] 3.1 RED `tests/test_settings.py`: `installed_tools()` returns `None` when `config/installed-tools.yaml` absent, `set()` for empty `tools:`, exact name set when populated, ignores unknown names
- [x] 3.2 GREEN `tools/settings.py`: add `installed_tools() -> set[str] | None` reading the flat `tools:` list

## Phase 4: `server.py` — registration gating

- [x] 4.1 RED `tests/test_server.py`: parametrize `create_server(installed=...)` over `None` (all 13, back-compat), a 2-tool set (only those registered), empty set (0 registered)
- [x] 4.2 GREEN `server.py`: `create_server(..., installed: set[str] | None = None)`; wrap each of 13 `@app.tool` blocks with `if _tool_enabled(name, installed):`; prod call resolves via `settings.installed_tools()`
- [x] 4.3 RED `tests/test_server.py`: importing `server` succeeds regardless of `installed_tools()` value, narrowed or absent config
- [x] 4.4 VERIFY 4.3 passes with no conditional imports added (shipped-but-disabled preserved)

## Phase 5: `deploy/smoke_test.py` — derived EXPECTED_TOOLS

- [x] 5.1 RED `tests/test_smoke_test.py`: `_read_installed_tools(path)` regex-scrapes `- (\w+)` lines, returns `None` if absent; `EXPECTED_TOOLS` narrows when present, else falls back to hardcoded `_DEFAULT_ALL_TOOLS` (13 names)
- [x] 5.2 GREEN `deploy/smoke_test.py`: add `_read_installed_tools()` (stdlib `re`, no `yaml`), `_DEFAULT_ALL_TOOLS`; wire into `EXPECTED_TOOLS` and `tools/list` validation (missing tool fails naming it, extras only noted)
- [x] 5.3 RED `tests/test_smoke_test.py`: `run_family()`/`run_files_family()` skip a zero-enabled family with verdict `"skipped"` (verdict-neutral); all families run when config absent
- [x] 5.4 GREEN `deploy/smoke_test.py`: filter `FAMILIES` (unchanged) against `EXPECTED_TOOLS`; emit `"skipped"` for a fully-disabled family

## Phase 6: Install-Time Selection (`install.ps1` / `install.bat`) — Maturity-Agnostic

- [x] 6.1 MODIFY `deploy/install.ps1`: read `tools/shipped-tools.json` from the staged package; trust only each tool's `default_enabled` flag (never recompute from `maturity` — display only); add `-Preset <json>` param
- [x] 6.2 MODIFY `deploy/install.ps1`: branch on `[Console]::IsInputRedirected` — non-interactive (no `-Preset`, redirected/no TTY) enables exactly the manifest's `default_enabled=true` set, no prompt, never blocks (priority: `-Preset` > redirected-defaults > interactive)
- [x] 6.3 MODIFY `deploy/install.ps1`: interactive branch — per-family Y/n (default Y) scoped to manifest families; each tool pre-checked per its `default_enabled` flag; per-family "all" shortcut plus per-tool toggles, unrestricted operator override
- [x] 6.4 MODIFY `deploy/install.ps1`: write `config/installed-tools.yaml` (flat `tools:` list) on completion, across `-Preset`, non-interactive, and interactive paths
- [x] 6.5 MODIFY `deploy/install.bat`: forward `%*` so `-Preset` and other flags reach `install.ps1`
- [x] 6.6 VERIFY modified `install.ps1` stays pure ASCII and PS 5.1-parseable (re-run Gates 4/5)

## Phase 7: QA/PRO Unattended Path

- [x] 7.1 VERIFY (no code change): `deploy-qa.sh`/`promote-pro.sh` remain byte-for-byte unmodified; confirm they invoke the default (no `--share`) build mode and their `< /dev/null` redirection into `install.bat` is untouched
- [x] 7.2 VERIFY manually: `install.ps1` with stdin from `/dev/null` against a default-build `shipped-tools.json` (all `default_enabled=true`) completes without blocking; `config/installed-tools.yaml` lists all shipped tools

## Phase 8: Full Suite, Docs

- [x] 8.1 Run `source .venv/bin/activate && python3.12 -m pytest -q`: full repo suite green (selection never subsets which tests run)
- [x] 8.2 MODIFY `README.md`: document `tools/catalog.yaml`, default vs `--share` build modes, `--tools=`, non-TTY `--share` failure behavior, `default_enabled` manifest semantics, `install.ps1 -Preset`, family/tool prompt, `config/installed-tools.yaml`, back-compat (absent file = all tools)

## Phase 9: Manual Verification (Windows host, not CI)

- [ ] 9.1 **[MANUAL]** Build with `--share`, install at an interactive console: onenote's 4 tools arrive pre-checked, the 9 alpha tools unchecked; drill down and override — check one alpha tool, uncheck one onenote tool; confirm the resulting `installed-tools.yaml` matches the override, not the maturity seed
- [ ] 9.2 **[MANUAL]** Build with `--share` and no TTY, no `--tools=`: confirm the build fails loudly and produces no package
- [ ] 9.3 **[MANUAL]** Build with `--share --tools=a,b` and no TTY: confirm it succeeds unattended, staging exactly the named tools, `shipped-tools.json` marks exactly those `default_enabled=true`
- [ ] 9.4 **[MANUAL]** Run `deploy-qa.sh` end-to-end unmodified against a default build: no stdin block; installed copy's `installed-tools.yaml` lists all 13 tools, unchanged from pre-change behavior
- [ ] 9.5 **[MANUAL]** Install a `--share` subset (e.g. onenote only) then run `deploy/smoke_test.py` against it: live checks run only for onenote, other families report `"skipped"`, overall verdict unaffected

## Phase 10: Share-Flow UX Refinements (Batch 6 addendum, user-requested during Phase 9)

- [x] 10.1 FIX defect found during review: share builds write to `dist/share/WinMCP-share-<STAMP>-<HHMMSS>.zip` instead of the same `dist/WinMCP-<STAMP>.zip` full builds use, so a share build can never overwrite or be auto-picked-up by `deploy-qa.sh`/`promote-pro.sh`'s `dist/WinMCP-*.zip` glob (verified by inspection, no edits to those two scripts); full-build naming/location unchanged
- [x] 10.2 MODIFY: ending report names the exact package path prominently in share mode, and "Next steps" step 1 names the file (`Copy <filename> to the target machine`) instead of the generic "Copy the zip"
- [x] 10.3 MODIFY: share INTERACTIVE mode (TTY, no `--tools=`) offers a post-report copy prompt - default destination `/mnt/c/usr/tmp` (created if missing), an alternate directory may be typed; on copy, prints both the `/mnt/c/...` path and the equivalent Windows path (`C:\...`); declining exits as before. Non-TTY share (`--tools=`) never prompts.
- [x] 10.4 ADD: `whiptail --checklist` TUI for the interactive tool picker when whiptail is on PATH and stdin is a TTY - one row per tool prefixed `[family]`, pre-checked from `share_preselection()`, maturity shown in the item description; Cancel aborts the build cleanly (nonzero exit, no zip). Plain `y`/`n` read-loop kept as automatic fallback when whiptail is absent, and forced via new `--no-tui` flag. Non-TTY contracts (`--tools=` list, fail-loudly without it) untouched.
- [ ] 10.5 **[MANUAL]** Walk the whiptail checklist on a real TTY (pre-checks match maturity seed, toggle + confirm applies the override, Cancel aborts with no zip written) and exercise the interactive copy offer end-to-end (default dest, a typed alternate dest, and Decline) - could not be exercised non-TTY in this environment; traced by hand against the whiptail syntax (`whiptail --help`) and a standalone parse-logic dry run instead
