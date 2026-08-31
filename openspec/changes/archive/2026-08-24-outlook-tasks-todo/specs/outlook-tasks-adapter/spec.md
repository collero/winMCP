# Outlook Tasks Adapter Specification

## Purpose

Isolate all Outlook Tasks/To Do COM access behind a single adapter interface
(`TaskPort`), mirroring `outlook-com-adapter`, so tool logic and its tests
never depend on `win32com` being importable on the WSL2 Linux dev/CI host.

## Requirements

### Requirement: Adapter Interface

The system MUST define a `TaskPort` `Protocol` exposing
`search(date_from, date_to, subject, status, include_no_due_date) -> list[TaskSummary]`
and `get_task(entry_id) -> TaskDetail`, where `date_from`/`date_to`/
`subject`/`status` are independently optional and `include_no_due_date`
defaults to `True`. Both real and fake implementations MUST satisfy it.

#### Scenario: Fake adapter satisfies the interface

- GIVEN a `FakeTaskAdapter` implementing `search()` and `get_task()` per `TaskPort`
- WHEN a tool is called with the fake adapter injected
- THEN the tool code runs unchanged, with no reference to `win32com` on the call path

### Requirement: Lazy COM Import

The real adapter implementation (`OutlookTaskAdapter`) MUST import
`win32com.client` lazily, inside its own module/functions — never at the top
level of `server.py`, `tools/`, or `models/` modules — so the test suite runs
on Linux without `win32com` installed.

#### Scenario: Test suite runs without win32com installed

- GIVEN this WSL2 dev environment where `import win32com` fails
- WHEN `python3.12 -m pytest -q` runs the full suite using only `FakeTaskAdapter`
- THEN all tests pass and no test triggers a `win32com` import

### Requirement: Real Adapter COM Access with Python-Side Filtering

On Windows, `OutlookTaskAdapter` MUST connect via
`win32com.client.Dispatch("Outlook.Application")`, `GetNamespace("MAPI")`,
and `GetDefaultFolder(13)` (`olFolderTasks`, synced with Microsoft To Do). It
MUST fetch `folder.Items` WITHOUT a DASL `Restrict()` call on due date — DASL
cannot express "in range OR no due date" — and instead apply subject,
status, and due-date/`include_no_due_date` filtering in Python, matching
`FakeTaskAdapter`'s filtering logic.

#### Scenario: Dispatch failure raises a typed error

- GIVEN `win32com.client.Dispatch("Outlook.Application")` raises (Outlook not
  installed/running) — simulated via a mocked `win32com.client` module whose
  `Dispatch` raises, or via `FakeTaskAdapter` raising `OutlookUnavailableError`
- WHEN either adapter method is called
- THEN the adapter raises `OutlookUnavailableError` (reused from
  `tools/errors.py`), not a bare/unhandled COM exception

#### Scenario: Mocked Items collection is filtered in Python, not via Restrict

- GIVEN a mocked `win32com.client` module whose Tasks folder's `Items`
  collection contains 4 items with mixed due dates (including one `None`),
  with no due-date `Restrict()` mock configured
- WHEN `OutlookTaskAdapter.search()` is called with a `date_from`/`date_to` range
- THEN the adapter iterates `folder.Items` directly (no `.Restrict()` call with a due-date clause)
- AND applies the range/`include_no_due_date` logic in Python to produce the filtered `TaskSummary` list

### Requirement: COM Status Mapping and Complete Override

`OutlookTaskAdapter` MUST map `TaskItem.Status` (`olTaskStatus`) to
`TaskStatus` as: `0 -> not_started`, `1 -> in_progress`, `2 -> completed`,
`3 -> waiting`, `4 -> deferred`; and read `TaskItem.Complete` directly into
`is_complete`. When `Complete` is `True`, `status` MUST be forced to
`completed` regardless of the raw `Status` value (`Complete` is the
authoritative "done" flag). Applied identically in `search()`/`get_task()`.

#### Scenario: Status=1 and Complete=False maps directly with no override

- GIVEN a mocked `win32com.client` module returning a Tasks item with `Status=1` and `Complete=False`
- WHEN `OutlookTaskAdapter.get_task()` is called with that item's entryId
- THEN the returned `TaskDetail` has `status="in_progress"` and `is_complete=False`

#### Scenario: Complete=True overrides a mismatched raw Status

- GIVEN a mocked `win32com.client` module returning a Tasks item with
  `Status=3` (`olTaskWaiting`) and `Complete=True`
- WHEN `OutlookTaskAdapter.get_task()` is called with that item's entryId
- THEN the returned `TaskDetail` has `status="completed"` (overriding the
  raw `waiting` mapping) and `is_complete=True`

### Requirement: Due-Date Sentinel Normalization

Real Outlook COM returns a sentinel datetime (year 4501, the `olNoDate`
convention) for a `TaskItem.DueDate` that was never set — not Python `None`.
`OutlookTaskAdapter` MUST normalize any `DueDate` whose year is `>= 4500` to
`None` before it reaches `TaskSummary`/`TaskDetail` or the
`include_no_due_date` filter, so "no due date" behaves identically whether
the underlying COM value is the sentinel or a genuine `None`. Applied
identically in `search()` and `get_task()`.

#### Scenario: Sentinel DueDate normalized to None in get_task

- GIVEN a mocked `win32com.client` module returning a Tasks item whose
  `DueDate` is a year-4501 sentinel datetime
- WHEN `OutlookTaskAdapter.get_task()` is called with that item's entryId
- THEN the returned `TaskDetail.due_date` is `None`, not the sentinel value

#### Scenario: Sentinel DueDate treated as undated by search filters

- GIVEN a mocked `win32com.client` module whose Tasks folder contains one
  item with a year-4501 sentinel `DueDate`
- WHEN `OutlookTaskAdapter.search()` is called with a due-date range and
  `include_no_due_date=True`
- THEN that item is included with `due_date=None`
- AND WHEN the same search is called with `include_no_due_date=False`
- THEN that item is excluded, exactly as a genuine `None` due date would be

### Requirement: Adapter Selection at Runtime

The server MUST select the real adapter only when `win32com` is importable
at startup/first use; otherwise task tool calls MUST fail with a clear
runtime error, not a module-import-time crash.

#### Scenario: win32com not importable

- GIVEN the server runs on a host without `win32com` installed (e.g. this Linux dev host)
- WHEN a task tool invokes the adapter
- THEN the tool returns a clear error stating the Outlook tasks adapter is
  unavailable on this platform, and the server process itself does not crash
  at import time
