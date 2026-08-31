# PowerShell Search Bridge Specification

## Purpose

Provide a fallback transport to the Windows Search index for `phrase`
(full-text) queries and index-enrichment lookups, used only when the
primary ADO adapter (`WindowsSearchAdapter`) raises
`WindowsSearchUnavailableError` — since ADO is unreachable from some
process spawn paths (`REGDB_E_CLASSNOTREG`) while a `powershell.exe`
child process reaching the index via `System.Data.OleDb` has been
independently validated.

## Requirements

### Requirement: Invocation Only on ADO Failure

The bridge MUST be invoked only after the primary ADO adapter raises
`WindowsSearchUnavailableError` for a `phrase` or enrichment query. It
MUST NOT be tried first or in parallel.

#### Scenario: Bridge is not invoked when ADO succeeds

- GIVEN a fake ADO adapter that returns results for a `phrase` query
- WHEN the query executes
- THEN the PowerShell bridge subprocess is never invoked

#### Scenario: Bridge is invoked after ADO raises

- GIVEN a fake ADO adapter that raises `WindowsSearchUnavailableError`
- WHEN a `phrase` query executes
- THEN the bridge's subprocess call is invoked exactly once with the query translated to its script's input

### Requirement: Subprocess Transport and Output Contract

The bridge MUST invoke a pinned `powershell.exe` (see "Host Pinning"
below) against a deployed `.ps1` script referenced by its ABSOLUTE
`-File` path, which opens an `OleDbConnection` using
`Provider=Search.CollatorDSO;Extended Properties='Application=Windows'`,
executes the SQL text it receives (see "Values Passed as Data via
Stdin" below), and prints one JSON document to stdout. The Python side
MUST parse that JSON into `FileSummary`/`FileDetail` rows using the same
field mapping as the ADO adapter.

#### Scenario: Valid JSON stdout is parsed into results

- GIVEN a mocked `subprocess.run` returning JSON rows on stdout, exit code 0
- WHEN the bridge executes a `phrase` query
- THEN the parsed rows are returned as `FileSummary` objects

### Requirement: Values Passed as Data via Stdin, Never on the Command Line

Caller-controlled values (`filename`, `phrase`, `scope`/`roots`, `path`)
MUST NEVER appear as `powershell.exe` command-line arguments and MUST
NOT be interpolated into any `-Command`/`-EncodedCommand` string. The
bridge builds the complete, already-escaped SQL text in Python (see "SQL
Value Escaping" below) and MUST serialize it as a single JSON object
(`{"sql": "<sql text>"}`), writing that to the subprocess's stdin; the
deployed script MUST read that JSON as data (`$input`/`[Console]::In`)
and execute the `sql` field verbatim as its `OleDbCommand.CommandText` —
it performs no escaping or interpolation of its own (a "dumb executor"),
so escaping/SQL-building lives in exactly one place. Only the fixed
script path and fixed flags may appear in argv.

#### Scenario: Caller-controlled values are absent from argv, present on stdin

- GIVEN a mocked `subprocess.run`/`Popen` capturing both the argv list and the bytes written to stdin
- WHEN the bridge is invoked with `phrase="user's report"`
- THEN `"user's report"` does not appear anywhere in the captured argv, and the stdin JSON's `sql` field contains the (quote-doubled) value

### Requirement: SQL Value Escaping

The bridge MUST escape every value, in Python, before it is placed into
the SQL text sent to the script: doubling embedded single quotes
(identically to the ADO adapter's `_escape_sql` discipline, via the
shared `_escape_like_value` helper for `LIKE` clauses), AND escaping the
`LIKE` wildcard metacharacters `%`, `_`, and `[` (bracket-wrapping each
into a literal-character escape — `[%]`, `[_]`, `[[]` — the Jet/ACE SQL
dialect's native convention) so a caller-supplied value cannot widen a
`LIKE`/`CONTAINS` match or break clause structure. No caller-controlled
string is ever interpolated raw, and the same escaping/SQL-building
functions (`_build_search_sql`/`_build_get_info_sql`) are shared
verbatim between this bridge and the ADO adapter (`WindowsSearchAdapter`)
— there is exactly one escaping code path, not two that could drift out
of sync.

#### Scenario: Phrase containing a single quote is escaped before invocation

- GIVEN a mocked subprocess capturing the stdin JSON payload passed to the script
- WHEN the bridge is invoked with `phrase="user's report"`
- THEN the SQL text in the stdin payload has the embedded quote doubled, not raw

#### Scenario: Filename containing LIKE metacharacters is neutralized

- GIVEN a mocked subprocess capturing the stdin JSON payload
- WHEN the bridge is invoked with `filename="100%_[done]"`
- THEN the SQL text in the stdin payload treats `%`, `_`, and `[` as literal characters, not wildcards

#### Scenario: The escaper is verified against a table of hostile and edge-case inputs

- GIVEN the shared `_escape_like_value` helper
- WHEN it is called with each of `o'brien`, `100%`, `a_b`, `[abc]`, `it''s`, a lone backslash, an empty string, a 1000-character string, and a string of only metacharacters
- THEN each produces the exact expected escaped SQL literal (quotes doubled, `%`/`_`/`[` bracket-neutralized, non-metacharacter content passed through unchanged)

### Requirement: Hostile Input Never Reaches PowerShell Evaluation

Because values travel as data (stdin JSON), a value that looks like
PowerShell syntax MUST NOT be evaluated by the shell — it MUST only
ever be treated as SQL-bound data by the script, producing either
matching results or a clean typed error, never PowerShell command
execution and never an unhandled SQL parse error.

#### Scenario: A single quote in filename produces results or a typed error, never a parse error

- GIVEN a mocked subprocess whose stdin capture confirms `filename="o'brien"` traveled as data, and a mocked stdout returning valid JSON results
- WHEN the bridge executes `filename="o'brien"`
- THEN matching `FileSummary` results are returned, with no exception other than the bridge's own typed errors

#### Scenario: A PowerShell command-substitution payload is never evaluated

- GIVEN a mocked subprocess capturing argv and stdin for `phrase="$(Get-Date)"`
- WHEN the bridge executes that query
- THEN `$(Get-Date)` appears only inside the stdin JSON payload (never in argv, never inside a `-Command` string), and the bridge returns either matching results or `WindowsSearchUnavailableError` — never evidence of shell evaluation (e.g. a substituted date string in place of the literal query value)

### Requirement: Host Pinning

The bridge MUST invoke Windows PowerShell 5.1 by its ABSOLUTE path,
`C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe` — never a
bare `powershell`/`pwsh` resolved via `PATH` — since `System.Data.OleDb`
is unreliable under PowerShell 7 (`pwsh`) on the target hosts. The
invocation MUST pass exactly `-NoProfile -NonInteractive
-ExecutionPolicy Bypass -File <absolute deployed script path>`.

#### Scenario: Invocation uses the pinned absolute path and required flags

- GIVEN a mocked `subprocess.run` capturing its argv
- WHEN the bridge executes any query
- THEN argv\[0\] is exactly `C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe`, and argv includes `-NoProfile`, `-NonInteractive`, `-ExecutionPolicy`, `Bypass`, and `-File` followed by an absolute script path

### Requirement: Timeout and Failure Mapping

The bridge MUST enforce a timeout (`file_search_ps_bridge_timeout_seconds`,
default `10`) on the subprocess call. Any failure — timeout, nonzero
exit code, malformed/non-JSON stdout, or `powershell.exe` not found —
MUST be mapped to `WindowsSearchUnavailableError`, never a raw
`subprocess` exception. A timeout (the process started but did not
finish in time) and a spawn failure (the process never started at all —
missing executable, AppLocker/Constrained Language Mode denial, access
denied) MUST raise the same error TYPE but with messages an operator can
tell apart, since the appropriate response differs ("check whether the
index is just slow" vs "check the deployment/policy") and spawn-blocked
is the common case on managed corporate machines.

#### Scenario: Subprocess timeout maps to the typed error

- GIVEN a mocked `subprocess.run` that raises `subprocess.TimeoutExpired`
- WHEN the bridge executes a query
- THEN `WindowsSearchUnavailableError` is raised, not the raw exception, with a message indicating a timeout

#### Scenario: Subprocess spawn failure maps to a distinctly-worded typed error

- GIVEN a mocked `subprocess.run` that raises `FileNotFoundError`/`OSError` (the child process never started)
- WHEN the bridge executes a query
- THEN `WindowsSearchUnavailableError` is raised with a message distinguishable from the timeout scenario's — e.g. indicating the bridge is blocked or unavailable, not that it timed out

#### Scenario: Nonzero exit code maps to the typed error

- GIVEN a mocked `subprocess.run` returning exit code 1 with no usable stdout
- WHEN the bridge executes a query
- THEN `WindowsSearchUnavailableError` is raised

#### Scenario: Malformed JSON maps to the typed error

- GIVEN a mocked `subprocess.run` returning exit code 0 with non-JSON stdout
- WHEN the bridge parses the result
- THEN `WindowsSearchUnavailableError` is raised, not an unhandled parse exception

### Requirement: Both-Transports-Exhausted Messaging

When both the ADO adapter and the PowerShell bridge fail for the same
`phrase` query, the resulting `WindowsSearchUnavailableError`'s message
MUST explicitly state that filename search still works.

#### Scenario: Combined failure message names the filename fallback

- GIVEN a fake ADO adapter and a mocked bridge subprocess that both fail
- WHEN a `phrase` query executes
- THEN the raised error's message states that filename search is still available
