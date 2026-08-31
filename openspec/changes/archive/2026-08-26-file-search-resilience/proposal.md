# Proposal: File Search Resilience (BUG-001 fix + architecture evolution)

## Intent

`file_search`/`file_get_info` fail 100% of calls whenever the Windows
Search index is unreachable — proven permanent in Claude-Desktop-spawned
processes (`REGDB_E_CLASSNOTREG` during query build; Outlook COM stays
healthy in the same process). Two of three allowed roots (`C:\usr`,
`C:\co`) aren't indexed at all, so filename search there never worked
even on a healthy machine. This removes that single point of failure:
`filename` search becomes index-independent, `phrase` search gets a
fallback transport.

## Scope

### In Scope
- `filename` → filesystem walk (`os.scandir`), always; fixes unindexed
  roots too.
- `phrase` → ADO first, PS+OleDb bridge on `WindowsSearchUnavailableError`.
- `file_get_info` → `os.stat` for universal facts; index as enrichment.
- Distinct error: "path doesn't exist" vs. "real but unindexed."
- Combined `filename`+`phrase` query rule (sdd-design decides shape).
- Verify only: no diagnostic code ships; smoke test's roots-policy probe
  stays valid unchanged.

### Out of Scope
- Reindexing/relevance tuning, network-only OneDrive content.
- Naming the CoCreate class behind `REGDB_E_CLASSNOTREG` (localized;
  not required to ship the fix).

## Capabilities

### New Capabilities
- `filesystem-walk-search`: bounded `os.scandir` walk powering `filename`.
- `powershell-search-bridge`: subprocess PowerShell/OleDb fallback
  transport for `phrase` when ADO is unavailable.

### Modified Capabilities
- `file-search`: `filename` index-independent; combined-query rule;
  degrade messaging when only `phrase` fails.
- `file-get-info`: `os.stat`-first metadata; index as enrichment; distinct
  not-found vs. unindexed-but-real error.
- `windows-search-adapter`: fallback-transport contract; error semantics
  when both transports fail.

## Approach

Split query kinds at the tool layer: `filename` never touches the
adapter; `phrase` tries ADO then the PS bridge on the existing
`WindowsSearchUnavailableError` contract. `file_get_info` calls `os.stat`
after the roots check, then enriches opportunistically from the index.

## Affected Areas

| Area | Impact |
|------|--------|
| `tools/file_search.py` | Walk-based filename, stat-based get_info, combined-query rule |
| `tools/file_search_adapter.py` | PS-bridge transport + fallback chain |
| `tools/errors.py` | New unindexed-but-real vs. not-found errors |
| `models/schemas.py` | `results_truncated`, enrichment fields |
| `config/settings.yaml` | Walk wall-clock/dir-count caps |
| `deploy/smoke_test.py` | Verify only, no code change expected |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Walk outage on huge trees | Med | Wall-clock/dir caps, `results_truncated` |
| Reparse cycle escapes roots | Low | Skip reparse points/junctions |
| PS-bridge fails too | Unknown | Robust either way; error names fallback |
| Enrichment leaks index errors | Med | Caught, never surfaced |

## Rollback Plan

Tool-layer only; adapter Protocol unchanged. Revert
`tools/file_search.py` + adapter addition, delete the PS script asset.
New fields/errors are additive — nothing to remove.

## Dependencies

- `powershell.exe` + .NET `OleDb` on target hosts (validated).

## Success Criteria

- [ ] `file_search {"filename": ".md", "scope": "C:\\usr\\WinMCP\\_chatCowork"}` succeeds.
- [ ] `phrase` survives ADO failure via the PS bridge, or names the
  filename fallback in its error.
- [ ] `file_get_info` on a real, unindexed file returns stat facts, not
  `file_not_found_in_index`.
- [ ] `pytest -q` passes on WSL2 with no real COM/PowerShell.
