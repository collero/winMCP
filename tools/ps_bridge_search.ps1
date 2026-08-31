# PowerShell search bridge (file-search-resilience change, Phase 3;
# ps-bridge-jsonl-hotfix: JSON Lines output contract).
#
# Deployed alongside tools/file_search_adapter.py's PowerShellSearchBridge,
# invoked as a pinned, absolute Windows PowerShell 5.1 child process:
#
#   C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile
#     -NonInteractive -ExecutionPolicy Bypass -File <this script's absolute
#     path>
#
# Security model: this script is a DUMB EXECUTOR. It reads exactly one
# JSON object from stdin -- {"sql": "<already-built, already-escaped SQL
# text>"} -- and runs that string verbatim against the Windows Search
# index via System.Data.OleDb. It performs NO escaping, NO string
# interpolation of caller-controlled values, and NO parsing of anything
# other than the "sql" field. All SQL construction and value escaping
# (quote-doubling + LIKE-metacharacter neutralization) happens in Python
# (tools/file_search_adapter.py's _build_search_sql / _build_get_info_sql
# / _escape_like_value) -- reusing the exact same functions the ADO
# adapter (WindowsSearchAdapter) calls -- so there is exactly one place
# escaping logic lives, per the file-search-resilience change's live
# security review ("escape in exactly one place": two independent
# escapers, one in Python and one in PowerShell, would silently drift out
# of sync). Since stdin here is only ever written by the parent WinMCP
# server process (never directly reachable by the MCP caller), a dumb
# executor adds no additional attack surface versus a self-escaping
# script -- the actual mitigation against command/SQL injection is that
# no caller-controlled value ever appears as a bare, unescaped literal:
# by the time this script sees it, it is already-escaped SQL text.
#
# Output contract (ps-bridge-jsonl-hotfix): JSON LINES on stdout -- one
# compact JSON object per matched row (keys: ItemName, ItemPathDisplay,
# ItemUrl, Size, DateModified, Kind, FileExtension, and for get_info
# additionally DateCreated, AutoSummary), written and flushed as each row
# is read from the reader, followed by a final sentinel line
# `{"done": true, "count": N}` marking a complete, non-truncated
# response. This replaces the prior single-JSON-document contract: the
# original SQL already caps rows via `SELECT TOP <n>` (built in Python,
# shared verbatim with the ADO adapter), but even a capped, popular-word
# result set can carry enough content (long System.Search.AutoSummary
# snippets, many rows) to exceed a bounded read somewhere downstream of
# this process -- with one JSON document per line, a read cut short costs
# at most the last (possibly partial) line instead of corrupting the
# entire response into unparseable JSON. The Python side
# (`_parse_bridge_stdout`) treats a stream that ends without the sentinel
# line -- or whose last line is a partial fragment -- as
# `results_truncated=true`, a RESULT rather than an error; a malformed
# line that is NOT the last line is treated as genuine corruption and
# raised as a typed error distinguishable from truncation.
#
# On failure (before or during query execution): a single JSON object
# with an "error" key plus a nonzero exit code -- this failure path is
# unchanged by the JSON-Lines hotfix, since the Python side checks the
# exit code before ever attempting to parse stdout as JSON Lines. Date/
# time values are formatted as ISO-8601 strings via .ToString("o") so the
# Python side's pydantic models can parse them directly without any
# PowerShell-side JSON datetime quirks.
#
# bridge-streaming-hotfix: the per-row WriteLine+Flush() discipline below
# (already present since ps-bridge-jsonl-hotfix) is exactly what lets the
# Python side (tools/file_search_adapter.py::PowerShellSearchBridge._invoke)
# read this script's stdout INCREMENTALLY -- a background reader thread
# blocked in readline(), polled by the main thread under an overall
# wall-clock deadline -- and still see each row the instant it is
# written, rather than only after this whole script exits. No script
# change was needed for that half of the fix: the flush-per-line
# contract was already exactly what streaming needs.
#
# Per-column/per-row salvage (0061-cowork-bug006-volume-theory-dead-any-
# row-kills.md): live evidence from the Claude-Desktop-descendant process
# route shows the query executes and the connection is healthy, but the
# bridge has never once delivered a row from there -- the failure is
# specifically MATERIALIZING a row, i.e. reading a property's value off
# the live OleDb rowset once there is a row to read (an exact echo, one
# layer down, of BUG-001's in-process ADO finding: "everything up to the
# data works"). Read-FieldSafe below wraps EVERY column read in its own
# try/catch: an unreadable value becomes JSON null instead of aborting
# the whole row, and the first time a given column name fails it is
# named on stderr (subsequent failures of the SAME column in the SAME
# run stay silent, so a systemically-unreadable column doesn't flood
# stderr with one line per row). The per-row emit (building + writing
# the JSON line) is wrapped the same way: a row that fails entirely (an
# exception Read-FieldSafe itself doesn't catch, e.g. from ConvertTo-Json)
# is skipped with its own stderr note, and the enclosing `while
# ($reader.Read())` loop CONTINUES to the next row rather than aborting
# the whole result set. This turns what would otherwise be a total,
# zero-row failure into rows-with-nulls (potentially fixing the bug
# outright, if the failure is a specific property/accessor throwing) --
# and if the rowset dies wholesale instead, the stderr notes name exactly
# where. The `{"done": true, ...}` sentinel's semantics are unchanged: it
# is written only once the loop finishes by exhausting `$reader.Read()`
# cleanly, never on a per-row skip.

