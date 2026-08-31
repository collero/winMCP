# Verify Report: config-live-folders

**Change**: config-live-folders
**Version**: N/A (expedited hotfix-style change, no design.md — by design, not flagged)
**Mode**: Strict TDD

---

### Completeness

| Metric | Value |
|--------|-------|
| Tasks total | 18 |
| Tasks complete | 18 |
| Tasks incomplete | 0 |

All tasks across Phases 0-5 are checked off. No incomplete tasks.

---

### Build & Tests Execution

**Build**: ➖ Not applicable (no build/type-check tooling configured for this project beyond pytest; deliberately no package rebuild in this change per tasks.md's closing note — deferred to a later combined rebuild)

**Tests**: ✅ 174 passed / 0 failed / 0 skipped

```
$ .venv/bin/python3.12 -m pytest -q
........................................................................ [ 41%]
........................................................................ [ 82%]
..............................                                           [100%]
174 passed in 1.99s
```

Matches the expected total exactly: 165 baseline + 9 new = 174.

**Coverage**: ➖ Not available (no coverage tool detected/configured in this project)

---

### TDD Compliance

| Check | Result | Details |
|-------|--------|---------|
| TDD Evidence reported | ✅ | `apply-progress.md` contains a complete "TDD Cycle Evidence" table for all 3 adapter tasks |
| All tasks have tests | ✅ | 3/3 adapter tasks have dedicated test files (`test_outlook_adapter.py`, `test_task_adapter.py`, `test_mail_adapter.py`) |
| RED confirmed (tests exist) | ✅ | All 9 new tests verified present in the codebase at the reported locations |
| GREEN confirmed (tests pass) | ✅ | 174/174 pass on real execution (this run), matching apply-progress's reported 174 |
| Triangulation adequate | ✅ | Each adapter has 2 behavioral cases (configured-value + absent-key-default) using distinct numeric values (42/9, 99/13, 61+51/6+5) plus 1 literal-key test — no single-case behaviors |
| Safety Net for modified files | ✅ | apply-progress reports pre-fix in-file pass counts (15/15, 17/17, 20/20) for the three modified adapter files before the fix landed |

**TDD Compliance**: 6/6 checks passed

Note on RED confirmation technique: since this project has no git repo, RED was confirmed by temporarily reverting `_resolve_folder_id()` to `return _DEFAULT_*_FOLDER_ID` and re-running the new tests in isolation (documented "Command Log (RED confirmation)" in apply-progress.md, showing 3 failures). This is a legitimate substitute for `git stash`-based RED confirmation and is verifiable in principle (the described revert-and-rerun is exactly what would make these assert_called_once_with(42)-style assertions fail against the old hardcoded-constant code).

---

### Test Layer Distribution

| Layer | Tests | Files | Tools |
|-------|-------|-------|-------|
| Unit | 9 | 3 | pytest + pytest-mock (`mocker.patch`, fake `win32com.client` injected into `sys.modules`) |
| Integration | 0 | 0 | not installed |
| E2E | 0 | 0 | not installed |
| **Total** | **9** | **3** | |

Consistent with the rest of the project's test suite (COM adapters are tested exclusively at the unit layer via injected fakes, per the outlook-com-adapter spec's "Lazy COM Import" design).

---

### Changed File Coverage

Coverage analysis skipped — no coverage tool detected in this project (no `pytest-cov`, no coverage config found).

---

### Assertion Quality

Reviewed all 9 new test functions in `tests/test_outlook_adapter.py`, `tests/test_task_adapter.py`, `tests/test_mail_adapter.py`.

| File | Line | Assertion | Issue | Severity |
|------|------|-----------|-------|----------|
| — | — | — | none found | — |

**Assertion quality**: ✅ All assertions verify real behavior. Each "configured value" test asserts `GetDefaultFolder.assert_called_once_with(<distinct non-default value>)` (42, 99, 61, 51) and each "absent key" test asserts the corresponding documented default (9, 13, 6, 5) — genuine behavioral assertions with real variance, not tautologies, not type-only checks, not ghost loops. The three literal-key tests assert exact values (`== 9`, `== 13`, `== 6`/`== 5`) against the real unmodified `config/settings.yaml`, exercising production code (`load_settings()`) with no mocking.

---

### Quality Metrics

**Linter**: ➖ Not available (no linter configured in cached testing capabilities)
**Type Checker**: ➖ Not available

