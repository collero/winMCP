# Apply Progress: Selective Tool Deployment

## Batches

### Batch 1 (this batch) — Phase 1: Catalog (Foundation)

**Mode**: Strict TDD (RED-GREEN-REFACTOR), full repo suite kept green.

**Completed**:
- [x] 1.1 CREATE `tools/catalog.yaml`
- [x] 1.2 RED `tests/test_catalog.py`
- [x] 1.3 GREEN `tools/catalog.py`

**Files changed**:

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/catalog.yaml` | Created | 5 families (`calendar`, `task`, `mail`, `file`, `onenote`) covering all 13 `server.py` tool names. Per-tool `maturity`: onenote's 4 tools = `beta`; the other 9 (calendar/task/mail/file) = `alpha`, per the user's decision (design.md Decision 8). Per-tool `deps: {modules, ps1, config_keys}` — onenote tools declare `tools/ps_bridge_onenote.ps1` + `tools/ps_bridge_transport.py`; others declare their own module + adapter, `ps1: []`. |
| `tools/catalog.py` | Created | `load_catalog(path) -> list[dict]` (flattens `families[].tools[]` into one dict per tool: `name`, `family`, `maturity`, `deps`), `families(catalog) -> dict[str, list[str]]`, `share_preselection(catalog) -> set[str]` (beta/stable pre-selected; alpha present in the catalog but excluded from the returned set). |
| `tests/test_catalog.py` | Created | 7 tests, RED-first (confirmed `ModuleNotFoundError: No module named 'tools.catalog'` before implementation). Covers: WSL2 parse w/ no win32com import, exact name-set match against `server.py`'s 13 `@app.tool(name=...)` names (regex-scraped from source — the runtime counterpart to the build-time Gate 7 check), a tool's bridge deps (`onenote_search`) triangulated against a non-bridge tool (`calendar_search`), family grouping consistency, and `share_preselection()`'s maturity-driven selection triangulated with a synthetic `stable`-maturity entry (tmp_path fixture) to prove it branches on the `maturity` value itself, not on tool identity. |

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|--------------|----------|
| 1.1/1.2/1.3 | `tests/test_catalog.py` | Unit | N/A (new file) | ✅ Written — ran first, failed with `ModuleNotFoundError: No module named 'tools.catalog'` | ✅ Passed — 7/7 after `tools/catalog.py` implemented | ✅ 7 cases: parse+count, exact name-set match, bridge-dep tool + non-bridge-dep tool (2 cases), family grouping, real beta/alpha preselection, synthetic stable-maturity preselection | ➖ None needed — module was written clean on first GREEN pass; no dead code or duplication surfaced |

### Test Summary
- **Total tests written**: 7
- **Total tests passing**: 7 (all, in `tests/test_catalog.py`)
- **Layers used**: Unit (7), Integration (0), E2E (0)
- **Approval tests** (refactoring): None — no refactoring tasks, both files are new
- **Pure functions created**: 3 (`load_catalog`, `families`, `share_preselection` — all deterministic, no side effects beyond the file read in `load_catalog`)

**Full suite**: `source .venv/bin/activate && python3.12 -m pytest -q` → **681 passed** (674 pre-existing baseline + 7 new `test_catalog.py` tests; zero regressions).

**Deviations from design**: None. Design's terse schema notation
(`families:[{name, tools:[{name, maturity}], deps:{modules, ps1,
config_keys}}]`) was interpreted as `deps` living under each *tool*
entry (not the family) — required by the tool-catalog spec's own
scenario ("`onenote_search`'s catalog entry ... its `deps` list is
read"), which only makes sense per-tool since different tools in the
same family have different dependency sets (e.g. `file_get_info` has no
`file_search_walk.py` dependency, unlike `file_search`).

**Issues found**: None.

### Batch 2 — Phase 2: Build-Time Selection (`make-deploy-package.sh`) — Two Modes

**Mode**: Standard (shell-only; per design.md Decision 7 and tasks.md's
own note, Gate 7 and the `--share`/`--tools=` build-mode paths stay
shell-only — no pytest wrapper. Verified by actually RUNNING the script
in both modes, not by a unit test. Strict TDD's RED-GREEN-REFACTOR cycle
does not apply to this batch's deliverable for that reason; the repo's
Python test suite is still run in full at the end and stays green).

**Completed**:
- [x] 2.1 MODIFY: default mode (no flags) stages all 13 tools unconditionally
- [x] 2.2 MODIFY: `--share` flag with interactive family→tool `read -p` prompt seeded by `share_preselection()`
- [x] 2.3 MODIFY: `--tools=a,b` explicit override (catalog-name-validated, hard-fail on unknown); non-TTY `--share` with `--tools=` succeeds with no prompt; non-TTY `--share` without `--tools=` fails loudly, no package
- [x] 2.4 MODIFY: emits `tools/shipped-tools.json` with per-tool `default_enabled` (default build: all true; share build: mirrors final selection)
- [x] 2.5 ADD Gate 7: name-set equality between catalog.yaml / server.py's registered `@app.tool` names / `shipped-tools.json`, PLUS every manifest tool's catalog `deps.modules`/`deps.ps1` verified present among the files this build actually staged
- [x] 2.6 VERIFIED (by actually running the script, not manually): default run stages all 13 incl. alpha, all `default_enabled=true`; `--share --tools=onenote_search,onenote_get_page,file_search,file_get_info` (non-TTY) overrides maturity correctly (2 alpha tools enabled, 2 beta tools left disabled); non-TTY `--share` with no `--tools=` exits 1, no zip written; Gates 1-6 pass unchanged in both modes. The genuinely-interactive TTY prompt branch (task 2.2's `read -p` loop) could not be exercised non-TTY per the batch instructions — implemented per design (mirrors `install.ps1`'s later per-family Y/n idiom) and code-reviewed, but its live click-through is deferred to Phase 9's manual verification (tasks 9.1-9.3) as originally planned.

**Files changed**:

| File | Action | What Was Done |
|------|--------|----------------|
| `make-deploy-package.sh` | Modified | Added: usage header for `--share`/`--tools=`; a `CLEANUP_PATHS`-based trap (replacing the old single-STAGE trap, since STAGE/REQDIR/BUILD_TMP now all need cleanup); `--share`/`--tools=` arg parsing; catalog loading via `tools/catalog.py` (TSV bridge into bash arrays: `ALL_TOOL_NAMES`, `TOOL_FAMILY`, `TOOL_MATURITY`, `TOOL_PRESELECTED`, `FAMILY_ORDER`); selection resolution (full/`--tools=`/interactive-TTY/non-TTY-fail-loud, in that priority); `tools/shipped-tools.json` generation (family-nested JSON, always all 13 tools, `default_enabled` per selection); staging of the generated manifest into `$STAGE/WinMCP/tools/shipped-tools.json` (not through the `MANIFEST` array's Gate-1 existence check, since it is a build artifact, not a checked-in source file); new Gate 7 (name-set equality + staged-deps consistency, described above); a build-mode/selection line in the final report. The pre-existing `MANIFEST` array, `LAUNCHERS` array, and Gates 1-6 are unchanged. |

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|--------------|----------|
| 1.1/1.2/1.3 | `tests/test_catalog.py` | Unit | N/A (new file) | ✅ Written — ran first, failed with `ModuleNotFoundError: No module named 'tools.catalog'` | ✅ Passed — 7/7 after `tools/catalog.py` implemented | ✅ 7 cases: parse+count, exact name-set match, bridge-dep tool + non-bridge-dep tool (2 cases), family grouping, real beta/alpha preselection, synthetic stable-maturity preselection | ➖ None needed — module was written clean on first GREEN pass; no dead code or duplication surfaced |
| 2.1-2.6 | N/A — shell-only, no pytest coverage by design (design.md Decision 7, tasks.md's own note) | Manual/build-time | Actual script runs (not RED/GREEN) | ➖ N/A | ✅ Verified by running: default build (all 7 gates PASS, manifest all-13-true, zip contains it); `--share --tools=onenote_search,onenote_get_page,file_search,file_get_info` (non-TTY, succeeds, manifest shows exactly those 4 enabled); non-TTY `--share` with no `--tools=` (exits 1, no zip) | ➖ N/A — no unit-test triangulation for shell logic; triangulated instead by running 3 distinct build invocations and inspecting `shipped-tools.json`/exit codes/zip presence directly | ➖ None needed on first pass |

### Test Summary (cumulative)
- **Total tests written**: 7 (unchanged this batch — Phase 2 is shell-only)
- **Total tests passing**: 7 (all, in `tests/test_catalog.py`)
- **Layers used**: Unit (7), Integration (0), E2E (0), Manual/build-script (3 build invocations this batch)
- **Approval tests** (refactoring): None
- **Pure functions created**: 3 (unchanged — `load_catalog`, `families`, `share_preselection`, from Batch 1)

**Full suite**: `source .venv/bin/activate && python3.12 -m pytest -q` → **681 passed** (unchanged from Batch 1 — Phase 2 added zero pytest tests by design; zero regressions).

**Build verification (actually run, not simulated)**:
1. Default build (no flags), non-TTY: all 7 gates PASS; `tools/shipped-tools.json` lists all 13 tools, all `default_enabled: true`; file present in the zip at `WinMCP/tools/shipped-tools.json`.
2. `--share --tools=onenote_search,onenote_get_page,file_search,file_get_info`, non-TTY: succeeds with no prompting; manifest shows exactly those 4 tools `default_enabled: true` (2 alpha overridden on, 2 beta tools staying at their maturity-seeded-off default) and the other 9 `default_enabled: false`; all 13 still listed (files always staged); all 7 gates PASS.
3. `--share` with no `--tools=`, non-TTY (`< /dev/null`): exits 1 immediately with `FAIL: --share with no TTY and no --tools= given ...`, before running any gate; `dist/` gains no new zip.
4. Bonus: `--tools=onenote_search,not_a_real_tool` hard-fails immediately with an unknown-tool-name error naming all 13 valid catalog names.

**Deviations from design**: None functionally. One interpretation call: tasks.md's task 2.5 phrasing ("name-set equality between `shipped-tools.json` and staged tool files' declared catalog `deps`") differs slightly from the orchestrator's batch-launch wording ("name-set equality between catalog.yaml, server.py's registered tools, and the generated manifest"). Implemented Gate 7 to satisfy BOTH: (a) three-way name-set equality across catalog.yaml/server.py/shipped-tools.json, and (b) per-manifest-tool verification that its catalog `deps.modules`/`deps.ps1` are present among the staged files. Also: `shipped-tools.json` always lists all 13 catalog tools in EVERY mode (never a subset) — only `default_enabled` varies — per design.md's explicit "Both stage identical files (shipped-but-disabled)" and Decision 2's "files never omitted" (interpreted as applying to the manifest's tool-name listing too, not just physical file staging); this keeps Gate 7's three-way name check mode-independent.

**Issues found**: None. One known-and-accepted gap: the genuinely-interactive `--share` TTY prompt loop (no `--tools=`, real terminal) cannot be exercised in this non-TTY environment; it is implemented and reviewed but its live behavior is deferred to Phase 9 manual verification (tasks 9.1-9.3), exactly as originally planned by the change's own task list.

### Batch 3 — Phases 3-5: `settings.py` accessor, `server.py` registration gating, `deploy/smoke_test.py` derived EXPECTED_TOOLS

**Mode**: Strict TDD (RED-GREEN-REFACTOR), full repo suite kept green.

**Interruption/recovery note**: this batch was interrupted mid-flight by
a session end. On resume, the repo was found with Phase 3 fully landed
(`tools/settings.py::_load_installed_tools_yaml()`/`installed_tools()`)
and Phase 4's `server.py::create_server(installed=...)` param + gating
also landed, but Phase 5's `run_family()`/`run_files_family()` skip
logic was only half-wired (`EXPECTED_TOOLS`/`_read_installed_tools()`/
`_compute_expected_tools()` existed, but `run_family`/`run_files_family`
did not yet accept `installed=`, and `main()`'s loop hadn't been updated
to pass it) — the full suite was RED at 6 failed/698 passed at that
point. Recovery: re-read all three production files + three test files
in full, confirmed no duplication/half-written code in
`tools/settings.py` or `server.py`, then finished `deploy/smoke_test.py`
(`_family_enabled()` + `installed=` param on both `run_family()` and
`run_files_family()`, wired into `main()`'s loop) and fixed one
pre-existing test (`test_main_probes_roots_policy_with_fixed_synthetic_
path_not_install_dir`)'s local `fake_run_files_family` stub, whose
signature no longer matched `run_files_family()`'s now-`installed`-aware
call site in `main()`. No other half-written state was found — no code
changes from this recovery beyond finishing Phase 5's own scope.

**Completed**:
- [x] 3.1 RED `tests/test_settings.py`: `installed_tools()` absent/empty/populated/ignores-unknown-top-level-keys
- [x] 3.2 GREEN `tools/settings.py::installed_tools()`
- [x] 4.1 RED `tests/test_server.py`: `create_server(installed=...)` over `None`/2-tool-set/empty-set
- [x] 4.2 GREEN `server.py`: `installed` param, `_tool_enabled()` closure, all 13 `@app.tool` blocks gated, `main()` resolves via `settings.installed_tools()`
- [x] 4.3 RED `tests/test_server.py`: import-safety regardless of `installed_tools()` value (narrowed and absent-file cases)
- [x] 4.4 VERIFIED: 4.3 passes with zero conditional imports added — every tool module still statically imported unconditionally
- [x] 5.1 RED `tests/test_smoke_test.py`: `_read_installed_tools(path)` absent/populated/empty-list; `_compute_expected_tools()` none-vs-narrowed; `EXPECTED_TOOLS` module constant
- [x] 5.2 GREEN `deploy/smoke_test.py`: `_read_installed_tools()` (stdlib `re` only), `_DEFAULT_ALL_TOOLS`, `_compute_expected_tools()`, `_INSTALLED_TOOLS`/`EXPECTED_TOOLS` module constants
- [x] 5.3 RED `tests/test_smoke_test.py`: `run_family()`/`run_files_family()` skip-when-zero-enabled, run-when-`installed=None`, run-when-at-least-one-tool-enabled, `aggregate_verdict()` treats `"skipped"` as neutral
- [x] 5.4 GREEN `deploy/smoke_test.py`: `_family_enabled()`, `installed=` param on both family runners, `main()`'s loop passes `_INSTALLED_TOOLS` through

**Files changed**:

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/settings.py` | Modified | `_INSTALLED_TOOLS_PATH` constant (`config/installed-tools.yaml`, distinct from `_SETTINGS_PATH`); `_load_installed_tools_yaml()` (raw loader, mockable, mirrors `load_settings()`'s convention); `installed_tools() -> set[str] \| None` — `None` when absent, `set()` for empty `tools:`, exact set when populated, ignores any top-level YAML key other than `tools:` (shape-restricted per design.md Decision 4). |
| `server.py` | Modified | `create_server(..., installed: set[str] \| None = None)`; a `_tool_enabled(name)` closure (`installed is None or name in installed`); each of the 13 `@app.tool(...)` blocks wrapped in `if _tool_enabled("name"):` with its body re-indented one level (mechanical transform, verified per-block against the original decorator name before rewriting); all module-level imports left untouched/unconditional; `main()` now calls `create_server(installed=settings.installed_tools())`; new `from tools import settings` import. |
| `deploy/smoke_test.py` | Modified | `_DEFAULT_ALL_TOOLS` (the old hardcoded 13-name literal, kept verbatim as the fallback); `_INSTALLED_TOOLS_PATH` (sibling `config/installed-tools.yaml` next to this script's own directory, matching the deployed flattened-to-package-root layout); `_INSTALLED_TOOLS_LINE_RE` + `_read_installed_tools(path)` (stdlib `re`-only scrape of a flat `- name` YAML list, no `yaml` import, no `tools/catalog.py` import); `_compute_expected_tools(installed)`; module constants `_INSTALLED_TOOLS`/`EXPECTED_TOOLS` computed once at import from the real path (absent in this dev/deploy-dir checkout → `_DEFAULT_ALL_TOOLS`, preserving every pre-existing test's assumption that `EXPECTED_TOOLS` is the full 13-tool set); `_family_enabled(tool_names, installed)` pure helper; `run_family()`/`run_files_family()` both gained an `installed=None` parameter and now return `("skipped", [...])` with zero `tools/call` sent when none of the family's tools are enabled; `main()`'s per-family loop and the `files`-family call now pass `installed=_INSTALLED_TOOLS` through. |
| `tests/test_settings.py` | Modified | 4 new tests for `installed_tools()` (absent/empty/populated/ignores-unknown-key), mocking `tools.settings._load_installed_tools_yaml` per that module's existing `load_settings`-mocking convention. |
| `tests/test_server.py` | Modified | 5 new tests: 3 parametrizing `create_server(installed=...)` (`None`/2-tool/empty), 2 import-safety regression tests (narrowed + absent-file `installed_tools()` mocks + `importlib.reload`). |
| `tests/test_smoke_test.py` | Modified | 14 new tests covering `_read_installed_tools()`, `_compute_expected_tools()`, the `EXPECTED_TOOLS`/`_DEFAULT_ALL_TOOLS` module constants, `run_family()`/`run_files_family()`'s skip/run-normally/run-when-partially-enabled behavior, and `aggregate_verdict()`'s neutral handling of `"skipped"`; also fixed one **pre-existing** test's local `fake_run_files_family` stub signature (added `installed=None`) so it still matches `run_files_family()`'s call site inside `main()`. |

### TDD Cycle Evidence (Batch 3)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|--------------|----------|
| 3.1/3.2 | `tests/test_settings.py` | Unit | ✅ 30/30 (pre-existing) before edit | ✅ Written — `ImportError: cannot import name 'installed_tools'` | ✅ Passed — 34/34 after `installed_tools()` implemented | ✅ 4 cases: absent→None, empty→set(), populated→exact set, ignores-unknown-key | ➖ None needed |
| 4.1/4.2 | `tests/test_server.py` | Unit/Integration (FastMCP in-process `Client`) | ✅ 44/44 (pre-existing) before edit | ✅ Written — `TypeError: create_server() got an unexpected keyword argument 'installed'` (3 cases) | ✅ Passed — 47/47 after `installed` param + gating implemented | ✅ 3 cases: `None` (all 13), 2-tool narrowed, empty (0 tools) | ➖ None needed — mechanical script-driven transform, verified block-by-block |
| 4.3/4.4 | `tests/test_server.py` | Unit | N/A (regression-safety test, no new production code required) | ✅ Written first (import-safety already held given unconditional imports; ran and passed immediately — no RED phase needed since 4.2 already satisfied it) | ✅ Passed — 49/49 | ✅ 2 cases: narrowed value, absent-file (`None`) value | ➖ None needed |
| 5.1/5.2 | `tests/test_smoke_test.py` | Unit | ✅ 35/35 relevant subset (pre-existing) before edit | ✅ Written — `AttributeError`/import errors for `_read_installed_tools`/`_compute_expected_tools`/`_DEFAULT_ALL_TOOLS` before implementation | ✅ Passed after implementation | ✅ absent/populated/empty-list for `_read_installed_tools`; none-vs-narrowed for `_compute_expected_tools` | ➖ None needed |
| 5.3/5.4 | `tests/test_smoke_test.py` | Unit (`StubServer`, no subprocess) | ✅ 35/35 (pre-existing, all still green) before edit | ✅ Written — `TypeError: run_family()/run_files_family() got an unexpected keyword argument 'installed'` (6 cases) | ✅ Passed — 48/48 after `_family_enabled()` + `installed=` param implemented | ✅ 6 cases: skip-when-zero-enabled (both runners), run-when-`None`, run-when-partially-enabled | ➖ None needed — one pre-existing test's stub signature updated to match, not a refactor of production code |

### Test Summary (cumulative through Batch 3)
- **Total tests written**: 34 (7 catalog + 4 settings + 5 server + 14 smoke_test + 4 already-counted-above... see per-file counts below)
- **Per-file test counts (this repo's suite, post-Batch-3)**: `tests/test_catalog.py` 7, `tests/test_settings.py` 34 (30 pre-existing + 4 new), `tests/test_server.py` 49 (44 pre-existing + 5 new), `tests/test_smoke_test.py` 48 (34 pre-existing + 14 new)
- **Layers used**: Unit (all of the above), Integration (FastMCP in-process `Client` calls in `test_server.py`, unchanged pattern from pre-existing tests), E2E (0)
- **Approval tests** (refactoring): None — no refactoring tasks this batch beyond the mechanical `server.py` block-rewrap (verified per-block against the original decorator text before transforming, functioning as an approval check)
- **Pure functions created this batch**: `tools.settings._load_installed_tools_yaml`/`installed_tools`; `server._tool_enabled` (closure, not standalone but pure given its closed-over `installed`); `deploy.smoke_test._read_installed_tools`/`_compute_expected_tools`/`_family_enabled`

**Full suite**: `source .venv/bin/activate && python3.12 -m pytest -q` → **704 passed, 0 failed** (690 after Phases 3-4 + 14 new Phase-5 tests; zero regressions). `tests/test_file_search_adapter.py` re-verified independently: **87/87 passed, untouched**.

**Deviations from design**: None functionally new this batch beyond
what Batch 1/2 already noted. One interpretation call on task 3.1's
"ignores unknown names" phrasing: implemented as "ignores any top-level
YAML key in `config/installed-tools.yaml` other than `tools:`" (the
file's shape is restricted to exactly that one flat list, per design.md
Decision 4's "shape-restricted flat YAML"), rather than validating
individual tool names against the catalog — `tools/settings.py` never
reads `tools/catalog.yaml` at runtime (design.md's "Technical Approach":
catalog.yaml is never read at runtime), so it has no catalog to validate
tool names against; an unrecognized tool *name* inside `tools:` simply
passes through in the returned set and is harmless downstream, since
`server.py`'s gating only checks the 13 real `@app.tool` names it
already knows about — an unknown name in the set matches nothing and is
implicitly ignored there instead.

**Issues found**: None, beyond the batch-launch interruption itself
(recovered cleanly — see the interruption/recovery note above; no data
or completed work was lost, since Phases 1-2's apply-progress record and
Phases 3-4's already-landed code were both intact and correct on
resume).

**Remaining tasks** (at the end of Batch 3, before this batch): Phase 6
(`install.ps1`/`install.bat`), Phase 7 (QA/PRO unattended-path
verification), Phase 8 (full suite + README), Phase 9 (manual
verification on a Windows host).

**Status at end of Batch 3**: 23/? tasks complete (Phases 1-5 of 9
phases, fully done). Full suite green at 704 passed, 0 failed.

### Batch 4 — Phases 6-7: `install.ps1`/`install.bat` selective install, QA/PRO unattended-path verification

**Mode**: Standard (shell/PowerShell-only; per design.md Decision 7,
install-time selection logic is not pytest-covered — PS 5.1 logic is not
unit-testable on this WSL2 host. Verified by actually RUNNING
`install.bat`/`install.ps1` non-interactively against real built
packages on the Windows side, not by a unit test. The repo's full Python
suite is still run at the end and stays green).

**Completed**:
- [x] 6.1 MODIFY `deploy/install.ps1`: reads `tools/shipped-tools.json` from the staged package (`$scriptDir\tools\shipped-tools.json`); trusts only `default_enabled` (never re-derives from `maturity`); added `-Preset <path-to-json-file>` param (`{"tools": [...]}` shape, catalog/manifest-name-validated, fails loudly on an unknown name)
- [x] 6.2 MODIFY `deploy/install.ps1`: priority chain `-Preset` > `[Console]::IsInputRedirected` (non-interactive: enables exactly the manifest's `default_enabled=true` set, zero prompts, never blocks) > interactive
- [x] 6.3 MODIFY `deploy/install.ps1`: interactive branch — per-family prompt with a 3-way answer (`y`=enable all in family / `n`=skip whole family / `s`=select individually), family default seeded from whether all/none/some of its tools are `default_enabled`; `s` drops into a per-tool y/n loop pre-checked per `default_enabled`; ends with a selection summary + a confirm-or-redo prompt (redo restarts the whole family walk, never aborts the install)
- [x] 6.4 MODIFY `deploy/install.ps1`: writes `config/installed-tools.yaml` (`tools:` flat list, or `tools: []` when nothing enabled) on completion across all three paths (`-Preset`, non-interactive, interactive); skipped entirely (no file written) when `tools/shipped-tools.json` is absent from the package (older zip) — exact current/back-compat behavior, since `tools/settings.py::installed_tools()` already treats an absent file as "everything"
- [x] 6.5 MODIFY `deploy/install.bat`: added `%*` to the `powershell.exe ... -File "%~dp0install.ps1"` invocation so `-Preset` (and any future flag) forwards through
- [x] 6.6 VERIFIED: re-ran `./make-deploy-package.sh` — Gate 4 (pure ASCII) and Gate 5 (PS 5.1 parse via cached portable pwsh, 0 errors) both PASS on the modified `install.ps1`/`install.bat`
- [x] 7.1 VERIFIED (no code change, confirmed by reading both files in full): `deploy-qa.sh`/`promote-pro.sh` untouched; both invoke the default (no `--share`) build mode implicitly (they just consume whatever zip is newest in `dist/` or is passed as an arg) and both already redirect stdin from `/dev/null` into `install.bat`
- [x] 7.2 VERIFIED manually end-to-end (see below)

**Files changed**:

| File | Action | What Was Done |
|------|--------|----------------|
| `deploy/install.ps1` | Modified | Added `-Preset` parameter to the `param()` block; new "Step 4b: tool selection" block inserted after the win32com smoke-check and before the Claude Desktop config-snippet printout — reads/parses `tools\shipped-tools.json` via `ConvertFrom-Json`, resolves the enabled-tool set via the `-Preset` > non-interactive-default > interactive priority chain described above, and writes `config\installed-tools.yaml`. No existing step's logic or numbering content changed. |
| `deploy/install.bat` | Modified | One-line change: `powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0install.ps1"` → same line + `%*` appended, so command-line args (notably `-Preset <path>`) reach `install.ps1`. |
| `deploy/smoke_test.py` | Modified (incidental, this batch) | Fixed one non-ASCII byte (a stray em-dash `—` on line 13, inside a comment) left over from Batch 3's Phase 5 edits — replaced with `--`. This was blocking Gate 4 (pure-ASCII) on `./make-deploy-package.sh`, which Phase 7 verification requires to run; harmless comment-only fix, zero behavior change, confirmed by the unchanged 704-pass pytest count before/after. |
| `openspec/changes/selective-tool-deployment/tasks.md` | Modified | Checked off 6.1-6.6 and 7.1-7.2. |

### TDD Cycle Evidence (Batch 4)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|--------------|----------|
| 6.1-6.6 | N/A — PS 5.1 logic, not pytest-covered by design (design.md Decision 7; PS 5.1 is not unit-testable on WSL2) | Manual/build+install-time | Gate 4 (ASCII) + Gate 5 (PS 5.1 parse via cached portable pwsh) both re-run and PASS; then actual `install.bat` runs (not simulated) against 3 distinct built packages (full/default, `--share --tools=...`, and a `-Preset` override) | N/A | Verified live: non-interactive default install of a 13-tool full build wrote all 13 to `installed-tools.yaml`; non-interactive default install of a 4-tool `--share --tools=` build wrote exactly those 4; `-Preset` with a 2-tool JSON file overrode the 4-tool manifest default down to exactly those 2; `-Preset` with one unknown tool name failed loudly (`ERROR: Preset: unknown tool name 'not_a_real_tool' ...`), installer exited non-zero, `install.bat` printed its failure banner | 4 distinct live runs (13-tool full, 4-tool share-subset, 2-tool valid preset, 1-bad-name preset) plus 2 gate re-runs (ASCII, PS-parse) | ➖ None needed on first pass |
| 7.1/7.2 | N/A — shell/live verification | Manual/deploy-time | Full `deploy-qa.sh` run against a real full-build zip, plus `deploy/smoke_test.py` run against the deployed QA copy via `cmd.exe`, plus a from-scratch scratch-dir install of a `--share --tools=` subset zip + its own `smoke_test.py` run | N/A | Both runs PASSED (see below) | 2 independent deployed installs (QA full-build; scratch-dir 4-tool share-subset), each smoke-tested live | ➖ None needed — no code path in `deploy-qa.sh`/`promote-pro.sh` touched |

### Test Summary (cumulative through Batch 4)
- **Total pytest tests**: unchanged this batch — 704 (Phase 6/7 add zero pytest coverage by design; `deploy/smoke_test.py`'s one-line ASCII fix is comment-only, no test changes needed or made)
- **Layers used**: Unit (all prior batches' 704), Integration (FastMCP in-process `Client`, unchanged), E2E (0 in pytest), Manual/live-deploy (this batch: 1 full `make-deploy-package.sh` run + 1 `--share --tools=` run, 1 `deploy-qa.sh` run + 1 deployed smoke test, 1 scratch-dir share-subset install + 1 deployed smoke test, 1 valid-preset install, 1 invalid-preset failure-path install — 7 live invocations total)
- **Approval tests** (refactoring): None
- **Pure functions created this batch**: none (PowerShell script logic only, no new Python functions)

**Full suite**: `source .venv/bin/activate && python3.12 -m pytest -q` → **704 passed, 0 failed** (unchanged from Batch 3; zero regressions from this batch's PS1/bat/smoke_test.py-comment changes). Also reconfirmed inline as Gate 2 during both `./make-deploy-package.sh` runs in this batch (704 passed both times).

**Live verification — full default build / QA path (Phase 7.2)**:
1. `./make-deploy-package.sh` (no flags): all 7 gates PASS; `tools/shipped-tools.json` lists all 13 tools, all `default_enabled: true`.
2. `./deploy-qa.sh` (no args, picks up the just-built zip): wiped/re-extracted `C:\usr\WinMCP-qa`; ran `install.bat` with stdin from `/dev/null` — completed without blocking, printed `Non-interactive install: enabling this package's default tool set (13 tool(s)).` and `OK: Wrote C:\usr\WinMCP-qa\config\installed-tools.yaml (13 tool(s) enabled).`
3. `C:\usr\WinMCP-qa\config\installed-tools.yaml` inspected directly: lists exactly all 13 tool names under `tools:`.
4. `cd /mnt/c/usr/WinMCP-qa && cmd.exe /c ".venv\Scripts\python.exe smoke_test.py"`: `tools/list` returned all 13 names; all 6 live families (calendar/tasks/mail-inbox/mail-sent/mail-drafts/files) ran and PASSed; final line `SMOKE TEST PASSED`.
5. PRO (`C:\usr\WinMCP`) confirmed untouched throughout — `ls` on its `config\` directory shows only the pre-existing `settings.yaml`, no `installed-tools.yaml`.

**Live verification — share-subset build (Phase 7, share-install check)**:
1. `./make-deploy-package.sh --share --tools=onenote_search,onenote_get_page,file_search,file_get_info`: all 7 gates PASS; `tools/shipped-tools.json` shows exactly those 4 tools `default_enabled: true` (2 alpha overridden on, `onenote_create_page`/`onenote_update_page` left at their beta-seeded-off default) and the other 9 `default_enabled: false`.
2. Extracted the resulting zip to a scratch dir `C:\usr\WinMCP-seltest` (NOT QA or PRO); ran `install.bat` with stdin from `/dev/null` — completed without blocking, printed `Non-interactive install: enabling this package's default tool set (4 tool(s)).`
3. `C:\usr\WinMCP-seltest\config\installed-tools.yaml` inspected directly: lists exactly `file_search`, `file_get_info`, `onenote_search`, `onenote_get_page` — the 4 named tools, nothing else.
4. Its `smoke_test.py` run: `tools/list` returned exactly those 4 names (narrowed `EXPECTED_TOOLS`); calendar/tasks/mail-inbox/mail-sent/mail-drafts all reported `SKIPPED` (`family '...' has zero enabled tools - skipped`), `files` PASSed live; final line `SMOKE TEST PASSED` (skips are verdict-neutral, per design.md Decision 6).
5. Scratch dir `C:\usr\WinMCP-seltest` removed afterward, per the batch's cleanup instruction.

**Live verification — `-Preset` path (bonus, not explicitly required by tasks.md but exercises new Phase 6 code)**:
1. Extracted the same 4-tool share-subset zip to a second scratch dir `C:\usr\WinMCP-presettest`; wrote a preset JSON `{"tools": ["onenote_search", "file_get_info"]}` (2 of the manifest's 4 `default_enabled=true` tools); ran `install.bat -Preset C:\usr\preset.json` with stdin from `/dev/null` — the preset took priority over the non-interactive default, printed `OK: Using preset selection from C:\usr\preset.json (2 tool(s)).`; resulting `installed-tools.yaml` listed exactly `onenote_search`/`file_get_info`, not the manifest's 4-tool default.
2. Re-ran the same install with a preset containing one unknown name (`not_a_real_tool`): installer printed `ERROR: Preset: unknown tool name 'not_a_real_tool' (not in this package's tools\shipped-tools.json)`, exited non-zero, `install.bat` printed its failure banner — fails loudly, no partial/silent selection applied.
3. Scratch dir `C:\usr\WinMCP-presettest` and the two preset JSON files removed afterward.

**Deviations from design**: Two interpretation calls, both consistent
with design.md's letter and intent:
1. `-Preset <json>` (task 6.1's literal phrasing) was implemented as
   `-Preset <path-to-a-json-file>`, not an inline JSON string passed on
   the command line — a file path is far less fragile to quote/escape
   correctly across `install.bat`'s `%*` forwarding into
   `powershell.exe -File`, and design.md's own File Changes table
   description ("`-Preset`, `IsInputRedirected` branch...") does not
   specify an inline-string contract. The preset file's shape,
   `{"tools": [...]}`, is a flat enabled-tool-name list — deliberately
   the simplest possible schema, mirroring `make-deploy-package.sh`'s own
   `--tools=a,b,c` validation convention (unknown name -> fail loudly,
   naming the offending tool).
2. The interactive per-family prompt (task 6.3) is a 3-way answer
   (`y`/`n`/`s`) rather than a strict binary Y/n with a separate
   always-shown per-tool pass — chosen because the spec's own scenario
   ("operator picks 'all' for 3 families... deselects one tool within a
   4th... no tools from the 5th") requires a full-family shortcut, a
   full-family skip, AND a way to alter individual tools within one
   family, which a plain binary Y/n cannot express without a redundant
   second full pass over every tool in every family. `s` is exactly the
   "per-tool toggles" design.md/tasks.md both call for, scoped to only
   the families the operator doesn't take the all/none shortcut on.
   Family default (`y`/`n`/`s`) is seeded from whether every/no/some of
   the family's tools are `default_enabled`, so pressing Enter on a
   uniformly-preselected or uniformly-unselected family does the
   sensible thing with zero extra keystrokes.

**Issues found**: One pre-existing (not this batch's) latent Gate-4
failure in `deploy/smoke_test.py` (a stray em-dash from Batch 3's Phase 5
edits) was discovered and fixed while running `./make-deploy-package.sh`
for this batch's own verification — see Files Changed above. No other
issues found. The genuinely-interactive TTY branch of `install.ps1`'s
new per-family prompt (task 6.3's `y`/`n`/`s` loop) could not be
exercised in this non-TTY WSL2 environment, exactly as anticipated by the
batch-launch instructions and by Batch 2's identical note for the
build-time picker; it is implemented and code-reviewed (traced by hand
against the spec's own multi-family scenario) but its live click-through
is deferred to Phase 9 manual verification (tasks 9.1-9.3), unchanged
from the original plan.

**Remaining tasks** (next batch, NOT started — out of scope for this
batch): Phase 8 (full suite + README doc update), Phase 9 (manual
verification on a real Windows host with an attached TTY).

**Status**: 32/? tasks complete (Phases 1-7 of 9 phases, fully done: 3
catalog + 6 build-time-selection + 2 settings-accessor + 4
server-registration-gating + 4 smoke-test-derivation + 6
install-time-selection + 2 QA/PRO-unattended-path-verification — see
tasks.md for the authoritative checklist). Full suite green at 704
passed, 0 failed. Live-verified on the Windows host: full-build QA
unattended install (13/13 tools, smoke test PASSED), share-subset
unattended install (4/4 tools, smoke test PASSED with 5 families
correctly SKIPPED), and the new `-Preset` override path (both the
success and the loud-failure cases). PRO (`C:\usr\WinMCP`) was never
touched. Ready for the next batch (Phase 8) — but Phase 8 must NOT be
started until explicitly requested; this batch stops here by design.

### Batch 5 — Phase 8: Full Suite, Docs

**Mode**: Docs-only batch, no production code touched (per the batch's own
scope restriction). No TDD cycle applies — nothing to RED/GREEN, only
`README.md`, `tasks.md`, and this file were written. The full pytest suite
and `./make-deploy-package.sh` were run as verification gates, not as
part of a RED-GREEN cycle.

**Completed**:
- [x] 8.1 Ran `source .venv/bin/activate && python3.12 -m pytest -q`: full
      repo suite green
- [x] 8.2 MODIFIED `README.md`: documented `tools/catalog.yaml`
      (families/maturity/deps, never read at runtime), the two build modes
      of `make-deploy-package.sh` (default vs `--share`/`--tools=`,
      non-TTY-`--share`-without-`--tools=`-fails-loudly), `shipped-tools.json`
      per-tool `default_enabled`, `install.ps1`'s selection priority
      (`-Preset` > non-interactive default > interactive family `y`/`n`/`s`
      prompt), `config/installed-tools.yaml` and its runtime effect on
      `server.py`/`smoke_test.py` (absent-file back-compat, empty list,
      unknown-name-ignored), and Gate 7. Also extended the manual
      verification steps with the Phase 9 items (interactive `--share`
      drill-down/override, non-TTY `--share` failure vs. success with
      `--tools=`, and a `--share` subset install + `smoke_test.py` run
      showing skipped families).

**Files changed**:

| File | Action | What Was Done |
|------|--------|----------------|
| `README.md` | Modified | Added four new subsections under "Building the package": "Selective tool deployment: choosing which tools ship enabled" (catalog.yaml, the two build modes, `shipped-tools.json`, Gate 7), "Choosing which tools install enabled" (`-Preset`/non-interactive/interactive priority chain), "Runtime effect of the installed-tools selection" (`server.py` gating + `smoke_test.py` family-skip derivation), and "Building a share package end-to-end" (command examples). Added a new "Manual verification: selective build/install (Windows host)" subsection covering the Phase 9 manual-only checks (interactive `--share` override, non-TTY `--share` failure/success, `--share`-subset install + smoke test). All claims verified against the shipped code (`tools/catalog.yaml`, `make-deploy-package.sh`, `deploy/install.ps1`, `server.py`, `deploy/smoke_test.py`, `tools/settings.py`) before writing, not just design.md. No contradictions introduced with the pre-existing "13 tools"/OneNote sections. |
| `openspec/changes/selective-tool-deployment/tasks.md` | Modified | Checked off 8.1 and 8.2. |

### Test Summary (cumulative through Batch 5)
- **Total pytest tests**: unchanged this batch — 704 passed, 0 failed
  (docs-only batch, zero test changes)
- **Layers used**: unchanged from Batch 4
- **Approval tests**: None
- **Pure functions created this batch**: none (docs only)

**Full suite**: `source .venv/bin/activate && python3.12 -m pytest -q` →
**704 passed, 0 failed** (unchanged from Batch 4; zero regressions).

**Final sanity check — `./make-deploy-package.sh` (default/full mode, no
flags), run twice**: all 7 gates PASS both times —
`PASS: gate 1` (26 manifest files + 5 launcher sources),
`PASS: gate 2` (full test suite, 704 passed),
`PASS: gate 3` (no module-level `win32com` import),
`PASS: gate 4`/`gate 4b` (pure ASCII, no unescaped parens),
`PASS: gate 5` (`install.ps1` parses cleanly via cached portable pwsh),
`PASS: gate 6` (wheel coverage, 78 files),
`PASS: gate 7` (13 tool names match across `catalog.yaml`/`server.py`/
`shipped-tools.json`; every manifest tool's catalog deps staged).
Build mode reported: `full (all tools default_enabled=true)`. Resulting
zip: `dist/WinMCP-20260828.zip`.

**Deviations from design**: None. This batch's README additions describe
exactly the shipped behavior confirmed by re-reading `tools/catalog.yaml`,
`make-deploy-package.sh`'s selection/Gate-7 logic, `deploy/install.ps1`'s
Step-4b selection block, `server.py`'s `_tool_enabled()` gating, and
`deploy/smoke_test.py`'s `_family_enabled()`/`"skipped"` verdict — not
copied uncritically from design.md's shorthand.

**Issues found**: None.

**Remaining tasks**: Phase 9 (manual verification on a real Windows host
with an attached TTY) — explicitly NOT started, out of scope for this
batch (manual, user-run).

**Status**: 34/39 tasks complete (Phases 1-8 of 9 phases, fully done; only
Phase 9's 5 manual-only tasks remain). Full suite green at 704 passed, 0
failed. `./make-deploy-package.sh` (default mode) verified clean with all
7 gates passing. README.md now documents the full selective-deployment
feature end-to-end, cross-checked against shipped code. Ready for
Phase 9 (manual, user-run on a Windows host) whenever the user chooses to
exercise it — this is the final automatable batch for this change.

### Batch 6 — Phase 10 (addendum): Share-Flow UX Refinements

**Mode**: Standard (shell-only; per design.md Decision 7, `make-deploy-
package.sh`'s build-mode/selection paths stay shell-only — no pytest
wrapper. Verified by actually running the script in multiple modes, not
by a unit test. The repo's full pytest suite is still run at the end and
stays green.)

**Origin**: user-requested during Phase 9 manual verification (the
interactive share prompt was live-verified working; these four items are
the user's refinements on top of it), plus one defect this batch's own
review surfaced before any of the four items were touched — see 10.1.

**Completed**:
- [x] 10.1 FIX (defect found during review, fixed first): share builds
      were writing the SAME `$DIST/WinMCP-$STAMP.zip` full builds use.
      `deploy-qa.sh`'s no-arg path (`ls -1t "$DIST"/WinMCP-*.zip`) and
      `promote-pro.sh`'s marker-resolved `$DIST/$MARKER_ZIP` lookup both
      resolve directly inside `dist/`, non-recursively — a share build
      could silently overwrite that day's full-build zip, or (if it
      happened to be newest and matched the marker) get auto-deployed/
      promoted as if it were the vetted pipeline package. Fixed: share
      builds now write to `dist/share/WinMCP-share-$STAMP-$(date
      +%H%M%S).zip` — a subdirectory the `dist/WinMCP-*.zip` glob never
      descends into, under a name distinct from the full-build pattern.
      Full-build naming/location (`dist/WinMCP-$STAMP.zip`) unchanged.
      Verified by inspection (not by editing) that `deploy-qa.sh` line ~26
      and `promote-pro.sh`'s `$DIST/$MARKER_ZIP` resolution are both
      non-recursive against `$DIST` directly; confirmed live by running a
      full build then a share build side by side and checking
      `dist/WinMCP-*.zip` still lists only the full-build zip.
- [x] 10.2 MODIFY: ending report/"Next steps" now names the file. Added a
      prominent `SHARE PACKAGE READY: <path>` banner right after the
      `package:` line in share mode; step 1 of "Next steps" reads "Copy
      `<basename>` to the target machine" in share mode (full mode keeps
      the original generic "Copy the zip to the Windows machine.").
- [x] 10.3 MODIFY: interactive copy offer. After the report, when
      `BUILD_MODE=share` AND the build went through the genuine
      interactive picker (not `--tools=`) AND stdin is still a TTY, prompt
      "Copy `<name>` now to a Windows-visible folder? [y/N]"; on yes,
      prompt for a destination directory (default `/mnt/c/usr/tmp`,
      `mkdir -p`'d if missing, or a typed alternate), copy the zip there,
      and print both the `/mnt/c/...` path and the derived Windows path
      (`C:\...`, via a regex-based `/mnt/<drive>/...` -> `<DRIVE>:\...`
      conversion). Decline (or any non-`y` answer) just prints "Skipped -
      package remains at `<OUT>`" and exits, same as today. Non-TTY share
      (`--tools=`) never reaches this block (`SHARE_INTERACTIVE` is only
      set to 1 inside the `[[ -t 0 ]]` selection branch).
- [x] 10.4 MODIFY: whiptail TUI for interactive tool selection. When
      `--share` runs with no `--tools=` override, stdin is a TTY, `--no-
      tui` was NOT passed, AND `command -v whiptail` succeeds, the picker
      is a single `whiptail --checklist` screen: one `tag`/`item`/`status`
      triple per tool, `tag="[family] tool_name"` (whiptail checklists are
      flat, so the family prefix is baked into the tag text itself —
      confirmed against `whiptail --help`'s `--checklist <text> <height>
      <width> <listheight> [tag item status]...` signature), `item` shows
      `maturity: <alpha|beta>`, `status` pre-seeded `ON`/`OFF` from
      `TOOL_PRESELECTED` (the same `share_preselection()`-derived array the
      plain loop already used). Output captured via the standard `3>&1
      1>&2 2>&3` fd-juggle idiom so the dialog paints on the terminal while
      the selected tags land on stdout; a nonzero whiptail exit (Cancel or
      Esc) calls `fail`, aborting the build before any gate runs (nonzero
      exit, no zip — same guarantee non-TTY-without-`--tools=` already
      had). Selected tags are parsed back into tool names via `eval
      "_WHIPTAIL_TAGS=($WHIPTAIL_OUT)"` (whiptail double-quotes each tag in
      its output, which is exactly what bash's array-literal syntax needs
      to re-split on the embedded spaces) then `name="${tag#*] }"` strips
      the `[family] ` prefix. The plain `y`/`n` per-family/per-tool `read
      -p` loop from Batch 2 is UNCHANGED and now serves two roles: the
      automatic fallback when whiptail isn't found, and the forced path
      when `--no-tui` is passed. Added `--no-tui` to the arg-parsing case
      statement (alongside `--share`/`--tools=`) and to the "unknown
      argument" error's list of supported flags.

**Files changed**:

| File | Action | What Was Done |
|------|--------|----------------|
| `make-deploy-package.sh` | Modified | Header comment documents the new `dist/share/` isolation, the whiptail TUI, and `--no-tui`. `OUT` is no longer computed at the top of the script (it depended on `STAMP` alone before; now it depends on `BUILD_MODE`, resolved after arg parsing) — moved to a new "Resolve output package path" block placed right after `shipped-tools.json` generation, before the `MANIFEST` section; full mode keeps `$DIST/WinMCP-$STAMP.zip`, share mode computes `$DIST/share/WinMCP-share-$STAMP-$(date +%H%M%S).zip`. Arg parsing gained `--no-tui` -> `USE_TUI=0` (default `USE_TUI=1`). The interactive (`-t 0`) selection branch gained a `SHARE_INTERACTIVE=1` flag (initialized `0` alongside `SELECTED_TOOL_NAMES=()`) and now branches on `USE_TUI`+`command -v whiptail` into either the new `whiptail --checklist` block or the pre-existing plain loop (kept verbatim, now nested one level deeper as the `else`). The "Zip it" section's `mkdir -p "$DIST"` became `mkdir -p "$(dirname "$OUT")"` so `dist/share/` is created on demand. The "Report" section gained `OUT_NAME="$(basename "$OUT")"`, a share-mode `SHARE PACKAGE READY:` banner, a share-mode-conditional step-1 wording, and a new interactive-copy-offer block gated on `BUILD_MODE=share && SHARE_INTERACTIVE=1 && -t 0`, using a `/mnt/<drive>/...` -> `<DRIVE>:\...` regex conversion for the printed Windows path. |
| `openspec/changes/selective-tool-deployment/tasks.md` | Modified | Added Phase 10 (10.1-10.4 checked, 10.5 an unchecked `[MANUAL]` item for the whiptail walk + copy-offer drill on a real TTY). |
| `openspec/changes/selective-tool-deployment/specs/selective-deploy-packaging/spec.md` | Modified | Added "Requirement: Share Package Output Is Isolated From The Pipeline Zip" with two Given/When/Then scenarios (share build lands outside the `dist/WinMCP-*.zip` glob under a distinct name; default build's output is unaffected). |
| `README.md` | Modified | Rewrote the `--share` bullet under "Building the package" to describe the whiptail checklist, `--no-tui`, the `dist/share/` isolation, the named-file report/next-steps behavior, and the interactive copy offer; updated the "Building a share package end-to-end" command examples to add `--no-tui`; extended the Phase-9 manual-verification item 1 to cover the whiptail checklist, Cancel, `--no-tui` fallback, and the copy offer (default dest, typed alt dest, decline). |

### TDD Cycle Evidence (Batch 6)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|--------------|----------|
| 10.1-10.4 | N/A — shell-only, no pytest coverage by design (design.md Decision 7, same as Batch 2's identical note) | Manual/build-time | Actual script runs (not RED/GREEN), plus a standalone `bash -c` dry run of the checklist-construction and tag-parsing logic, plus a standalone dry run of the `/mnt/...` -> Windows-path conversion, plus `whiptail --help` cross-check of the `--checklist` flag signature | N/A | Verified by running: full default build (all 7 gates PASS, unchanged zip name/location); `--share --tools=... < /dev/null` (all 7 gates PASS, zip under `dist/share/`, report names the file, no prompts); `--share < /dev/null` with no `--tools=` (exits 1 immediately, no zip anywhere, not even `dist/share/`); `--share --tools=... --no-tui < /dev/null` (flag accepted, same successful outcome) | 4 distinct live invocations (full, share+tools, share-no-tools-fail, share+tools+no-tui) plus 3 hand-traced dry runs (checklist tag construction + parse-back, Windows-path regex conversion, `whiptail --help` signature match) since the whiptail screen and the copy-offer `read -p` prompts cannot be driven without a real TTY in this environment | ➖ None needed on first pass |

### Test Summary (cumulative through Batch 6)
- **Total pytest tests**: unchanged this batch — 705 passed, 0 failed (shell-only UX refinements, zero pytest coverage by design; the task's stated baseline of 705 matches exactly)
- **Layers used**: unchanged from Batch 5, plus Manual/build-script (4 live invocations this batch) and 3 standalone non-TTY dry-run traces of the TTY-only logic (checklist construction/parse, Windows-path conversion, whiptail flag-signature check)
- **Approval tests**: None
- **Pure functions created this batch**: none (shell script logic only)

**Full suite**: `source .venv/bin/activate && python3.12 -m pytest -q` →
**705 passed, 0 failed** (matches the task's stated 705 baseline exactly;
zero regressions from this batch's shell-only changes).

**Build verification (actually run, not simulated)**:
1. Full default build (no flags): all 7 gates PASS; `dist/WinMCP-20260828.zip` — unchanged name/location, "Copy the zip to the Windows machine." wording preserved in "Next steps".
2. `--share --tools=onenote_search,file_search` (non-TTY, `< /dev/null`): all 7 gates PASS; package written to `dist/share/WinMCP-share-20260828-131723.zip`; report includes a `SHARE PACKAGE READY: ...` banner naming the exact path; "Next steps" step 1 reads "Copy WinMCP-share-20260828-131723.zip to the target machine."; no prompts of any kind (confirms the copy offer correctly gates on `SHARE_INTERACTIVE`, which the `--tools=` branch never sets).
3. `--share` with no `--tools=` (non-TTY, `< /dev/null`): exits 1 immediately with the pre-existing fail-loud message, before any gate runs; `dist/share/` left empty, no zip anywhere.
4. `--share --tools=onenote_search --no-tui` (non-TTY, `< /dev/null`): flag parses without an "unknown argument" error; same successful outcome as invocation 2 (the `--tools=` branch is taken regardless of `--no-tui`/whiptail, so this only proves flag-acceptance, not the fallback-selection branch itself — see Issues Found).
5. `dist/WinMCP-*.zip` glob re-checked after invocation 2: lists only the full-build zip from step 1, confirming `dist/share/`'s content is invisible to `deploy-qa.sh`'s (and, by the same non-recursive-glob logic, `promote-pro.sh`'s marker-resolved) zip lookup — by inspection only, `deploy-qa.sh`/`promote-pro.sh` were NOT modified.
6. `bash -n make-deploy-package.sh`: clean, no syntax errors.
7. `whiptail --help` cross-checked: confirms `--checklist <text> <height> <width> <listheight> [tag item status]...` matches the implemented call exactly (`24 78 14` + tag/item/status triples, `3>&1 1>&2 2>&3` capture idiom).
8. Standalone `bash -c` dry run of the checklist-item-construction loop and the tag-parsing (`eval "_WHIPTAIL_TAGS=($WHIPTAIL_OUT)"` + `${tag#*] }`) against representative "[onenote] onenote_search"-style tags: correctly reconstructs the array and strips the family prefix back to the bare tool name.
9. Standalone dry run of the `/mnt/<drive>/...` -> `<DRIVE>:\...` conversion: `/mnt/c/usr/tmp` + `WinMCP-share-....zip` correctly produces `C:\usr\tmp\WinMCP-share-....zip`.

**Deviations from design**: None — this is a UX-only addendum on top of
Batch 2's already-landed build-time selection; no design.md decision is
touched (the `--share`/`--tools=` non-TTY contracts, the maturity-seeded
`share_preselection()`, and Gate 7 are all unchanged). One interpretation
call: the task prompt's item 3 framing ("in share INTERACTIVE mode only
(TTY)... Non-TTY share (--tools=) prints the path but never prompts")
left open whether a *TTY* run that still passes `--tools=` should get the
copy offer. Implemented as: the copy offer is gated on
`SHARE_INTERACTIVE` (set only inside the genuine `-t 0` picker branch —
whiptail or plain-loop), not merely on `-t 0` itself — so a TTY run with
an explicit `--tools=` override (a scripted/explicit invocation, even if
launched from a terminal) does NOT get prompted, matching the spirit of
"the interactive picker ran" rather than "a TTY happens to be attached".

**Issues found**: None new in the shell logic itself. One known-and-
accepted gap, expected going in: the whiptail checklist screen and both
`read -p` prompts in the interactive-copy-offer block are genuinely
TTY-only and could not be click-through-exercised in this non-TTY WSL2
environment — traced by hand instead (checklist construction/parse dry
run, `whiptail --help` signature cross-check, Windows-path conversion dry
run; see Build verification items 7-9 above) and flagged as task 10.5, an
explicit unchecked `[MANUAL]` item, for the user's next real-TTY run
(same pattern Batches 2/4 used for the earlier interactive prompts, now
also covering the copy offer and the Cancel path specifically).

**Remaining tasks**: Phase 9's original 5 manual-only tasks (9.1-9.5,
unchanged, not started) PLUS this batch's new 10.5 (whiptail checklist
walk + copy-offer drill on a real TTY) — both sets are manual/user-run
and were never in scope for automated batches.

**Status**: 38/44 tasks complete (Phases 1-8 and Phase 10's 4 automatable
items fully done; Phase 9's 5 manual items and Phase 10's 1 manual item
remain — 6 manual-only tasks total, all requiring a real Windows/TTY
console). Full suite green at 705 passed, 0 failed. The share-zip
collision defect (10.1) is fixed and live-verified; the ending
report/next-steps naming (10.2) is live-verified; the interactive copy
offer (10.3) and whiptail TUI (10.4) are implemented, code-reviewed, and
traced by hand via non-TTY dry runs, with their live TTY walk-through
deferred to 10.5 exactly as anticipated.

## Batch 6 addendum — whiptail terminfo hotfix (2026-08-28, orchestrator inline)

The user's first live TUI run failed instantly: `TERM=wezterm` has no
system terminfo entry, newt died with "Unknown terminal: wezterm", and the
script misreported it as a user cancel. Fixes in `make-deploy-package.sh`:

1. Terminfo-aware TERM fallback: if `infocmp "$TERM"` fails, the whiptail
   call runs under `TERM=xterm-256color` (skip TUI entirely if even that
   entry is missing).
2. Error-vs-cancel distinction: nonzero whiptail exit WITH text on the
   answer channel = runtime error -> WARN + fall back to the plain y/n
   picker; empty answer = genuine Esc/Cancel -> abort as before.
3. Plain-picker branch now keyed off an explicit `SELECTION_DONE` flag.

Verified under a pseudo-TTY (`script -qec`) with TERM=wezterm: checklist
renders via the fallback (13 tools, family-grouped, onenote pre-checked),
Enter -> 4/13 selection -> all 7 gates PASS -> dist/share/ zip + named
banner + copy offer ([y/N] prompt confirmed); Esc -> clean cancel, exit 1,
no zip. Test artifacts removed. `bash -n` clean; pytest suite untouched
(shell-only change).

## Catalog data fix (2026-08-28, orchestrator inline, surfaced by hard-tool-exclusion design)

`tools/catalog.yaml`'s file-family deps were incomplete: file_search /
file_get_info omitted `tools/ps_bridge_transport.py` (which
file_search_adapter.py imports) and `tools/ps_bridge_search.ps1` (which
PowerShellSearchBridge executes). Harmless under shipped-but-disabled
(every file always staged; Gate 7 only checks declared deps ARE staged,
not that declarations are complete) but load-bearing for the upcoming
hard-tool-exclusion change, whose owner-set staging rule would have
dropped the transport and search bridge from any share package excluding
onenote. Both tools' deps corrected; suite 705 green; all package gates
PASS. Follow-up idea for hard-tool-exclusion: an import-graph gate that
catches undeclared module deps (grep imports of family modules vs
catalog declarations).
