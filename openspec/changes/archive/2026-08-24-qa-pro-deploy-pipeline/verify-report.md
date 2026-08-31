# Verify Report: qa-pro-deploy-pipeline

**Change**: qa-pro-deploy-pipeline
**Version**: N/A (no version field in specs)
**Mode**: Strict TDD (hybrid convention per design: TDD for `deploy/smoke_test.py`, script-gate + manual for `deploy-qa.sh`/`promote-pro.sh`)
**Date**: 2026-08-24

---

### Completeness

| Metric | Value |
|--------|-------|
| Tasks total | 22 |
| Tasks complete | 22 |
| Tasks incomplete | 0 |

All 22 tasks across Phases 1-8 are checked `[x]` in `tasks.md`, including the 3 manual Phase 8 tasks. Apply-progress records 3 automated batches (Phases 1-3, 4-5, 6-7) plus a Phase 8 section appended after real Windows-host execution.

---

### Build & Tests Execution

**Build**: ➖ N/A (no build step for this Python/bash project; package rebuild verified separately below)

**Tests**: ✅ 161 passed / ❌ 0 failed / ⚠️ 0 skipped

```
.venv/bin/python3.12 -m pytest -q
........................................................................ [ 44%]
........................................................................ [ 89%]
.................                                                        [100%]
161 passed in 1.48s
```

