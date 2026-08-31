# OneNote Get Page Specification

## Purpose

Fetch full, read-only text detail for a single OneNote page identified by
its page id, typically after an `onenote_search` call. Fetching a page
MUST NOT mutate any notebook/section/page state.

## Requirements

### Requirement: Get Page Input/Output

The `onenote_get_page` tool MUST accept `pageId` (string, required) and
MUST return a `PageDetail` object with `pageId`, `title`, `bodyText`
(plain text, paragraphs joined), `notebookName`, `sectionName`, and
`lastModifiedDateTime` (ISO 8601).

#### Scenario: Successful fetch

- GIVEN a fake adapter whose `get_page("PAGE-1")` returns a `PageDetail`
  with `title="Reunión semanal"`, `body_text="Notas de la reunión."`
- WHEN `onenote_get_page` is called with `pageId="PAGE-1"`
- THEN the tool returns `title`, `bodyText`, `notebookName`,
  `sectionName`, and `lastModifiedDateTime` matching the adapter's result

### Requirement: Page Not Found

The tool MUST return a clear not-found error, not a crash, when `pageId`
does not resolve to a page.

#### Scenario: Unknown pageId

- GIVEN a fake adapter whose `get_page("BAD-ID")` raises
  `OneNotePageNotFoundError` (code `onenote_page_not_found`)
- WHEN `onenote_get_page` is called with `pageId="BAD-ID"`
- THEN the tool returns an MCP tool error with code
  `onenote_page_not_found`

### Requirement: Empty Body Handling

The tool MUST return an empty string for `bodyText` (not an error) when
the page has no body paragraphs.

#### Scenario: Page with no body text

- GIVEN a fake adapter whose `get_page("PAGE-2")` returns a `PageDetail`
  with `body_text=""`
- WHEN `onenote_get_page` is called with `pageId="PAGE-2"`
- THEN the tool returns successfully with `bodyText=""` and the correct
  `title`

### Requirement: OneNote Unavailable

The tool MUST surface `OneNoteUnavailableError` (code `onenote_unavailable`)
as a clear MCP tool error when the adapter cannot reach OneNote/the
bridge.

#### Scenario: Bridge failure

- GIVEN a fake adapter configured to raise `OneNoteUnavailableError` from
  `get_page()`
- WHEN `onenote_get_page` is called with any `pageId`
- THEN the tool returns an MCP tool error with code `onenote_unavailable`

### Requirement: No Mutation on Fetch

Fetching a page's detail MUST NOT change any notebook/section/page state.

#### Scenario: Fetch does not alter the page

- GIVEN a fake adapter whose seeded `PageDetail` for `pageId="PAGE-3"` has
  no mutable state tracked by the fake
- WHEN `onenote_get_page` is called with `pageId="PAGE-3"` twice in a row
- THEN both calls return identical content and the fake adapter records
  no call to `create_page`/`update_page`
