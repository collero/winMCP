# Verification Report

**Change**: hard-tool-exclusion
**Version**: N/A (no version field in specs)
**Mode**: Strict TDD (per `openspec/config.yaml` `strict_tdd: true`)

---

### Completeness

| Metric | Value |
|--------|-------|
| Tasks total | 16 (Phase 1-4: 15; Phase 5: 1) |
| Tasks complete | 15 |
| Tasks incomplete | 1 |

Incomplete: 5.1 (manual Windows-host install/enable-attempt verification). Explicitly out of scope per the orchestrator's launch brief ("Phase 5 manual, out of verify scope") and per tasks.md's own header. Not a blocker.

---

### Build & Tests Execution

**Build**: N/A (no compiled build step; `./make-deploy-package.sh` is the packaging pipeline, verified separately below)

**Tests**: ✅ 725 passed / 0 failed / 0 skipped
```
725 passed in 5.09s
```
`tests/test_file_search_adapter.py` re-run in isolation: 87 passed (untouched by this change, as claimed).

**Coverage**: Not configured in this project (`coverage_threshold: 0`, no pytest-cov installed) — Not available.

---

### Live Build Verification (executed by this verification pass)

1. **Full build** (`./make-deploy-package.sh`, no flags): all 7 gates PASS (gate 5 via cached portable pwsh 7.4.17), 115 files staged, `tools/shipped-tools.json` lists all 13 tools, `default_enabled=true`. Zip removed after inspection.
2. **Exclusion build** (`./make-deploy-package.sh --share --tools=onenote_search,onenote_get_page`): all 7 gates PASS, 105 files staged. `unzip -l` confirms:
   - **Present**: `tools/onenote.py`, `tools/onenote_adapter.py`, `tools/ps_bridge_onenote.ps1`, `tools/ps_bridge_transport.py` (shared infra), `tools/settings.py`, `tools/errors.py`, `models/schemas.py`, `server.py`, `tools/shipped-tools.json`.
   - **Absent**: every `mail`/`calendar`/`task`/`file_search*` module, `tools/outlook_adapter.py`, `tools/mail_adapter.py`, `tools/task_adapter.py`, `tools/ps_bridge_search.ps1`.
   - `tools/shipped-tools.json` content: exactly `{"families":[{"name":"onenote","tools":[{"name":"onenote_search",...},{"name":"onenote_get_page",...}]}]}` — no other family, no other onenote tool.
   - Only near-miss on the negative grep: `tools/fake_file_search_adapter.py` (pre-existing, already flagged in apply-progress as an unrelated manifest-hygiene nit — confirmed still present, not a regression from this change) and `wheels/email_validator-*.whl` (substring match on "mail", irrelevant).
   - Test zip and `dist/share/` directory removed after inspection; full-build test zip also removed. `dist/` left empty as found.

Both runs independently corroborate apply-progress's Batch 2/3 live-build claims.

---

### Spec Compliance Matrix

