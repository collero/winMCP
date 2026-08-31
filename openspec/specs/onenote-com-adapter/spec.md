# OneNote COM Adapter Specification

## Purpose

Isolate all `OneNote.Application` COM access behind a single adapter
interface (`OneNotePort`) so tool logic and its tests never depend on COM
or `powershell.exe` being available — the dev/CI host is WSL2 Linux while
the runtime target is Windows. Access is via COM through a dedicated
PowerShell 5.1 bridge process, mirroring `powershell-search-bridge`'s
dumb-executor pattern; Windows Search's `SystemIndex` has zero `onenote:`
items (spike-verified), so this bridge is the only route to OneNote
content, not a fallback.

## Requirements

### Requirement: Adapter Interface

The system MUST define a `OneNotePort` `Protocol` exposing
`search(query) -> list[PageSummary]`, `get_hierarchy(depth=4) ->
HierarchyNode`, `get_page(page_id) -> PageDetail`, `create_page(section_id,
title, body_text) -> PageDetail`, and `update_page(page_id, body_text,
date_expected_last_modified) -> PageDetail`. Both `OneNoteAdapter` (real)
and `FakeOneNoteAdapter` (test) MUST satisfy this interface.

#### Scenario: Fake adapter satisfies the interface

- GIVEN a `FakeOneNoteAdapter` implementing every `OneNotePort` method
- WHEN a tool is called with the fake injected
- THEN the tool runs unchanged, with no reference to `powershell.exe`/COM
  on the call path

### Requirement: Dumb-Executor Bridge Transport

`OneNoteAdapter` MUST invoke a pinned `powershell.exe` 5.1 (absolute path
`C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe`) running
`tools/ps_bridge_onenote.ps1`, writing exactly one `{"op": ...}` JSON
request to the child's stdin per call and reading its stdout as JSON
Lines: zero or more result-row objects followed by a terminating
`{"done": true}` line, or a single `{"error": ...}` object plus a nonzero
exit code. The script performs no interpretation of caller values beyond
dispatching on `op` (`FindPages`, `GetHierarchy`, `GetPageContent`,
`CreateNewPage`, `UpdatePageContent`) against `OneNote.Application` — all
validation/allowlisting happens in Python before the call.

#### Scenario: A search op is sent as one JSON line on stdin

- GIVEN a mocked subprocess capturing stdin and argv
- WHEN `OneNoteAdapter.search("factura")` is called
- THEN exactly one JSON object with `"op": "FindPages"` and the query is
  written to stdin, and no query text appears in argv

#### Scenario: A script error maps to a typed error

- GIVEN a mocked subprocess whose stdout is `{"error": "..."}` and exit
  code nonzero
- WHEN any adapter method is called
- THEN `OneNoteUnavailableError` is raised, never a bare
  subprocess/parse exception

### Requirement: Dynamic XML Namespace Detection

Every adapter operation that parses OneNote XML (`GetHierarchy`,
`GetPageContent`) MUST read the `one` namespace URI from the returned
document's own root element rather than hardcoding a version string
(e.g. `.../2013/onenote`), since the namespace is OneNote-version
dependent.

#### Scenario: A page's namespace differs from the spike-observed default

- GIVEN a fake page XML payload whose root element declares a different
  `one` namespace URI than `.../2013/onenote`
- WHEN the adapter parses it
- THEN title/body extraction succeeds using the namespace read from that
  document, not a hardcoded one

### Requirement: Page Content Extraction

`get_page()`/`create_page()`/`update_page()` MUST extract a page's title
from `//one:Title//one:T` and its body as the concatenation of
`one:Outline/OEChildren/OE/T` text nodes (CDATA), returning both as plain
Unicode text in `PageDetail`.

#### Scenario: Title and body are extracted from nested CDATA nodes

- GIVEN a fake page XML payload with a `Title` element and two `OE`/`T`
  body paragraphs
- WHEN `get_page(page_id)` is called
- THEN `PageDetail.title` and `PageDetail.body_text` (paragraphs joined)
  match the payload's text content

### Requirement: Failure Mapping

Any bridge spawn failure, malformed output, or script-reported error MUST
raise `OneNoteUnavailableError` (code `onenote_unavailable`), never a
raw/unhandled exception. An unresolved `page_id` on
`get_page`/`update_page` MUST raise `OneNotePageNotFoundError` (code
`onenote_page_not_found`).

#### Scenario: Unknown page_id raises OneNotePageNotFoundError

- GIVEN a mocked bridge whose `GetPageContent` op for `page_id="BAD-ID"`
  returns `{"error": "not found"}`
- WHEN `get_page("BAD-ID")` is called
- THEN `OneNotePageNotFoundError` is raised with code `onenote_page_not_found`

### Requirement: Adapter Selection at Runtime

The server MUST select the real adapter only when `powershell.exe` and
`tools/ps_bridge_onenote.ps1` are resolvable at startup/first use;
otherwise OneNote tool calls MUST fail with a clear runtime error, not a
module-import-time crash.

#### Scenario: Bridge unavailable on this platform

- GIVEN the server runs on a host without a Windows PowerShell 5.1
  executable (e.g. this WSL2 dev host)
- WHEN a OneNote tool invokes the adapter
- THEN the tool returns a clear error stating the OneNote adapter is
  unavailable on this platform, and the server process does not crash at
  import time
