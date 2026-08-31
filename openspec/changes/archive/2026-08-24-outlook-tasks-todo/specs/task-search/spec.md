# Task Search Specification

## Purpose

Lightweight search over the user's default Outlook Tasks folder (To Do sync
target), returning a minimal task list so a client can locate an item before
fetching full detail via `task_get_task`.

## Requirements

### Requirement: Search Input Parameters (all optional)

The `task_search` tool MUST accept `dueFrom` (ISO 8601 datetime, optional),
`dueTo` (ISO 8601 datetime, optional), `subject` (string, optional,
case-insensitive substring match), `status` (string enum, optional: one of
`not_started`, `in_progress`, `waiting`, `deferred`, `completed`), and
`includeNoDueDate` (boolean, optional, default `true`). Unlike
`calendar_search`, ALL parameters are optional: Tasks folders are bounded
personal lists, not unbounded event streams, so a filterless call MUST be
accepted and MUST return every task in the default Tasks folder.

#### Scenario: Valid due-date range and subject provided

- GIVEN a fake adapter seeded with 3 tasks due on 2026-08-03, one subject "Renovar licencia"
- WHEN `task_search` is called with `dueFrom=2026-08-03T00:00:00`, `dueTo=2026-08-03T23:59:59`, `subject="renovar"`
- THEN the adapter's `search()` is invoked with the given range and subject filter
- AND exactly one `TaskSummary` is returned

#### Scenario: Status-only filter provided

- GIVEN a fake adapter seeded with tasks of mixed status
- WHEN `task_search` is called with `status="completed"` only (no due dates, no subject)
- THEN the adapter's `search()` is invoked with `status="completed"` and no due-date bounds
- AND only tasks with status `completed` are returned

#### Scenario: All filters omitted returns the whole folder

- GIVEN a fake adapter seeded with 5 tasks of varying subjects, statuses, and due dates (including one with no due date)
- WHEN `task_search` is called with `dueFrom`, `dueTo`, `subject`, and `status` all omitted
- THEN the tool MUST NOT reject the call
- AND all 5 `TaskSummary` items are returned

### Requirement: Optional Inclusive Due-Date Filtering

When `dueFrom`/`dueTo` are both omitted, no due-date filter is applied and
`includeNoDueDate` has no effect. When at least one of `dueFrom`/`dueTo` is
given, a task passes the due-date filter if its `dueDate` falls within the
given bound(s) (open-ended on any omitted bound), OR its `dueDate` is `null`
AND `includeNoDueDate` is `true`. When `includeNoDueDate` is `false`, tasks
with a `null` `dueDate` MUST be excluded whenever a due-date bound is given.

#### Scenario: Default include_no_due_date passes a no-due-date task through a range filter

- GIVEN a fake adapter seeded with one task due 2026-08-03 and one task with `dueDate=null`
- WHEN `task_search` is called with `dueFrom=2026-08-01T00:00:00`, `dueTo=2026-08-31T23:59:59` (no `includeNoDueDate` given)
- THEN both tasks are returned

#### Scenario: includeNoDueDate=false excludes the no-due-date task

- GIVEN the same fake adapter as above
- WHEN `task_search` is called with the same `dueFrom`/`dueTo` and `includeNoDueDate=false`
- THEN only the task with `dueDate=2026-08-03` is returned

#### Scenario: Subject-only filter is unaffected by due-date bounds

- GIVEN a fake adapter seeded with a task with `dueDate=null` and subject "Sin fecha"
- WHEN `task_search` is called with `subject="sin fecha"` only
- THEN the no-due-date task is included in the results regardless of `includeNoDueDate`

### Requirement: Search Output Shape

The tool MUST return a list of objects containing `entryId`, `subject`,
`dueDate` (ISO 8601 string or `null`), `status`, and `isComplete` (boolean).
It MUST NOT include the task body.

#### Scenario: Empty result set

- GIVEN a fake adapter whose `search()` returns an empty list for the given filters
- WHEN `task_search` is called with `subject="Nonexistent"`
- THEN the tool returns an empty list, not an error

### Requirement: Outlook Unavailable

The tool MUST surface a clear, catchable error (not an unhandled crash) when
the underlying adapter cannot reach Outlook.

#### Scenario: COM dispatch failure

- GIVEN a fake adapter configured to raise `OutlookUnavailableError` from `search()`
  (simulating `win32com.client.Dispatch("Outlook.Application")` failing because
  Outlook is not installed or not running)
- WHEN `task_search` is called with any valid filter
- THEN the tool returns an MCP tool error whose message identifies Outlook as unavailable
