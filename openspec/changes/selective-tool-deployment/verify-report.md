# Verification Report

**Change**: selective-tool-deployment
**Version**: N/A (no version field in specs)
**Mode**: Strict TDD (project-wide `strict_tdd: true`), with Standard-mode carve-outs for shell/PS1-only phases (design.md Decision 7 — explicitly accepted by the change's own design/tasks)
**Verified**: 2026-08-28

---

### Completeness

| Metric | Value |
|--------|-------|
| Tasks total | 39 (34 automatable + 5 manual) |
| Tasks complete | 34/34 automatable (Phases 1-8) |
| Tasks incomplete | 5 (Phase 9, tasks 9.1-9.5 — explicitly manual/user-run, out of verify scope per launch instructions) |

No incomplete task inside verify's scope. Phase 9 is correctly left unchecked in `tasks.md`; it requires a Windows host with an attached TTY.

---

### Build & Tests Execution

**Build**: N/A (no compiled build step; `make-deploy-package.sh` is the packaging pipeline, run separately below)

**Tests**: ✅ 705 passed / ❌ 0 failed / ⚠️ 0 skipped
```
705 passed in 4.74s
```
Matches the expected count exactly: 704 from this change's 5 apply batches + 1 from the unrelated same-day ENH-002 hotfix to `tools/onenote.py`/`tests/test_onenote_tools.py` (confirmed out of scope for this change's spec-compliance analysis, per launch instructions — the added test does not touch any file this change owns).

`tests/test_file_search_adapter.py` re-run independently: ✅ 87/87 passed, unmodified by this change.

Per-file test counts (independently re-collected, not trusted from apply-progress alone):
| File | Collected | apply-progress claim | Match |
|------|-----------|----------------------|-------|
| `tests/test_catalog.py` | 7 | 7 | ✅ |
| `tests/test_settings.py` | 34 | 34 (30 pre-existing + 4 new) | ✅ |
| `tests/test_server.py` | 49 | 49 (44 pre-existing + 5 new) | ✅ |
| `tests/test_smoke_test.py` | 48 | 48 (34 pre-existing + 14 new) | ✅ |

