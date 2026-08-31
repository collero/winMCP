# Archive Report: config-live-folders

**Date Archived**: 2026-08-24  
**Verification Status**: PASS (174/174 tests, all scenarios compliant, 6/6 TDD checks)  
**Artifact Store**: openspec

---

## Change Summary

**Change**: config-live-folders

**Intent**: Close dead-config debt by making all three real Outlook adapters resolve their folder ids lazily from `config/settings.yaml` at COM-access time, with fallback to documented defaults. Reverses the `outlook-mail-read` decision to omit `inbox_folder_id`/`sent_folder_id` keys — now live alongside other configured keys.

**Scope**:
- Wire `OutlookCalendarAdapter` to read `calendar_folder_id` (default `9`)
- Wire `OutlookTaskAdapter` to read `tasks_folder_id` (default `13`)
- Wire `OutlookMailAdapter` to read `inbox_folder_id` (default `6`) and `sent_folder_id` (default `5`)
- Add new keys to `config/settings.yaml` with doc comments
- Update README "Configuration" section and `pyproject.toml`
- All via Strict TDD: 9 new tests, 18 total tasks, full suite green at 174 passed

---

## Specs Synced

| Domain | Action | Requirements | Details |
|--------|--------|--------------|---------|
| outlook-com-adapter | Updated (MERGED) | **Configurable Folder Ids** (7 scenarios ADDED) | Delta spec merged into main spec at `/openspec/specs/outlook-com-adapter/spec.md`. New requirement appended to Requirements section (after existing 5 requirements). 7 scenarios cover: calendar configured-value, calendar absent-key-default, tasks configured-value, tasks absent-key-default, mail inbox+sent configured-values, mail inbox+sent absent-key-defaults, literal-key-in-settings.yaml. All 7 scenarios compliant per verify-report. |

**Merge Details**:
- Existing requirements preserved: Adapter Interface, Lazy COM Import, Per-Thread COM Initialization, Real Adapter COM Access, Adapter Selection at Runtime
- New requirement "Configurable Folder Ids" appended as the 6th requirement
- Maintains Markdown formatting and heading hierarchy consistency
- No destructive changes; all prior content intact

---

## Archive Contents

All SDD artifacts present and verified:

