# Task Get Detail Specification

## Purpose

Fetch full detail for a single Outlook Task / To Do item identified by its
`entryId`, typically after a `task_search` call.

## Requirements

### Requirement: Get Task Input/Output

The `task_get_task` tool MUST accept `entryId` (string, required) and MUST
return an object with `entryId`, `subject`, `body`, `dueDate` (ISO 8601
string or `null`), `status`, and `isComplete` (boolean).

#### Scenario: Successful fetch

- GIVEN a fake adapter whose `get_task("TASK-1")` returns a `TaskDetail` with
  subject "Renovar licencia", `status="in_progress"`, `isComplete=false`
- WHEN `task_get_task` is called with `entryId="TASK-1"`
- THEN the tool returns `subject`, `body`, `dueDate`, `status`, and
  `isComplete` matching the adapter's result

### Requirement: Task Not Found

The tool MUST return a clear not-found error, not a crash, when `entryId`
does not resolve to an item.

#### Scenario: Unknown or invalid entryId

- GIVEN a fake adapter whose `get_task("BAD-ID")` raises `TaskNotFoundError`
  (simulating Outlook's `GetItemFromID` returning nothing/raising for a bad ID)
- WHEN `task_get_task` is called with `entryId="BAD-ID"`
- THEN the tool returns an MCP tool error indicating the task was not found

### Requirement: Empty Body Handling

The tool MUST return an empty string for `body` (not an error) when the task
has no body/notes text.

#### Scenario: Task with no notes

- GIVEN a fake adapter whose `get_task("TASK-2")` returns a `TaskDetail` with `body=""`
- WHEN `task_get_task` is called with `entryId="TASK-2"`
- THEN the tool returns successfully with `body=""` and the correct `subject`/`status`

### Requirement: Status/Complete Consistency

Every `TaskDetail` the tool returns MUST satisfy: if `isComplete` is `true`,
`status` MUST equal `"completed"`. This invariant is enforced by the adapter
(see `outlook-tasks-adapter`'s COM Status Mapping requirement); the tool
layer MUST pass both fields through unchanged rather than re-deriving one
from the other.

#### Scenario: Completed task reports consistent fields

- GIVEN a fake adapter whose `get_task("TASK-3")` returns a `TaskDetail` with
  `status="completed"` and `isComplete=true`
- WHEN `task_get_task` is called with `entryId="TASK-3"`
- THEN the tool returns `status="completed"` and `isComplete=true`

#### Scenario: In-progress task reports consistent fields

- GIVEN a fake adapter whose `get_task("TASK-1")` returns a `TaskDetail` with
  `status="in_progress"` and `isComplete=false`
- WHEN `task_get_task` is called with `entryId="TASK-1"`
- THEN the tool returns `status="in_progress"` and `isComplete=false`
