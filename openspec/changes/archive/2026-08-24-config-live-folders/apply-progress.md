# Apply Progress: Live Folder-Id Configuration for All Outlook Adapters

**Mode**: Strict TDD (runner: `.venv/bin/python3.12 -m pytest -q`)

## Baseline

`165 passed` confirmed before any change (Phase 0).

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1/1.2/1.3 Calendar adapter | `tests/test_outlook_adapter.py` | Unit | ✅ 15/15 (pre-fix) | ✅ Written — `test_search_uses_configured_calendar_folder_id` failed (`GetDefaultFolder` called with `9` instead of `42`) when `_resolve_folder_id` was forced to ignore settings | ✅ Passed — 18/18 in file after fix | ✅ 2 cases (configured value + absent-key default) plus literal-key test | ➖ None needed — `_resolve_folder_id()` replaces the `__init__`-cached value in place |
| 2.1/2.2/2.3 Task adapter | `tests/test_task_adapter.py` | Unit | ✅ 17/17 (pre-fix) | ✅ Written — `test_search_uses_configured_tasks_folder_id` failed (`GetDefaultFolder` called with `13` instead of `99`) under the same forced-default probe | ✅ Passed — 20/20 in file after fix | ✅ 2 cases (configured value + absent-key default) plus literal-key test | ➖ None needed |
| 3.1/3.2/3.3 Mail adapter | `tests/test_mail_adapter.py` | Unit | ✅ 20/20 (pre-fix) | ✅ Written — `test_search_uses_configured_inbox_and_sent_folder_ids` failed under the same forced-default probe | ✅ Passed — 23/23 in file after fix | ✅ both folders x 2 cases (configured + absent-key default) plus literal-key test | ➖ None needed — new module-level `_resolve_folder_id(folder)` helper, no existing logic touched beyond the id lookup |

### RED Confirmation Technique

Rather than reverting via git (no git repo in this project), each
adapter's already-drafted `_resolve_folder_id()` body was temporarily
replaced with a one-line `return _DEFAULT_*_FOLDER_ID` (settings ignored)
to reproduce the pre-fix behavior, the new "configured value used" tests
were run in isolation to confirm they fail against that reverted body, and
the real `_resolve_folder_id()` implementation was then restored. This
proves the tests actually exercise the settings-read path rather than
passing vacuously.

### Test Summary

- **Total tests written**: 9 (3 per adapter file: 1 configured-value test +
  1 absent-key-default test + 1 settings.yaml literal-key test)
- **Total tests passing**: 174 (165 baseline + 9 new)
- **Layers used**: Unit (9)
- **Approval tests** (refactoring): None
- **Pure functions created**: `tools/mail_adapter.py::_resolve_folder_id`
  (module-level; the calendar/task adapters use an equivalent instance
  method, `_resolve_folder_id(self)`, since `_FOLDER_MAP` is mail-specific)

## Command Log (RED confirmation)

```
$ .venv/bin/python3.12 -m pytest -q -k "uses_configured or configured_folder_ids"
3 failed, 1 passed, 170 deselected
FAILED tests/test_mail_adapter.py::test_search_uses_configured_inbox_and_sent_folder_ids
FAILED tests/test_outlook_adapter.py::test_search_uses_configured_calendar_folder_id
FAILED tests/test_task_adapter.py::test_search_uses_configured_tasks_folder_id
```

(the 1 "passed" in that run was `test_settings_yaml_declares_mail_lookback_days_90`,
an unrelated pre-existing test matched by the `-k` substring filter, not one
of the 3 new probes)

## Command Log (GREEN + full suite)

```
$ .venv/bin/python3.12 -m pytest -q
174 passed
```

Zero regressions across the full suite (165 baseline + 9 new).

## Files Changed

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/outlook_adapter.py` | Modified | Removed `__init__(folder_id=...)`; added `_resolve_folder_id()` reading `calendar_folder_id` from `load_settings()` at COM-access time, falling back to `_DEFAULT_CALENDAR_FOLDER_ID`; `search()` now calls `self._resolve_folder_id()`. |
| `tools/task_adapter.py` | Modified | Identical fix, mirrored (`tasks_folder_id`, default `13`). |
| `tools/mail_adapter.py` | Modified | `_FOLDER_MAP` values extended with each folder's settings key; new module-level `_resolve_folder_id(folder)` helper; `search()` resolves `folder_id` through it instead of reading `_FOLDER_MAP` directly. Updated the stale "settings.yaml folder ids omitted" comment to record the reversal. |
| `config/settings.yaml` | Modified | Added `inbox_folder_id: 6`, `sent_folder_id: 5` with doc comments matching the file's style. |
| `README.md` | Modified | "Configuration" section documents the two new keys and notes every settings.yaml key is now live. |
| `pyproject.toml` | Modified | `[project].description` now mentions calendar, tasks, and mail tool families. |
| `tests/test_outlook_adapter.py` | Modified | Added 3 tests (configured value, absent-key default, settings.yaml literal-key). |
| `tests/test_task_adapter.py` | Modified | Same additions, mirrored. |
| `tests/test_mail_adapter.py` | Modified | Same additions, mirrored (covers both folders). |
| `tests/test_mail_tools.py` | Modified | Corrected a stale comment calling `calendar_folder_id`/`tasks_folder_id` "dead" — no longer accurate. |
| `openspec/changes/config-live-folders/proposal.md` | Created | Proposal — intent, mail-key reversal rationale, scope, risk, rollback. |
| `openspec/changes/config-live-folders/specs/outlook-com-adapter/spec.md` | Created | Delta spec — ADDED "Configurable Folder Ids" requirement with 7 scenarios. |
| `openspec/changes/config-live-folders/tasks.md` | Created/Updated | Task checklist, all items checked off. |

## Deviations from Design

None — implementation matches the proposal. One implementation detail not
pre-specified: the mail adapter's folder-id resolution is a module-level
function (`_resolve_folder_id(folder)`) rather than an instance method,
since `OutlookMailAdapter` has no `__init__`/per-instance state and
`_FOLDER_MAP` is already a module-level table — keeping the resolver at
the same scope avoids introducing an unnecessary constructor.

## Issues Found

None.

## Status

18/18 tasks complete (Phases 0-5). No package rebuild in this change (per
scope — a combined rebuild happens later, after the next change). Ready
for sdd-verify / archive.