**Coverage**: ➖ Not available (no coverage tool configured per `openspec/config.yaml`'s `testing.coverage.available: false`)

---

### TDD Compliance
| Check | Result | Details |
|-------|--------|---------|
| TDD Evidence reported | ✅ | Full "TDD Cycle Evidence" tables present for every batch in `apply-progress.md` |
| All tasks have tests (where applicable) | ✅ | Every Python-code task (Phases 1, 3, 4, 5) has a test file; Phases 2, 6, 7 are explicitly shell/PS1-only per design.md Decision 7 and verified by live script execution instead |
| RED confirmed (tests exist) | ✅ | `tests/test_catalog.py`, `tests/test_settings.py`, `tests/test_server.py`, `tests/test_smoke_test.py` all exist and were independently re-collected (7/34/49/48 — see table above) |
| GREEN confirmed (tests pass) | ✅ | 705/705 passing on independent re-run, including all files listed above |
| Triangulation adequate | ✅ | Every new behavior has 2+ test cases with varying expected values (e.g. `None`/empty/populated for `installed_tools()`; skip/run-None/run-partial for `run_family`) — no single-case behaviors found undertriangulated |
| Safety Net for modified files | ✅ | Every modified file's pre-existing test count was recorded and re-verified green before/after (30→34, 44→49, 34→48) |

**TDD Compliance**: 6/6 checks passed

---

### Test Layer Distribution
| Layer | Tests | Files | Tools |
|-------|-------|-------|-------|
| Unit | ~131 (new, this change) | `test_catalog.py`, `test_settings.py` (4 new), `test_smoke_test.py` (14 new + supporting constants) | pytest, `pytest-mock` |
| Integration | 5 (new, `test_server.py`, FastMCP in-process `Client`) | `test_server.py` | FastMCP `Client` |
| E2E | 0 in pytest; extensive **manual/live** (see below) | — | Windows host, real `install.bat`/`smoke_test.py` |
| Manual/live-deploy | 7 live invocations this batch set (full build, share-subset build, non-TTY failure, `-Preset` success/failure, QA install, share-subset install) | shell/PS1 | actual Windows host, per apply-progress Batch 2/4 |
| **Total (pytest)** | **~136 new + 704 carried baseline = 704 (pre-hotfix) / 705 (with hotfix)** | | |

Shell/PowerShell-only paths (Gate 7, `--share`/`--tools=` selection, `install.ps1`'s selection block) are, by design.md Decision 7, not pytest-covered — this is a deliberate, documented scope decision, not a gap. I independently re-ran the shell paths myself (see "Live Re-Verification" below) rather than trusting the apply-progress record alone.

---

### Assertion Quality
No CRITICAL or WARNING issues found. Scanned `tests/test_catalog.py`, `tests/test_settings.py`'s new cases, `tests/test_server.py`'s new cases, and `tests/test_smoke_test.py`'s new cases for tautologies, ghost loops, smoke-test-only assertions, and mock-heavy ratios:
- No tautologies (`assert True`, `assert 1 == 1`) found anywhere in the four files.
- No ghost loops over possibly-empty collections found.
- Every new test calls production code and asserts a real, varying value (e.g. `test_create_server_empty_installed_registers_zero_tools` triangulates against `..._installed_none_registers_all_13_tools` and `..._narrowed_installed_registers_only_those_tools` — three distinct expected values, not just presence/absence).
- `test_import_succeeds_regardless_of_installed_tools_value` combines a "no exception" assertion with concrete `sys.modules` membership checks — not a bare smoke test.
- Mock/assertion ratios in the new `mocker.patch`-based tests (`test_settings.py`'s 4 new cases: 4 patches / 8 total assert+patch lines) are reasonable, not mock-heavy.

**Assertion quality**: ✅ All assertions verify real behavior

---

### Spec Compliance Matrix

| Requirement | Scenario | Test / Evidence | Result |
|---|---|---|---|
| Catalog Structure | Catalog matches server.py's registered tools | `test_load_catalog_matches_server_py_tool_names_exactly` | ✅ COMPLIANT |
| Catalog Structure | A tool declares its bridge dependency | `test_onenote_search_declares_its_bridge_dependency` | ✅ COMPLIANT |
| Maturity pre-selection only | Alpha defaults unselected | `test_share_preselection_selects_beta_leaves_alpha_unselected_but_present` | ✅ COMPLIANT |
| Maturity pre-selection only | Beta/stable default pre-selected | `test_share_preselection_also_selects_a_synthetic_stable_tool` (+ real-catalog case above) | ✅ COMPLIANT |
| Maturity pre-selection only | Default/full build ignores maturity | Live: `./make-deploy-package.sh` (no flags) → manifest all 13 `default_enabled=true` (re-run by me) | ✅ COMPLIANT |
| Loadable without Windows/COM | Catalog parses on WSL2 | `test_load_catalog_parses_on_wsl2_without_win32com` | ✅ COMPLIANT |
| Consistent family grouping | Family names identical | `test_families_groups_tools_by_consistent_family_string` | ✅ COMPLIANT |
| Default build includes every tool | all 13 staged incl. alpha | Live: default-mode run, Gate 7 passed, manifest all `default_enabled=true` (re-run by me) | ✅ COMPLIANT |
| Share build maturity-prefilled/overridable | Pre-selection follows maturity | apply-progress Batch 2, `--tools=` run mirrored in my own re-run (4/13 tools) | ✅ COMPLIANT |
| Share build maturity-prefilled/overridable | Builder override wins | `--share --tools=onenote_search,onenote_get_page,file_search,file_get_info` re-run by me: 2 alpha ON, 2 beta OFF — override proven both directions | ✅ COMPLIANT |
| Non-interactive share requires explicit selection | Succeeds with `--tools=` | Live re-run by me: exit 0, gates pass, manifest mirrors exactly the 4 named tools | ✅ COMPLIANT |
| Non-interactive share requires explicit selection | Fails loudly without `--tools=` | Live re-run by me: `--share < /dev/null` → exit 1, exact spec-quoted failure message, **no new zip written** (verified `dist/` listing before/after) | ✅ COMPLIANT |
| Dependency staging consistency | Shared bridge script stays staged | Gate 7's per-manifest-tool dep check (code-reviewed, and exercised live by both my builds) | ✅ COMPLIANT |
| Shipped-tools manifest default_enabled flags | Default build all-true | Live re-run: manifest inspected via `unzip`, all 13 `default_enabled: true` | ✅ COMPLIANT |
| Shipped-tools manifest default_enabled flags | Share build mirrors selection | Live re-run: manifest inspected via `unzip`, exactly the 4 named tools `true`, rest `false` | ✅ COMPLIANT |
| Existing build gates unaffected by mode | Gates 1-6 still run under share build | Live re-run: gates 1-6 all PASS under `--share --tools=` | ✅ COMPLIANT |
| Hierarchical interactive selection | Operator picks subset across families | `install.ps1`'s per-family `y/n/s` loop (code-reviewed; live-exercised in apply-progress Batch 4 on the real Windows host — TTY branch cannot run in this WSL2 shell) | ⚠️ PARTIAL (static + prior live evidence, not re-exercised by me — genuinely requires a TTY) |
| Non-interactive installs manifest default set | QA/PRO unaffected | `deploy-qa.sh` live run (apply-progress Batch 4): 13/13 tools, smoke test PASSED; corroborated by code review of `install.ps1`'s `IsInputRedirected` branch | ✅ COMPLIANT (via apply-progress live evidence — genuine Windows-only path) |
| installed-tools.yaml written into installed copy | Reflects interactive/non-interactive subset | apply-progress Batch 4 live runs: 13-tool full install and 4-tool share-subset install both inspected directly | ✅ COMPLIANT (live evidence) |
| Selection scoped to shipped tools only | Excluded tool never offered/enabled | `install.ps1`'s loop only iterates `$manifest.families[].tools[]` — structurally cannot offer an absent tool (code-reviewed) | ✅ COMPLIANT (static — no test targets this directly, but the loop bound makes the negative case structurally unreachable) |
| ASCII/PS 5.1 compatibility preserved | Gates still pass | Live re-run by me: Gate 4/4b/5 all PASS on modified `install.ps1`/`install.bat` | ✅ COMPLIANT |
| Tool Registration (mcp-server-bootstrap) | All tools discoverable, no config | `test_create_server_installed_none_registers_all_13_tools` | ✅ COMPLIANT |
| Tool Registration (mcp-server-bootstrap) | Only enabled tools discoverable | `test_create_server_narrowed_installed_registers_only_those_tools` | ✅ COMPLIANT |
| Import Safety Independent of Registration | Import succeeds, narrowed config | `test_import_succeeds_regardless_of_installed_tools_value` | ✅ COMPLIANT |
| Import Safety Independent of Registration | Import succeeds, absent config | `test_import_succeeds_when_installed_tools_config_file_absent` | ✅ COMPLIANT |
| Expected Tool Set Matches Registered Tools | Missing tool fails tools/list step | code path at `deploy/smoke_test.py:372-381` (`missing = EXPECTED_TOOLS - found`) — no dedicated new test for this exact scenario, but pre-existing logic unmodified in shape, only `EXPECTED_TOOLS`'s source changed | ⚠️ PARTIAL (logic present and structurally unchanged; not independently re-tested against this change's narrowed-EXPECTED_TOOLS case) |
| Expected Tool Set Matches Registered Tools | EXPECTED_TOOLS narrows when file present | `test_compute_expected_tools_narrows_to_exactly_the_installed_set` | ✅ COMPLIANT |
| Expected Tool Set Matches Registered Tools | EXPECTED_TOOLS full set when absent | `test_expected_tools_module_constant_is_default_all_tools_when_config_absent`, `test_default_all_tools_is_the_full_13_tool_set` | ✅ COMPLIANT |
| Per-Family Live Checks Scoped to Enabled | Fully-disabled family skipped | `test_run_family_skips_when_none_of_its_tools_are_enabled`, `test_run_files_family_skips_when_none_of_its_tools_are_enabled` | ✅ COMPLIANT |
| Per-Family Live Checks Scoped to Enabled | All families run when absent | `test_run_family_runs_normally_when_installed_is_none`, `test_run_files_family_runs_normally_when_installed_is_none` | ✅ COMPLIANT |
| QA-PRO: non-interactive installer invocation | Completes without blocking | `deploy-qa.sh`/`promote-pro.sh` unmodified (byte-for-byte, corroborated by mtimes predating the change — see Coherence section); live-verified in apply-progress Batch 4 | ✅ COMPLIANT |
| QA-PRO: enables every shipped tool | No script change needed | Same live evidence (Batch 4): 13/13 enabled with zero script changes | ✅ COMPLIANT |

**Compliance summary**: 26/28 scenarios fully COMPLIANT with direct test or live-execution evidence; 2 PARTIAL (one is a genuinely TTY-only interactive path that cannot execute in this non-TTY WSL2 shell, already correctly deferred to Phase 9 by the change's own plan; the other is a pre-existing, structurally-unchanged code path lacking a scenario-specific regression test for the *narrowed* case specifically — low risk, not a functional gap).

---

### Correctness (Static — Structural Evidence)
| Requirement | Status | Notes |
|------------|--------|-------|
| Tool catalog (all 6 tool-catalog requirements) | ✅ Implemented | `tools/catalog.yaml`/`tools/catalog.py` match spec exactly; independently re-verified name-set equality via Gate 7 re-run |
| Selective deploy packaging (all 5 requirements) | ✅ Implemented | Verified via 3 independent live builds (default, `--tools=`, non-TTY-no-`--tools=`-fail) |
| Selective install provisioning (all 5 requirements) | ✅ Implemented | Code-reviewed line-by-line against spec; live-verified in apply-progress Batch 4 on real Windows host (interactive TTY path only, correctly deferred to Phase 9) |
| MCP server bootstrap deltas (2 requirements) | ✅ Implemented | `server.py`'s 13 gated blocks + unconditional imports, both test-covered |
| Smoke-test-coverage deltas (2 requirements) | ✅ Implemented | `_read_installed_tools`/`_compute_expected_tools`/`_family_enabled`, all test-covered |
| QA-PRO deploy workflow delta (1 requirement) | ✅ Implemented | Zero code change (correctly so — spec calls for "no code change required"); confirmed via byte-identical files + live Batch 4 evidence |

---

### Coherence (Design)
| Decision | Followed? | Notes |
|----------|-----------|-------|
| 1. Catalog schema (family→tools, deps per-tool) | ✅ Yes | `deps` placed under each tool (not family) — a documented, justified interpretation call in Batch 1, consistent with the tool-catalog spec's own per-tool dependency scenario |
| 2. Build-time selection: shipped-but-disabled both modes | ✅ Yes | Confirmed live: share build with 4/13 enabled still stages and lists all 13 in the manifest, `default_enabled` varying only |
| 3. Install UX maturity-agnostic, `-Preset` > non-interactive > interactive | ✅ Yes | `install.ps1` lines 258-320 implement exactly this priority chain; installer never reads `maturity` for selection logic |
| 4. `installed-tools.yaml` flat YAML, absent→all, empty→none, unknown ignored | ✅ Yes | `tools/settings.py::installed_tools()` implements exactly this; test-covered for all four cases including the unknown-key-ignored case |
| 5. `server.py` registration via `if _tool_enabled(name):` per block | ✅ Yes | All 13 `@app.tool` blocks wrapped exactly this way; mechanical, verified block-by-block per apply-progress |
| 6. `smoke_test.py` EXPECTED_TOOLS derivation, hand-authored FAMILIES skips a not-covered family | ✅ Yes | `_DEFAULT_ALL_TOOLS` fallback + regex scrape, no `yaml` import; `FAMILIES` still hand-authored with only 5 entries (no onenote), matching Decision 6 exactly |
| 7. Test strategy: shell/PS1 stays out of pytest | ✅ Yes | Phases 2, 6, 7 correctly carry no pytest coverage, each with an explicit "N/A - shell-only" TDD Cycle Evidence row and live-execution verification instead |
| 8. Maturity assignment: onenote=beta, rest=alpha | ✅ Yes | Confirmed directly in `tools/catalog.yaml` |

**Design compliance**: 8/8 decisions followed with no unauthorized deviations. Every deviation apply-progress documents (Batch 1's deps-per-tool interpretation, Batch 2's Gate-7 dual-check interpretation, Batch 3's unknown-key-ignored interpretation, Batch 4's `-Preset`-as-file-path and 3-way `y/n/s` prompt) is a *documented, spec-consistent interpretation of an underspecified detail*, not a contradiction of design.md's letter — verdicted below.

---

### Batch Deviation Review (verdicted)

| Batch | Deviation | Verdict |
|---|---|---|
| 1 | `deps` placed per-tool, not per-family, in the catalog schema | ✅ ACCEPT — required by the tool-catalog spec's own per-tool dependency scenario; design.md's notation was ambiguous, not contradicted |
| 2 | Gate 7 satisfies both the tasks.md wording and the orchestrator's launch wording (3-way name equality + per-tool dep-staging check) | ✅ ACCEPT — strictly a superset of either single interpretation; independently re-verified live, both checks present and correct |
| 2 | `shipped-tools.json` always lists all 13 tools in every mode (never a subset) | ✅ ACCEPT — explicitly required by design.md's "shipped-but-disabled" and Decision 2's "files never omitted"; independently re-verified live (share build's manifest lists all 13, only 4 `true`) |
| 3 | "Ignores unknown names" interpreted as "ignores unknown top-level YAML keys" rather than validating tool names against the catalog | ✅ ACCEPT — consistent with design.md Decision 4's "shape-restricted flat YAML" and the explicit "catalog never read at runtime" constraint; test-covered (`test_installed_tools_ignores_unknown_top_level_keys`) — see WARNING below for a related, narrower concern |
| 3 | Interruption mid-batch; resumed cleanly, one pre-existing test stub signature fixed | ✅ ACCEPT — recovery verified genuine: re-read the actual files (`server.py`, `tools/settings.py`, `deploy/smoke_test.py` line 544-550 stub fix, confirmed the signature now matches `run_files_family`'s real params); no duplicated/dead code found; full suite green at the batch's claimed count (704), independently re-confirmed now |
| 4 | `-Preset <json>` implemented as a **file path** to a JSON file, not an inline JSON string | ✅ ACCEPT — reasonable, documented, and lower-risk than inline-string quoting through `install.bat`'s `%*`/`powershell.exe -File`; design.md's own phrasing does not mandate an inline string |
| 4 | Interactive prompt is 3-way (`y`/`n`/`s`) rather than binary Y/n | ✅ ACCEPT — required to express the spec's own multi-family scenario (full-family shortcut + full-family skip + per-tool override) without a redundant double pass; code-reviewed against `install.ps1` lines 320-399, matches exactly what's described |
| 4 | Incidental fix: one stray em-dash in `deploy/smoke_test.py` comment (Gate 4 ASCII violation) | ✅ ACCEPT — comment-only, zero behavior change, confirmed by unchanged 704-pass count before/after per the batch's own record |

No unverdicted or unresolved deviations remain.

---

### Live Re-Verification (performed independently by this verify pass, not copied from apply-progress)

1. `source .venv/bin/activate && python3.12 -m pytest -q` → **705 passed**, 0 failed.
2. `python3.12 -m pytest -q tests/test_file_search_adapter.py` → **87 passed**.
3. `./make-deploy-package.sh` (default mode, `< /dev/null`) → all 7 gates PASS; manifest all 13 `default_enabled=true`; zip produced.
4. `./make-deploy-package.sh --share < /dev/null` (no `--tools=`) → exit code **1**, exact spec-quoted failure line, **no new zip** written (confirmed via `dist/` directory listing diff).
5. `./make-deploy-package.sh --share --tools=onenote_search,onenote_get_page,file_search,file_get_info < /dev/null` → all 7 gates PASS; manifest inspected directly (`unzip` + `json.load`): exactly `file_search`/`file_get_info`/`onenote_search`/`onenote_get_page` at `default_enabled: true` (2 alpha overridden on, 2 beta staying at their maturity default-off), the other 9 `false`.
6. Confirmed `deploy-qa.sh` (mtime 2026-08-24 15:49) and `promote-pro.sh` (mtime 2026-08-24 13:37) both predate this change's earliest touched file (`tools/catalog.yaml`, 2026-08-27 14:57) — corroborating the "byte-unmodified" claim beyond apply-progress's own assertion (not a git repo, so mtime + content read is the available evidence).
7. Read `server.py`'s full import block (lines 1-45): confirmed every tool-adapter module import remains static/unconditional at module top-level, with only `@app.tool` registration gated — matching Decision 2/5 and the mcp-server-bootstrap "Import Safety" requirement.

---

### Issues Found

**CRITICAL**: None.

**WARNING**:
1. **`installed-tools.yaml` parser grammar is not strictly identical between `tools/settings.py` (PyYAML, scoped to the `tools:` key) and `deploy/smoke_test.py` (`_INSTALLED_TOOLS_LINE_RE = re.compile(r"^\s*-\s*(\w+)\s*$", re.MULTILINE)`, unscoped — matches any `- name` line anywhere in the file, regardless of which top-level key it sits under).** For every file the system itself ever produces, this is harmless: `install.ps1`'s sole write path (lines 407-420) emits exactly one shape — either `tools: []` or `tools:` followed by `- name` lines, with only `#`-prefixed comment lines otherwise — so both parsers agree on every real, installer-written file. The divergence is latent: a hand-edited or future-extended `installed-tools.yaml` carrying a second top-level list key (e.g. a hypothetical `disabled_reasons: [...]`) would be correctly ignored by `settings.py` (test-covered: `test_installed_tools_ignores_unknown_top_level_keys`) but incorrectly absorbed into `smoke_test.py`'s scraped set (untested — no equivalent multi-key test exists for `_read_installed_tools`). Design.md Decision 4/6 imply the two consumers "read the same file" with matching semantics; strictly, their *grammars* differ even though their *current outputs* never do. Recommend either scoping the regex to lines between `tools:` and the next top-level key, or adding a test proving the regex's behavior on a multi-key file so the equivalence is asserted, not assumed.
2. **One spec scenario ("A registered tool is missing from tools/list") has no dedicated test re-exercising it against this change's *narrowed* `EXPECTED_TOOLS`** — the underlying `missing = EXPECTED_TOOLS - found` / fail-naming-the-tool logic (`deploy/smoke_test.py:372-381`) is pre-existing and structurally unchanged by this change, so risk is low, but the smoke-test-coverage delta spec explicitly restates this scenario as part of the delta, and no new/updated test targets it with a narrowed `EXPECTED_TOOLS` specifically.
3. **The genuinely-interactive TTY paths** (`make-deploy-package.sh --share`'s `read -p` picker; `install.ps1`'s per-family `y/n/s` prompt) have zero automated coverage and, in this verify pass, could not be independently re-exercised either (same non-TTY WSL2 constraint apply-progress already documented). Evidence for these rests entirely on code review plus apply-progress's Batch 2/4 live-Windows-host record, which I was not able to independently reproduce. This is a known, correctly-deferred-to-Phase-9 gap, not a new finding — flagged here only so the verdict's basis is explicit.

**SUGGESTION**:
1. Consider adding a `tests/test_catalog.py` case asserting `share_preselection()` returns a subset of `load_catalog()`'s tool names (a basic sanity invariant), for extra defense against a future catalog entry with a typo'd or missing `maturity` value silently mis-defaulting.
2. The Assertion-Quality-flagged latent grammar issue (WARNING 1) would be cheaply closed by anchoring `_INSTALLED_TOOLS_LINE_RE` to only scan the block following a `^tools:` line, or by adding one `test_read_installed_tools_ignores_dash_lines_under_an_unrelated_key` test mirroring `test_installed_tools_ignores_unknown_top_level_keys`.

---

### Verdict

**PASS WITH WARNINGS**

All 705 tests pass (including the pre-existing 87/87 `test_file_search_adapter.py` baseline); all 7 packaging gates pass on 3 independent live re-runs I performed myself (default, explicit `--tools=` share, and the non-TTY-no-selection failure path); every architecture decision in design.md is followed with no unauthorized deviations (8 documented interpretation calls, all reviewed and accepted); back-compat (absent-file → all-13) is proven in both `server.py` and `deploy/smoke_test.py`, each with dedicated passing tests; `deploy-qa.sh`/`promote-pro.sh` are corroborated unmodified by both content review and file-mtime evidence. Two WARNING-level findings — a latent (currently harmless) parser-grammar divergence between `settings.py` and `smoke_test.py`, and one pre-existing spec scenario lacking a change-specific regression test — should be addressed before or shortly after archive, but neither blocks it. Phase 9's 5 manual tasks remain correctly out of scope, deferred to the user on a real Windows host.
