"""FileSearchPort — the seam between tool logic and Windows Search / ADODB
access (file-search change).

Defines the `FileSearchPort` Protocol satisfied by both the real,
win32com/ADODB-backed `WindowsSearchAdapter` (below — Phase 3, per the
windows-search-adapter spec's "Lazy COM Import and Per-Thread
CoInitialize" and "SQL Value Escaping" requirements) and the test-only
`FakeFileSearchAdapter` (tools/fake_file_search_adapter.py). Mirrors
`MailPort` (tools/mail_adapter.py) / `CalendarPort` (tools/outlook_adapter.py)
/ `TaskPort` (tools/task_adapter.py) — see design.md's "Mirror the mail
seam exactly" approach.

The adapter is config-unaware: allowed-roots policy is enforced by the
tool layer (`tools/file_search.py`, a later batch), not here — see the
windows-search-adapter spec's "Adapter Interface" requirement. `filename`/
`phrase` are kept as two independently-optional parameters (rather than a
single merged "query" string) because they drive semantically different
SQL clauses on the real adapter: `filename` is a `System.FileName`
substring match, `phrase` is a full-text `CONTAINS()` match — see the
file-search spec's "Search Input Parameters" requirement and the
windows-search-adapter spec's escaping scenarios, which reference
`filename=`/`phrase=` as distinct adapter call arguments. `roots` is a
list because the SQL `WHERE` clause ORs together one `SCOPE=` per root
(design.md's Data Flow / ADODB-specifics decision) — a single validated
`scope` collapses to a one-item list; unconfigured defaults may resolve to
several.

`search(filename, phrase, roots, top_n)` is the reconciled signature
across design.md/tasks.md/this module (Batch 1's apply-progress deviation
note — design.md's Interfaces/Contracts section now reads this way too).
"""
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote

from models.schemas import FileDetail, FileSummary
from tools.errors import FileNotFoundInIndexError, WindowsSearchUnavailableError
from tools.ps_bridge_transport import _PS_EXE, PsBridgeTransport, PsBridgeTransportError
from tools.settings import file_search_bridge_debug_log, file_search_ps_bridge_timeout_seconds


class FileSearchPort(Protocol):
    """Interface both the real and fake Windows Search adapters satisfy."""

    def search(
        self,
        filename: str | None,
        phrase: str | None,
        roots: list[str],
        top_n: int,
    ) -> list[FileSummary]:
        """Return file summaries matching `filename` (case-insensitive
        substring on `System.FileName`) and/or `phrase` (full-text
        `CONTAINS()` match), restricted to the given `roots` (one SQL
        `SCOPE=` per root, ORed together on the real adapter), capped at
        `top_n` rows (`SELECT TOP {top_n}` — never fetched unbounded and
        truncated client-side).

        Raises WindowsSearchUnavailableError if the index cannot be
        reached at all.
        """
        ...

    def get_info(self, path_or_url: str) -> FileDetail:
        """Return full indexed metadata for the single item identified by
        `path_or_url` — either the native `System.ItemPathDisplay` form or
        the `file:///`-style `System.ItemUrl` form.

        Raises FileNotFoundInIndexError if `path_or_url` does not resolve
        to any indexed item, WindowsSearchUnavailableError if the index
        cannot be reached at all.
        """
        ...


# --- Real adapter (Phase 3) ---

_CONNECTION_STRING = "Provider=Search.CollatorDSO;Extended Properties='Application=Windows'"

# Fields fetched for search() results — exactly design.md's ADODB
# specifics decision's SELECT list.
_SUMMARY_FIELDS: tuple[str, ...] = (
    "System.ItemName",
    "System.ItemPathDisplay",
    "System.ItemUrl",
    "System.Size",
    "System.DateModified",
    "System.Kind",
    "System.FileExtension",
)

# get_info() additionally needs System.DateCreated (FileDetail.created_time
# is required, unlike FileSummary's optional-ness) and a content-derived
# snippet field. Search.CollatorDSO's summary/preview text property is
# `System.Search.AutoSummary`; this batch's own extension beyond
# design.md's search()-only SELECT list, since no spec fixes get_info()'s
# exact SQL shape.
_DETAIL_FIELDS: tuple[str, ...] = _SUMMARY_FIELDS + (
    "System.DateCreated",
    "System.Search.AutoSummary",
)


