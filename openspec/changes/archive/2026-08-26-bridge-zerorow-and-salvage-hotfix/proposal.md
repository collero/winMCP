# Proposal: Bridge Zero-Row Rule, Per-Column Salvage, and Invocation Debug Log

## Intent

BUG-006 (`/mnt/c/usr/WinMCP/_chatCowork/0061-cowork-bug006-volume-theory-
dead-any-row-kills.md`): live evidence from the Claude-Desktop-descendant
process route refutes the prior "full-text ranking at volume" theory.
Five phrases of wildly different expected hit counts (`Informa` ~200+,
`Solunion`/`LeanXcale` a handful, `Meloneras`/`zzqqxxyyw` zero) split
cleanly on ONE axis: every phrase that matches *anything* fails; every
phrase that matches *nothing* succeeds cleanly. The bridge has never
once delivered a row from this route — every previously-recorded
"success" was an empty answer. The failure is specifically
**materializing a row**: reading a property's value off the live OleDb
rowset once there is a row to read (an exact echo, one layer down, of
BUG-001's in-process ADO finding — "everything up to the data works").

Separately, and regardless of BUG-006's root cause, `file_search
{"phrase": "Informa"}` on the bridge-streaming-hotfix build returns
`{"results": [], "resultsTruncated": true}` — a silent wrong answer.
Auditing `PowerShellSearchBridge._invoke()`'s streaming read loop found
the actual gap: `tools/ps_bridge_search.ps1`'s own top-level `catch`
writes a single valid-JSON `{"error": "..."}` line to STDOUT (not
stderr) before exiting nonzero on a catastrophic failure. That line is
syntactically valid JSON and is not the `{"done": ...}` sentinel, so the
streaming reader appended it to `rows` as if it were a real result row.
Downstream, `_row_from_mapping` built a `FileSummary` from that bogus
row with every field empty/`None`; `tools/file_search.py`'s post-call
"drop any row outside the allowed roots" defense-in-depth filter then
silently dropped that empty-path row — losing the only diagnostic
evidence (the script's own error message) that the call had actually
failed, and leaving `results: []`, `resultsTruncated: true` with nothing
for an operator to act on. Confirmed via a new RED test constructing
exactly this stdout shape: it raised an unhandled
`pydantic.ValidationError` (caught by `tools/file_search.py`'s BUG-007
blanket-exception guard and surfaced as a generic "failed unexpectedly"
message) rather than the bridge's own typed diagnostic — the streaming
zero-row rule's blind spot was that "at least one row was actually
parsed" was checked by list-emptiness alone, not by whether the parsed
value was actually a data row.

## Fix

1. **Zero-row rule closes the blind spot.** `_invoke()`'s streaming loop
   now recognizes a `{"error": ...}` line (script-reported failure, not
   the `{"done": ...}` sentinel) and does NOT append it to `rows`; its
   message is folded into the stderr excerpt for diagnostics instead.
   With this line correctly excluded from the row count, the pre-existing
   "zero rows parsed + (killed OR died OR no sentinel) => raise" /
   "zero rows + clean exit + sentinel => legitimate empty result" rule
   (already covered by the existing streaming-hotfix test matrix) now
   also covers this previously-blind case: zero REAL rows plus a
   script-error line raises `WindowsSearchUnavailableError` with the exit
   condition and stderr excerpt, exactly as every other zero-row failure
   shape already does; a script-error line arriving after some real rows
   streamed still yields those rows as a truncated result, with the
   error line simply dropped rather than corrupting/padding it.
2. **Per-column/per-row salvage in `tools/ps_bridge_search.ps1`.**
   `Read-FieldSafe` wraps every individual column read
   (`$reader["System.*"]`) in its own try/catch: an unreadable value
   becomes JSON `null` instead of throwing, and the first failure of a
   given column name is named on stderr (`column '<name>' unreadable:
   <message>`) — later failures of the SAME column in the same run stay
   silent, so a systemically-unreadable column doesn't flood stderr with
   one line per row. The per-row emit (building the ordered hashtable
   through writing+flushing its JSON line) is wrapped in its own
   try/catch too: a row that fails entirely writes a `row skipped: ...`
   stderr note and the loop continues to the next row rather than
   aborting the whole result set. If BUG-006's live failure is a specific
   property/accessor throwing, this converts a total, zero-row failure
   into rows-with-nulls — potentially fixing the underlying bug outright;
   if the rowset dies wholesale instead, the stderr notes name exactly
   where. The `{"done": true, ...}` sentinel's semantics are unchanged —
   emitted only once the loop exhausts `$reader.Read()` cleanly.
3. **Permanent, config-gated bridge invocation debug log.** New
   `file_search_bridge_debug_log()` (`tools/settings.py`,
   `file_search_bridge_debug_log` in `config/settings.yaml`, default
   `true` for this diagnostic build — flip to `false` once BUG-006
   closes). When true, every `PowerShellSearchBridge._invoke()` call
   appends one JSON line to `bridge_invocations.log`, derived from the
   deployed script's own path (`_PS_BRIDGE_SCRIPT.parent.parent`) so each
   install (PRO/QA) logs to its own tree rather than colliding. Each line
   carries `utc`, `duration_seconds`, `exit_condition`, `rows_streamed`,
   `sentinel_seen`, `stderr_first_200`, and `sql_first_120` — written
   regardless of whether the call succeeded, returned a truncated
   result, or raised, via a `finally` wrapping the read/parse sequence.
   Wrapped fully in its own `try/except`: a broken log path (permissions,
   missing directory) never surfaces as an exception from `search()`/
   `get_info()` itself.

## Risk

Low. The zero-row-rule fix is a narrowly-scoped addition to an already-
covered code path (one new `isinstance(parsed, dict) and "error" in
parsed` branch); the per-column/per-row salvage only WIDENS what the
script tolerates (a column/row that already worked keeps working
identically); the debug log is purely additive, off by a single config
read that fails open (log-write failure is swallowed, never raised).
`tools/ps_bridge_search.ps1` has no direct pytest coverage on this WSL2
dev host (no real PowerShell available) per this file's own long-
standing precedent — verified here by careful manual review only, same
as every prior `.ps1`-touching hotfix in this project's history.

## Rollback

Redeploy the previous zip. No data migration. `file_search_bridge_debug_log`
is a new, additive config key (absent -> defaults to `true`); removing it
from `config/settings.yaml` is a no-op rollback of the log's default.

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `tools/file_search_adapter.py` | Modified | `_invoke()`'s streaming loop no longer counts a `{"error": ...}` line as a row; renamed/split into `_invoke()` (timing + `finally`-logging wrapper) + `_invoke_impl()` (the original spawn/read/parse body, now mutating a `record` dict at each exit point); new `_log_bridge_invocation()` helper and `_BRIDGE_DEBUG_LOG_PATH` module constant |
| `tools/ps_bridge_search.ps1` | Modified | New `Read-FieldSafe` per-column salvage helper (with per-column stderr dedup via `$script:LoggedColumnFailures`); per-row emit wrapped in its own try/catch with a `row skipped: ...` stderr note and loop continuation |
| `tools/settings.py` | Modified | New `file_search_bridge_debug_log()` |
| `config/settings.yaml` | Modified | New `file_search_bridge_debug_log: true` key + explanatory comment |
| `tests/test_file_search_adapter.py` | Modified | New script-error-line-is-not-a-row tests (zero real rows raises; real rows + error line stays truncated-not-padded); new bridge-invocation-debug-log tests (enabled writes expected shape; disabled writes nothing; written even when `search()` raises; write failure never raises) |
| `openspec/specs/powershell-search-bridge/spec.md` | Modified | New "Script-Reported Failure Line Is Never Counted As a Row" and "Bridge Invocation Debug Log" requirements |

## Success Criteria

- [x] A script-reported `{"error": ...}` stdout line with zero real rows
      raises `WindowsSearchUnavailableError` (exit condition + stderr),
      never a silent empty/truncated result
- [x] The same line arriving after real rows streamed does not pad or
      corrupt those rows — they are still returned, truncated, as before
- [x] `tools/ps_bridge_search.ps1` never aborts a whole result set over
      one unreadable column or one failed row — both are salvaged/skipped
      with a stderr note, and the sentinel's clean-completion semantics
      are unchanged
- [x] `file_search_bridge_debug_log` (default `true`) makes every bridge
      invocation's exit condition/rows-streamed/sentinel/stderr/sql
      observable from a log file, never raising even if the write itself
      fails
- [x] Full test suite green, zero regressions
