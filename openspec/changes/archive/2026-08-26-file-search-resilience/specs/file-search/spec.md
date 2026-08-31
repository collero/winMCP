# Delta for File Search

## ADDED Requirements

### Requirement: Filename Queries Do Not Require the Index

A `filename`-only query MUST be satisfied entirely by the filesystem
walk (see `filesystem-walk-search`) and MUST NOT call the Windows Search
adapter. This holds regardless of index health, and makes unindexed
allowed roots (e.g. `C:\usr`, `C:\co`) searchable for the first time.

#### Scenario: Filename query succeeds with the index unavailable

- GIVEN a fake adapter whose `search()`/`get_info()` would raise `WindowsSearchUnavailableError` if called, and a mocked filesystem walk finding one match
- WHEN `file_search` is called with `filename=".md"` only
- THEN one result is returned and the adapter is never called

#### Scenario: Filename query succeeds under an unindexed root

- GIVEN `scope="C:\usr\WinMCP\_chatCowork"` (not in the index) and a mocked walk finding markdown files there
- WHEN `file_search` is called with `filename=".md"`, `scope="C:\usr\WinMCP\_chatCowork"`
- THEN the matching files are returned

### Requirement: Combined Filename and Phrase Query Rule

When both `filename` and `phrase` are provided, the tool MUST run the
filesystem walk for `filename` candidates and the index (ADO, then the
PowerShell bridge on ADO failure) for the `phrase` condition, then
return only results present in BOTH sets (intersection by normalized
`path`). If the index leg fails on both transports, the combined query
MUST fail with the same `WindowsSearchUnavailableError` (filename-still-
works message) rather than silently degrading to filename-only results.

#### Scenario: Combined query intersects walk and index results

- GIVEN a mocked walk matching `report.md`, `report-old.md` for `filename="report"`, and a fake adapter's phrase query matching only `report.md`
- WHEN `file_search` is called with `filename="report"`, `phrase="quarterly"`
- THEN only `report.md` is returned

#### Scenario: Combined query fails when the index leg is exhausted

- GIVEN a mocked walk with matches, and both ADO and the PowerShell bridge failing for the phrase leg
- WHEN `file_search` is called with both `filename` and `phrase` set
- THEN `WindowsSearchUnavailableError` is raised, not a filename-only result set

## MODIFIED Requirements

### Requirement: Search Output Shape

The tool MUST return a list of `FileSummary` objects: `path`, `name`,
`size` (bytes), `lastModified` (ISO 8601). It MUST NOT include content.
The response MUST additionally report `results_truncated`: `true` when
the filesystem walk stopped early due to a result/time/directory cap
(see `filesystem-walk-search`), `false` otherwise.
(Previously: no `results_truncated` field existed.)

#### Scenario: Empty result set

- GIVEN a fake adapter/mocked walk whose result is empty for the given filters
- WHEN `file_search` is called with `filename="doesnotexist"`
- THEN the tool returns an empty list, not an error, with `results_truncated: false`

#### Scenario: Truncated walk is flagged

- GIVEN a mocked walk that hits its row cap before finishing
- WHEN `file_search` is called with a broad `filename` filter
- THEN the returned list is capped and `results_truncated: true`

### Requirement: Windows Search Unavailable

The tool MUST surface a clear, catchable error when BOTH the ADO adapter
and the PowerShell bridge fail to reach the index for a `phrase`-
involving query. This requirement no longer applies to filename-only
queries, which never touch the index. The error message MUST state that
filename search still works.
(Previously: fired for any adapter failure, including filename-only
queries, with no filename-still-works messaging.)

#### Scenario: Both transports fail on a phrase query

- GIVEN a fake adapter/mocked bridge where both raise `WindowsSearchUnavailableError`
- WHEN `file_search` is called with `phrase="quarterly report"`
- THEN the tool returns an MCP tool error naming the index as unavailable and stating filename search still works

#### Scenario: Filename-only query is unaffected by index failure

- GIVEN a fake adapter that would raise `WindowsSearchUnavailableError` if called
- WHEN `file_search` is called with `filename="report"` only
- THEN the call succeeds via the walk and no error is raised