def _escape_sql(value: str) -> str:
    """Double every embedded single quote so a string value cannot break
    out of its SQL clause — `Search.CollatorDSO` has no parameterized
    query API, per the windows-search-adapter spec's "SQL Value Escaping"
    requirement. Used for every interpolated value: filename, phrase,
    scope/root, path."""
    return value.replace("'", "''")


def _escape_contains_phrase(value: str) -> str:
    """`_escape_sql`, plus stripping embedded `"` — `CONTAINS()`'s phrase
    argument is itself wrapped in double quotes
    (`CONTAINS(*, '"...text..."')`), and there is no escape sequence for a
    `"` inside that phrase, so it is dropped rather than doubled."""
    return _escape_sql(value).replace('"', "")


def _escape_like_metacharacters(value: str) -> str:
    """Neutralize the Jet/ACE SQL dialect's `LIKE` wildcard
    metacharacters `%`, `_`, and `[` by bracket-wrapping each into a
    literal-character escape (`[[]`, `[%]`, `[_]`) — this dialect's
    native LIKE-escaping convention (no `ESCAPE` clause required, unlike
    ANSI SQL), per the powershell-search-bridge spec's "SQL Value
    Escaping" requirement. `[` MUST be escaped first: escaping `%`/`_`
    introduces new `[` characters that must not themselves be
    re-escaped."""
    value = value.replace("[", "[[]")
    value = value.replace("%", "[%]")
    value = value.replace("_", "[_]")
    return value


def _escape_like_value(value: str) -> str:
    """Full escaping discipline for a value interpolated inside a `LIKE`
    clause: quote-doubling (`_escape_sql`) THEN Jet/ACE bracket-escaping
    of the wildcard metacharacters (`_escape_like_metacharacters`).

    This is the single place `System.FileName LIKE` values are escaped —
    used by BOTH `_build_search_sql` below (the ADO adapter's leg) and
    `PowerShellSearchBridge` (which reuses `_build_search_sql`/
    `_build_get_info_sql` directly rather than re-implementing SQL
    construction) — per the file-search-resilience change's live
    security review: two independent escapers (Python and PowerShell)
    would silently drift out of sync, so escaping/SQL-building happens
    in exactly one place, and the deployed `.ps1` script is a dumb
    executor of the finished SQL text it receives over stdin."""
    return _escape_like_metacharacters(_escape_sql(value))


def _build_search_sql(
    filename: str | None, phrase: str | None, roots: list[str], top_n: int
) -> str:
    """Build the `SELECT TOP {top_n} ... FROM SystemIndex WHERE (SCOPE=...)
    AND ...` query per design.md's ADODB specifics decision. `top_n` is
    injected as-is (already a validated int from the tool layer — no
    adapter-side default, no client-side truncation). Shared verbatim by
    the PowerShell bridge (`PowerShellSearchBridge`) — see
    `_escape_like_value`'s docstring."""
    clauses: list[str] = []
    if roots:
        scope_clause = " OR ".join(f"SCOPE='file:{_escape_sql(root)}'" for root in roots)
        clauses.append(f"({scope_clause})")
    if filename:
        clauses.append(f"System.FileName LIKE '%{_escape_like_value(filename)}%'")
    if phrase:
        clauses.append(f"CONTAINS(*, '\"{_escape_contains_phrase(phrase)}\"')")

    sql = f"SELECT TOP {int(top_n)} {', '.join(_SUMMARY_FIELDS)} FROM SystemIndex"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    return sql


def _build_get_info_sql(path_or_url: str) -> str:
    """Exact lookup by either the native path form or the `file:///`-style
    URL form the caller may pass — matches whichever column the value
    actually came from, since `path_or_url` may be either."""
    escaped = _escape_sql(path_or_url)
    return (
        f"SELECT TOP 1 {', '.join(_DETAIL_FIELDS)} FROM SystemIndex "
        f"WHERE System.ItemPathDisplay = '{escaped}' OR System.ItemUrl = '{escaped}'"
    )


