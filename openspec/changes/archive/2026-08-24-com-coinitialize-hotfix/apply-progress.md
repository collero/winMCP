# Apply Progress: CoInitialize Hotfix for Real Outlook Adapters

**Mode**: Strict TDD (runner: `.venv/bin/python3.12 -m pytest -q`)

## Baseline

`152 passed` confirmed before any change (Phase 0).

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1/1.2 Calendar adapter | `tests/test_outlook_adapter.py` | Unit | ✅ 7/7 (pre-fix) | ✅ Written — `test_search_calls_coinitialize_before_dispatch` + `test_get_event_calls_coinitialize_before_dispatch` failed (`AssertionError: 'CoInitialize' not in ['Dispatch']`) | ✅ Passed — 10/10 in file after fix | ✅ 2 cases (search + get_event call paths) | ➖ None needed — change is a 2-line addition inside existing try/except |
| 2.1/2.2 Task adapter | `tests/test_task_adapter.py` | Unit | ✅ 10/10 (pre-fix) | ✅ Written — `test_search_calls_coinitialize_before_dispatch` + `test_get_task_calls_coinitialize_before_dispatch` failed identically | ✅ Passed — 12/12 in file after fix | ✅ 2 cases (search + get_task) | ➖ None needed |
| 3.1/3.2 Mail adapter | `tests/test_mail_adapter.py` | Unit | ✅ 12/12 (pre-fix) | ✅ Written — `test_search_calls_coinitialize_before_dispatch` + `test_get_message_calls_coinitialize_before_dispatch` failed identically | ✅ Passed — 14/14 in file after fix | ✅ 2 cases (search + get_message) | ➖ None needed |

