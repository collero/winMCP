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

### Requirement: Subprocess Transport and Streaming Output Contract

The bridge MUST invoke a pinned `powershell.exe` (see "Host Pinning"
below) against a deployed `.ps1` script referenced by its ABSOLUTE
`-File` path, which opens an `OleDbConnection` using
`Provider=Search.CollatorDSO;Extended Properties='Application=Windows'`,
executes the SQL text it receives (see "Values Passed as Data via
Stdin" below), and prints its results to stdout as **JSON Lines**: one
compact JSON object per matched row, written and flushed as each row is
read, followed by a final sentinel line `{"done": true, "count": N}`
marking a complete, non-truncated response.

The bridge MUST spawn the child as a long-running process (`Popen`, not
a single blocking call that only returns once the child exits) and read
its stdout INCREMENTALLY, line-by-line, as each line is flushed —
bridge-streaming-hotfix — rather than waiting for the child to finish
and reading its output all at once. Reading line-by-line, live, means a
stream that is cut short anywhere (a large payload, a killed/hung
child) costs at most the trailing sentinel line or one partial row,
never the whole response — and, combined with the "Wall-Clock Read
Deadline and Partial Results on Kill" requirement below, lets the bridge
act on rows as they arrive rather than only discovering a hang after the
fact. The Python side MUST parse this JSON-Lines stream into
`FileSummary`/`FileDetail` rows using the same field mapping as the ADO
adapter.

#### Scenario: Valid JSON Lines stdout is parsed into results

- GIVEN a mocked subprocess child streaming one JSON object per line plus a trailing `{"done": true, "count": N}` sentinel line on stdout, exit code 0
- WHEN the bridge executes a `phrase` query
- THEN the parsed rows are returned as `FileSummary` objects

### Requirement: Wall-Clock Read Deadline and Partial Results on Kill

The bridge MUST enforce an overall wall-clock deadline
(`file_search_ps_bridge_timeout_seconds`, default `30` —
bridge-streaming-hotfix, bumped from `10`) on its streaming read of the
child's stdout. If the deadline elapses, or the child's stdout closes
(the child exited or died) before the `{"done": true, ...}` sentinel is
reached, the bridge MUST kill the child (if the deadline was what
triggered this) and return whatever rows parsed cleanly before the cut
— a RESULT, not an error, exactly as when the sentinel is simply missing
(see "Truncated Stream Is a Result, Not an Error" below): a child killed
after already streaming N rows yields N results. This holds regardless
of WHY the sentinel was never reached — deadline expiry or the child
dying/exiting on its own — as long as at least one row parsed. Only
when ZERO rows parsed AND the sentinel was never reached MUST the bridge
raise `WindowsSearchUnavailableError`, since an empty-but-unconfirmed
read is indistinguishable from a broken bridge with nothing to show for
it (an empty CONFIRMED result — the sentinel reached with zero rows — is
never an error; see the file-search spec).

This rule is keyed ENTIRELY on whether the `{"done": ...}` sentinel was
reached, never on the child's exit code — a clean `exit code 0` with
zero rows and no sentinel MUST raise exactly like any other exit
condition in this situation (alias-containment-hotfix, verifier's
refinement: the exit code is diagnostic detail carried in the raised
message, not itself part of the pass/fail decision).

#### Scenario: A child that streams rows then hangs is killed and its rows returned

- GIVEN a mocked subprocess child that streams N JSON row lines on stdout, then never writes further output and never closes its pipe
- WHEN the bridge executes a query and the configured deadline elapses
- THEN the child is killed, and the N rows already streamed are returned as `FileSummary` objects with no exception raised

#### Scenario: A child that exits early with no sentinel yields its rows, not an error

- GIVEN a mocked subprocess child that streams N JSON row lines then closes its stdout (exits) without ever writing the `{"done": true, ...}` sentinel
- WHEN the bridge executes a query
- THEN the N rows already streamed are returned as `FileSummary` objects with no exception raised, and no kill is issued (the child already exited on its own)

#### Scenario: Zero rows and no sentinel raises, never returned as an empty result

- GIVEN a mocked subprocess child whose stdout closes with zero row lines written and no sentinel line
- WHEN the bridge executes a query
- THEN `WindowsSearchUnavailableError` is raised rather than an empty result list

**Known platform limitation (documented, not a defect):** on the
Claude-Desktop-descendant process ancestry, live evidence shows the
`OleDbConnection` rowset reliably delivers its FIRST chunk of rows (~50)
but dies partway through fetching the SECOND chunk — the child streams
those ~50 real rows, then either emits a script-reported `{"error":
...}` line or simply closes its stdout, with no `{"done": ...}`
sentinel. Per the rules above, this is a truncated RESULT (the ~50 rows
are returned, `results_truncated: true`), not an error, as long as at
least one row parsed. On this process ancestry, a broad `phrase` query
therefore effectively caps at the provider's first chunk regardless of
how many total matches exist in the index — a platform/COM-marshalling
limitation of this specific spawn path, not something either
`tools/ps_bridge_search.ps1` or `PowerShellSearchBridge` can work
around by retrying or re-querying.

### Requirement: Truncated Stream Is a Result, Not an Error

When the JSON Lines stdout stream ends without ever reaching the
`{"done": true, ...}` sentinel line — whether because the sentinel line
is missing entirely, the last line is a partial JSON fragment (the exact
shape produced when a read is cut mid-record), or the read was cut short
by the deadline/kill mechanics above — the bridge MUST NOT raise (unless
zero rows parsed at all — see "Wall-Clock Read Deadline and Partial
Results on Kill" above). It MUST return the rows that parsed cleanly
before the cut. This is distinct from a malformed line that is NOT the
last line: that line had every opportunity to be written in full, so
failing to parse it is genuine corruption (the script emitting something
unexpected), not truncation, and MUST raise
`WindowsSearchUnavailableError` with a message that names it as
unparseable output — worded distinguishably from the timeout/blocked/
nonzero-exit messages, since the correct operator response differs (the
script itself needs investigation, not "the index was slow" or "the
process was blocked"). A genuinely corrupt stream MUST also cause the
child to be killed, since its output can no longer be trusted.

#### Scenario: Missing sentinel line yields partial results, not an error

- GIVEN a mocked subprocess child whose stdout closes after valid row lines but no trailing `{"done": true, ...}` sentinel line, exit code 0
- WHEN the bridge executes a `phrase` query
- THEN the rows that parsed cleanly are returned as `FileSummary` objects, and no exception is raised

#### Scenario: Partial last line yields the earlier complete rows, not an error

- GIVEN a mocked subprocess child whose stdout closes with a JSON fragment cut mid-object as the last line, with complete row lines before it
- WHEN the bridge executes a `phrase` query
- THEN the rows from the complete lines before the cut are returned, and no exception is raised

#### Scenario: A non-last-line parse failure is genuine corruption, raises, and kills the child

- GIVEN a mocked subprocess child whose stdout streams a line that is NOT the last line and fails to parse as JSON, followed by a further line
- WHEN the bridge executes a `phrase` query
- THEN `WindowsSearchUnavailableError` is raised, with a message stating the output was unparseable — distinguishable from a truncation result and from the timeout/blocked/nonzero-exit messages — and the child is killed

### Requirement: Script-Reported Failure Line Is Never Counted As a Row

The deployed script's own top-level failure handler writes a single
valid-JSON `{"error": "<message>"}` line to stdout (not stderr) before
exiting nonzero, distinct from a per-row/per-column data line and from
the `{"done": true, ...}` sentinel. The bridge's streaming reader MUST
recognize this shape (a parsed JSON object containing an `"error"` key
that is not the `"done"` sentinel) and MUST NOT append it to the parsed
rows — a script-reported failure line is not a data row, and counting it
as one would let the "at least one row was actually parsed" test in the
zero-row rule (see "Wall-Clock Read Deadline and Partial Results on
Kill") pass on a call that in fact produced zero usable results,
silently masking the failure as an empty or garbage result instead of
raising. Its message MUST be folded into the failure's diagnostic detail
(the same stderr-excerpt channel every other failure message already
uses) rather than discarded. Whether zero rows had been parsed before
this line arrived (raises, per the zero-row rule) or one or more real
rows had already streamed (those rows are returned as a truncated
result, exactly as when the sentinel is otherwise missing — the error
line is dropped, not appended) follows the same rule already governing
every other "no sentinel reached" shape.

The error line's text MUST ALSO be recorded into the bridge invocation
debug log (see "Bridge Invocation Debug Log" below) under its own
`error_line_first_200` field — independently of whether the call
actually raised — so a partial-success shape (one or more real rows
streamed, THEN the error line, so `search()` returns normally rather
than raising) still leaves the script's own error text somewhere an
operator can find it, since in that shape it never reaches any raised
exception's message at all (alias-containment-hotfix piece 3).

#### Scenario: A script-error line's text is recorded in the debug log even when the call does not raise

- GIVEN `file_search_bridge_debug_log` is true and a mocked subprocess child that streams one real row, then an `{"error": "..."}` line, then closes (no sentinel), exit code nonzero
- WHEN the bridge executes a `phrase` query
- THEN `search()` returns the one streamed row without raising, and the debug log's `error_line_first_200` field contains the error line's text

#### Scenario: A lone script-error line with zero real rows raises, not an empty result

- GIVEN a mocked subprocess child whose stdout is exactly one `{"error": "..."}` line (no sentinel), exit code nonzero
- WHEN the bridge executes a `phrase` query
- THEN `WindowsSearchUnavailableError` is raised (never an empty or garbage result), carrying the exit condition and the script's error text

#### Scenario: A script-error line after real rows does not pad or corrupt the result

- GIVEN a mocked subprocess child that streams one or more valid row lines, then a `{"error": "..."}` line, then closes (no sentinel), exit code nonzero
- WHEN the bridge executes a `phrase` query
- THEN the rows streamed before the error line are returned as a truncated result, with no extra/garbage entry for the error line itself

### Requirement: Bridge Invocation Debug Log

The bridge MUST support a config-gated, permanent diagnostic log: when
`file_search_bridge_debug_log` (`config/settings.yaml`, default `true`)
is true, every invocation — successful, truncated-partial, or raised —
MUST append exactly one line to a log file derived from the deployed
script's own installed location (so a QA install logs to its own tree,
never colliding with a PRO install), recording at minimum: the UTC
timestamp, the call's duration, the exit condition (a real exit code,
`killed@Ns`, or an equivalent descriptor), the count of rows actually
streamed, whether the `{"done": ...}` sentinel was seen, the first
~200 characters of stderr, the first ~120 characters of the SQL
text sent, and the first ~200 characters of the script's own
`{"error": ...}` line's text when one was seen during the invocation
(`error_line_first_200`, empty string when none was seen —
alias-containment-hotfix piece 3; see "Script-Reported Failure Line Is
Never Counted As a Row" above). This logging MUST be entirely
best-effort: a failure to read the config, format the line, or write
the file MUST NOT raise or alter the outcome of the call that triggered
it. When the config flag is false, nothing MUST be written.

#### Scenario: An enabled debug log records a call's shape regardless of outcome

- GIVEN `file_search_bridge_debug_log` is true and a mocked subprocess child that streams rows and reaches the sentinel
- WHEN the bridge executes a query
- THEN one log line is appended containing the UTC timestamp, duration, exit condition, rows-streamed count, sentinel-seen flag, stderr excerpt, and SQL excerpt

#### Scenario: A disabled debug log writes nothing

- GIVEN `file_search_bridge_debug_log` is false
- WHEN the bridge executes any query
- THEN no log file write occurs

#### Scenario: The debug log is written even when the call raises

- GIVEN `file_search_bridge_debug_log` is true and a mocked subprocess child whose stdout closes immediately with zero rows and a nonzero exit code
- WHEN the bridge executes a query and raises `WindowsSearchUnavailableError`
- THEN a log line is still appended, recording the exit condition and stderr excerpt that also appear in the raised error's message

#### Scenario: A broken log path never raises from the bridge call itself

- GIVEN `file_search_bridge_debug_log` is true and the log file's path is unwritable
- WHEN the bridge executes a query
- THEN the query's own result (or typed error) is unaffected, and no exception escapes from the logging attempt itself

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

- GIVEN a mocked subprocess capturing its argv
- WHEN the bridge executes any query
- THEN argv\[0\] is exactly `C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe`, and argv includes `-NoProfile`, `-NonInteractive`, `-ExecutionPolicy`, `Bypass`, and `-File` followed by an absolute script path

### Requirement: Failure Mapping and Diagnostic Detail

Any failure — spawn failure, the read deadline being hit with zero rows,
a child exiting with zero rows and no sentinel, or malformed/non-JSON
output — MUST be mapped to `WindowsSearchUnavailableError`, never a raw
`subprocess`/`queue`/`threading` exception or any other untyped
exception. A spawn failure (the process never started at all — missing
executable, AppLocker/Constrained Language Mode denial, access denied)
MUST raise a message an operator can tell apart from every other failure
class, since the appropriate response differs ("check the deployment/
policy" vs. "check whether the index is just slow" vs. "the script
itself is broken") and spawn-blocked is the common case on managed
corporate machines.

Every failure message (bridge-streaming-hotfix requirement 4) MUST
include the exit condition — the child's actual exit code, or
`killed@Ns` when the configured read deadline itself is what triggered
the kill — and, when the child produced any stderr output, the first
approximately 200 characters of it. An operator seeing
`windows_search_unavailable` must never have to guess whether the child
ran at all, finished, was killed, or said anything on stderr before that
happened.

Beyond the specific failure shapes enumerated above and in "Wall-Clock
Read Deadline and Partial Results on Kill" / "Truncated Stream Is a
Result, Not an Error" above, the ENTIRE spawn-read-parse sequence MUST
be wrapped in a blanket exception mapping so that any unforeseen
exception — not just the ones this spec enumerates — is also mapped to
`WindowsSearchUnavailableError` rather than escaping as a raw, untyped
exception. The typed error is the contract at this boundary; an
unhandled exception of any kind breaks it.

#### Scenario: Spawn failure maps to a distinctly-worded typed error

- GIVEN a mocked subprocess spawn call that raises `FileNotFoundError`/`OSError` (the child process never started)
- WHEN the bridge executes a query
- THEN `WindowsSearchUnavailableError` is raised with a message indicating the bridge is blocked or unavailable, distinguishable from every other failure class's message

#### Scenario: Read deadline hit with zero rows raises with a killed-at-deadline exit descriptor

- GIVEN a mocked subprocess child that never writes any output and never closes its pipe
- WHEN the bridge executes a query and the configured deadline elapses
- THEN `WindowsSearchUnavailableError` is raised with a message including `killed@Ns` (the configured deadline) as the exit descriptor

#### Scenario: Child exits with zero rows and a nonzero exit code raises with the exit code and stderr excerpt

- GIVEN a mocked subprocess child whose stdout closes immediately with zero row lines, exit code 1, and stderr text
- WHEN the bridge executes a query
- THEN `WindowsSearchUnavailableError` is raised with a message including the exit code and the stderr text

#### Scenario: Malformed non-last line maps to the typed error and includes diagnostics

- GIVEN a mocked subprocess child whose stdout streams a non-JSON line that is NOT the last line, followed by a further line
- WHEN the bridge parses the result
- THEN `WindowsSearchUnavailableError` is raised, not an unhandled parse exception, with the same exit-condition/stderr diagnostic detail as every other failure — see "Truncated Stream Is a Result, Not an Error" above for the last-line exception to this rule

#### Scenario: Absent stderr does not itself raise a fresh untyped exception while building the message

- GIVEN a mocked subprocess child with zero rows, a nonzero exit code, and no stderr output at all
- WHEN the bridge executes a query
- THEN `WindowsSearchUnavailableError` is raised describing the exit condition, without any exception raised while building that message

#### Scenario: An unforeseen exception during invocation still maps to the typed error

- GIVEN a mocked subprocess spawn call that raises an exception of a type this spec does not otherwise enumerate (e.g. a bare `ValueError`/`RuntimeError`)
- WHEN the bridge executes a query
- THEN `WindowsSearchUnavailableError` is raised, carrying the original exception's message, rather than the raw exception type escaping

### Requirement: Both-Transports-Exhausted Messaging

When both the ADO adapter and the PowerShell bridge fail for the same
`phrase` query, the resulting `WindowsSearchUnavailableError`'s message
MUST explicitly state that filename search still works, joined to the
underlying cause as a properly punctuated separate sentence (`'. '`
between the cause and the advice) — never a bare-space concatenation,
which reads as one run-on/garbled clause since the cause's own message
never carries trailing punctuation (BUG-006,
0043-cowork-bug-006-ps-bridge-malformed-json.md).

#### Scenario: Combined failure message names the filename fallback

- GIVEN a fake ADO adapter and a mocked bridge subprocess that both fail
- WHEN a `phrase` query executes
- THEN the raised error's message states that filename search is still available

#### Scenario: Combined failure message is two properly punctuated sentences

- GIVEN a fake ADO adapter and a mocked bridge subprocess that both fail with a cause message carrying no trailing punctuation
- WHEN a `phrase` query executes
- THEN the raised error's full message reads as the cause, a period and a space, then the filename-still-works advice — never the cause's last word run directly into the advice's first word

### Requirement: Exposes Whether Its Last Search Was Truncated

The bridge MUST expose, after every `search()` call, whether that call
returned a truncated result (per "Wall-Clock Read Deadline and Partial
Results on Kill" / "Truncated Stream Is a Result, Not an Error" above)
via a `last_search_truncated` boolean attribute — `True` when rows were
returned without the sentinel being reached, `False` on a clean,
sentinel-terminated response. This is a documented attribute rather
than a widened `search()` return type, so the `FileSearchPort` interface
and every other implementation of it (`WindowsSearchAdapter`,
`FakeFileSearchAdapter`) are unaffected — callers read it via
`getattr(adapter, "last_search_truncated", False)`, which defaults
cleanly for any transport that never sets it. The file-search spec's
"Search Output Shape" requirement covers how this signal is folded into
`FileSearchResponse.results_truncated` at the tool layer.

#### Scenario: A truncated bridge search sets the attribute true

- GIVEN a mocked subprocess child that streams rows then is killed at the read deadline before the sentinel
- WHEN the bridge's `search()` returns
- THEN `bridge.last_search_truncated` is `True`

#### Scenario: A clean, sentinel-terminated search sets the attribute false

- GIVEN a mocked subprocess child that streams rows followed by the `{"done": true, ...}` sentinel
- WHEN the bridge's `search()` returns
- THEN `bridge.last_search_truncated` is `False`