def _decode_item_url(item_url: Any) -> str | None:
    """Decode `System.ItemUrl`'s `file:///`-style form (`file:///`-strip +
    percent-decode + `/`->`\\`) into a native path, UNCONDITIONALLY —
    independent of whether `System.ItemPathDisplay` is also present.
    Windows Search can report a redirected-library alias in
    `ItemPathDisplay` (e.g. a `Documents` library shortcut into a
    OneDrive-synced tree) while `ItemUrl` still carries the real,
    containable path underneath — alias-containment-hotfix. Returns
    `None` when `item_url` itself is falsy (nothing to decode)."""
    if not item_url:
        return None
    decoded = unquote(str(item_url))
    if decoded.lower().startswith("file:///"):
        decoded = decoded[len("file:///") :]
    return decoded.replace("/", "\\")


def _normalize_path(path_display: Any, item_url: Any) -> str:
    """Prefer the native `System.ItemPathDisplay` form; fall back to
    decoding `System.ItemUrl` via `_decode_item_url` only if absent —
    windows-search-adapter spec's "Path Representation Normalization"
    requirement. Mirrors `tools/fake_file_search_adapter.py::_normalize`'s
    decode logic. `_decode_item_url` is ALSO called independently of this
    function (see `_row_to_summary`/`_row_from_mapping`) to expose the
    url-derived form even when `path_display` is present and thus
    preferred here — alias-containment-hotfix."""
    if path_display:
        return str(path_display)
    decoded = _decode_item_url(item_url)
    return decoded if decoded is not None else ""


def _field(recordset: Any, name: str) -> Any:
    """Read one `System.*` column's value off the current recordset row."""
    return recordset.Fields.Item(name).Value


def _normalize_multi_value(value: Any) -> str | None:
    """Some Windows Search properties (e.g. `System.Kind`) are multi-value
    (`VT_VECTOR`) — real ADODB/win32com hands them back as a tuple/list of
    strings rather than a plain string, even when there is only one value
    (`('link',)`), and occasionally several (`('document', 'picture')`).
    `FileSummary.kind`/`FileDetail.kind` are plain `str | None`, so collapse
    a tuple/list into one string, joining multiple elements with `"; "`
    (a single element collapses to just that element, an empty tuple to
    `None`). A plain string passes through unchanged; `None` stays `None`
    — matching how the schema already treats a missing/absent value."""
    if value is None:
        return None
    if isinstance(value, (tuple, list)):
        parts = [str(item) for item in value if item]
        return "; ".join(parts) if parts else None
    return str(value) if value != "" else None


def _row_to_summary(recordset: Any) -> FileSummary:
    item_url = _field(recordset, "System.ItemUrl")
    path = _normalize_path(_field(recordset, "System.ItemPathDisplay"), item_url)
    name = _field(recordset, "System.ItemName") or path.rsplit("\\", 1)[-1]
    return FileSummary(
        path=path,
        name=name,
        size=int(_field(recordset, "System.Size") or 0),
        last_modified=_field(recordset, "System.DateModified"),
        kind=_normalize_multi_value(_field(recordset, "System.Kind")),
        extension=_field(recordset, "System.FileExtension"),
        # alias-containment-hotfix: exposed regardless of whether `path`
        # above preferred the display form — see _decode_item_url's
        # docstring and FileSummary.alt_url_path's.
        alt_url_path=_decode_item_url(item_url),
    )


def _row_to_detail(recordset: Any) -> FileDetail:
    summary = _row_to_summary(recordset)
    return FileDetail(
        path=summary.path,
        name=summary.name,
        size=summary.size,
        last_modified=summary.last_modified,
        kind=summary.kind,
        extension=summary.extension,
        alt_url_path=summary.alt_url_path,
        created_time=_field(recordset, "System.DateCreated"),
        snippet=_field(recordset, "System.Search.AutoSummary") or None,
    )


