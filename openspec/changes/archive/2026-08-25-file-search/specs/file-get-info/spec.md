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

### Requirement: Get Info Output Shape

The tool MUST return a `FileDetail` containing `path`, `name`, `size`
(bytes), `createdTime` (ISO 8601), `lastModified` (ISO 8601), and
`extension`. It MAY include a content-derived `snippet` field when
available from the index.

#### Scenario: Detail omits content when not indexed

- GIVEN a fake adapter whose seeded file has no indexed content snippet
- WHEN `file_get_info` is called with that file's path
- THEN the returned `FileDetail` has `snippet=None` rather than raising an error

### Requirement: File Not Found In Index

The tool MUST surface a clear, catchable error, code `file_not_found_in_index`,
when `path` does not resolve to any indexed item — never an unhandled
crash or a silently empty/default response.

#### Scenario: Unknown path yields a typed error

- GIVEN a fake adapter configured so `path="C:\Users\ana\ghost.txt"` raises `FileNotFoundInIndexError`
- WHEN `file_get_info` is called with that path
- THEN the tool returns an MCP tool error with code `file_not_found_in_index`

### Requirement: OneDrive Placeholder Metadata

For a locally-synced OneDrive Files-On-Demand placeholder (not yet
hydrated), `file_get_info` MUST still return core metadata (`path`, `name`,
`size`, `createdTime`, `lastModified`, `extension`) sourced from the index,
even when content-derived properties (e.g. `snippet`) are sparse or absent
because the file body has not been downloaded. This is a documented
limitation of the underlying index, not a tool error.

#### Scenario: Placeholder file still returns core metadata

- GIVEN a fake adapter seeded with a placeholder file that has `size` and
  timestamps but no content snippet
- WHEN `file_get_info` is called with that file's path
- THEN the tool returns a `FileDetail` with populated `path`/`name`/`size`/timestamps and `snippet=None`, not an error

### Requirement: Windows Search Unavailable

The tool MUST surface a clear, catchable error when the adapter cannot
reach the Windows Search index.

#### Scenario: ADODB connection failure

- GIVEN a fake adapter configured to raise `WindowsSearchUnavailableError` from `get_info()`
- WHEN `file_get_info` is called with any path
- THEN the tool returns an MCP tool error whose message identifies the Windows Search index as unavailable
