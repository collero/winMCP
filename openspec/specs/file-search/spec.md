# File Search Specification

## Purpose

Search files under the local disk and locally-synced OneDrive tree via the
Windows Search index, returning a minimal list so a client can locate an
item before fetching detail via `file_get_info`. Constrained to configured
allowed roots.

## Requirements

### Requirement: Search Input Parameters

The `file_search` tool MUST accept `filename` (string, optional,
case-insensitive substring match on `System.FileName`), `phrase` (string,
optional, full-text `CONTAINS()` match on file content/properties), and
`scope` (string, optional, an absolute path constraining the search to
that subtree). At least one of `filename`/`phrase` MUST be provided; the
tool MUST reject a call with both omitted as a `ValueError` before any
adapter call, mirroring `calendar_search`'s mandatory-filter rule.

#### Scenario: Filename and scope provided together

- GIVEN a fake adapter seeded with a file `report.docx` under `C:\Users\ana\Documents`
- WHEN `file_search` is called with `filename="report"`, `scope="C:\Users\ana\Documents"`
- THEN the adapter's `search()` is invoked with the filename filter and scope
- AND exactly one `FileSummary` is returned

#### Scenario: Both filename and phrase omitted is rejected

- WHEN `file_search` is called with `filename`, `phrase` both omitted (`scope` alone or absent)
- THEN the tool raises a `ValueError` before calling the adapter, stating a filter is required

### Requirement: Allowed-Roots Enforcement

The tool MUST load `file_search_allowed_roots` from `config/settings.yaml` (via
`load_settings()`, read live per call) and reject any request whose
`scope` — or, when omitted, the unrestricted query — is not contained
within a configured root. When `file_search_allowed_roots` is absent/empty, the
tool MUST fall back to `%USERPROFILE%` and any of `%OneDrive%`,
`%OneDriveConsumer%`, `%OneDriveCommercial%` set in the environment,
resolved at call time, never hardcoded.

#### Scenario: Out-of-root scope is refused before the adapter is called

- GIVEN `file_search_allowed_roots: ["C:\\Users\\ana"]`
- WHEN `file_search` is called with `filename="x"`, `scope="D:\\Shared"`
- THEN the tool raises `SearchRootNotAllowedError` (code `search_root_not_allowed`) and the adapter's `search()` is never invoked

#### Scenario: Default roots resolved from environment when unconfigured

- GIVEN `config/settings.yaml` has no `file_search_allowed_roots` key, and the environment has `USERPROFILE=C:\Users\ana` and `OneDrive=C:\Users\ana\OneDrive`
- WHEN `file_search` is called with `filename="x"`, `scope="C:\Users\ana\OneDrive\Docs"`
- THEN the request is allowed (contained within the resolved `OneDrive` default root)

### Requirement: Path Normalization for Containment Check