class WindowsSearchAdapter:
    """Real, ADODB (`Search.CollatorDSO`)-backed `FileSearchPort`
    implementation. Mirrors `tools/outlook_adapter.py::OutlookCalendarAdapter`'s
    lazy-import/`CoInitialize` discipline: `win32com.client`/`pythoncom`
    are imported only inside `_dispatch_connection`, never at module
    scope, and `CoInitialize()` is called (once per call, no
    `CoUninitialize()` pairing — idempotent per thread) before the first
    `Dispatch("ADODB.Connection")`, per the windows-search-adapter spec's
    "Lazy COM Import and Per-Thread CoInitialize" requirement.

    The adapter is config-unaware: `roots`/`top_n` arrive already
    validated/resolved from the tool layer (a later batch) — see the
    windows-search-adapter spec's "Adapter Interface" requirement.
    """

    # ADO reads the whole recordset to EOF before returning — there is no
    # partial/truncated read on this transport, unlike
    # `PowerShellSearchBridge` (bridge-streaming-hotfix). Documented here,
    # read via `getattr(adapter, "last_search_truncated", False)` by
    # `FallbackSearchAdapter`/`tools/file_search.py` so both transports
    # expose the same duck-typed signal without widening `FileSearchPort`
    # itself.
    last_search_truncated: bool = False

    def _dispatch_connection(self) -> Any:
        """Lazily import win32com/pythoncom, CoInitialize(), open an
        `ADODB.Connection` against `Search.CollatorDSO`. Any failure here
        — missing win32com, or the Windows Search service unreachable —
        is mapped to WindowsSearchUnavailableError so callers never see a
        raw ImportError or COM exception."""
        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:
            raise WindowsSearchUnavailableError(
                "win32com is not available on this platform"
            ) from exc
        try:
            pythoncom.CoInitialize()
            connection = win32com.client.Dispatch("ADODB.Connection")
            connection.Open(_CONNECTION_STRING)
            return connection
        except Exception as exc:
            raise WindowsSearchUnavailableError(
                f"Could not connect to the Windows Search index: {exc}"
            ) from exc

    def _execute(self, connection: Any, sql: str) -> Any:
        """Open an `ADODB.Recordset` against `sql` on the given
        connection. `win32com.client` is already imported successfully by
        the time this runs (only ever called after `_dispatch_connection`
        succeeds) — re-imported here (still lazily, still inside a
        method) rather than threading the module reference through, since
        the import is a cheap `sys.modules` lookup once cached."""
        import win32com.client

        try:
            recordset = win32com.client.Dispatch("ADODB.Recordset")
            recordset.Open(sql, connection)
            return recordset
        except Exception as exc:
            raise WindowsSearchUnavailableError(
                f"Windows Search query failed: {exc}"
            ) from exc

    def search(
        self,
        filename: str | None,
        phrase: str | None,
        roots: list[str],
        top_n: int,
    ) -> list[FileSummary]:
        connection = self._dispatch_connection()
        sql = _build_search_sql(filename, phrase, roots, top_n)
        recordset = self._execute(connection, sql)

        results: list[FileSummary] = []
        while not recordset.EOF:
            results.append(_row_to_summary(recordset))
            recordset.MoveNext()
        return results

    def get_info(self, path_or_url: str) -> FileDetail:
        connection = self._dispatch_connection()
        sql = _build_get_info_sql(path_or_url)
        recordset = self._execute(connection, sql)

        if recordset.EOF:
            raise FileNotFoundInIndexError(f"No indexed file at {path_or_url!r}")
        return _row_to_detail(recordset)


# --- PowerShell bridge (Phase 3, file-search-resilience change) ---
#
# Fallback transport for `phrase`/enrichment queries, used only after the
# ADO adapter above raises WindowsSearchUnavailableError — since ADO is
# unreachable from some process spawn paths (REGDB_E_CLASSNOTREG) while a
# `powershell.exe` child process reaching the index via
# `System.Data.OleDb` has been independently validated (see
# /mnt/c/usr/winmcp_ps_search_probe.ps1's proven `OleDbConnection`
# idiom). Security-critical per the powershell-search-bridge spec: caller
# values MUST NEVER reach argv or a `-Command`/`-EncodedCommand` string —
# they travel only as a JSON object over the child's stdin.

# `_PS_EXE` (pinned Windows PowerShell 5.1 absolute path, never a bare
# "powershell"/"pwsh" resolved via PATH — powershell-search-bridge spec's
# "Host Pinning" requirement) now lives in `tools/ps_bridge_transport.py`
# — the ONE place both this bridge and the OneNote one pin it — and is
# re-exported here (imported at module top) so existing callers/tests
# importing `tools.file_search_adapter._PS_EXE` keep working unchanged.

