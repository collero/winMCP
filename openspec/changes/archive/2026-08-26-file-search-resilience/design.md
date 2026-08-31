# Design: File Search Resilience

## Technical Approach

Split dispatch in `tools/file_search.py` by query kind: `filename` runs a
new bounded walk, never touching the adapter; `phrase`/enrichment go
through a new fallback-composing adapter (ADO, then PowerShell bridge)
behind the unchanged `FileSearchPort` Protocol. `file_get_info` sources
core facts from `os.stat`, enriches best-effort from the index.

## Architecture Decisions

### Decision: Walk lives in a new `tools/file_search_walk.py`

**Choice**: New module, `walk_filename(roots, filename, max_results,
time_budget_s, max_dirs) -> tuple[list[FileSummary], bool]` (bool =
truncated). Called from `file_search()` after `_check_contained`.
**Alternatives**: inline in `tools/file_search.py` (grows the roots-policy
module with unrelated recursion logic); inside the adapter (violates the
adapter's config-unaware, index-only charter).
**Rationale**: keeps `file_search.py` as orchestration/policy, isolates
walk internals (caps, reparse skip) for focused testing.

### Decision: Composing `FallbackSearchAdapter` implements `FileSearchPort`

**Choice**: New class wrapping `WindowsSearchAdapter` +
`PowerShellSearchBridge`; `search()`/`get_info()` try ADO, `except
WindowsSearchUnavailableError:` try the bridge, re-raising if both fail.
`server.py::_resolve_real_file_search_adapter()` constructs this instead
of a bare `WindowsSearchAdapter`.
**Alternatives**: fallback logic inside `WindowsSearchAdapter` itself.
**Rationale**: Protocol signature untouched; each transport stays a
single-responsibility, independently-fake-able unit (mirrors
`FakeFileSearchAdapter` precedent); satisfies "Fallback Transport
Ordering" without new coupling.

### Decision: PS bridge passes a pre-built SQL string as stdin JSON to a pinned, absolute `-File` invocation

**Choice** (revised per live security review — supersedes both the
original `-EncodedCommand` choice AND this batch's first draft, which
had the `.ps1` do its own field-level escaping): `PowerShellSearchBridge`
invokes a fixed, absolute path,
`C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe` (pinned to
Windows PowerShell 5.1, never `PATH`-resolved `powershell`/`pwsh` —
`pwsh` 7's `System.Data.OleDb` support is unreliable on target hosts),
with `subprocess.run([PS_EXE, "-NoProfile", "-NonInteractive",
"-ExecutionPolicy", "Bypass", "-File", <absolute deployed script path>],
input=json.dumps({"sql": sql}), capture_output=True, text=True,
timeout=file_search_ps_bridge_timeout_seconds)`, where `sql` is the
COMPLETE, ALREADY-ESCAPED SQL text produced by `_build_search_sql`/
`_build_get_info_sql` — the exact same builder functions
`WindowsSearchAdapter` calls, now escaping `filename`'s `LIKE` clause via
a shared `_escape_like_value` (`_escape_sql` quote-doubling composed
with `_escape_like_metacharacters`'s `%`/`_`/`[` bracket-neutralization)
so both transports share one escaping/SQL-building code path rather than
two that could silently drift out of sync. Caller-controlled values
NEVER appear in argv and are NEVER interpolated into a
`-Command`/`-EncodedCommand` string — they travel only as part of the
`sql` string inside the stdin JSON payload. The deployed script is a
DUMB EXECUTOR: it reads that JSON as data
(`[Console]::In.ReadToEnd() | ConvertFrom-Json`), takes `.sql` and runs
it VERBATIM as `OleDbCommand.CommandText` — no escaping, no
interpolation, no field-by-field reconstruction on the PowerShell side
at all. Script prints one JSON array to stdout, one object per row with
keys matching `_SUMMARY_FIELDS`/`_DETAIL_FIELDS` (e.g.
`ItemPathDisplay`, `ItemUrl`, `Size`, `DateModified`, `Kind`,
`FileExtension`, `DateCreated`, `AutoSummary`).
**Alternatives**: `-EncodedCommand` with the query baked into the
encoded script text (rejected — a value that looks like PowerShell
syntax, e.g. `phrase="$(Get-Date)"`, would sit inside command text
rather than pure data, and base64-encoding does not change that it is
still "command", not "argument"); values as bare CLI args (rejected —
visible in process listings/argv, and still risks quoting escapes); the
script re-escaping each field itself from a `{"filename":...,
"phrase":..., "roots":..., "path":...}` payload (rejected on live
security review — two independent escapers, one in Python and one in
PowerShell, would silently drift out of sync over time; since stdin here
is only ever written by this parent process, never caller-reachable
directly, a dumb SQL-executor script adds no new attack surface versus a
self-escaping one).
**Rationale**: the values-as-data rule is the actual mitigation — a
malicious-looking string can only ever be JSON-decoded and end up as
already-escaped text inside a SQL literal, never parsed as PowerShell
syntax, regardless of its content. `-File` with a fixed absolute path
also means argv itself is 100% static and auditable (no per-call script
content to review). Escaping in exactly one place (Python) makes the
whole discipline unit-testable on this Linux host via a table-driven
test over `_escape_like_value` (`o'brien`, `100%`, `a_b`, `[abc]`,
`it''s`, a lone backslash, empty string, a 1000-char string, a
metacharacters-only string), plus tests asserting the bridge's captured
stdin `sql` is byte-for-byte what `_build_search_sql`/
`_build_get_info_sql` produce for the same inputs. `json.loads(stdout)`
reuses a `_row_from_mapping()` helper mirroring `_row_to_summary`'s
field mapping, adapted for `dict` instead of a recordset.
**Portability note**: on a host running AppLocker or PowerShell
Constrained Language Mode, this child process may be blocked outright —
`subprocess.run` raises `OSError`/`FileNotFoundError` (the child never
starts), which is mapped to `WindowsSearchUnavailableError` with a
message distinguishable from the timeout case ("PowerShell bridge
blocked or unavailable" vs "PowerShell bridge timed out" — same error
TYPE, different operator response: "check the deployment/policy" vs
"check whether the index is just slow"; blocked is the common case on
managed corporate machines). The bridge is enrichment/fallback-only by
design — `phrase` search then degrades to the existing
`WindowsSearchUnavailableError` with its filename-still-works message,
and `filename` search is unaffected since it never depends on
PowerShell at all. No special CLM detection is needed; the existing
failure-mapping requirement already covers "the child could not run" the
same as any other subprocess failure, just with a more specific message.

### Decision: New `PathNotFoundError`; `FileNotFoundInIndexError` stays adapter-internal

**Choice**: Add `PathNotFoundError` (code `path_not_found`) to
`tools/errors.py`. `FileNotFoundInIndexError` remains — raised by
`WindowsSearchAdapter.get_info()`/the bridge when a path is absent from
the index — but `file_get_info()`'s enrichment `try/except` catches
*both* `WindowsSearchUnavailableError` and `FileNotFoundInIndexError`,
swallowing to `kind=None`/`snippet=None`. Neither ever reaches the
caller from `file_get_info()`.
**Rationale**: matches the file-get-info delta's REMOVED-requirement note
exactly; no adapter Protocol change needed.

## Data Flow — acceptance scenario

    file_search(filename=".md", scope="C:\usr\WinMCP\_chatCowork")
        │
        ▼
    _check_contained(scope, allowed_roots)   # unchanged, pre-call
        │ OK
        ▼
    walk_filename([scope], ".md", max_results, time_budget, max_dirs)
        │ (adapter never called)
        ▼
    [FileSummary...], results_truncated=False

## Combined Query Algorithm

1. `walk_filename` runs first (cheap, local) → candidate paths. If empty,
   short-circuit: return `[]` without an index round-trip.
2. Otherwise run the `phrase` query against the adapter, scoped to the
   same `search_roots`.
3. Intersect by `_normalize_path()`-normalized path; return the
   intersection, adapter's `results_truncated` OR'd with the walk's.

## File Changes

| File | Action | Description |
|------|--------|--------------|
| `tools/file_search_walk.py` | Create | `walk_filename()`, reparse-skip, caps |
| `tools/file_search_adapter.py` | Modify | Add `PowerShellSearchBridge`, `FallbackSearchAdapter` |
| `tools/ps_bridge_search.ps1` | Create | Deployed script: reads stdin JSON, builds escaped SQL, prints JSON |
| `tools/file_search.py` | Modify | Dispatch split, combined-query intersection, `os.stat`-based `file_get_info` |
| `tools/errors.py` | Modify | Add `PathNotFoundError` |
| `models/schemas.py` | Modify | Add `results_truncated` to `FileSummary`/response |
| `tools/settings.py` / `config/settings.yaml` | Modify | 3 new keys, defaults 5/5000/10 |
| `server.py` | Modify | Construct `FallbackSearchAdapter` in the resolver |

## Reparse-Point Check

`_is_reparse_point(entry: os.DirEntry) -> bool`: `entry.is_symlink()` OR
(on Windows) `entry.stat(follow_symlinks=False).st_file_attributes &
stat.FILE_ATTRIBUTE_REPARSE_POINT`. Tests inject fake `os.DirEntry`-like
objects with a settable `is_symlink()`/attribute — no real junction
needed on WSL2.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | walk caps/reparse/permission-skip | mocked `os.scandir` trees |
| Unit | PS bridge escaping/timeout/JSON parse | mocked `subprocess.run` |
| Unit | `FallbackSearchAdapter` ordering | fake ADO + fake bridge |
| Unit | `file_get_info` stat/enrichment split | mocked `os.stat` + fake adapter |
| Integration | `server.py` wiring | injected fake adapters, `create_server()` |

## Verification (no code change expected)

`deploy/smoke_test.py`'s live `file_search` check already tolerates 0+
hits and its roots-policy probe doesn't depend on `scope`; confirm both
still pass, no edit needed. Confirm the repo's `tools/file_search_adapter.py`
carries no diagnostic/forensic code (already clean — only PRO's deployed
copy has it, out of repo scope).

## Open Questions

None — the PS-child-of-poisoned-process outcome is handled by the
fallback ordering regardless of which way it resolves.
