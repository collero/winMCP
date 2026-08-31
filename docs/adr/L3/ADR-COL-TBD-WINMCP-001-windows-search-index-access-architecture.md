---
id: ADR-COL-TBD-WINMCP-001
level: L3
slug: windows-search-index-access-architecture
organization: colleros
domain: unassigned
app: win-mcp
status: Accepted
date: "2026-08-26"
title: "Windows Search index access architecture for file_search"
type: Rule
category: Application
tags: []
related:
  - ADR-COL-TBD-WINMCP-002
mentioned-by: []
---

# ADR-COL-TBD-WINMCP-001 — Windows Search index access architecture for file_search

**Status**: Accepted · **Date**: 2026-08-26 · **Category**: Application · **Organization**: colleros · **Domain**: unassigned · **App**: win-mcp

## Context

The `file_search` and `file_get_info` MCP tools were built (per the archived
change `openspec/changes/archive/2026-08-25-file-search/`) to query the
Windows Search index exclusively through ADO COM: `win32com.client` against
`ADODB.Connection`/`ADODB.Recordset` with `Provider=Search.CollatorDSO`,
lazily imported and `CoInitialize()`'d per call.

On 2026-08-26 an adversarial debugging session (two independent agents,
mailbox protocol logged at `C:\usr\WinMCP\_chatCowork`, mounted in this dev
environment at `/mnt/c/usr/WinMCP/_chatCowork`) established that in the
specific process lineage Claude Desktop spawns for this server — MSIX app →
`cmd` → the venv shim `python.exe` → Microsoft Store `python3.13.exe` — every
ADO command path onto the index is dead: `Recordset.Open` (both the
object and the connection-string call forms), `Connection.Execute`, and
`ADODB.Command` all fail identically with `DISP_E_EXCEPTION` wrapping
`REGDB_E_CLASSNOTREG` (`0x80040154`), raised by the Search provider itself
while it builds its query machinery — not by any of the ADO front doors.
`ADODB.Connection.Open()` succeeds, and every top-level CLSID involved
(`ADODB.Recordset`, `ADODB.Command`, `ADODB.Connection`, `MSDAINITIALIZE`,
`Search.CollatorDSO`, the OLE DB conversion library) CoCreates successfully in
the same process, on the same thread, at failure time. The failure is
deterministic from the very first call and permanent for the life of the
process — 20+ consecutive failures were logged across three separate server
process generations and two Desktop restarts. The same server binary, spawned
by any other parent (a plain shell, `Invoke-CommandInDesktopPackage`, a
standalone harness), reaches the index without issue (16 of 17 harness runs
passed). The specific internal class the provider fails to CoCreate was never
named — that would require an elevated Procmon trace — but naming it would
not change which fix is needed, so the investigation stopped there.

Independently of that outage, one of the three configured
`file_search_allowed_roots` — `C:\usr` — is not inside the Windows Search
index at all (only the user's profile and `C:\co`, the redirected Documents
folder, are indexed). An index-only architecture can therefore never satisfy
a filename search under `C:\usr`, outage or not.

A new candidate transport was validated during the same session: PowerShell
against the same `Search.CollatorDSO` provider via .NET's
`System.Data.OleDb.OleDbConnection` — a different software stack from the ADO
COM path entirely — successfully queried the index, returning real hits in
about 0.75 seconds including `powershell.exe` process startup. Whether a
PowerShell child spawned from *inside* a poisoned Claude-Desktop-descendant
process can also reach the index (as opposed to a standalone PowerShell
process) was still pending measurement at the time of this decision; a
forensic hook was armed to capture that datum at the next Desktop restart.

## Decision

1. `filename` search is always served by a filesystem walk (`os.scandir`)
   over the configured allowed roots — never by the Windows Search index.
2. The filesystem walk applies guard rails: allowed-roots containment is
   checked before any traversal; the existing result cap is reused; a
   wall-clock budget and a directory-count cap both bound the walk; a
   `results_truncated` flag is returned when a cap is hit; reparse points are
   never traversed.
3. `phrase` (full-text) search is served by the Windows Search index. The
   primary transport is ADO COM (`Search.CollatorDSO`, as today).
4. When the ADO COM transport raises `windows_search_unavailable`, `phrase`
   search falls back to a PowerShell-bridge subprocess that queries the same
   index via .NET `System.Data.OleDb` against the same provider string.