# Absolute path to the deployed script, resolved next to this module —
# never a relative path, so argv's -File value is always absolute
# regardless of the process's current working directory.
_PS_BRIDGE_SCRIPT = Path(__file__).resolve().parent / "ps_bridge_search.ps1"

# Permanent, config-gated bridge-invocation debug log (BUG-006 volume-
# theory-dead hotfix, 0061-cowork-bug006-volume-theory-dead-any-row-
# kills.md): one line per invocation, appended beside the deployed
# install rather than next to this module — derived from the script
# path's parent's parent (tools/ -> the install root), so a QA
# deployment's own copy of tools/ps_bridge_search.ps1 logs to its own QA
# tree instead of colliding with a PRO install's log.
_BRIDGE_DEBUG_LOG_PATH = _PS_BRIDGE_SCRIPT.parent.parent / "bridge_invocations.log"


def _log_bridge_invocation(
    *,
    started_at: float,
    sql: str,
    rows_streamed: int,
    sentinel_seen: bool,
    exit_condition: str,
    stderr_excerpt: str,
    error_line_first_200: str = "",
) -> None:
    """Append one diagnostic line to `_BRIDGE_DEBUG_LOG_PATH` when
    `file_search_bridge_debug_log()` is true — never raises, regardless
    of whether the config read, the timestamp/json formatting, or the
    file write itself fails, since this is a best-effort diagnostic aid,
    never part of the bridge's actual contract. Writes nothing at all
    when the flag is false (checked first, before touching the
    filesystem).

    `error_line_first_200` (alias-containment-hotfix piece 3) is the
    first ~200 characters of the script's own `{"error": "..."}`
    stdout line's text, when one was seen during this invocation —
    distinct from `stderr_first_200` (which already folds the same text
    in, prefixed as `"script error: ..."`, for the raised exception's
    message) so an operator scanning the log can find a script-reported
    failure by this field alone, including the partial-success case
    where the call did NOT raise (rows already streamed before the
    error line arrived) and the error text would otherwise never reach
    any exception message at all. Empty string when no such line was
    seen."""
    try:
        if not file_search_bridge_debug_log():
            return
        line = json.dumps(
            {
                "utc": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": round(time.monotonic() - started_at, 3),
                "exit_condition": exit_condition,
                "rows_streamed": rows_streamed,
                "sentinel_seen": sentinel_seen,
                "stderr_first_200": stderr_excerpt[:200],
                "sql_first_120": sql[:120],
                "error_line_first_200": error_line_first_200[:200],
            }
        )
        with _BRIDGE_DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


def _row_from_mapping(row: dict[str, Any], *, detail: bool) -> FileSummary | FileDetail:
    """Map one JSON object emitted by `tools/ps_bridge_search.ps1`'s
    stdout — keys matching `_SUMMARY_FIELDS`/`_DETAIL_FIELDS` with the
    `System.`/`System.Search.` prefix dropped (e.g. `ItemPathDisplay`,
    `Size`, `DateModified`, `Kind`, `AutoSummary`) — into a `FileSummary`
    (`detail=False`) or `FileDetail` (`detail=True`). The bridge's
    counterpart to `_row_to_summary`/`_row_to_detail`, which read a COM
    recordset instead of a plain dict. Date fields arrive as ISO-8601
    strings (the script formats them explicitly) — pydantic's `datetime`
    field coerces those natively, no manual parsing needed here."""
    item_url = row.get("ItemUrl")
    path = _normalize_path(row.get("ItemPathDisplay"), item_url)
    name = row.get("ItemName") or path.rsplit("\\", 1)[-1]
    summary = FileSummary(
        path=path,
        name=name,
        size=int(row.get("Size") or 0),
        last_modified=row.get("DateModified"),
        kind=_normalize_multi_value(row.get("Kind")),
        extension=row.get("FileExtension"),
        # alias-containment-hotfix: see _row_to_summary's identical note.
        alt_url_path=_decode_item_url(item_url),
    )
    if not detail:
        return summary
    return FileDetail(
        path=summary.path,
        name=summary.name,
        size=summary.size,
        last_modified=summary.last_modified,
        kind=summary.kind,
        extension=summary.extension,
        alt_url_path=summary.alt_url_path,
        created_time=row.get("DateCreated"),
        snippet=row.get("AutoSummary") or None,
    )