---

### Spec Compliance Matrix

Delta spec: `openspec/changes/config-live-folders/specs/outlook-com-adapter/spec.md` — ADDED "Configurable Folder Ids" (7 scenarios).

| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Configurable Folder Ids | Configured calendar folder id is used | `tests/test_outlook_adapter.py::test_search_uses_configured_calendar_folder_id` | ✅ COMPLIANT |
| Configurable Folder Ids | Absent calendar folder id key falls back to the default | `tests/test_outlook_adapter.py::test_search_absent_calendar_folder_id_falls_back_to_default_9` | ✅ COMPLIANT |
| Configurable Folder Ids | Configured tasks folder id is used | `tests/test_task_adapter.py::test_search_uses_configured_tasks_folder_id` | ✅ COMPLIANT |
| Configurable Folder Ids | Absent tasks folder id key falls back to the default | `tests/test_task_adapter.py::test_search_absent_tasks_folder_id_falls_back_to_default_13` | ✅ COMPLIANT |
| Configurable Folder Ids | Configured inbox/sent folder ids are used | `tests/test_mail_adapter.py::test_search_uses_configured_inbox_and_sent_folder_ids` | ✅ COMPLIANT |
| Configurable Folder Ids | Absent inbox/sent folder id keys fall back to the defaults | `tests/test_mail_adapter.py::test_search_absent_folder_ids_fall_back_to_defaults_6_and_5` | ✅ COMPLIANT |
| Configurable Folder Ids | settings.yaml declares every folder-id key live | `tests/test_outlook_adapter.py::test_settings_yaml_declares_calendar_folder_id_9`, `tests/test_task_adapter.py::test_settings_yaml_declares_tasks_folder_id_13`, `tests/test_mail_adapter.py::test_settings_yaml_declares_inbox_and_sent_folder_ids` | ✅ COMPLIANT (jointly cover all 4 keys) |

**Compliance summary**: 7/7 scenarios compliant

---

### Correctness (Static — Structural Evidence)

| Requirement | Status | Notes |
|------------|--------|-------|
| Calendar adapter resolves `calendar_folder_id` lazily at COM-access time | ✅ Implemented | `tools/outlook_adapter.py:78-86` — `_resolve_folder_id()` calls `load_settings()` inside the method (not `__init__`), called from `search()` at `outlook_adapter.py:123`. No `__init__` remains — verified no caching. |
| Tasks adapter resolves `tasks_folder_id` lazily at COM-access time | ✅ Implemented | `tools/task_adapter.py:134-142`, called from `search()` at `task_adapter.py:181`. Same pattern. |
| Mail adapter resolves `inbox_folder_id`/`sent_folder_id` lazily at COM-access time | ✅ Implemented | `tools/mail_adapter.py:65-74` (module-level `_resolve_folder_id(folder)`), called from `search()` at `mail_adapter.py:206`. `_FOLDER_MAP` (line 59-62) carries the settings key per folder. |
| Fallback default matches pre-change hardcoded constant exactly | ✅ Implemented | `_DEFAULT_CALENDAR_FOLDER_ID = 9`, `_DEFAULT_TASKS_FOLDER_ID = 13`, `_FOLDER_MAP` defaults `6`/`5` — identical to the values `config/settings.yaml` ships with, so an unmodified settings.yaml produces byte-for-byte identical `GetDefaultFolder()` calls to the pre-change hardcoded behavior. |
| Settings failure path falls back to default (not raise) | ✅ Implemented | All three adapters wrap `load_settings()` in `try/except Exception: return <default>` (`outlook_adapter.py:82-85`, `task_adapter.py:138-141`, `mail_adapter.py:70-73`) — matches the delta spec's "falling back... when... settings.yaml is unreadable" wording exactly. Not covered by an automated test (no test mocks `load_settings` to raise), but the code path is present, symmetric across all three adapters, and structurally sound. |
| `config/settings.yaml` has new keys with doc comments | ✅ Implemented | `config/settings.yaml:14-19` documents `inbox_folder_id`/`sent_folder_id` in the same header-comment style as the existing keys; values present at lines 29-30. |
| README documents all live keys | ✅ Implemented | `README.md:156-186` "Configuration" section documents all 6 settings.yaml keys including the closing note "Every key above is live." |
| pyproject.toml description mentions all three tool families | ✅ Implemented | `pyproject.toml:4` — "Outlook calendar (...), tasks/to-do (...), and mail (...) tools". |
| API-change ripple: no orphaned `folder_id=` constructor callers | ✅ Implemented | Repo-wide grep of source, tests, and `deploy/` for `OutlookCalendarAdapter(`, `OutlookTaskAdapter(`, `OutlookMailAdapter(` found only zero-arg calls (`server.py:73,87,101`; all test files). No caller passes `folder_id=`. The only remaining `folder_id=...` constructor pattern lives in `build/lib/tools/{outlook_adapter,mail_adapter,task_adapter}.py` — a stale compiled build artifact, not source, and out of scope per tasks.md's explicit note that "no package rebuild in this change — a combined rebuild happens later." |
| No module-level `win32com`/`pythoncom` imports introduced | ✅ Implemented | `grep -n "^import win32com\|^import pythoncom\|^from win32com\|^from pythoncom" tools/*.py` returns nothing — both remain lazy, inside `_dispatch_outlook()`/`_resolve_folder_id()` only. |
| Fake adapters correctly out of scope | ✅ Confirmed | `tools/fake_adapter.py`, `tools/fake_task_adapter.py`, `tools/fake_mail_adapter.py` contain no `folder_id`/`load_settings` references — consistent with the delta spec, which explicitly scopes the requirement to the three *real* adapters only. |