- **proposal.md** ✅ — intent, reversal rationale, scope (6 areas modified), risk (low), rollback plan
- **specs/** ✅ — `outlook-com-adapter/spec.md` (delta spec, 7 scenarios for Configurable Folder Ids)
- **design.md** ✅ — (not created; expedited hotfix-style change by design per task instructions, not flagged as gap)
- **tasks.md** ✅ — 18 tasks (5 phases: Baseline + Calendar/Task/Mail adapters + Config/Docs/Suite)
- **apply-progress.md** ✅ — TDD Cycle Evidence table, task completion record, 165 baseline + 9 new = 174 passed
- **verify-report.md** ✅ — PASS verdict, 174/174 tests, all 7 spec scenarios compliant, 6/6 TDD checks, zero CRITICAL/WARNING issues

---

## Source of Truth Updated

The main spec now reflects the new behavior:

**File**: `/home/master/WinMCP/openspec/specs/outlook-com-adapter/spec.md`

**Changes**:
- Added complete "Configurable Folder Ids" requirement section (7 scenarios)
- Requirement defines lazy resolution from `config/settings.yaml` at COM-access time
- Fallback defaults: calendar=9, tasks=13, inbox=6, sent=5
- Covers absence, configuration, and literal-key-in-settings.yaml cases
- Requirement fully traceable to implementation code and tests (per verify-report)

---

## Implementation Verification (from verify-report)

| Aspect | Result | Evidence |
|--------|--------|----------|
| **Spec Compliance** | PASS 7/7 scenarios | All scenarios tested and passing per verify-report spec-compliance matrix |
| **Code Implementation** | ✅ | Lazy `_resolve_folder_id()` in all 3 adapters, called fresh on every `search()`; fallback defaults as module constants; try/except wrapping for unreadable settings.yaml |
| **Configuration** | ✅ | `config/settings.yaml` has all 4 keys with documented defaults; `README.md` "Configuration" section documents all 6 keys; `pyproject.toml` mentions all three tool families |
| **TDD Compliance** | ✅ 6/6 checks | RED confirmed (9 new tests present and initially failing), GREEN confirmed (174 passed), triangulation adequate (2+ cases per adapter with distinct numeric values), safety net confirmed (pre-fix pass counts recorded for modified files) |
| **Test Execution** | ✅ 174/174 passed | `.venv/bin/python3.12 -m pytest -q` confirmed 174 passed (165 baseline + 9 new), zero regressions, zero skipped |
| **Assertion Quality** | ✅ | All 9 assertions verified real behavior (assert_called_once_with distinct values: 42/9, 99/13, 61+51/6+5; literal-key tests assert exact values against production code). No tautologies, no type-only checks, no ghost loops. |

**Zero Blockers**:
- No CRITICAL issues
- No WARNING issues (settings-unreadable fallback path is implemented symmetrically but untested; noted as low-priority suggestion)
- Two suggestions (settings-error-path dedicated test, stale build artifacts noted for eventual rebuild)

---

## Monday.com Integration

**Status**: SKIPPED — Monday integration disabled for this change. No item id provided; no closeout required.

---

## Archive Structure

```
openspec/changes/archive/2026-08-24-config-live-folders/
├── proposal.md
├── specs/
│   └── outlook-com-adapter/
│       └── spec.md (delta spec)
├── design.md (none, not created)
├── tasks.md (all 18 marked complete)
├── apply-progress.md (TDD cycle evidence)
├── verify-report.md (PASS verdict)
└── archive-report.md (this file)
```

---

## SDD Cycle Complete

✅ **Proposal** — intent and scope defined, risk assessed (low), rollback plan documented  
✅ **Spec** — delta spec created (7 scenarios for new requirement)  
✅ **Design** — N/A (expedited hotfix-style by design)  
✅ **Tasks** — 18 tasks defined (Phases 0-5)  
✅ **Apply** — all tasks completed, 9 new tests added, 174 passed (TDD Cycle Evidence recorded)  
✅ **Verify** — PASS, all 7 scenarios compliant, 6/6 TDD checks, zero blockers  
✅ **Archive** — specs merged into main spec, change folder moved to archive, this report written  

**Next Steps**: Ready for deployment. No package rebuild in this change (deferred to later combined rebuild per task instructions).

---

## Audit Trail

| Artifact | Location | Observation ID |
|----------|----------|---|
| Proposal | `archive/2026-08-24-config-live-folders/proposal.md` | N/A (openspec mode) |
| Spec (Delta) | `archive/2026-08-24-config-live-folders/specs/outlook-com-adapter/spec.md` | N/A (openspec mode) |
| Design | N/A (not created) | N/A |
| Tasks | `archive/2026-08-24-config-live-folders/tasks.md` | N/A (openspec mode) |
| Apply Progress | `archive/2026-08-24-config-live-folders/apply-progress.md` | N/A (openspec mode) |
| Verify Report | `archive/2026-08-24-config-live-folders/verify-report.md` | N/A (openspec mode) |
| Main Spec (Merged) | `/openspec/specs/outlook-com-adapter/spec.md` | N/A (openspec mode) |

**Artifact Store**: openspec (file-based, all artifacts committable with git history)

---

## Closing Remarks

The change successfully closes a long-standing configuration debt by wiring all three Outlook adapters to resolve their folder ids lazily from `config/settings.yaml`, with sensible fallbacks. The delta spec's 7 scenarios are comprehensively tested and compliant. The spec merge is complete and non-destructive. The change is production-ready.

**Archived by**: sdd-archive phase  
**SDD Version**: 1.0 (openspec mode)
