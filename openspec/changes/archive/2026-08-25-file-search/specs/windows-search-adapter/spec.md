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

### Requirement: Connection Failure Raises a Typed Error

When `ADODB.Connection.Open` (or `Recordset.Open`) raises, the adapter MUST
raise `WindowsSearchUnavailableError` (code `windows_search_unavailable`,
subclassing `CalendarToolError` per the existing taxonomy-reuse decision),
never a bare/unhandled COM exception.

#### Scenario: Connection.Open failure is mapped to a typed error

- GIVEN a fake `win32com.client` module whose `ADODB.Connection.Open` raises a COM error
- WHEN the real adapter's `search()` or `get_info()` is called
- THEN the adapter raises `WindowsSearchUnavailableError`, not the raw COM exception