---

### Coherence (Design)

No `design.md` exists for this change — expedited hotfix-style change per the task instructions; its absence is not flagged as a gap.

Cross-checked against the proposal's "Scope" and "Affected Areas" sections instead:

| Decision (from proposal.md) | Followed? | Notes |
|----------|-----------|-------|
| Lazy resolution mirroring `tools/calendar.py::_lookback_days()`, not cached at construction | ✅ Yes | Confirmed — `_resolve_folder_id()` is called fresh on every `search()` invocation; `OutlookCalendarAdapter`/`OutlookTaskAdapter` no longer have an `__init__` at all. |
| Module-level `_DEFAULT_*_FOLDER_ID` constants remain as fallback only | ✅ Yes | Retained unchanged as the `except`/`.get(..., default)` fallback value in both instance-method adapters. |
| Mail adapter mirrors the same lazy, default-on-absence pattern | ✅ Yes | Implemented as a module-level function instead of an instance method — an explicitly documented, reasonable deviation (`OutlookMailAdapter` has no per-instance state; noted in apply-progress's "Deviations from Design" section). |
| `tests/test_mail_tools.py` stale comment corrected | ✅ Yes | `tests/test_mail_tools.py:237-241` — comment now explains `calendar_folder_id`/`tasks_folder_id` were dead only "at the time this comment was first written." |
| Success Criteria: full suite green, 165 pre-existing + new, zero regressions | ✅ Yes | 174 passed confirmed on this run. |

---

### Issues Found

**CRITICAL** (must fix before archive):
None.

**WARNING** (should fix):
None. (The settings-unreadable-at-resolve-time fallback path — see Correctness table — is implemented symmetrically across all three adapters but has no dedicated automated test; this is noted as informational, not a blocker, since the code path is trivial, structurally identical across all three adapters, and the two already-tested paths — configured value and absent key — exercise the same `try/except`+`.get()` machinery.)

**SUGGESTION** (nice to have):
- Consider adding one test (on any single adapter, not all three) that mocks `load_settings` to raise (e.g., `side_effect=FileNotFoundError`) and asserts the fallback default is used, to close the last untested edge of the "or settings.yaml is unreadable" clause in the delta spec's requirement text. Low priority — the `except Exception: return <default>` code is simple enough that behavioral risk is minimal, and this is a hotfix-style expedited change.
- `build/lib/tools/{outlook_adapter,mail_adapter,task_adapter}.py` still contain the pre-change `folder_id=` constructor pattern. This is a known, explicitly deferred (per tasks.md) stale build artifact — flagging only so the eventual "combined rebuild" step is not forgotten before the next deploy/package.

---

### Verdict

**PASS**

All 18 tasks complete, full suite green at the expected 174/174, all 7 spec scenarios behaviorally compliant with real passing tests, TDD evidence complete and cross-validated (6/6 checks), assertion quality clean (no trivial/tautological assertions), config/README/pyproject documentation complete and consistent, and the API-change ripple check found zero orphaned `folder_id=` callers in source, tests, or deploy scripts. No CRITICAL or WARNING issues block archive.