Each adapter's RED failure was confirmed via direct pytest invocation before
touching production code (see command log below). Module-level-import
tests (`test_pythoncom_not_imported_at_module_level`) trivially passed
before the fix too (since `pythoncom` wasn't imported at all yet) — they
exist to lock in the lazy-import convention going forward, mirroring the
existing `win32com` module-level-import tests.

### Test Summary
- **Total tests written**: 9 (3 per adapter file: 2 CoInitialize-order tests + 1 module-level-import test)
- **Total tests passing**: 161 (152 baseline + 9 new)
- **Layers used**: Unit (9)
- **Approval tests** (refactoring): None — no refactoring tasks, this is a pure additive fix
- **Pure functions created**: 0 — fix is inside an existing method, no new pure logic to extract

## Order-Assertion Technique

Both the fake `pythoncom.CoInitialize` mock and the fake
`win32com.client.Dispatch` mock are attached to a shared `mocker.Mock()`
"manager" via `attach_mock(...)`, so `manager.mock_calls` records both
calls in true chronological order regardless of which module fired them.
The test asserts `call_names.index("CoInitialize") <
call_names.index("Dispatch")`.

## Command Log (RED confirmation)

```
$ .venv/bin/python3.12 -m pytest -q tests/test_outlook_adapter.py -k "coinitialize or pythoncom"
2 failed, 1 passed, 7 deselected
FAILED test_search_calls_coinitialize_before_dispatch
FAILED test_get_event_calls_coinitialize_before_dispatch

$ .venv/bin/python3.12 -m pytest -q tests/test_task_adapter.py -k "coinitialize"
2 failed, 10 deselected
FAILED test_search_calls_coinitialize_before_dispatch
FAILED test_get_task_calls_coinitialize_before_dispatch

$ .venv/bin/python3.12 -m pytest -q tests/test_mail_adapter.py -k "coinitialize"
2 failed, 12 deselected
FAILED test_search_calls_coinitialize_before_dispatch
FAILED test_get_message_calls_coinitialize_before_dispatch
```

## Command Log (GREEN + full suite)

```
$ .venv/bin/python3.12 -m pytest -q tests/test_outlook_adapter.py   -> 10 passed
$ .venv/bin/python3.12 -m pytest -q tests/test_task_adapter.py      -> 12 passed
$ .venv/bin/python3.12 -m pytest -q tests/test_mail_adapter.py      -> 14 passed
$ .venv/bin/python3.12 -m pytest -q                                 -> 161 passed
```

Zero regressions across the full suite.

## Files Changed

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/outlook_adapter.py` | Modified | `_dispatch_outlook()`: lazily import `pythoncom` alongside `win32com.client`; call `pythoncom.CoInitialize()` before `Dispatch(...)`. No `CoUninitialize()` pairing (idempotent, long-lived worker threads). |
| `tools/task_adapter.py` | Modified | Identical fix, mirrored. |
| `tools/mail_adapter.py` | Modified | Identical fix, mirrored. |
| `tests/test_outlook_adapter.py` | Modified | Added `_install_fake_pythoncom` helper; extended `_install_fake_win32com` to auto-install a default fake `pythoncom` (so all ~7 pre-existing call sites keep working unmodified); added 3 new tests. |
| `tests/test_task_adapter.py` | Modified | Same additions, mirrored. |
| `tests/test_mail_adapter.py` | Modified | Same additions, mirrored. |
| `openspec/changes/com-coinitialize-hotfix/proposal.md` | Created | Hotfix proposal — bug, root cause, fix, risk, rollback. |
| `openspec/changes/com-coinitialize-hotfix/specs/outlook-com-adapter/spec.md` | Created | Delta spec — ADDED "Per-Thread COM Initialization" requirement with 4 scenarios. |
| `openspec/changes/com-coinitialize-hotfix/tasks.md` | Created/Updated | Task checklist, all items checked off. |

## Deviations from Design

None — implementation matches the proposal exactly. The one design
decision made during implementation (not pre-specified in the proposal,
since this is a hotfix with no separate design.md) was to extend
`_install_fake_win32com` to transparently install a default fake
`pythoncom` module if one isn't already present, rather than editing
every one of the ~26 pre-existing test functions across the three files
to call `_install_fake_pythoncom` explicitly. This kept the diff
byte-minimal on the pre-existing tests (zero of them needed to change)
while still exercising the real `_dispatch_outlook()` code path, which
now unconditionally imports and calls `pythoncom`.

## Issues Found

None.

## Package Rebuild

`./make-deploy-package.sh` run end-to-end after the full suite went
green. All gates passed:

- gate 1: manifest/launcher files present
- gate 2: full test suite passes (161 passed)
- gate 3: no module-level `win32com` import (lazy-only) — `pythoncom` also
  remains lazy-only, confirmed via `test_pythoncom_not_imported_at_module_level`
  in each adapter's test file
- gate 4 / 4b: launcher scripts ASCII-clean, no unescaped parens
- gate 5: `install.ps1` parses cleanly via portable pwsh
- gate 6: full offline wheel closure resolved and staged (79 wheels,
  including `pywin32` for both cp312/cp313 win_amd64)

**New zip**: `dist/WinMCP-20260824.zip` (overwrote the same-day build, as expected)
**sha256**: `f94a6e2b2d682d43c26d82ab677f1f27f046fdaa780fe29269944a127c1e3b77`

Verified via `unzip -p dist/WinMCP-20260824.zip WinMCP/tools/<adapter>.py |
grep -n CoInitialize` that all three packaged adapter modules
(`outlook_adapter.py`, `task_adapter.py`, `mail_adapter.py`) contain the
`import pythoncom` / `pythoncom.CoInitialize()` fix inside the shipped zip.

## Status

12/12 tasks complete (Phases 0-4). Ready for sdd-verify / archive.

## Post-verify remediation

Closes the verify-report's single WARNING ("Failed pythoncom import still
maps to OutlookUnavailableError" had no dedicated isolated test).

- Added `test_pythoncom_import_error_raises_outlook_unavailable_error` to
  each of `tests/test_outlook_adapter.py`, `tests/test_task_adapter.py`,
  `tests/test_mail_adapter.py`. Each test forces `import pythoncom` to
  raise `ImportError` (`sys.modules["pythoncom"] = None`) while a real fake
  `win32com.client` is installed directly (bypassing
  `_install_fake_win32com`'s own pythoncom auto-install), proving the
  `win32com` import would have succeeded had `pythoncom` not failed first —
  isolating the pythoncom-only branch of `_dispatch_outlook`'s shared
  `try/except ImportError` block from the pre-existing win32com-only tests.
- RED confirmed for all 3 new tests by temporarily changing each adapter's
  `except ImportError as exc:` to `except KeyError as exc:` (production
  code, reverted immediately after) — all 3 failed with an unhandled
  `ModuleNotFoundError`, confirming a broken except-block would be caught.
  GREEN confirmed after revert.
- No production code changes. Full suite: 165 passed (161 baseline + 4 —
  the 3 tests here plus 1 unrelated test added for the
  `qa-pro-deploy-pipeline` remediation the same session), zero regressions.