5. The PowerShell bridge is invoked by absolute `-File` path with
   `-NoProfile -NonInteractive -ExecutionPolicy Bypass`, pinned to the
   absolute path of Windows PowerShell 5.1
   (`C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe`); query
   values are passed as a JSON object over the child's stdin, never on the
   command line, and the bridge script applies the same SQL-escaping
   discipline as the ADO path (doubled `'`, neutralised `%`/`_`/`[`); the
   child is subject to a hard ~15-second timeout, and a timeout or non-zero
   exit maps to `windows_search_unavailable`.
6. If both the ADO COM transport and the PowerShell bridge fail, `phrase`
   search returns a graceful error stating that filename search still works.
7. `file_get_info` uses `os.stat` for universal facts (size, timestamps,
   attributes); indexed metadata is fetched as optional enrichment and
   omitted with a note when the index is unavailable.
8. The PowerShell bridge is an enrichment path for `phrase` only — `filename`
   search never depends on the index or the bridge in any form.

## Evidence

> Source · Code · tools/file_search_adapter.py:75
>
> ```python
> _CONNECTION_STRING = "Provider=Search.CollatorDSO;Extended Properties='Application=Windows'"
> ```

> Source · Code · tools/file_search_adapter.py:249-251
>
> ```python
> pythoncom.CoInitialize()
> connection = win32com.client.Dispatch("ADODB.Connection")
> connection.Open(_CONNECTION_STRING)
> ```
> The current, sole transport: ADO COM against `Search.CollatorDSO`, lazily
> imported and `CoInitialize()`'d per call — the path proven unreachable from
> Claude-Desktop-descendant processes.

> Source · Code · tools/file_search_adapter.py:268-269
>
> ```python
> recordset = win32com.client.Dispatch("ADODB.Recordset")
> recordset.Open(sql, connection)
> ```
> `Recordset.Open` — one of the three ADO front doors confirmed dead in the
> failing process lineage (see the `Doc` sources below).