class _BridgeUnparseableLineError(Exception):
    """Internal signal raised when a JSON Lines record from the bridge
    script fails to parse for a reason OTHER than the stream simply being
    cut short (see `_parse_bridge_stdout`'s docstring for the
    truncation-vs-corruption distinction — the streaming `_invoke()`
    below applies the identical rule line-by-line as it reads, rather
    than after the fact over a fully-buffered string). Caught by
    `_invoke` and re-raised as `WindowsSearchUnavailableError` with a
    message an operator can tell apart from a truncated-but-otherwise-
    healthy response — ps-bridge-jsonl-hotfix."""


def _parse_bridge_stdout(stdout: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse `tools/ps_bridge_search.ps1`'s stdout under the JSON Lines
    output contract (ps-bridge-jsonl-hotfix): one compact JSON object per
    row, followed by a final sentinel line `{"done": true, "count": N}`
    marking a complete, non-truncated response.

    Returns `(rows, results_truncated)`. Reading line-by-line means a
    stdout stream cut short (a large payload hitting a bounded read, a
    killed/interrupted child, etc.) costs at most the trailing sentinel
    line or one partial row — never the whole document, unlike the prior
    single-JSON-document contract this replaces.

    Truncation is treated as a RESULT, not an error: if the sentinel line
    is never reached, `results_truncated` is `True` and whatever rows
    parsed cleanly before the cut are returned. A malformed LAST line
    (the exact point a truncated read would land) is silently dropped as
    the expected shape of a truncation, not raised. Only a malformed line
    that is NOT the last line — i.e. a line the stream had every
    opportunity to finish writing — is a genuine corruption, distinct
    from truncation, and raises `_BridgeUnparseableLineError`.

    Operates on a fully-buffered stdout string — kept as the pure-
    function reference implementation of the truncation-vs-corruption
    rule (and directly unit-tested as such). `PowerShellSearchBridge._invoke`
    (bridge-streaming-hotfix) no longer calls this: it applies the
    identical rule incrementally, line-by-line, as each line is read off
    a live pipe under a wall-clock deadline, since waiting for the whole
    stdout string to be available first would defeat the point of
    streaming (a hung child would never produce one)."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    rows: list[dict[str, Any]] = []
    done = False
    for index, line in enumerate(lines):
        is_last_line = index == len(lines) - 1
        try:
            parsed = json.loads(line)
        except (json.JSONDecodeError, TypeError) as exc:
            if is_last_line:
                # Truncated mid-record: the stream was cut before this
                # line finished writing. Drop the partial fragment and
                # report truncation instead of raising.
                break
            raise _BridgeUnparseableLineError(line) from exc
        if isinstance(parsed, dict) and parsed.get("done") is True:
            done = True
            break
        rows.append(parsed)
    return rows, not done


class PowerShellSearchBridge:
    """Fallback `FileSearchPort` transport (Phase 3): invokes a pinned,
    absolute Windows PowerShell 5.1 executable against a deployed `.ps1`
    script (`tools/ps_bridge_search.ps1`) via `-File`, passing the
    already-built, already-escaped SQL text as a single JSON object
    (`{"sql": "..."}`) over the child's stdin — never on the command
    line, never interpolated into a `-Command`/`-EncodedCommand` string
    — per the powershell-search-bridge spec's "Values Passed as Data via
    Stdin" and "Host Pinning" requirements.

    Escape/build in exactly one place: this class reuses
    `_build_search_sql`/`_build_get_info_sql` VERBATIM — the exact same
    functions `WindowsSearchAdapter` calls — rather than re-implementing
    SQL construction. Only Python ever escapes a value or assembles SQL
    text; the deployed `.ps1` script is a dumb executor that runs the
    received `sql` string as-is against its own `OleDbConnection` and
    prints the resulting rows as JSON Lines — one compact JSON object per
    row, flushed as each row is read, plus a final `{"done": true,
    "count": N}` sentinel. Per the file-search-resilience change's live
    security review: two independent escapers (Python and PowerShell)
    would silently drift out of sync over time, and since stdin here is
    only ever written by this parent process (never caller-reachable
    directly), a dumb executor adds no new attack surface versus a
    self-escaping script. Not unit-tested directly (no real PowerShell on
    WSL2) per tasks.md 3.11 — covered indirectly by
    tests/test_file_search_adapter.py's stdin-capture assertions against
    the SQL text this class sends.

    `search()` sets `self.last_search_truncated` (bridge-streaming-hotfix)
    after every call — `True` when the deadline was hit or the child died
    before writing the `{"done": true, ...}` sentinel and rows already
    parsed were returned anyway, `False` on a clean sentinel-terminated
    response. `FallbackSearchAdapter`/`tools/file_search.py` read this via
    `getattr(adapter, "last_search_truncated", False)` rather than
    `FileSearchPort.search()` itself returning a `(rows, truncated)` tuple
    — the documented-attribute shape keeps `FileSearchPort`'s signature,
    `WindowsSearchAdapter`, and `FakeFileSearchAdapter` completely
    unchanged, at the cost of the caller having to read a side-channel
    attribute instead of unpacking a tuple. Chosen over widening the port
    because every other adapter/test in this codebase constructs
    `search()` calls expecting a bare `list[FileSummary]` back; widening
    the return type would touch `WindowsSearchAdapter`,
    `FakeFileSearchAdapter`, and every test file that exercises either of
    them, for a signal only the bridge transport ever produces.
    """

    def __init__(self, transport: "PsBridgeTransport | None" = None) -> None:
        self.last_search_truncated: bool = False
        # Shared use-case-agnostic engine (design.md Decision 1) — owns
        # the spawn/deadline/JSON-Lines-parse/diagnostic-suffix mechanics
        # this class used to implement itself. Injectable for tests that
        # want to double the transport directly; defaults to a real one
        # (mirrors `FallbackSearchAdapter`'s own primary/bridge injection
        # pattern).
        self._transport: PsBridgeTransport = transport if transport is not None else PsBridgeTransport()

    def _invoke(self, sql: str) -> tuple[list[dict[str, Any]], bool]:
        """Thin wrapper around `PsBridgeTransport.invoke()`: builds the
        `{"sql": ...}` request (the dumb-executor contract — see the class
        docstring), delegates the actual spawn/deadline/JSON-Lines-parse
        sequence to the shared transport, and re-raises any
        `PsBridgeTransportError` as `WindowsSearchUnavailableError` with
        the SAME message text (design.md Decision 2 — the transport stays
        domain-agnostic; this adapter owns its own typed error).

        BUG-006 volume-theory-dead hotfix
        (0061-cowork-bug006-volume-theory-dead-any-row-kills.md): every
        call — success, truncated-partial, or raised — is still logged
        via `_log_bridge_invocation` (config-gated,
        `file_search_bridge_debug_log()`) regardless of outcome, via the
        `finally` below, so an operator can see exit condition/rows-
        streamed/sentinel/stderr/sql even when the caller only ever sees
        the friendlier wrapped exception. `record` is populated by the
        transport's own `diagnostics=` output param — this class's own
        richer, SQL-aware log line is built from that plus `sql` itself,
        which the transport (deliberately domain-agnostic) never sees."""
        started_at = time.monotonic()
        record: dict[str, Any] = {
            "rows_streamed": 0,
            "sentinel_seen": False,
            "exit_condition": "unknown",
            "stderr_excerpt": "",
            "error_line_first_200": "",
        }
        try:
            return self._invoke_impl(sql, record)
        finally:
            _log_bridge_invocation(
                started_at=started_at,
                sql=sql,
                rows_streamed=record["rows_streamed"],
                sentinel_seen=record["sentinel_seen"],
                exit_condition=record["exit_condition"],
                stderr_excerpt=record["stderr_excerpt"],
                error_line_first_200=record["error_line_first_200"],
            )

    def _invoke_impl(
        self, sql: str, record: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], bool]:
        """The actual delegation to `PsBridgeTransport.invoke()` — split
        out of `_invoke` purely so the latter can wrap this in a `finally`
        that logs the invocation exactly once regardless of how this
        returns/raises. `record` is passed straight through as the
        transport's `diagnostics` output param, mutated in place with
        whatever diagnostic detail is known by the time each exit point
        is reached, for `_invoke`'s `finally` to read back."""
        timeout = file_search_ps_bridge_timeout_seconds()
        try:
            return self._transport.invoke(
                _PS_BRIDGE_SCRIPT,
                {"sql": sql},
                timeout=timeout,
                log_label="search",
                diagnostics=record,
            )
        except PsBridgeTransportError as exc:
            raise WindowsSearchUnavailableError(str(exc)) from exc

    def search(
        self,
        filename: str | None,
        phrase: str | None,
        roots: list[str],
        top_n: int,
    ) -> list[FileSummary]:
        sql = _build_search_sql(filename, phrase, roots, top_n)
        rows, truncated = self._invoke(sql)
        self.last_search_truncated = truncated
        return [_row_from_mapping(row, detail=False) for row in rows]

    def get_info(self, path_or_url: str) -> FileDetail:
        sql = _build_get_info_sql(path_or_url)
        rows, _truncated = self._invoke(sql)
        if not rows:
            raise FileNotFoundInIndexError(f"No indexed file at {path_or_url!r}")
        return _row_from_mapping(rows[0], detail=True)