The containment check MUST compare `scope` and each configured root using a
case-insensitive, separator-normalized form (NTFS paths are
case-insensitive), so a request cannot bypass the policy via case or `/`
vs `\` variation, and a sibling directory sharing a name prefix is not
mistaken for a contained subpath.

#### Scenario: Case/separator variant of an allowed root is accepted

- GIVEN `file_search_allowed_roots: ["C:\\Users\\ana"]`
- WHEN `file_search` is called with `scope="c:/users/ana/Documents"`
- THEN the request is allowed

#### Scenario: Sibling directory with a shared name prefix is refused

- GIVEN `file_search_allowed_roots: ["C:\\Users\\ana"]`
- WHEN `file_search` is called with `scope="C:\\Users\\ana2\\Documents"`
- THEN the tool raises `SearchRootNotAllowedError`

### Requirement: Result Cap

The tool MUST cap returned results via `file_search_max_results` from
`config/settings.yaml` (default `200` when absent), passed to the adapter
as a `TOP n` bound, not truncated after an unbounded fetch.

#### Scenario: Default cap applied when unconfigured

- GIVEN `config/settings.yaml` has no `file_search_max_results` key
- WHEN `file_search` is called with a valid filter
- THEN the adapter's `search()` is invoked with a cap of `200`

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

### Requirement: Alias-Aware Allowed-Roots Containment

Windows Search can report a redirected-library alias in
`System.ItemPathDisplay` (e.g. a `Documents` library shortcut into a
OneDrive-synced tree, such as `C:\Documents\OneDrive - Informa\...`)
while `System.ItemUrl` still resolves to the real, allowed-roots-
containable path underneath (e.g. `C:\co\OneDrive - Informa\...`). The
post-call allowed-roots filter (see "Allowed-Roots Enforcement") MUST
treat a row as contained if EITHER the display-derived path OR the
`ItemUrl`-decoded native path falls under an allowed root — not the
display-derived path alone. When only the `ItemUrl`-derived form
passes, the row MUST be kept with its returned `path` rewritten to that
real, openable form — never left as the unopenable alias. A row whose
display-derived path already passes containment on its own MUST be
returned completely unchanged (never rewritten to the `ItemUrl` form
even when one happens to also be present). A row where NEITHER form is
contained within an allowed root is still dropped.

#### Scenario: Alias display path outside roots but URL-derived path inside is kept and rewritten

- GIVEN `file_search_allowed_roots: ["C:\\co"]` and a phrase-query adapter row whose `System.ItemPathDisplay`-derived path is `C:\Documents\OneDrive - Informa\notes.txt` (outside the allowed root) and whose `System.ItemUrl`-derived path is `C:\co\OneDrive - Informa\notes.txt` (inside it)
- WHEN `file_search` is called with `phrase="informa"`
- THEN the row is returned, with `path` equal to the `ItemUrl`-derived form, not the alias

#### Scenario: Row dropped when both forms are outside allowed roots

- GIVEN `file_search_allowed_roots: ["C:\\co"]` and a phrase-query adapter row whose display-derived and `ItemUrl`-derived paths are both outside `C:\co`
- WHEN `file_search` is called with `phrase="informa"`
- THEN the row is dropped, not returned

#### Scenario: Row whose display path already passes containment is unchanged

- GIVEN `file_search_allowed_roots: ["C:\\co"]` and a phrase-query adapter row whose display-derived path is already `C:\co\notes.txt` (contained) and whose `ItemUrl`-derived path is some other value
- WHEN `file_search` is called with `phrase="informa"`
- THEN the row is returned with `path` exactly as the adapter reported it, never rewritten to the `ItemUrl` form

### Requirement: Search Output Shape

The tool MUST return a list of `FileSummary` objects: `path`, `name`,
`size` (bytes), `lastModified` (ISO 8601). It MUST NOT include content.
The response MUST additionally report `results_truncated`: `true` when
the filesystem walk stopped early due to a result/time/directory cap
(see `filesystem-walk-search`), OR when the phrase-involving adapter
call itself returned a truncated result (bridge-streaming-hotfix — the
PowerShell bridge leg was killed at its read deadline, or its child
exited early, after already streaming some rows; see the
powershell-search-bridge spec's "Exposes Whether Its Last Search Was
Truncated" requirement), `false` otherwise. For a `filename`-only query
(no adapter call at all) this is exactly the walk's own flag. For a
`phrase`-only query it is exactly the adapter's `last_search_truncated`
(there is no walk leg to contribute). For a combined `filename`+`phrase`
query it is the OR of both — either leg stopping early is enough to
warn the caller there may be more.

#### Scenario: Empty result set

- GIVEN a fake adapter/mocked walk whose result is empty for the given filters
- WHEN `file_search` is called with `filename="doesnotexist"`
- THEN the tool returns an empty list, not an error, with `results_truncated: false`

#### Scenario: Truncated walk is flagged

- GIVEN a mocked walk that hits its row cap before finishing
- WHEN `file_search` is called with a broad `filename` filter
- THEN the returned list is capped and `results_truncated: true`

#### Scenario: Truncated phrase-leg bridge result is flagged

- GIVEN an adapter whose `search()` call returns rows and sets `last_search_truncated` to `true` (a PowerShell bridge child killed at its read deadline after already streaming some rows)
- WHEN `file_search` is called with `phrase="quarterly report"` only
- THEN the response reports `results_truncated: true`

#### Scenario: Truncated phrase leg still flags a combined query even when the walk finished cleanly

- GIVEN a mocked walk that finishes cleanly (`results_truncated: false`) and an adapter whose `search()` call sets `last_search_truncated` to `true`
- WHEN `file_search` is called with both `filename` and `phrase` set
- THEN the response reports `results_truncated: true`

### Requirement: Windows Search Unavailable

The tool MUST surface a clear, catchable error when BOTH the ADO adapter
and the PowerShell bridge fail to reach the index for a `phrase`-
involving query. This requirement no longer applies to filename-only
queries, which never touch the index. The error message MUST state that
filename search still works.

#### Scenario: Both transports fail on a phrase query

- GIVEN a fake adapter/mocked bridge where both raise `WindowsSearchUnavailableError`
- WHEN `file_search` is called with `phrase="quarterly report"`
- THEN the tool returns an MCP tool error naming the index as unavailable and stating filename search still works

#### Scenario: Filename-only query is unaffected by index failure

- GIVEN a fake adapter that would raise `WindowsSearchUnavailableError` if called
- WHEN `file_search` is called with `filename="report"` only
- THEN the call succeeds via the walk and no error is raised
