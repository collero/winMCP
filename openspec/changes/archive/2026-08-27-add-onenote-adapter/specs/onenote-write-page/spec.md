# OneNote Write Page Specification

## Purpose

Create and update OneNote pages via `OneNote.Application`, restricted to a
configurable writable-notebook allowlist so an LLM-driven write can never
land on one of the 8 live Informa notebooks by mistake.
`UpdatePageContent`'s `dateExpectedLastModified` parameter provides
optimistic concurrency: a stale write MUST surface as a typed conflict,
never a silent overwrite.

## Requirements

### Requirement: Writable Notebook Allowlist

Every `onenote_create_page`/`onenote_update_page` call MUST be checked, in
Python before any adapter/COM call, against `onenote_writable_notebooks`
(`config/settings.yaml`, read via `tools/settings.py::load_settings()`), a
list of notebook names. When the key is absent, the default MUST be
exactly `["z - Test Notebook"]`. A write whose target page's/section's
notebook is not in the allowlist MUST be rejected with
`OneNoteWriteNotAllowedError` (code `onenote_notebook_not_allowed`) before the
adapter is invoked.

#### Scenario: Write to the default test notebook succeeds

- GIVEN `onenote_writable_notebooks` unset (default applies) and a fake
  adapter whose target section resolves to notebook `"z - Test Notebook"`
- WHEN `onenote_create_page` is called targeting that section
- THEN the adapter's `create_page()` is invoked

#### Scenario: Write to a live notebook is refused before any adapter call

- GIVEN `onenote_writable_notebooks` unset (default applies) and a fake
  adapter whose target section resolves to notebook
  `"Informa - Proyectos"`
- WHEN `onenote_update_page` is called targeting that section
- THEN the tool raises `OneNoteWriteNotAllowedError` (code
  `onenote_notebook_not_allowed`) and the adapter's `update_page()` is
  never called

#### Scenario: Configured allowlist widens the writable set

- GIVEN `onenote_writable_notebooks: ["z - Test Notebook", "Sandbox"]` and
  a fake adapter whose target resolves to notebook `"Sandbox"`
- WHEN `onenote_create_page` is called targeting that section
- THEN the write proceeds

### Requirement: Create Page Input/Output

The `onenote_create_page` tool MUST accept `sectionId` (string, required)
and `title`/`bodyText` (strings, required), and MUST return the created
`PageDetail` (including its new `pageId`).

#### Scenario: Successful creation

- GIVEN an allowlisted section and a fake adapter whose
  `create_page(section_id, title, body_text)` returns a `PageDetail` with
  a new `pageId`
- WHEN `onenote_create_page` is called with that `sectionId`, `title`,
  `bodyText`
- THEN the returned `PageDetail.pageId` matches the adapter's result

### Requirement: Update Page Requires Optimistic Concurrency

The `onenote_update_page` tool MUST accept `pageId`, `bodyText`
(required), and `dateExpectedLastModified` (ISO 8601, required), passing
it through to the adapter's `UpdatePageContent` call unchanged — never
defaulting it to `[DateTime]::MinValue` or any other value that would
bypass the concurrency check.

#### Scenario: Matching dateExpectedLastModified succeeds

- GIVEN an allowlisted page and a fake adapter whose `update_page(page_id,
  body_text, date_expected_last_modified)` succeeds when the passed date
  matches the page's real last-modified
- WHEN `onenote_update_page` is called with that page's current
  `dateExpectedLastModified`
- THEN the update succeeds and the returned `PageDetail` reflects the new
  `bodyText`

### Requirement: Conflicting Update Raises, Never Silently Overwrites

When the page was modified after the caller's `dateExpectedLastModified`,
the adapter/bridge MUST report a conflict and the tool MUST raise
`OneNotePageConflictError` (code `onenote_page_conflict`), never silently apply
the write.

#### Scenario: Stale dateExpectedLastModified is rejected

- GIVEN a fake adapter whose `update_page()` raises `OneNotePageConflictError`
  when the passed date is older than the page's real last-modified
- WHEN `onenote_update_page` is called with a stale
  `dateExpectedLastModified`
- THEN the tool returns an MCP tool error with code
  `onenote_page_conflict`, and the fake adapter records no successful
  write

### Requirement: OneNote Unavailable

Both write tools MUST surface `OneNoteUnavailableError` (code
`onenote_unavailable`) as a clear MCP tool error when the adapter cannot
reach OneNote/the bridge.

#### Scenario: Bridge failure on create

- GIVEN an allowlisted section and a fake adapter configured to raise
  `OneNoteUnavailableError` from `create_page()`
- WHEN `onenote_create_page` is called
- THEN the tool returns an MCP tool error with code `onenote_unavailable`