161 = the expected full suite (includes 9 tests from the separately-applied `com-coinitialize-hotfix` change applied the same day; not counted toward this change's own delta). This change's own contribution is the 13 tests in `tests/test_smoke_test.py`, confirmed in isolation:

```
.venv/bin/python3.12 -m pytest -q tests/test_smoke_test.py
.............
13 passed in 0.67s
```

Apply-progress's own running totals (152 at end of Batch 3, pre-hotfix) plus the 9-test hotfix delta reconcile to 161 — consistent, no discrepancy.

**Coverage**: ➖ Not available (`pytest-cov` not installed per `openspec/config.yaml` testing capabilities; informational only, not blocking per Strict TDD Verify rules).

---

### TDD Compliance

| Check | Result | Details |
|-------|--------|---------|
| TDD Evidence reported | ✅ | Full "TDD Cycle Evidence" table present in apply-progress Batch 1 for tasks 1.1-3.5 |
| All tasks have tests | ✅ | 5/5 TDD-scoped task groups (1.1-1.2, 2.1-2.4, 2.5, 3.1-3.2, 3.4-3.5) have `tests/test_smoke_test.py` cases |
| RED confirmed (tests exist) | ✅ | All 13 test cases exist in `tests/test_smoke_test.py`, verified by direct read |
| GREEN confirmed (tests pass) | ✅ | 13/13 pass on execution (see above) |
| Triangulation adequate | ✅ | `aggregate_verdict`: 4 cases (all-pass, warn-degrades, fail-wins, 5-way mixed); `run_family`: 5 distinct scenarios (hit-chain, empty, warn-hint, other-error, internal-catch); `format_summary`: 2 cases |
| Safety Net for modified files | ✅ | `deploy/smoke_test.py` modified — apply-progress reports baseline 139/139 before Batch 1, confirmed green before each sub-batch |

**TDD Compliance**: 6/6 checks passed

Phases 4-5 (`deploy-qa.sh`/`promote-pro.sh`) and Phases 6-7 (docs/legacy-removal/rebuild) are correctly out of Strict TDD scope per `design.md`'s own Testing Strategy table ("Script-gate: `bash -n`" / manual) and apply-progress's explicit "Mode: Standard" declarations for Batches 2 and 3 — this is the documented hybrid convention, not a TDD violation.

---

### Test Layer Distribution

| Layer | Tests | Files | Tools |
|-------|-------|-------|-------|
| Unit | 12 | 1 (`tests/test_smoke_test.py`) | stdlib + pytest |
| Integration | 1 | 1 (same file — `test_expected_tools_matches_server_registered_names`, FastMCP in-process `Client` against real `server.py` + fake adapters) | fastmcp |
| E2E | 0 | — | not available in this environment (Windows/Outlook required) — covered instead by Phase 8 manual/live evidence |
| **Total** | **13** | **1** | |

Script-gate layer (not pytest): `deploy-qa.sh`/`promote-pro.sh` verified via `bash -n` (both pass, confirmed independently below) and by direct code inspection against every `qa-pro-deploy-workflow` requirement. `shellcheck` is not installed on this host (confirmed via `which shellcheck`); its absence is recorded, not a failure, per task 4.2/5.2 wording ("shellcheck if installed").

---

### Assertion Quality

Scanned all 13 tests in `tests/test_smoke_test.py` (23 `assert` statements total) for the banned patterns in the Strict TDD assertion-quality audit:

- No tautologies (`assert True`, `expect(true).toBe(true)` equivalents) — none found.
- No assertions divorced from production-code calls — every test calls `aggregate_verdict`, `run_family`, `do_tools_list`, or `format_summary` directly.
- No ghost loops over possibly-empty collections as the sole assertion.
- Empty-collection assertions (`detail_calls == []` in the empty-search test) have a companion non-empty-chain test (`test_search_hit_chains_the_detail_call_on_entry_id`) exercising the opposite branch — not an orphan.
- No CSS/implementation-detail coupling (no UI, N/A for this test suite).
- No mocks used at all (a hand-written `StubServer` duck-type, not `unittest.mock`) — mock-heavy ratio check N/A.
- Triangulation: each behavior has 2+ test cases asserting different expected values (e.g. `pass`/`warning`/`fail` are each independently exercised, not just checked for "not None").

**Assertion quality**: ✅ All assertions verify real behavior

---

### Quality Metrics

**Linter**: ➖ Not available (no linter configured per `openspec/config.yaml`)
**Type Checker**: ➖ Not available (no type checker configured)

---

### Spec Compliance Matrix

**smoke-test-coverage**

| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Expected Tool Set Matches Registered Tools | A registered tool is missing from tools/list | `tests/test_smoke_test.py::test_tools_list_missing_tool_fails_naming_it` | ✅ COMPLIANT |
| Expected Tool Set Matches Registered Tools | (implicit: EXPECTED_TOOLS == server's 7 tools) | `tests/test_smoke_test.py::test_expected_tools_matches_server_registered_names` | ✅ COMPLIANT |
| Per-Family Live Steps and Search-and-Chain | Search hit chains the detail call | `tests/test_smoke_test.py::test_search_hit_chains_the_detail_call_on_entry_id` | ✅ COMPLIANT |
| Per-Family Live Steps and Search-and-Chain | Empty search result passes without chaining | `tests/test_smoke_test.py::test_empty_search_result_passes_without_chaining` | ✅ COMPLIANT |
| Per-Family Live Steps and Search-and-Chain | "...a fake server erroring on initialize FAILS the run before any family step runs" (second clause of the same scenario) | (none — no dedicated automated test) | ⚠️ PARTIAL |
| Per-Family Verdict Classification | Outlook-unavailable error yields WARN, not FAIL | `tests/test_smoke_test.py::test_outlook_unavailable_error_yields_warning_not_fail` | ✅ COMPLIANT |
| Per-Family Verdict Classification | (implicit: other error yields FAIL) | `tests/test_smoke_test.py::test_other_error_yields_fail_not_warning` | ✅ COMPLIANT |
| Pure Aggregate Verdict Function | Any FAIL wins over WARN | `tests/test_smoke_test.py::test_any_fail_wins_over_warning` (+ `test_mixed_combo_all_three_present_fails`) | ✅ COMPLIANT |
| Pure Aggregate Verdict Function | WARN with no FAIL degrades the verdict | `tests/test_smoke_test.py::test_warning_with_no_fail_degrades_the_verdict` | ✅ COMPLIANT |
| Pure Aggregate Verdict Function | (implicit: all PASS) | `tests/test_smoke_test.py::test_all_pass_yields_smoke_test_passed` | ✅ COMPLIANT |
| Human-Eyeball-Friendly Output | Output includes one line per family and a final verdict | `tests/test_smoke_test.py::test_format_summary_one_line_per_family_and_final_verdict` (+ `test_format_summary_all_pass_final_line`) | ✅ COMPLIANT |
| Live Execution Is Manual-Verification-Only | Manual verification on the Windows target | Live evidence: apply-progress Phase 8.2 — real `test.bat`-equivalent run, `SMOKE TEST PASSED` observed with all 4 families exercising real hit-chains | ✅ COMPLIANT (behavioral, non-pytest, per spec's own design) |

**qa-pro-deploy-workflow** (script-gate + manual per spec; no pytest layer applies)

| Requirement | Scenario | Verification | Result |
|-------------|----------|--------------|--------|
| Zip Resolution for Both Scripts | Defaults and mismatch-refusal resolve correctly | Code inspection: `deploy-qa.sh` L22-28 (arg-or-newest-by-mtime), `promote-pro.sh` L48-58 + L64-75 (marker-default + sha256 mismatch refusal + `--force`). Default-path resolution independently hand-verified in apply-progress Batch 3 against real `dist/` contents. Mismatch-refusal branch itself not exercised live. | ⚠️ PARTIAL (structurally complete, default path live-verified, refusal branch code-verified only) |
| QA Folder Fully Wiped, Top-Level Folder Renamed | Prior install wiped, contents unnested | Code inspection: `deploy-qa.sh` L34-52 (`rm -rf`, `mktemp -d`, existence check, `mv`). Live: Phase 8.1, run twice, clean from-scratch install both times. | ✅ COMPLIANT |
| Non-Interactive Windows Installer Invocation | Installer completes without blocking | Code: both scripts invoke `cmd.exe /c "...install.bat" < /dev/null` (L67 `deploy-qa.sh`, L120 `promote-pro.sh`). Live: Phase 8.1/8.3, non-interactive install confirmed both times, UNC warning cosmetic as designed. | ✅ COMPLIANT |
| QA Isolation, Marker, and Test Instruction | PRO untouched, marker and instruction present | Code: `deploy-qa.sh` never references `$PRO_DIR`/PRO path except in comments/echo text (grep-confirmed). Live: `QA-VALIDATED.txt` exists on disk at `/mnt/c/usr/WinMCP-qa/QA-VALIDATED.txt` with correct `zip:`/`sha256:`/`validated_utc:` schema. | ✅ COMPLIANT |
| Hard Gate on a Live PRO Process | Live process blocks; its absence allows promotion | Code: `promote-pro.sh` L77-99 (`Get-CimInstance` query, PID grep, refusal). Live: Phase 8.3 — refused with real live PIDs (34252, 37124) and exit code 1 while Claude Desktop was open; promoted successfully once closed. Strongest live evidence in this change. | ✅ COMPLIANT |
| PRO Extraction and Promotion Side Effects | .venv preserved, wheels replaced, audit trail written | Code: `promote-pro.sh` L102-140. Live: `DEPLOYED.txt` exists at `/mnt/c/usr/WinMCP/DEPLOYED.txt` (correct schema), OneDrive `_OUT` folder contains `WinMCP-20260824.zip`, restart reminder printed per Phase 8.3. `.venv` preservation confirmed by design (`unzip -o` semantics, never touches `.venv/`) and by the post-promote smoke test passing (proves the venv/tools were intact). | ✅ COMPLIANT |
| Fail-Fast, but a UNC-CWD Warning Is Not a Failure | Real failure aborts; cosmetic UNC warning does not | Code: `set -euo pipefail` (L14 both scripts); exit-code-only check around `cmd.exe` calls, UNC text never grepped. Live: Phase 8.1/8.3 note "UNC warning cosmetic as designed". | ✅ COMPLIANT |
| Legacy Deploy Script Removed | deploy.sh absent; full flow confirmed manually | `dist/deploy.sh` confirmed absent from filesystem. Full QA→PRO flow confirmed live end-to-end per Phase 8. | ✅ COMPLIANT |

**Compliance summary**: 16/18 scenario-rows COMPLIANT, 2 PARTIAL, 0 FAILING, 0 UNTESTED.

---

### Correctness (Static — Structural Evidence)

| Requirement | Status | Notes |
|------------|--------|-------|
| `EXPECTED_TOOLS` == 7 registered tools | ✅ Implemented | `deploy/smoke_test.py` L50-58 lists exactly the 7 names; cross-checked against `server.py`'s 7 `@app.tool(name=...)` decorators (L142, 156, 168, 178, 200, 212, 235) — exact match |
| `FAMILIES` table (4 families) | ✅ Implemented | L410-439, calendar/tasks/mail-inbox/mail-sent, correct search/detail tool pairing per design |
| `run_family`/`aggregate_verdict`/`format_summary` pure-ish contracts | ✅ Implemented | Signatures match design.md's "Interfaces / Contracts" verbatim (dict-keyed, not list — see Coherence note below) |
| `deploy-qa.sh` full spec coverage | ✅ Implemented | All 7 requirement clauses present and correctly wired (see Spec Compliance Matrix) |
| `promote-pro.sh` full spec coverage | ✅ Implemented | All 7 requirement clauses present and correctly wired, including the security-critical lock gate |
| `dist/deploy.sh` removed | ✅ Implemented | Confirmed absent; only reference left is a historical comment in `promote-pro.sh` L103 ("Same mechanics as the retired dist/deploy.sh") and one README prose mention, both intentional/inert |
| README documents QA→PRO flow accurately | ✅ Implemented | README.md L326-385 walks build→deploy-qa→manual validate→promote-pro→restart; verdict strings, marker schema, and lock-gate behavior all match the actual scripts |
| `smoke_test.py` stdlib-only | ✅ Implemented | Only `argparse`, `itertools`, `json`, `os`, `queue`, `subprocess`, `sys`, `threading`, `time`, `collections.namedtuple`, `datetime.datetime` imported — no third-party packages |
| Verdict strings byte-identical to originals | ✅ Implemented | Diffed against `dist/WinMCP-20260731.zip` and `dist/WinMCP-20260729.zip`'s bundled `smoke_test.py` (pre-change) — `"SMOKE TEST FAILED"`, `"SMOKE TEST PASSED WITH WARNINGS"`, `"SMOKE TEST PASSED"` are byte-identical in both old and new |

---

### Coherence (Design)

| Decision | Followed? | Notes |
|----------|-----------|-------|
| Family model / `TOTAL_STEPS` | ✅ Yes | `Family` namedtuple, `TOTAL_STEPS = 3 + len(FAMILIES)` — verbatim |
| Calendar detail tool = `calendar_get_event` | ✅ Yes | Confirmed in `FAMILIES` table L415 |
| Empty search result → PASS, no chain | ✅ Yes | `run_family` L384-385 |
| Verdict strings reused verbatim | ✅ Yes | Confirmed byte-identical (see Correctness table) |
| JSON-RPC ids: shared `itertools.count(1)` | ✅ Yes | `main()` L524, threaded through `do_initialize`/`do_tools_list`/`run_family`/`_call_tool` |
| Handshake vs. family failure isolation | ✅ Yes | `main()` L525-544 (handshake `StepFailed` aborts outright) vs. `run_family` L400-403 (catches internally) |
| QA install: full wipe + mktemp + mv | ✅ Yes | `deploy-qa.sh` L34-52 |
| PRO install: wipe wheels + `unzip -o` (preserves `.venv`) | ✅ Yes | `promote-pro.sh` L107-111 |
| PRO lock gate via `Get-CimInstance` | ✅ Yes | `promote-pro.sh` L77-99; live-proven against real PIDs |
| Marker format: plain `key: value` lines | ✅ Yes | Confirmed live on disk, exact schema match |
| `promote-pro.sh` zip default + sha256 refusal | ✅ Yes | L48-75; apply-progress notes the sha256 check runs unconditionally (stricter than design's literal wording — a documented, safe deviation, not a gap) |
| Non-interactive install via `cmd.exe /c ... </dev/null` | ✅ Yes | Both scripts, confirmed |
| **`aggregate_verdict` signature: spec prose (list) vs design (dict)** | ⚠️ Deviated from spec prose, followed design | See dedicated note below |

**Dict-vs-list `aggregate_verdict` signature note** (flagged by apply-progress Batch 1, re-verified here): `specs/smoke-test-coverage/spec.md`'s scenario prose writes `family_results` as bracketed list literals (`[PASS, WARN, FAIL]`), while `design.md`'s "Interfaces / Contracts" section types it as `dict[str, str]`. The implementation (`deploy/smoke_test.py` L82-93) uses a dict keyed by family name, matching design.md, not the spec's list notation. This is a **documentation-precision issue, not a functional defect**: the truth-table semantics (any fail→FAIL, elif any warning→WARN, else PASS) are identical regardless of container type, and all 4 truth-table tests pass with the dict-based implementation. Design.md is the more precise, binding source for an actual function signature per SDD convention (specs describe behavior/scenarios; design specifies interfaces). No CRITICAL/WARNING — recommend a SUGGESTION-level spec wording fix at archive time (reword the scenario tables to describe verdict values, not a literal list argument), but this does not block archival.

---

### Issues Found

**CRITICAL** (must fix before archive):
None.

**WARNING** (should fix):
1. `specs/smoke-test-coverage/spec.md`'s "Empty search result passes without chaining" scenario bundles two independent claims in one scenario block — the empty-result-passes assertion (tested) and a separate "fake server erroring on `initialize` FAILS the run before any family step runs" assertion (not covered by any automated test in `tests/test_smoke_test.py`). The behavior is structurally correct by code inspection (`main()` L525-544: a handshake `StepFailed` — which `do_initialize` raises on an `"error"` key in the response, per L265-266 — returns before the family loop at L546 ever starts), and is indirectly reinforced by the live Phase 8 evidence path (a working handshake was a precondition for every real run), but there is no dedicated unit test that scripts a `StubServer` to fail `initialize` and asserts zero family calls occurred. Low severity: this is the least novel part of the change (handshake failure handling existed before this change and is unmodified `StepFailed`-catching logic), but it is a real gap against the spec's own scenario text.

**SUGGESTION** (nice to have):
1. Reword `specs/smoke-test-coverage/spec.md`'s `aggregate_verdict` scenario tables to describe verdict *values* rather than literal `[PASS, WARN, FAIL]` list arguments, to remove the prose-vs-design-contract ambiguity flagged in apply-progress Batch 1 and re-confirmed above. Purely a documentation clarity fix; no behavior change needed.
2. Split the "Empty search result passes without chaining" scenario in the same spec file into two separate scenarios (one for the empty-result case, one for the initialize-failure case) — this would have made the WARNING above visible as an explicit UNTESTED scenario rather than a half-covered one, and is good practice regardless of whether a test gets added for the initialize-failure half.
3. Consider adding one lightweight automated test asserting that an `initialize`-erroring `StubServer` causes `main()` (or a testable slice of it) to short-circuit before any family runs — would fully close the WARNING above at low cost, reusing the existing `StubServer`/`_rpc_error` fixtures already in `tests/test_smoke_test.py`.

---

### Live Evidence Cross-Check (Phase 8, trusted per launch instructions)

All claimed live evidence was independently re-verified against artifacts still present on disk at verification time:

| Claim | Verification | Result |
|---|---|---|
| `deploy-qa.sh` ran, wrote `QA-VALIDATED.txt` | `/mnt/c/usr/WinMCP-qa/QA-VALIDATED.txt` exists, correct schema, zip `WinMCP-20260824.zip`, sha256 present, `validated_utc: 2026-08-24T12:01:23Z` | ✅ Confirmed |
| `promote-pro.sh` promoted, wrote `DEPLOYED.txt` | `/mnt/c/usr/WinMCP/DEPLOYED.txt` exists, correct schema, same zip name, `deployed_utc: 2026-08-24T12:02:13Z` (59s after QA validation — plausible manual gap) | ✅ Confirmed |
| Zip copied to OneDrive `_OUT` | `/mnt/c/co/od/_DEV/WinMCP/_OUT/WinMCP-20260824.zip` present (32,366,044 bytes, Aug 24 14:02) alongside the older `WinMCP-20260729.zip` | ✅ Confirmed |
| PRO's deployed `smoke_test.py` still carries the exact verbatim verdict strings | `grep "SMOKE TEST" /mnt/c/usr/WinMCP/smoke_test.py` → all 3 strings present, byte-identical | ✅ Confirmed |
| Post-hotfix re-promotion (com-coinitialize-hotfix, same day) | `DEPLOYED.txt`'s sha256 (`f94a6e2b...`) differs from the pre-hotfix sha256 quoted in apply-progress Batch 3 (`c9f1225e...`) — consistent with the narrated "fixed in `com-coinitialize-hotfix` and re-promoted the same day" | ✅ Consistent, not a discrepancy |

---

### Verdict

**PASS WITH WARNINGS**

The change is functionally complete, all 161 tests pass (13 net-new to this change, matching apply-progress's TDD evidence exactly), both shell scripts pass `bash -n` and satisfy every `qa-pro-deploy-workflow` requirement by direct code inspection, real live execution evidence (QA install, smoke PASSED, promotion refusal with live PIDs, promotion success, post-promote smoke PASSED, and the CoInitialize WARN-path proving itself live) is corroborated by artifacts still on disk, `dist/deploy.sh` is gone and unreferenced except in intentional historical comments, and README accurately documents the actual script behavior. One WARNING (a spec scenario's second clause — initialize-failure isolation — lacks a dedicated automated test, though it is code-inspection-verified and behaviorally unmodified from pre-existing handling) and a pre-existing dict-vs-list spec/design wording mismatch (already self-flagged in apply-progress, non-blocking) keep this from a clean PASS. Neither issue blocks archival.