$ErrorActionPreference = "Stop"

# Emit UTF-8 on stdout regardless of the host's OEM codepage, paired with
# PsBridgeTransport's encoding="utf-8" decode (add-onenote-adapter change).
# Previously non-ASCII bytes (accented file names in ItemName/AutoSummary)
# left in the console codepage were mis-decoded on the Python side. Set
# BEFORE the first [Console]::Out access so the writer is created with it.
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function ConvertTo-IsoStringOrNull($value) {
    if ($null -eq $value) { return $null }
    return $value.ToString("o")
}

# Tracks which column names have already had a read failure reported on
# stderr this run, so a column that fails on every row (the systemic
# case) logs exactly once instead of once per row.
$script:LoggedColumnFailures = @{}

function Read-FieldSafe($reader, [string]$columnName) {
    try {
        return $reader[$columnName]
    } catch {
        if (-not $script:LoggedColumnFailures.ContainsKey($columnName)) {
            [Console]::Error.WriteLine("column '$columnName' unreadable: $($_.Exception.Message)")
            $script:LoggedColumnFailures[$columnName] = $true
        }
        return $null
    }
}

try {
    $requestJson = [Console]::In.ReadToEnd()
    $request = $requestJson | ConvertFrom-Json
    $sql = $request.sql

    if ([string]::IsNullOrEmpty($sql)) {
        throw "No 'sql' field present in the stdin request"
    }

    $stdout = [Console]::Out
    $count = 0

    $conn = New-Object System.Data.OleDb.OleDbConnection(
        "Provider=Search.CollatorDSO;Extended Properties='Application=Windows'")
    $conn.Open()
    try {
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = $sql
        $reader = $cmd.ExecuteReader()
        try {
            while ($reader.Read()) {
                # Per-row salvage: everything from reading this row's
                # columns through writing its JSON line is wrapped in one
                # try/catch. Read-FieldSafe already turns an individual
                # unreadable COLUMN into a null (see its own comment
                # above) rather than throwing, so this outer catch is for
                # whatever ELSE can still go wrong materializing/emitting
                # the row (e.g. ConvertTo-Json itself failing) -- a row
                # that fails entirely is skipped with a stderr note, and
                # the loop CONTINUES to the next row rather than aborting
                # the whole result set.
                try {
                    $row = [ordered]@{
                        ItemName        = Read-FieldSafe $reader "System.ItemName"
                        ItemPathDisplay = Read-FieldSafe $reader "System.ItemPathDisplay"
                        ItemUrl         = Read-FieldSafe $reader "System.ItemUrl"
                        Size            = Read-FieldSafe $reader "System.Size"
                        DateModified    = ConvertTo-IsoStringOrNull (Read-FieldSafe $reader "System.DateModified")
                        Kind            = Read-FieldSafe $reader "System.Kind"
                        FileExtension   = Read-FieldSafe $reader "System.FileExtension"
                    }
                    # get_info's SELECT list additionally carries these two
                    # columns (see _DETAIL_FIELDS); a search() query's SELECT
                    # list never includes them, so the reader simply won't
                    # have these columns -- guarded explicitly below rather
                    # than relying on an ordinal lookup throwing.
                    $fieldNames = @()
                    for ($i = 0; $i -lt $reader.FieldCount; $i++) {
                        $fieldNames += $reader.GetName($i)
                    }
                    if ($fieldNames -contains "System.DateCreated") {
                        $row["DateCreated"] = ConvertTo-IsoStringOrNull (Read-FieldSafe $reader "System.DateCreated")
                    }
                    if ($fieldNames -contains "System.Search.AutoSummary") {
                        $row["AutoSummary"] = Read-FieldSafe $reader "System.Search.AutoSummary"
                    }
                    # JSON Lines: one compact JSON object per row, written and
                    # flushed immediately -- unlike building one big array and
                    # serializing it at the end, a bounded/truncated read of
                    # stdout then costs at most the last (possibly partial)
                    # line instead of corrupting the entire response.
                    $stdout.WriteLine((ConvertTo-Json -InputObject ([pscustomobject]$row) -Compress -Depth 6))
                    $stdout.Flush()
                    $count++
                } catch {
                    [Console]::Error.WriteLine("row skipped: $($_.Exception.Message)")
                    continue
                }
            }
        } finally {
            $reader.Close()
        }
    } finally {
        $conn.Close()
    }

    # Final sentinel line: marks a complete, non-truncated stream and
    # carries the total row count actually emitted. A stream cut short by
    # a bounded read downstream loses this line entirely (or ends mid-
    # line) -- the Python side (_parse_bridge_stdout) treats either case
    # as results_truncated=true, not a parse error.
    $stdout.WriteLine((ConvertTo-Json -InputObject ([ordered]@{ done = $true; count = $count }) -Compress))
    $stdout.Flush()
} catch {
    [pscustomobject]@{ error = $_.Exception.Message } | ConvertTo-Json -Compress
    exit 1
}
