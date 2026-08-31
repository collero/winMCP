# Windows Search Adapter Specification

## Purpose

Isolate Windows Search / ADODB access behind one adapter interface
(`FileSearchPort`) so `file_search`/`file_get_info` logic and tests never
depend on `win32com` being importable — dev/CI is WSL2 Linux, runtime
target is Windows. Mirrors `outlook-com-adapter`'s seam discipline.

## Requirements

### Requirement: Adapter Interface

The system MUST define a `FileSearchPort` `Protocol` exposing
`search(filename, phrase, scope, top) -> list[FileSummary]` and
`get_info(path) -> FileDetail`. Both the real (`WindowsSearchAdapter`) and
fake (`FakeFileSearchAdapter`) implementations MUST satisfy this interface.
The adapter is config-unaware: allowed-roots policy is enforced by the tool
layer (`file-search`/`file-get-info`), not here.

#### Scenario: Fake adapter satisfies the interface

- GIVEN a fake adapter implementing `search()` and `get_info()` per the protocol
- WHEN a tool is called with the fake adapter injected
- THEN the tool code runs unchanged, with no reference to `win32com` on the call path

### Requirement: Lazy COM Import and Per-Thread CoInitialize

`WindowsSearchAdapter` MUST import `win32com.client` lazily, inside its own
dispatch helper — never at module scope — and MUST call
`pythoncom.CoInitialize()` (also lazily imported) on the current thread
before any `Dispatch("ADODB.Connection")` call, mirroring the
`com-coinitialize-hotfix` precedent (FastMCP's worker-thread pool makes COM
apartments thread-local). MUST NOT pair with `CoUninitialize()`.

#### Scenario: win32com not imported at module level

- GIVEN this WSL2 dev environment where `import win32com` fails
- WHEN `tools/file_search_adapter.py` is imported
- THEN the import succeeds and `win32com` is not added to `sys.modules`

#### Scenario: CoInitialize called before Dispatch on search and get_info

- GIVEN a fake `pythoncom` module and a fake `win32com.client` module injected into `sys.modules`
- WHEN the real adapter's `search()` or `get_info()` method is called
- THEN `pythoncom.CoInitialize()` is called before `win32com.client.Dispatch("ADODB.Connection")`

### Requirement: SQL Value Escaping

Because `Provider=Search.CollatorDSO` has no parameterized query API, the
adapter MUST escape every string value it interpolates into SQL
(`filename`, `phrase`, `scope`, `path`) by doubling embedded single quotes
before building the `WHERE`/`SCOPE=`/`CONTAINS()` clause, so a quoted value
cannot break out of its clause.

#### Scenario: Filename containing a single quote is escaped

- GIVEN a fake `win32com.client` module capturing the SQL text passed to `Recordset.Open`
- WHEN the real adapter's `search()` is called with `filename="o'brien"`
- THEN the captured SQL contains `''` in place of the raw `'`, and the clause is not truncated early

#### Scenario: Phrase containing a single quote is escaped in CONTAINS()

- GIVEN a fake `win32com.client` module capturing the SQL text
- WHEN the real adapter's `search()` is called with `phrase="user's report"`
- THEN the captured `CONTAINS()` argument has the embedded quote escaped

### Requirement: Result Cap via SQL TOP

The adapter MUST build its `SELECT TOP n ...` clause using exactly the cap
value passed by the tool layer — it MUST NOT apply its own independent
default, and MUST NOT fetch unbounded rows and truncate client-side.

#### Scenario: Adapter SQL reflects the requested cap

- GIVEN a fake `win32com.client` module capturing the SQL text
- WHEN the real adapter's `search()` is called with `top=50`
- THEN the captured SQL contains `SELECT TOP 50`

### Requirement: Path Representation Normalization

The adapter MUST normalize `System.ItemUrl` (percent-encoded
`file:///C:/...`) and/or `System.ItemPathDisplay` (native `C:\...`) into
one consistent native-path form before populating
`FileSummary.path`/`FileDetail.path`, so output paths are stable — the
same form the tool layer's roots check compares against.

#### Scenario: Percent-encoded ItemUrl is decoded and separator-normalized

- GIVEN a fake `win32com.client` recordset row whose `System.ItemUrl` is `file:///C:/Users/ana/My%20Report.docx`
- WHEN the real adapter's `search()` maps that row to a `FileSummary`
- THEN `FileSummary.path` equals `C:\Users\ana\My Report.docx`

### Requirement: Multi-Value Field Normalization

