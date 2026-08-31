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

### Requirement: Search Output Shape

The tool MUST return a list of `FileSummary` objects: `path`, `name`,
`size` (bytes), `lastModified` (ISO 8601). It MUST NOT include content.

#### Scenario: Empty result set

- GIVEN a fake adapter whose `search()` returns an empty list for the given filters
- WHEN `file_search` is called with `filename="doesnotexist"`
- THEN the tool returns an empty list, not an error

### Requirement: Windows Search Unavailable

The tool MUST surface a clear, catchable error when the adapter cannot
reach the index.

#### Scenario: ADODB connection failure

- GIVEN a fake adapter that raises `WindowsSearchUnavailableError` from `search()` (simulating `ADODB.Connection.Open` failing)
- WHEN `file_search` is called with any valid filter
- THEN the tool returns an MCP tool error naming the index as unavailable
