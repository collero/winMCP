# File Get Info Specification

## Purpose

Retrieve full indexed metadata for a single file located via
`file_search`'s `path`, so a client can inspect one result without a second
broad query. Subject to the same allowed-roots policy as `file_search`.

## Requirements

### Requirement: Get Info Input Parameters

The `file_get_info` tool MUST accept `path` (string, required) — an
absolute file path, in either `System.ItemPathDisplay` native form or the
`file:///`-style `System.ItemUrl` form previously returned by `file_search`.

#### Scenario: Valid indexed path returns detail

- GIVEN a fake adapter seeded with `C:\Users\ana\Documents\report.docx`
- WHEN `file_get_info` is called with `path="C:\Users\ana\Documents\report.docx"`
- THEN the adapter's `get_info()` is invoked with that path
- AND a `FileDetail` is returned

### Requirement: Allowed-Roots Enforcement

The tool MUST apply the same `file_search_allowed_roots` policy and default
resolution as `file_search` (see the `file-search` capability) to the
requested `path`, refusing before any adapter call when the path is not
contained within a configured or default root, using the same
case-insensitive, separator-normalized containment check.

#### Scenario: Out-of-root path is refused before the adapter is called

- GIVEN `file_search_allowed_roots: ["C:\\Users\\ana"]`
- WHEN `file_get_info` is called with `path="D:\\Shared\\budget.xlsx"`
- THEN the tool raises `SearchRootNotAllowedError` (code `search_root_not_allowed`) and the adapter's `get_info()` is never invoked

### Requirement: Path Not Found On Disk

When `path` (after the roots check and any `file:///`/native
normalization) does not resolve to an existing file or directory on
disk, the tool MUST raise a distinct, catchable error, code
`path_not_found`, before attempting any index enrichment. This is
separate from a real path simply being outside the index (see the
MODIFIED "Get Info Output Shape" requirement) — callers can now tell
"your path is wrong" from "this tree is not indexed."

#### Scenario: Nonexistent path raises the not-found error

- GIVEN a mocked `os.stat` that raises `FileNotFoundError` for `path="C:\Users\ana\ghost.txt"`
- WHEN `file_get_info` is called with that path
- THEN the tool returns an MCP tool error with code `path_not_found`

### Requirement: Get Info Output Shape

The tool MUST return a `FileDetail` containing `path`, `name`, `size`
(bytes), `createdTime` (ISO 8601), `lastModified` (ISO 8601), and
`extension`, all sourced from `os.stat` on the resolved path — never
from the Windows Search index — so a real, unindexed file returns full
core metadata. It MAY include content-derived `kind`/`snippet` fields,
populated only as enrichment when the index is reachable and the path
is indexed; both are `None` otherwise.

#### Scenario: Real, unindexed file returns full stat-based metadata

- GIVEN a mocked `os.stat` returning size/timestamps for a real file that is absent from a fake adapter's index
- WHEN `file_get_info` is called with that file's path
- THEN a `FileDetail` is returned with populated `path`/`name`/`size`/timestamps/`extension` and `snippet=None`, `kind=None` — not an error

#### Scenario: Indexed file gets enrichment fields populated

- GIVEN a mocked `os.stat` for a real file, and a fake adapter's index returning `kind`/`snippet` for that same path
- WHEN `file_get_info` is called with that file's path
- THEN the returned `FileDetail` has the enriched `kind`/`snippet` populated alongside the stat-based fields

### Requirement: Index Enrichment Failure Never Surfaces

Any failure while attempting index-backed enrichment (`kind`, `snippet`)
— whether the index is unreachable (both ADO and the PowerShell bridge
exhausted) or the path is simply absent from the index — MUST be
swallowed. `kind`/`snippet` MUST be populated as `None` rather than
raising, once the universal `os.stat` facts have already been
established for a real path.

#### Scenario: Index unavailable during enrichment does not fail the call

- GIVEN a real file confirmed to exist via a mocked `os.stat`, and a fake adapter/bridge that both raise `WindowsSearchUnavailableError` during enrichment
- WHEN `file_get_info` is called with that path
- THEN a `FileDetail` is returned with `kind=None`, `snippet=None`, not an error