| Requirement (domain) | Scenario | Test / Evidence | Result |
|---|---|---|---|
| Family Is the Unit of Physical Exclusion (hard-tool-exclusion) | Zero-selection family physically absent | Live build #2 `unzip -l` negative check | ✅ COMPLIANT |
| Family Is the Unit of Physical Exclusion | Shared infrastructure always ships | Live build #2 `unzip -l` positive check (ps_bridge_transport.py, settings.py, schemas.py, errors.py, server.py) | ✅ COMPLIANT |
| Partially-Selected Family's Unselected Tools Unenableable (hard-tool-exclusion) | Unselected sibling cannot be enabled via config edit | `tests/test_server.py::test_registration_ceiling_end_to_end_via_real_deployed_layout` | ✅ COMPLIANT |
| Partially-Selected Family... | Installer never offers unselected sibling | No code change (Decision 4) — manifest-driven `install.ps1` already omits absent entries structurally; not independently pytest-covered (PowerShell, Windows-only) but logically entailed by the manifest generator's own tests/live-build evidence | ⚠️ PARTIAL (sound by construction, not independently executed) |
| Registration Allowlist Is Intersection (hard-tool-exclusion) | Hand-edited config cannot resurrect excluded family | `test_registration_ceiling_end_to_end_via_real_deployed_layout` + `test_create_server_shipped_ceiling_blocks_unshipped_sibling_even_if_installed` | ✅ COMPLIANT |
| Import Safety Under Any Family Subset (hard-tool-exclusion) | Single-family share package starts, serves exactly its tools | `test_import_succeeds_with_one_family_absent_and_registers_zero_of_its_tools` + live build #2 | ✅ COMPLIANT |
| Full Build Unaffected (hard-tool-exclusion) | Full build byte-identical | Live build #1 (this pass) all-gates-PASS, 115 files, 13/13 shipped; apply-progress Batch 3's full-vs-all-13-share diff (byte-identical file list) | ✅ COMPLIANT |
| Protection Limits Documented (hard-tool-exclusion) | README states honesty limits | `README.md` lines 645-689, "What this does not protect against" paragraph | ✅ COMPLIANT |
| Tool Registration (mcp-server-bootstrap delta) | All 4 precedence rows | `test_create_server_installed_none_registers_all_13_tools` (absent/absent), `test_create_server_shipped_present_installed_absent_registers_every_shipped_tool` (present/absent), `test_create_server_shipped_none_falls_back_to_installed_only_today_behavior` (absent/present), `test_create_server_shipped_and_installed_both_present_registers_intersection` (present/present) | ✅ COMPLIANT (all 4 rows) |
| Tool Registration | Hand-edit cannot resurrect a hard-excluded tool | `test_registration_ceiling_end_to_end_via_real_deployed_layout` | ✅ COMPLIANT |
| Import Safety Under Physical Family Absence (mcp-server-bootstrap delta) | Single-family package imports/serves cleanly | `test_import_succeeds_with_one_family_absent_and_registers_zero_of_its_tools` | ✅ COMPLIANT |
| Import Safety Under Physical Family Absence | Absent family doesn't break present families | `test_import_succeeds_with_mail_absent_and_other_families_still_register` | ✅ COMPLIANT |
| Shipped-Tools Manifest Per-Mode Flags (selective-deploy-packaging delta) | Default build all-enabled | Live build #1: 13/13 `default_enabled=true` | ✅ COMPLIANT |
| Shipped-Tools Manifest... | Share build lists only selection | Live build #2: manifest lists exactly 2 | ✅ COMPLIANT |
| Dependency Files Omitted Only When No Owner Selected (selective-deploy-packaging delta) | Zero-selection family's files never staged | `test_excluded_files_drops_a_zero_selected_familys_modules_and_bridge`; live build #2 | ✅ COMPLIANT |
| Dependency Files Omitted... | Partial family keeps needed shared files | `test_excluded_files_cross_family_shared_file_survives_either_family_selected`; live build #2 (`ps_bridge_transport.py` present) | ✅ COMPLIANT |
| Gate 7 Verifies Excluded-Dependency Absence (selective-deploy-packaging delta) | Gate 7 fails on leaked excluded file | Not independently pytest-covered (would require injecting a staging bug); Gate 7's check 4 code read + live-clean-pass evidence (Batch 2/3 + this pass) | ⚠️ PARTIAL (mechanism verified present and passing; a deliberately-broken-staging negative test was not run) |
| Gate 7 Verifies... | Gate 7 passes on clean share build | Live build #2 (this pass), gate 7 output | ✅ COMPLIANT |
| Non-Interactive Default Installs Manifest Set (selective-install-provisioning delta) | Share package non-interactive install enables all shipped | Not independently tested this pass (Windows-only, `install.ps1`, deferred per Phase 5/COM); code-inspection: no logic change per Decision 4, manifest-driven default_enabled path unchanged | ⚠️ PARTIAL (design-sound, deferred to manual Phase 5) |
| Absent Families Never Appear as Empty Prompt Groups (selective-install-provisioning delta) | Hard-excluded family produces no prompt artifact | Same as above — `install.ps1` code inspected (iterates `manifest.families`, an absent family entry never exists to iterate), not independently executed | ⚠️ PARTIAL (design-sound, deferred to manual Phase 5) |
| Owner-Set Based Retention (tool-catalog delta) | Owner set spans exactly declaring tools | `test_excluded_files_cross_family_shared_file_survives_either_family_selected`, `test_excluded_files_shared_file_excluded_when_both_owning_families_unselected` | ✅ COMPLIANT |
| Family's Minimum Retained Set (tool-catalog delta) | Selected tool's full dep set never omitted | `test_excluded_files_full_selection_excludes_nothing`; live build #2 (onenote_search's own files present) | ✅ COMPLIANT |