# --- Fallback composing adapter (Phase 4, file-search-resilience change) ---


class FallbackSearchAdapter:
    """`FileSearchPort` seam composing `WindowsSearchAdapter` (primary,
    ADO-backed) and `PowerShellSearchBridge` (fallback) — per design.md's
    "Composing FallbackSearchAdapter implements FileSearchPort" decision
    and the windows-search-adapter spec's "Fallback Transport Ordering"
    requirement: the ADO transport is always tried first; the bridge is
    only attempted when ADO raises `WindowsSearchUnavailableError`
    (never tried first, never in parallel). If the bridge also raises
    `WindowsSearchUnavailableError`, that exception propagates
    unchanged — this seam stays config- and message-neutral; any
    "filename search still works" messaging is the tool layer's job (a
    later batch), never this seam's.

    `FileNotFoundInIndexError` (a reachable index reporting "no such
    item", as opposed to an unreachable index) is never treated as a
    transport failure and never triggers the bridge fallback — see the
    windows-search-adapter spec's "Enrichment Lookups Use the Same
    Fallback Ordering" requirement.

    `server.py::_resolve_real_file_search_adapter()` constructs this
    instead of a bare `WindowsSearchAdapter` (Phase 6, a later batch).

    `self.last_search_truncated` (bridge-streaming-hotfix) mirrors
    whichever transport actually served the most recent `search()` call —
    read via `getattr(transport, "last_search_truncated", False)` so a
    plain `WindowsSearchAdapter` (which never sets the attribute) reads
    as `False` without needing one. `tools/file_search.py` reads this
    same attribute off whatever adapter it was handed (this class in
    production, `FakeFileSearchAdapter`/a hand-rolled stub in tests) to
    OR the phrase leg's truncation into `FileSearchResponse.results_truncated`.
    """

    def __init__(
        self,
        primary: "FileSearchPort | None" = None,
        bridge: "FileSearchPort | None" = None,
    ):
        self._primary: FileSearchPort = primary if primary is not None else WindowsSearchAdapter()
        self._bridge: FileSearchPort = bridge if bridge is not None else PowerShellSearchBridge()
        self.last_search_truncated: bool = False

    def search(
        self,
        filename: str | None,
        phrase: str | None,
        roots: list[str],
        top_n: int,
    ) -> list[FileSummary]:
        try:
            results = self._primary.search(filename, phrase, roots, top_n)
            self.last_search_truncated = bool(getattr(self._primary, "last_search_truncated", False))
            return results
        except WindowsSearchUnavailableError:
            results = self._bridge.search(filename, phrase, roots, top_n)
            self.last_search_truncated = bool(getattr(self._bridge, "last_search_truncated", False))
            return results

    def get_info(self, path_or_url: str) -> FileDetail:
        try:
            return self._primary.get_info(path_or_url)
        except WindowsSearchUnavailableError:
            return self._bridge.get_info(path_or_url)
