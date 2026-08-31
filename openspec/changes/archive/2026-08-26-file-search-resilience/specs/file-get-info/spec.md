# Delta for File Get Info

## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Get Info Output Shape

The tool MUST return a `FileDetail` containing `path`, `name`, `size`
(bytes), `createdTime` (ISO 8601), `lastModified` (ISO 8601), and
`extension`, all sourced from `os.stat` on the resolved path — never
from the Windows Search index — so a real, unindexed file returns full
core metadata. It MAY include content-derived `kind`/`snippet` fields,
populated only as enrichment when the index is reachable and the path
is indexed; both are `None` otherwise.
(Previously: metadata was sourced from the index, and `snippet` was
`None` only for a lack of indexed content — an unindexed real file was
previously indistinguishable from a nonexistent one, see "File Not
Found In Index" below.)

#### Scenario: Real, unindexed file returns full stat-based metadata

- GIVEN a mocked `os.stat` returning size/timestamps for a real file that is absent from a fake adapter's index
- WHEN `file_get_info` is called with that file's path
- THEN a `FileDetail` is returned with populated `path`/`name`/`size`/timestamps/`extension` and `snippet=None`, `kind=None` — not an error

#### Scenario: Indexed file gets enrichment fields populated

- GIVEN a mocked `os.stat` for a real file, and a fake adapter's index returning `kind`/`snippet` for that same path
- WHEN `file_get_info` is called with that file's path
- THEN the returned `FileDetail` has the enriched `kind`/`snippet` populated alongside the stat-based fields

## REMOVED Requirements

### Requirement: File Not Found In Index

(Reason: `file_get_info` no longer determines existence via the index —
existence is now an `os.stat` check, covered by the new "Path Not Found
On Disk" requirement above. The index is enrichment-only, and a failure
or miss there never raises; see "Index Enrichment Failure Never
Surfaces." `FileNotFoundInIndexError`/`file_not_found_in_index` remains
part of the adapter's internal vocabulary but is no longer raised to
`file_get_info` callers.)

### Requirement: OneDrive Placeholder Metadata

(Reason: subsumed by the MODIFIED "Get Info Output Shape" requirement —
core metadata is now always sourced from `os.stat`, which already
returns valid size/timestamps for an unhydrated Files-On-Demand
placeholder without any special-casing.)
