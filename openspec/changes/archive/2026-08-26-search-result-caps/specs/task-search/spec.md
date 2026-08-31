# Delta for task-search

## ADDED Requirements

### Requirement: Result Limit Parameter

The `task_search` tool MUST accept an optional `limit` (integer)
request parameter bounding the number of `TaskSummary` rows returned.
When omitted, `limit` defaults to `50`. When `<= 0`, the tool MUST
reject the call as a `ValueError` before any adapter call. When `>
200`, the tool MUST clamp it to `200` (never reject) — matching
`mail_search`/`calendar_search`/`file_search`'s cap convention. The
adapter MUST apply the bound at the source, never fetching unbounded
and truncating client-side.

#### Scenario: Default limit applied to a filterless call

- GIVEN a mocked Tasks `Items` collection seeded with 80 tasks
- WHEN `task_search` is called with all filters and `limit` omitted
- THEN exactly 50 `TaskSummary` items are returned and `results_truncated` is `true`

#### Scenario: limit above hard max is clamped, not rejected

- GIVEN a mocked adapter seeded with 40 tasks
- WHEN `task_search` is called with `limit=1000`
- THEN the adapter's `search()` is invoked with limit `200`, not `1000`, and no error is raised

#### Scenario: Non-positive limit is rejected

- WHEN `task_search` is called with `limit=0`
- THEN the tool raises a `ValueError` before calling the adapter

### Requirement: Result Ordering (Due-Date Priority)

Tasks carry no analogue to `ReceivedTime`/`start` for a literal
"newest-first" order. `task_search` results MUST instead be ordered by
`dueDate` ascending (soonest first), with `null`-`dueDate` tasks
ordered last, so a truncated page is the most actionable subset.

#### Scenario: Out-of-order source items are returned soonest-due-first

- GIVEN a mocked Tasks `Items` collection seeded with 3 tasks due out of order (Aug 20, Aug 1, Aug 10)
- WHEN `task_search` is called with no filters
- THEN the returned list is ordered Aug 1, Aug 10, Aug 20

#### Scenario: No-due-date tasks sort after all dated tasks

- GIVEN a task due 2026-08-10 and a task with `dueDate=null`
- WHEN `task_search` is called with no filters
- THEN the dated task is returned before the no-due-date task

## MODIFIED Requirements

### Requirement: Search Input Parameters (all optional)

The `task_search` tool MUST accept `dueFrom`, `dueTo` (ISO 8601,
optional), `subject` (optional substring), `status` (optional enum),
`includeNoDueDate` (boolean, default `true`), and `limit` (integer,
optional, default `50`, hard max `200` — see "Result Limit
Parameter"). Unlike `calendar_search`, ALL filter parameters are
optional — Tasks folders are bounded personal lists, so a filterless
call MUST be accepted. A filterless call MUST return every task in the
folder up to the effective `limit`, marking `results_truncated` when
the folder holds more tasks than `limit`.
(Previously: a filterless call returned every task with no cap and no
`limit` parameter.)

#### Scenario: Valid due-date range and subject provided

- GIVEN 3 tasks due on 2026-08-03, one subject "Renovar licencia"
- WHEN `task_search` is called with matching `dueFrom`/`dueTo`/`subject`
- THEN the adapter's `search()` is invoked with that range/subject and exactly one `TaskSummary` is returned

#### Scenario: Status-only filter provided

- GIVEN tasks of mixed status
- WHEN `task_search` is called with `status="completed"` only
- THEN only tasks with status `completed` are returned

#### Scenario: All filters omitted returns the whole folder when under the cap

- GIVEN 5 tasks of varying subjects/statuses/due dates (one with no due date)
- WHEN `task_search` is called with all filters (incl. `limit`) omitted
- THEN the call is not rejected, all 5 items are returned, and `results_truncated` is `false`

#### Scenario: All filters omitted returns at most the default limit when over the cap

- GIVEN a fake adapter seeded with 80 tasks
- WHEN `task_search` is called with all filters omitted
- THEN exactly 50 items are returned and `results_truncated` is `true`

### Requirement: Search Output Shape

The tool MUST return objects with `entryId`, `subject`, `dueDate` (ISO
8601 or `null`), `status`, `isComplete`. It MUST NOT include the task
body — unchanged, must not regress; the body stays in `task_get_task`.
The response MUST additionally convey a `results_truncated` boolean,
`true` when `limit` cut the true match count, `false`/absent otherwise.
The exact response shape carrying it is left to `design.md`.
(Previously: a plain list with no truncation signal and no cap.)

#### Scenario: Empty result set

- GIVEN a fake adapter whose `search()` returns an empty list
- WHEN `task_search` is called with `subject="Nonexistent"`
- THEN the tool returns an empty result with `results_truncated` falsy, not an error

#### Scenario: Rows never carry body content

- GIVEN a task with a large body/notes property
- WHEN `task_search` matches that task
- THEN the returned `TaskSummary` contains no body field