`System.Kind` is a Windows multi-value (`VT_VECTOR`) property: real ADODB/
win32com returns it as a tuple of strings — a single-element tuple (e.g.
`('link',)`) in the common case, occasionally several (e.g. `('document',
'picture')`) — never a plain string. The adapter MUST normalize it to one
string before populating `FileSummary.kind`/`FileDetail.kind`: a
single-element tuple collapses to that element, multiple elements join
with `"; "`, and a `None`/empty value stays `None`. A plain string (some
providers/rows may still hand one back) MUST also pass through unchanged.

#### Scenario: Single-element System.Kind tuple collapses to the plain string

- GIVEN a fake `win32com.client` recordset row whose `System.Kind` value is the single-element tuple `('link',)`
- WHEN the real adapter's `search()` maps that row to a `FileSummary`
- THEN `FileSummary.kind` equals `"link"`

#### Scenario: Multi-element System.Kind tuple is joined into one string

- GIVEN a fake `win32com.client` recordset row whose `System.Kind` value is the tuple `('document', 'picture')`
- WHEN the real adapter's `search()` maps that row to a `FileSummary`
- THEN `FileSummary.kind` equals `"document; picture"`

### Requirement: Connection Failure Raises a Typed Error

When `ADODB.Connection.Open` (or `Recordset.Open`) raises, the adapter MUST
raise `WindowsSearchUnavailableError` (code `windows_search_unavailable`,
subclassing `CalendarToolError` per the existing taxonomy-reuse decision),
never a bare/unhandled COM exception.

#### Scenario: Connection.Open failure is mapped to a typed error

- GIVEN a fake `win32com.client` module whose `ADODB.Connection.Open` raises a COM error
- WHEN the real adapter's `search()` or `get_info()` is called
- THEN the adapter raises `WindowsSearchUnavailableError`, not the raw COM exception

### Requirement: Fallback Transport Ordering

For any query that needs the index (`phrase` search, or `file_get_info`
enrichment), the adapter-facing seam MUST attempt the ADO
(`WindowsSearchAdapter`) transport first. Only when ADO raises
`WindowsSearchUnavailableError` MUST it attempt the PowerShell bridge
(`powershell-search-bridge` capability) as a second transport. If the
bridge also raises `WindowsSearchUnavailableError`, that exception
propagates to the tool layer unchanged; the tool layer (not this seam)
is responsible for adding the filename-still-works messaging before it
reaches the caller (see the `file-search` delta's "Windows Search
Unavailable" requirement) — this seam stays config- and message-neutral,
consistent with the adapter's existing config-unaware design.

#### Scenario: ADO success skips the bridge entirely

- GIVEN a fake ADO adapter returning results and a bridge that would raise if invoked
- WHEN a `phrase` query executes
- THEN the bridge is never invoked

#### Scenario: ADO failure falls through to the bridge, which succeeds

- GIVEN a fake ADO adapter raising `WindowsSearchUnavailableError` and a mocked bridge returning results
- WHEN a `phrase` query executes
- THEN the bridge's results are returned and no error propagates

#### Scenario: Both transports exhausted propagates the typed error unchanged

- GIVEN a fake ADO adapter and a mocked bridge that both raise `WindowsSearchUnavailableError`
- WHEN a `phrase` query executes
- THEN `WindowsSearchUnavailableError` propagates to the tool layer, with no filename-still-works text added at this layer

### Requirement: Enrichment Lookups Use the Same Fallback Ordering

`file_get_info`'s index-enrichment lookup (for `kind`/`snippet`) MUST use
the same ADO-then-bridge ordering as `phrase` search, and MUST raise
`WindowsSearchUnavailableError` (not `FileNotFoundInIndexError`) when
both transports fail to reach the index — a miss (path not indexed) is
distinguished from unreachability at this seam so the tool layer can
treat both as "no enrichment available" without conflating them
internally.

#### Scenario: Enrichment lookup falls back to the bridge

- GIVEN a fake ADO adapter raising `WindowsSearchUnavailableError` for `get_info()`, and a mocked bridge returning enrichment data
- WHEN `file_get_info` attempts enrichment for an indexed path
- THEN the bridge's `kind`/`snippet` values are used

#### Scenario: Enrichment lookup exhausted raises the unavailable error, not not-found

- GIVEN both ADO and the bridge raising `WindowsSearchUnavailableError` for `get_info()`
- WHEN `file_get_info` attempts enrichment
- THEN `WindowsSearchUnavailableError` propagates from this seam, not `FileNotFoundInIndexError`
