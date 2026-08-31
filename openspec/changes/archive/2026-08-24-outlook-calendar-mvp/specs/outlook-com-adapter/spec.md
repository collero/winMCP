# Outlook COM Adapter Specification

## Purpose

Isolate all Outlook COM access behind a single adapter interface (protocol) so
tool logic and its tests never depend on `win32com` being importable — required
because the dev/CI host is WSL2 Linux while the runtime target is Windows.

## Requirements

### Requirement: Adapter Interface

The system MUST define an adapter interface (e.g. a `Protocol`/ABC) exposing
`search(from, to, subject) -> list[EventSummary]` and
`get_event(entry_id) -> EventDetail`. Both the real (`win32com`-backed) and fake
(test) implementations MUST satisfy this interface.

#### Scenario: Fake adapter satisfies the interface

- GIVEN a fake adapter implementing `search()` and `get_event()` per the protocol
- WHEN a tool is called with the fake adapter injected
- THEN the tool code runs unchanged, with no reference to `win32com` on the call path

### Requirement: Lazy COM Import

The real adapter implementation MUST import `win32com.client` lazily, inside its
own module/functions — never at the top level of `server.py`, `tools/`, or
`models/` modules — so the test suite runs on Linux without `win32com` installed.

#### Scenario: Test suite runs without win32com installed

- GIVEN this WSL2 dev environment where `import win32com` fails
- WHEN `python3.12 -m pytest -q` runs the full suite using only the fake adapter
- THEN all tests pass and no test triggers a `win32com` import

### Requirement: Real Adapter COM Access

On Windows, the real adapter MUST connect via
`win32com.client.Dispatch("Outlook.Application")`, `GetNamespace("MAPI")`, and
`GetDefaultFolder(9)` (default Calendar folder) to satisfy `search()` and
`get_event()`.

#### Scenario: Dispatch failure raises a typed error

- GIVEN `win32com.client.Dispatch("Outlook.Application")` raises (Outlook not
  installed or not running) — simulated in tests via a fake adapter configured
  to raise `OutlookUnavailableError` from `search()`/`get_event()`
- WHEN either adapter method is called
- THEN the adapter raises `OutlookUnavailableError` (or a documented subclass),
  not a bare/unhandled COM exception, so calling tools can map it to an MCP error

### Requirement: Adapter Selection at Runtime

The server MUST select the real adapter only when `win32com` is importable at
startup/first use; otherwise tool calls MUST fail with a clear runtime error
rather than crashing at module import time.

#### Scenario: win32com not importable

- GIVEN the server runs on a host without `win32com` installed (e.g. this Linux dev host)
- WHEN a tool invokes the adapter
- THEN the tool returns a clear error stating the Outlook adapter is unavailable
  on this platform, and the server process itself does not crash at import time