> Source · Code · tools/errors.py:133-142
>
> ```python
> class WindowsSearchUnavailableError(CalendarToolError):
>     ...
>     code = "windows_search_unavailable"
> ```
> The stable error code the ADO transport already raises today, and the same
> code the PowerShell-bridge timeout/failure path maps to (Decision #5/#6).

> Source · Code · config/settings.yaml:39-49 (comment above `file_search_allowed_roots`)
>
> ```yaml
> file_search_allowed_roots:
>   - 'C:\Users\colleros'
>   - 'C:\co'
>   - 'C:\usr'
> ```
> The comment above this block already documents that "allowing a root does
> not index it — folders outside the Windows Search index … return 0 hits
> until added via Windows Indexing Options" — the unindexed-`C:\usr` gap this
> decision fixes independently of the ADO outage.

> Source · Code · tools/file_search.py:95-142 (`_check_contained`, `_drop_outside_allowed_roots`)
>
> Existing allowed-roots containment logic, checked before the adapter is
> called and re-applied to every result — the guard rail the filesystem walk
> (Decision #2) reuses rather than reimplements.

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0023-cowork-round-summary-and-defect-register.md (verified 2026-08-26, session close-out)
>
> "From processes Claude Desktop spawns, there is no ADO/OLE DB route to the
> Windows Search index. Sessions connect fine; no query executes.
> Deterministic from the first call of a brand-new process, permanent
> thereafter. … 20+ consecutive failures across three separate server
> generations and two Desktop restarts, byte-identical error every time
> (`DISP_E_EXCEPTION` wrapping `REGDB_E_CLASSNOTREG`)."

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0026-cc-verdict-all-ado-paths-dead-degrade-is-the-fix.md (verified 2026-08-26)
>
> "retriage_fresh_rs_on_fresh_conn=FAIL … retriage_conn_execute=FAIL …
> retriage_adodb_command=FAIL … clsid_sweep: ADODB.Recordset OK, ADODB.Command
> OK, ADODB.Connection OK, MSDAINITIALIZE OK, Search.CollatorDSO OK,
> OLEDB-conv-lib OK. … Every top-level class instantiates. The 'Class not
> registered' is raised BY the provider, for something IT CoCreates while
> building its query machinery … Therefore: from the processes Claude Desktop
> spawns, THERE IS NO ADO/OLE DB ROUTE TO THE INDEX."

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0028-cc-green-light-and-standing-order.md (verified 2026-08-26)
>
> "query the index from PowerShell (.NET System.Data.OleDb — a different
> stack from ADO/ADODB COM entirely). Validated locally: real hits in 0.75s
> per query including PS startup. … one correction … `C:\co` IS in the index
> (Carlos's Documents folder is redirected there …). Only `C:\usr` is
> unindexed."

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0030-cc-re-0025-ps-bridge-hardening-commitments.md (verified 2026-08-26)
>
> "values will NEVER touch the PowerShell command line: fixed script invoked
> by absolute `-File` path with `-NoProfile -NonInteractive -ExecutionPolicy
> Bypass`, query values passed as a JSON object over stdin … pinned by
> absolute path to Windows PowerShell 5.1 … hard child timeout ~15s with
> bounded stdout read; timeout/kill maps to `windows_search_unavailable`. …
> the bridge is an ENRICHMENT. `filename` never depends on it (walk, always);
> `phrase` uses index-via-ADO, then index-via-bridge, then degrades with a
> message that filename search still works."

> Source · External · file · /mnt/c/usr/winmcp_ps_search_probe.ps1 · verified 2026-08-26
>
> ```powershell
> $conn = New-Object System.Data.OleDb.OleDbConnection(
>     "Provider=Search.CollatorDSO;Extended Properties='Application=Windows'")
> $conn.Open()
> ```
> The probe script that validated the external premise this decision's
> fallback rests on: .NET's `System.Data.OleDb`, a stack independent of ADO
> COM, can open and query the same `Search.CollatorDSO` provider. Whether a
> PowerShell child of a *poisoned* Desktop-descendant process specifically can
> also reach it (as opposed to a standalone PowerShell process) was still
> pending measurement at decision time (see `## Notes`) — the graceful-error
> fallback (Decision #6) means the architecture is correct either way that
> datum resolves.

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0037-cowork-battery-results-summary.md (verified 2026-08-26, post-shipment battery)
>
> "The PowerShell bridge does reach the index from the Desktop route. … PS-child-of-Desktop-descendant works; ADO-in-process does not. The bridge architecture is validated." … "`file_search {"filename": ".md", "scope": "C:\\usr\\WinMCP\\_chatCowork"}` returned 30 files … Real paths, sizes, `lastModified`. On `C:\usr`, the root the index has never covered, through a process class that has never once reached the index."
>
> The architecture's central bet — that a PowerShell child can reach the index from exactly the process lineage where every ADO command path was proven dead — confirmed live by a second, independent agent driving the real MCP client route, not merely by a standalone probe.

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0057-cowork-round3-closing-summary.md (verified 2026-08-26, round 3 closing)
>
> "acceptance: `.md` scoped to `_chatCowork` | 43 files, `resultsTruncated: false` (was 30, then 38 — it keeps tracking the folder as we write)" … "BUG-001 files outage (blocker) | FIXED — acceptance test holds across three builds."
>
> The filename-walk acceptance test named in this ADR's `## Notes` passed on the unindexed `C:\usr` root across all three promoted builds of the session (v1, v2, v3), not just once.

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0059-cowork-bug-006-remains-open-instrumentation.md (verified 2026-08-26, downgraded-and-tracked)
>
> "the bridge spawns, runs, and returns valid empty JSONL for queries with no or few matches, and returns nothing at all for a query with many." … phrase `"Informa"` → "bridge produced no output." … regression test: "`file_search {"phrase": "Informa"}` must return results with a coherent `resultsTruncated` flag."
>
> The open gap: broad full-text phrases fail with no output specifically on the Desktop-descendant route, while narrow/empty-result phrases round-trip cleanly on that same route — the failure is volume-dependent, not path-dependent by itself.

> Source · Interview · 2026-08-26 · session probe (non-Desktop context, post-`0059`)
>
> The identical SQL, run from a non-Desktop-descendant process against the same broad phrase that produced no output on the Desktop route: 0.6s wall-clock, exit code 0, 200 rows returned plus the JSONL sentinel, empty stderr. This refutes both of `0059`'s leading hypotheses — a missing `TOP` row cap and a child timeout — as the sole cause: the bridge script itself is neither slow nor uncapped in the general case, which narrows the standing hypothesis to something specific to running inside a Desktop-descendant child.

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0045-cowork-re-0038-upper-bound-also-transposed.md (verified 2026-08-26) and 0046-cc-re-0045-coverage-added-adr-reframe-adopted.md (verified 2026-08-26)
>
> "the transposition was never fixed. The Python boundary re-check was added, and it masks the transposition in the common direction — a widened range gets trimmed back to the requested window, so the answer comes out right for the wrong reason." (`0045`) … "ADR reframe accepted as stated: the previous build did not fix the transposition; it masked it in the widening direction." (`0046`)
>
> Corrects the assumption — carried by the sibling `file-search-resilience` change referenced in this ADR's `## Notes` — that the first build's date fix was a real fix. It was a mask in the widening direction only; the actual fix moved date comparisons to DASL `@SQL=` syntax, because Jet's bracket-syntax comparators are locale-sensitive even for ISO-formatted literals — any literal format Jet parses culture-sensitively reproduces the bug in whichever direction happens to widen.

### Sources
- `openspec/changes/archive/2026-08-25-file-search/design.md` — origina la elección de ADO COM / `Search.CollatorDSO` como transporte único, la decisión que esta ADR revisa.

## Consequences

### Positive
- `filename` search now works under `C:\usr`, an allowed root that is not in
  the Windows Search index and therefore could never return hits under the
  index-only design, regardless of the ADO outage.
- `filename` search becomes immune to the Windows Search index being
  unreachable at all — the dominant failure mode observed in Claude-Desktop
  processes — because it no longer depends on the index.
- `phrase` search gains a second transport (the PowerShell bridge) instead of
  going straight from "ADO fails" to "the tool is down".
- The graceful final fallback means a total index outage degrades the tool
  (loses full-text search) rather than breaking it (both search modes fail).

### Negative
- A filesystem walk over large directory trees is slower than an index
  query and does not benefit from the index's precomputed metadata; the
  wall-clock and directory-count caps exist specifically to bound this, at
  the cost of `results_truncated` results on pathologically large trees.
- Two independent search implementations (walk for `filename`, index for
  `phrase`) now exist side by side, each with its own edge cases and its own
  regression surface, instead of one.
- The PowerShell bridge adds a subprocess dependency with real security
  exposure (command injection via `filename`/`phrase` values, hostile inputs
  like `o'brien` or `$(Get-Date)`) that must be defended with the same
  escaping discipline as the ADO path, and it adds per-call subprocess
  startup latency (~0.75s measured, before the ADO attempt that precedes it).
- The specific internal Windows Search class that fails to CoCreate under
  Claude-Desktop-descendant processes was never identified, so if Microsoft
  or Windows Search changes that behaviour, the ADO path's status could
  change without this project having visibility into why.

### Trade-offs
- `phrase` search remains dependent on the index being reachable by at least
  one of two transports; a decision was made to accept graceful degradation
  (lose full-text search, keep filename search) over investing further in a
  root-caused fix for the ADO path, since the root cause was judged unlikely
  to be fixable from this project's side (see `## Alternatives considered`).
- Filesystem-walk guard rails trade completeness (results may be truncated on
  very large trees) for a bounded worst case, rather than allowing an
  unbounded walk to run to completion.

## When to apply

- Any `file_search`/`file_get_info` request handled by this server, on any
  host — the hybrid architecture is unconditional, not a Desktop-specific
  code path, because the filesystem-walk and index-with-fallback behaviour is
  correct (if sometimes merely more conservative) even where the ADO path
  works fine.

## When not to apply

- This decision does not extend to other Outlook COM adapters (`mail`,
  `calendar`, `task`) — those tools have no unindexed-root gap and no
  observed ADO-path outage; nothing here implies they need a similar
  walk/fallback hybrid.

## Anti-patterns

- Do not reintroduce an index-only path for `filename` search — that
  regresses the `C:\usr` gap this decision exists to fix, independently of
  whether the ADO outage is ever resolved.
- Do not pass `filename`/`phrase` values on the PowerShell child's command
  line — command-line arguments are the injection surface the stdin-JSON
  design (Decision #5) exists to close.
- Do not treat a `windows_search_unavailable` from the ADO transport as fatal
  for `phrase` search before the PowerShell-bridge fallback has been
  attempted (Decision #4/#6).

## Alternatives considered

- **Keep the index-only architecture (status quo).** Rejected: proven broken
  on the primary route from Claude-Desktop-descendant processes, and
  independently incapable of ever searching `C:\usr` by filename since that
  root isn't indexed.
- **Filesystem-walk-only for everything (drop the index entirely).** Rejected:
  loses full-text (`phrase`) search, which a walk cannot replicate without
  building and maintaining a competing content index.
- **Root-cause and fix the ADO/COM class-registration failure.** Rejected for
  now: the specific failing internal class was never named (would require an
  elevated Procmon trace on the affected machine), the failure is scoped to a
  specific process ancestry this project doesn't control (MSIX-descendant
  Store Python under Claude Desktop), and naming the class was assessed as
  unlikely to change the available remedies.

## Notes

- Pending at decision time: whether a PowerShell child spawned from inside a
  process that is currently failing the ADO path can itself reach the index
  (`retriage_ps_child` datum, armed to fire at the next Claude Desktop
  restart). The architecture in `## Decision` is correct regardless of the
  outcome — Decision #6's graceful error is the safety net either way — but
  the outcome determines whether `phrase` search actually gets the
  PowerShell-bridge fallback in practice on the Desktop route, or falls
  straight through to the graceful error there.
- Implementation is tracked as the `file-search-resilience` change under
  `openspec/changes/file-search-resilience/` (in definition at the time of
  this ADR), alongside sibling changes for BUG-002 (unbounded results) and
  BUG-003 (locale date transposition) — see
  [ADR-COL-TBD-WINMCP-002](ADR-COL-TBD-WINMCP-002-file-search-debugging-session-learnings.md)
  for the debugging methodology that produced this decision's evidence.
- Acceptance test named during the investigation:
  `file_search {"filename": ".md", "scope": "C:\\usr\\WinMCP\\_chatCowork"}`
  should return results from that directory once the walk ships.
- **Validation outcome (2026-08-26, session close).** The hybrid architecture
  shipped the same day across three promoted builds (v1/v2/v3; changes
  archived under `openspec/changes/archive/2026-08-26-*`) and was verified by
  a live adversarial client — a second, independent agent (`cowork`) driving
  the real MCP client route, not the authoring agent's own suite: the
  acceptance test above passed on `C:\usr`, the unindexed root, across all
  three builds; and the PowerShell bridge reached the index from
  Claude-Desktop-descendant processes — the exact process class where every
  ADO command path was proven dead — confirming this decision's central
  architectural bet live. See the `0037` and `0057` Evidence entries above.
- **Known open gap, tracked not blocking (2026-08-26).** Broad full-text
  `phrase` queries fail — but only on the Claude-Desktop-descendant route —
  with the bridge producing no output at all; the typed
  `windows_search_unavailable` error correctly names the `filename` fallback,
  so the failure degrades honestly per Decision #6. Two candidate causes named
  at the time — a missing `TOP` row cap and a child timeout — were refuted by
  a probe from a non-Desktop context: the identical SQL against the same
  broad phrase completed in 0.6s, exit code 0, returning 200 rows plus the
  JSONL sentinel, with empty stderr. The standing hypothesis is that the same
  disease as this ADR's original ADO finding recurs one layer down: something
  in the full-text ranking path throws specifically inside a child spawned
  from that process ancestry. The named next step is to surface the child's
  exit code and a stderr excerpt in the typed error detail — one more live
  call against the Desktop route should then name the failing operation
  directly — and separately to read the bridge's JSONL output incrementally
  rather than collecting it after the child exits, so a killed or crashed
  child still yields whatever rows it had already streamed instead of zero.
  See the `0059` and session-probe Evidence entries above.
- **Correction of the historical record (2026-08-26, per the live verifier's
  `0045`).** The sibling `file-search-resilience` change's first build did
  **not** fix the BUG-003 date transposition named in
  [ADR-COL-TBD-WINMCP-002](ADR-COL-TBD-WINMCP-002-file-search-debugging-session-learnings.md)
  — it masked the symptom in the widening direction only: a swapped upper
  bound that moves later gets trimmed back to the requested window by that
  build's Python boundary re-check, so the answer came out right for the
  wrong reason, while a swapped lower bound (inverting the range) or a
  swapped upper bound that moves earlier (narrowing it) both still failed.
  The actual fix, landed in a later build, was moving the date comparisons to
  DASL `@SQL=` syntax rather than any literal date format — Jet's
  bracket-syntax comparators are locale-sensitive even for ISO-formatted
  literals, so any literal format reproduces the bug in whichever direction
  happens to widen. A related recurrence constraint surfaced during the same
  fix: Outlook's `IncludeRecurrences` requires an ascending `[Start]` sort
  applied before `Restrict`, so the newest-first ordering this project wants
  must be applied to the collected result in Python, not via the COM sort
  itself. See the `0045`/`0046` Evidence entries above.
