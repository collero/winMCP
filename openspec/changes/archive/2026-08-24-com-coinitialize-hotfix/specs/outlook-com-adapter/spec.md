# Outlook COM Adapter Specification (Delta)

## ADDED Requirements

### Requirement: Per-Thread COM Initialization

Every real Outlook adapter (`OutlookCalendarAdapter`, `OutlookTaskAdapter`,
`OutlookMailAdapter`) MUST call `pythoncom.CoInitialize()` on the current
thread before issuing any COM `Dispatch()` call. `pythoncom` MUST be
imported lazily, inside the adapter's own dispatch helper — never at the
top level of `server.py`, `tools/`, or `models/` modules — mirroring the
existing `win32com.client` lazy-import requirement. This is required
because FastMCP dispatches tool calls across a worker-thread pool, and COM
apartments are thread-local: a thread that has never called
`CoInitialize()` fails any COM call with
`(-2147221008, 'CoInitialize has not been called.', ...)`.
`CoInitialize()` MUST NOT be paired with a matching `CoUninitialize()` in
the adapter, since FastMCP worker threads are long-lived and reused across
calls, and `CoInitialize()` is idempotent per thread (a repeat call on an
already-initialized thread returns `S_FALSE` and is harmless).

#### Scenario: CoInitialize called before Dispatch on search

- GIVEN a fake `pythoncom` module injected into `sys.modules` with a mock
  `CoInitialize`, and a fake `win32com.client` module with a mock
  `Dispatch`
- WHEN a real adapter's `search()` method is called
- THEN `pythoncom.CoInitialize()` is called before
  `win32com.client.Dispatch("Outlook.Application")`

#### Scenario: CoInitialize called before Dispatch on a get call

- GIVEN a fake `pythoncom` module injected into `sys.modules` with a mock
  `CoInitialize`, and a fake `win32com.client` module with a mock
  `Dispatch`
- WHEN a real adapter's get method (`get_event`/`get_task`/`get_message`)
  is called
- THEN `pythoncom.CoInitialize()` is called before
  `win32com.client.Dispatch("Outlook.Application")`

#### Scenario: pythoncom not imported at module level

- GIVEN this WSL2 dev environment where `import pythoncom` fails (module
  not installed)
- WHEN the adapter module (`tools/outlook_adapter.py`,
  `tools/task_adapter.py`, or `tools/mail_adapter.py`) is imported/reloaded
  with `pythoncom` absent from `sys.modules`
- THEN the import succeeds and `pythoncom` is not added to `sys.modules`

#### Scenario: Failed pythoncom import still maps to OutlookUnavailableError

- GIVEN `pythoncom` is not importable on this platform
- WHEN a real adapter's `search()` or get method is called
- THEN the adapter raises `OutlookUnavailableError`, not a bare
  `ImportError`
