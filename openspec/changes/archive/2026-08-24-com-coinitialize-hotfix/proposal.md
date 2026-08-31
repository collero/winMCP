# Proposal: CoInitialize Hotfix for Real Outlook Adapters

## Intent

None of the three real Outlook adapters (`OutlookCalendarAdapter`,
`OutlookTaskAdapter`, `OutlookMailAdapter`) calls
`pythoncom.CoInitialize()` before `win32com.client.Dispatch(...)`. COM
requires per-thread initialization, but FastMCP dispatches tool calls on
worker-pool threads, so a thread that has never had `CoInitialize()`
called on it fails with:

```
[outlook_unavailable] ... (-2147221008, 'CoInitialize has not been called.', ...)
```

This is intermittent by nature — it depends on which worker thread
happens to pick up the call — and was reproduced live: the same deployed
zip passed 4/4 smoke-test families in one run, then 1/4 in the very next
run (calendar PASS, tasks/mail-inbox/mail-sent all `CoInitialize`
warnings). The bug has existed in every real adapter since the calendar
MVP; it was never caught by the test suite because the fake win32com
mocks in `tests/test_*_adapter.py` don't model per-thread COM state.

## Root Cause

Each adapter's lazy `_dispatch_outlook()` helper imports `win32com.client`
and calls `Dispatch("Outlook.Application")` directly, with no
`pythoncom.CoInitialize()` call on the current thread first. COM apartments
are thread-local; a thread must initialize COM before using any COM object
on it. The calendar/tasks/mail MVPs all copied the same `_dispatch_outlook`
shape without ever adding this call.

## Fix

In each real adapter's `_dispatch_outlook()` (`tools/outlook_adapter.py`,
`tools/task_adapter.py`, `tools/mail_adapter.py`), lazily import
`pythoncom` (same lazy-import discipline as `win32com.client` — never at
module level) and call `pythoncom.CoInitialize()` on the current thread
before `win32com.client.Dispatch(...)`. `CoInitialize()` is idempotent per
thread — calling it again on an already-initialized thread returns
`S_FALSE` and is harmless — so no `CoUninitialize()` pairing is needed or
wanted, since these are long-lived FastMCP worker threads, not
short-lived per-call threads. All failures (including a failed
`pythoncom`/`win32com` import) continue to map to
`OutlookUnavailableError`, unchanged from today's contract.

## Risk

Low. The change is additive (one new call in an existing try/except
block) and does not alter any adapter's public interface, return shapes,
or error mapping. `CoInitialize()`'s idempotency means it is safe to call
on every `_dispatch_outlook()` invocation, including on a thread that
already has COM initialized (e.g. by a previous tool call on the same
worker thread). No behavior change on non-Windows hosts: `pythoncom`
remains lazily imported and its absence still maps to
`OutlookUnavailableError`, exactly as `win32com.client`'s absence does
today.

## Rollback

Redeploy the previous zip (`dist/WinMCP-20260824.zip`, pre-hotfix). No
data migration, no config change, no schema change — a redeploy fully
reverts the fix.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `tools/outlook_adapter.py` | Modified | `_dispatch_outlook()`: add lazy `pythoncom` import + `CoInitialize()` before `Dispatch()` |
| `tools/task_adapter.py` | Modified | Same fix, mirrored |
| `tools/mail_adapter.py` | Modified | Same fix, mirrored |
| `tests/test_outlook_adapter.py` | Modified | New tests: `CoInitialize` called before `Dispatch`; `pythoncom` not imported at module level |
| `tests/test_task_adapter.py` | Modified | Same, mirrored |
| `tests/test_mail_adapter.py` | Modified | Same, mirrored |
| `openspec/specs/outlook-com-adapter/spec.md` | Modified (via archive) | New requirement documenting the CoInitialize contract |

## Success Criteria

- [ ] All three real adapters call `pythoncom.CoInitialize()` before any
      COM `Dispatch()` call, on the current thread
- [ ] `pythoncom` remains a lazy, per-function import — never at module
      level — mirroring the existing `win32com` convention
- [ ] Full test suite green: 152 pre-existing tests + new CoInitialize
      tests, zero regressions
- [ ] `./make-deploy-package.sh` passes end-to-end; the packaged zip's
      adapter modules contain the `CoInitialize` call