**Compliance summary**: 16/21 fully COMPLIANT via automated test/live execution; 5 PARTIAL — all 5 are Windows-only `install.ps1` behaviors explicitly deferred to Phase 5 (manual, out of verify scope per the launch brief) or a not-independently-negative-tested build gate (Gate 7's own failure path). None indicate a defect; all are sound by code inspection and by the absence-of-artifact structural argument (`install.ps1` iterates the manifest directly — an absent entry cannot render).

---

### Correctness (Static — Structural Evidence)

| Requirement | Status | Notes |
|------------|--------|-------|
| `excluded_files()` owner-set union | ✅ Implemented | `tools/catalog.py`, matches design.md Decision 3/Interfaces exactly |
| `shipped_tools()` ceiling | ✅ Implemented | `tools/settings.py`, mirrors `installed_tools()`'s absent/`None` convention |
| `server.py` per-family `find_spec` guards | ✅ Implemented | 5 families, guards both tool-callables and Port types (extends design.md's snippet, which only showed the callable fallback) |
| `_tool_enabled()` ceiling | ✅ Implemented | Family-presence AND shipped AND installed, single closure |
| `make-deploy-package.sh` staging omission + Gate 7 | ✅ Implemented | `EXCLUDED_FILES`/`STAGED_MANIFEST`, Gate 7 5-check structure |
| README protection-limits documentation | ✅ Implemented | New subsection, explicit "what this does not protect against" |

---

### Coherence (Design)

| Decision | Followed? | Notes |
|----------|-----------|-------|
| 1. Import safety via `find_spec` presence, not blind `except ImportError` | ✅ Yes | Verified the guard's shape is correct: independently confirmed via a standalone experiment (see below) that `find_spec` never executes the module, so a genuine bug (SyntaxError/NameError) inside a *present* module still propagates unguarded through the unconditional `from tools.X import ...` statement |
| 2. `shipped_tools()` allowlist from `tools/shipped-tools.json`, not re-derived from catalog | ✅ Yes | |
| 3. File-granular, owner-set-based omission (not family-level flag) | ✅ Yes | Cross-family sharing (`ps_bridge_transport.py`) correctly retained/excluded per test suite and live builds |
| 4. No `install.ps1` code change | ✅ Yes | Confirmed via file mtimes (`install.ps1`/`smoke_test.py` timestamped ~2h before this change's other touched files) and content grep (no hard-tool-exclusion-specific additions; existing manifest-iteration code already handles omission structurally) |
| 5. No wheels change | ✅ Yes | Gate 6 unaffected, passed cleanly on both live builds |
| 6. Test strategy (unit + shell, no bash-wrapper pytest) | ✅ Yes | Matches predecessor's Decision 7 |
| 7. Sequencing (rebase on predecessor's landed code, don't race) | ✅ Yes | apply-progress explicitly reads-current-file-first per tasks.md's sequencing note; both catalog data bugs (predecessor's ps_bridge_transport/ps_bridge_search fix, this change's file_search_walk fix) are consistent with "read current file first," not stale-snapshot drift |

**Subtle guard-shape verification** (explicitly requested): ran an isolated experiment — a package with a module that raises `SyntaxError` at import time. Confirmed `importlib.util.find_spec()` reports the module present (it never executes the module body) while the subsequent real `import` statement still raises the `SyntaxError` normally. This confirms `server.py`'s guard pattern (`if _X_PRESENT: from tools.X import ...`) cannot mask a genuine bug in a present module as "family absent" — only a module's non-discoverability (physically missing file) is swallowed. No repo test explicitly exercises this exact scenario (a present-but-broken module) end-to-end through `server.py`'s reload path; the guarantee currently rests on code-shape inspection plus this verification-time experiment, not a permanent regression test. See WARNING below.

---

### Issues Found

**CRITICAL**: None.

**WARNING**:
1. **No permanent regression test for "genuine bug in a present module still propagates."** The two `find_spec`-based import-safety tests (`test_import_succeeds_with_one_family_absent_and_registers_zero_of_its_tools`, `test_import_succeeds_with_mail_absent_and_other_families_still_register`) only simulate *absence* (mocking `find_spec` to return `None`). Neither test simulates a present-but-broken module to confirm the error propagates rather than being swallowed. This is the single most safety-critical property of Decision 1 (it's the entire reason `find_spec` was chosen over blind `except ImportError`), and it is currently verified only by manual/one-off reasoning (this report's live experiment), not by an automated test that would catch a future accidental broadening of the guard (e.g. someone later wrapping the import in a `try/except ImportError` "for safety"). Recommend adding one test before archive: monkeypatch a family's module to raise on import (e.g. via a fake broken module inserted into `sys.modules`/`sys.path`, or monkeypatching `builtins.__import__`) and assert `importlib.reload(server)` raises, not silently registers zero tools.

2. **The import-graph completeness gate (Gate 7 check 5) only guards `deps.modules`, not `deps.ps1`.** Check 5 greps each dependency module's own `from tools.X import`/`import tools.X` lines and cross-checks against `deps.modules` — this is exactly the mechanism that caught the `file_get_info`/`file_search_walk.py` gap in this change and would have caught the predecessor's `ps_bridge_transport.py`/`ps_bridge_search.ps1` gap had it existed at the module level. However, `.ps1` bridge scripts are never statically imported by Python — they are invoked via hardcoded `Path(__file__).resolve().parent / "some_bridge.ps1"` constants (confirmed in `tools/onenote_adapter.py`'s `_PS_BRIDGE_ONENOTE_SCRIPT` and `tools/file_search_adapter.py`'s `_PS_BRIDGE_SCRIPT`) and only fail at *runtime* (subprocess spawn) if the file is missing, not at import time. No automated check verifies that a module referencing a `.ps1` bridge by such a path actually declares that file in its own `deps.ps1`. This is the same class of oversight that has already bitten this project twice (ps_bridge_transport/ps_bridge_search, file_search_walk) — both were catalog `deps.modules` gaps caught by inspection/the new gate; a `deps.ps1` gap of the same shape (a tool referencing a `.ps1` file not declared as its own dep) would currently ship silently in a partial-family share build and only surface as a runtime `FileNotFoundError`/subprocess failure when the tool is actually invoked on the recipient's machine — not caught by Gate 2 (pytest, since nothing exercises the real subprocess path on Linux), Gate 7, or any CI-time check. Recommend a future task: extend check 5 (or add check 6) to grep each family-owning module for `.ps1` string-literal references and cross-check against `deps.ps1`, mirroring the existing module check.

3. `config_keys` is correctly judged NOT a systemic risk of the same kind: `config/settings.yaml` always ships in full regardless of tool selection (it is shared infra, never a per-family staged/omitted file), so an undeclared `config_keys` entry has no build-time omission consequence — it is genuinely informational-only as the catalog's own comment states, unlike `deps.modules`/`deps.ps1` which directly drive staging.

4. Pre-existing, not introduced by this change (already flagged in apply-progress and reconfirmed by this verification's live build #2): `tools/fake_file_search_adapter.py` and `tools/fake_onenote_adapter.py` (test-only fakes) are staged into every build via the `tools/*.py` glob; `make-deploy-package.sh`'s exclusion grep pattern only lists the three older fakes (`fake_adapter`, `fake_task_adapter`, `fake_mail_adapter`). Manifest hygiene nit, not a hard-exclusion defect (fakes are never registered as tools regardless).

**SUGGESTION**:
1. The five spec scenarios marked PARTIAL in the compliance matrix above (installer-prompt behavior and Gate-7's-own-failure-path) are all sound by construction/code inspection but have no independent automated proof. Four of the five are legitimately Windows-only and already correctly deferred to Phase 5. The fifth (Gate 7 failing when an excluded file leaks into staging) *could* be tested on this Linux host — e.g. a small script-level test that monkeypatches the staged-file list to include a known-excluded file and confirms Gate 7's Python check block exits 1 — but this is a nice-to-have given the check's logic is simple and mirrors an already-tested pure function (`excluded_files()`).

---

### Warnings closed (Batch 4)

Both WARNINGs above are now closed by a dedicated apply batch (tasks 4.5/4.6). Summary (full detail in apply-progress.md):

1. **WARNING 1 closed** — `tests/test_server.py` gained
   `test_present_but_internally_broken_family_module_still_raises_not_swallowed`
   and its inverse control,
   `test_genuinely_absent_family_module_still_imports_cleanly`. Both run a
   real `python -c "import server"` subprocess (not an in-process
   `importlib.reload`) against a hermetic `tmp_path` copy of the real
   `tools/`/`models/`/`server.py`, so server.py's module-level `find_spec`
   guards execute genuinely fresh. The bug used is a `ModuleNotFoundError`
   raised from *inside* a present family module (a stray internal import
   referencing a nonexistent module) rather than a plain `SyntaxError` —
   empirically verified (one-off local experiment, not shipped) that a
   `SyntaxError`-based version would pass identically whether the guard is
   correct or replaced by the exact `try: ... except ImportError:`
   anti-pattern this test exists to catch (since `SyntaxError` is never an
   `ImportError` subclass), so it would not have been RED against that
   regression. The `ModuleNotFoundError`-shaped bug is: with the real,
   current `find_spec`-gated `server.py`, the new test is GREEN (bug
   propagates, exit nonzero); with `tools/calendar.py`'s guard temporarily
   rewritten to the blind `try/except ImportError` shape (edit made,
   verified RED, then immediately reverted — `server.py` restored
   byte-identical, diff-confirmed), the same test goes RED (bug silently
   swallowed, exit 0) — proving the test's protective value. Full suite:
   727 passed (725 + 2 new), 0 regressions.

2. **WARNING 2 closed** — Gate 7's check 5 (import-graph completeness) in
   `make-deploy-package.sh` now also greps every catalog-declared
   dependency module's source for `ps_bridge_*.ps1` string references and
   requires any catalog-tracked bridge script it references to be
   declared in the SAME tool's own `deps.ps1`, mirroring the existing
   module-closure check. Verified live: (a) full build — all 7 gates
   PASS, gate 7's success message now reads "...import-graph completeness
   OK (modules + .ps1 bridge scripts)"; (b) a `--share
   --tools=onenote_search,onenote_get_page` build — all 7 gates PASS;
   (c) negative case — temporarily removed `tools/ps_bridge_search.ps1`
   from `file_search`'s `deps.ps1` directly in the real `tools/
   catalog.yaml` (the script has no alternate-catalog-path flag), ran the
   full build, confirmed Gate 7 failed with `file_search:
   tools/file_search_adapter.py references tools/ps_bridge_search.ps1,
   which is catalog-tracked but not declared in file_search's own
   deps.ps1 ...`, then immediately restored `catalog.yaml` from a backup
   (diff-confirmed byte-identical) before re-running the full build to
   confirm all 7 gates PASS again; (d) full pytest suite green (727)
   after restoration. No `catalog.yaml` change was needed for the current
   codebase — the existing `ps1` declarations were already complete; this
   batch only added the missing *check*.

Both fixes are test/tooling-only — no production runtime code
(`server.py`'s guards, `tools/catalog.py`, `tools/settings.py`) changed in
this batch.

---

### Verdict

**PASS WITH WARNINGS**

All success criteria from proposal.md are met and independently re-verified live: a share build can hard-exclude a family (files physically absent from the zip); `server.py` imports successfully with an excluded family's files absent; `shipped-tools.json`/installer never list an excluded family; the full/default build is unaffected (all gates pass, 115 files, 13/13 shipped); README documents the exclusion's explicit protection limits. The full suite is green at exactly 725 (705 baseline + 20 new), with zero regressions and `test_file_search_adapter.py` untouched at 87/87. The two WARNINGs are test-coverage gaps in defense-in-depth around the two most safety-critical guarantees in this change (guard-shape correctness under a genuine present-module bug; `.ps1`-dependency completeness) — neither reflects a currently-broken behavior, both are recommended for a small follow-up task before or shortly after archive.
