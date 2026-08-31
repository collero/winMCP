# Apply Progress: PowerShell Search Bridge JSON Lines Hotfix

**Mode**: Strict TDD (runner: `.venv/bin/python3.12 -m pytest -q`)

## Baseline

`456 passed` confirmed before any change (Phase 0).

## TDD Cycle Evidence

| Task | Test File | Layer | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|-----|-------|-------------|----------|
| 1.1/1.2 Row-cap verification | `tests/test_file_search_adapter.py` | Unit | ➖ Already true by construction (`_build_search_sql`/`_build_get_info_sql` shared verbatim by both transports) — these are regression-lock tests, not bug-driven RED cases | ✅ Both pass against unchanged code | ✅ 2 cases (search leg via `_build_search_sql`, get_info leg via `_build_get_info_sql`) | ➖ None needed |
| 2.1/2.2 JSON Lines parser | `tests/test_file_search_adapter.py` | Unit | ✅ Rewriting stdout fixtures to JSONL shape (`_jsonl` helper) broke every existing bridge test against the still-single-document `json.loads(completed.stdout)` in `_invoke()` | ✅ All pass after adding `_parse_bridge_stdout()` + `_BridgeUnparseableLineError`, rewiring `_invoke()` to call it | ✅ Existing happy-path/hostile-input/get_info tests all exercise the new parser through their rewritten fixtures | ➖ None needed |
| 2.3 `.ps1` JSON Lines emission | `tools/ps_bridge_search.ps1` | N/A (not unit-tested on WSL2, per tasks.md 3.11 precedent) | ➖ No real PowerShell on this host | ✅ Rewrote the reader loop to emit one flushed `ConvertTo-Json -Compress` line per row plus a final sentinel line; visually verified against the new Python-side contract | ➖ N/A | ➖ N/A |
| 2.4 Truncation-as-result | `tests/test_file_search_adapter.py` | Unit | ✅ Written against the OLD `_invoke()` first — a stream without the sentinel line, or with a partial last line, raised `WindowsSearchUnavailableError("...malformed JSON")`, the exact wrong behavior being fixed | ✅ Passes after `_parse_bridge_stdout()`'s last-line-tolerant logic: a malformed LAST line breaks the loop without raising, `results_truncated=True` | ✅ 4 cases (missing sentinel via `bridge.search()`, partial-last-line via `bridge.search()`, and both again directly against `_parse_bridge_stdout()`) | ➖ None needed |
| 2.5 Genuine corruption still raises | `tests/test_file_search_adapter.py` | Unit | ✅ A non-last-line garbage line, run against the fix, was checked to still raise (not silently accepted as a truncation) | ✅ Confirmed `_BridgeUnparseableLineError` → `WindowsSearchUnavailableError("...returned unparseable output (not valid JSON Lines)")`, distinct wording from timeout/blocked/truncation | ✅ 2 cases (via `bridge.search()` and directly against `_parse_bridge_stdout()`) | ➖ None needed |
| 2.6 Repurposed collapse test | `tests/test_file_search_adapter.py` | Unit | ➖ Old test asserted a PowerShell-5.1-specific quirk (`ConvertTo-Json` collapsing a 1-element array to a bare object) that cannot occur under JSON Lines (each row is already emitted as its own bare object) | ✅ Renamed/repurposed to `test_bridge_search_single_row_plus_sentinel_parses`, same basic single-row coverage, updated docstring | ➖ N/A | ➖ N/A |
| 3.1/3.2 Message punctuation | `tests/test_file_search_adapter.py`, `tests/test_file_search_tools.py` | Unit | ✅ New tool-layer test written against the OLD `_raise_unavailable_with_filename_hint()` reproduced the exact reported concatenation: `"Windows Search index unreachable filename search still works — ..."` (no separator) | ✅ Passes after joining with `'. '`: `"Windows Search index unreachable. filename search still works — ..."` | ✅ 3 adapter-level exact-message cases (timeout, spawn-blocked, nonzero-exit) + 1 tool-layer combined-message case | ➖ None needed — 1-character join-string change |

### Test Summary
- **Total tests added (net)**: 8 (456 → 464)
- **New test functions**: 9 —
  `test_build_search_sql_row_cap_is_shared_by_both_transports`,
  `test_build_get_info_sql_is_capped_at_top_1`,
  `test_bridge_search_unparseable_line_raises_distinctly_worded_unavailable_error`,
  `test_bridge_search_missing_sentinel_returns_partial_rows_not_error`,
  `test_bridge_search_partial_last_line_returns_earlier_rows_not_error`,
  `test_parse_bridge_stdout_reports_results_truncated_true_when_sentinel_missing`,
  `test_parse_bridge_stdout_reports_results_truncated_false_when_sentinel_present`,
  `test_parse_bridge_stdout_raises_on_non_last_line_corruption`,
  `test_search_phrase_only_ado_then_bridge_failed_full_message_is_properly_punctuated`
- **Tests removed (repurposed in place)**: 1 —
  `test_bridge_search_malformed_json_stdout_maps_to_windows_search_unavailable`
  (superseded by the unparseable-line test, which distinguishes
  corruption from truncation; the old test's "any non-JSON stdout raises"
  premise no longer holds now that a truncated-but-partially-valid stream
  is a result, not an error)
- **Layers used**: Unit (9)
- **Pure functions created**: 1 — `_parse_bridge_stdout()` (plus the
  internal `_BridgeUnparseableLineError` signal type), directly unit
  tested independent of `PowerShellSearchBridge.search()`/`get_info()`

## Root Cause (confirmed via investigation, not RED reproduction — no real PowerShell/Windows host available)

Both defects were confirmed by reading, not by reproducing a live COM
failure (impossible on WSL2):

1. `tools/ps_bridge_search.ps1` accumulated `$rows` across the whole
   reader loop and serialized it as ONE `ConvertTo-Json` document at the
   very end; `tools/file_search_adapter.py::PowerShellSearchBridge._invoke()`
   parsed stdout as exactly one JSON document
   (`json.loads(completed.stdout)`). Any interruption to that one
   document — regardless of cause — corrupts the entire response, and a
   capped-but-snippet-heavy result set (many rows, each carrying
   `System.Search.AutoSummary` text) is a lot of bytes to serialize/
   transmit/parse atomically. No explicit Python-side byte bound exists
   in this path (`subprocess.run(capture_output=True)` reads to
   EOF/timeout with no size cap of its own) — confirmed by grep across
   `tools/*.py`; the fragility is structural (one document, any cut =
   total loss), not a too-tight constant to raise.
2. `tools/file_search.py::_raise_unavailable_with_filename_hint()` built
   `f"{exc} {_FILENAME_STILL_WORKS_HINT}"` — a bare-space join.
   `_UnavailableAdapter`'s own message
   ("Windows Search index unreachable") and every real
   `PowerShellSearchBridge` error message
   ("...timed out", "...malformed JSON", "...blocked or unavailable: ...")
   never carry trailing punctuation, so the join always produced a
   run-on sentence.

## Command Log (RED → GREEN)

```
$ .venv/bin/python3.12 -m pytest -q tests/test_file_search_adapter.py tests/test_file_search_tools.py
# after rewriting stdout fixtures to _jsonl(...) shape, before touching _invoke():
FAILED (multiple) — every bridge test whose fixture now emits JSON Lines
  broke against json.loads(completed.stdout) expecting one document

# after adding _parse_bridge_stdout()/_BridgeUnparseableLineError and
# rewiring _invoke():
85 passed

$ .venv/bin/python3.12 -m pytest -q tests/test_file_search_tools.py::test_search_phrase_only_ado_then_bridge_failed_full_message_is_properly_punctuated
# before the '. ' join fix:
FAILED — AssertionError: "Windows Search index unreachable filename
  search still works — ..." != "Windows Search index unreachable.
  filename search still works — ..."

# after the join fix:
1 passed

$ .venv/bin/python3.12 -m pytest -q
464 passed in 2.79s
```

Zero regressions across the full suite.

## Files Changed

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/ps_bridge_search.ps1` | Modified | Rewrote the reader loop to write one `ConvertTo-Json -Compress` line per row (flushed immediately via `$stdout.Flush()`) instead of accumulating `$rows` and serializing once at the end; added a final `{"done": true, "count": N}` sentinel line after the loop; updated the header comment block's "Output contract" section |
| `tools/file_search_adapter.py` | Modified | Added `_BridgeUnparseableLineError` (internal signal) and `_parse_bridge_stdout()` (line-by-line JSONL parser distinguishing a truncated-last-line/missing-sentinel result from genuine non-last-line corruption); rewrote `_invoke()`'s stdout-parsing block to call it instead of `json.loads()` on the whole document; updated `PowerShellSearchBridge`'s class docstring |
| `tools/file_search.py` | Modified | `_raise_unavailable_with_filename_hint()`: `f"{exc}. {_FILENAME_STILL_WORKS_HINT}"` (was `f"{exc} {_FILENAME_STILL_WORKS_HINT}"`); docstring note citing BUG-006 |
| `tests/test_file_search_adapter.py` | Modified | Added `_jsonl()` test helper; rewrote every bridge stdout fixture to the JSON Lines shape; added exact-message assertions to the timeout/spawn-blocked/nonzero-exit tests; added 6 new tests for truncation-as-result, genuine-corruption, and row-cap regression guards; repurposed the array-collapse test |
| `tests/test_file_search_tools.py` | Modified | Added `test_search_phrase_only_ado_then_bridge_failed_full_message_is_properly_punctuated` asserting the full combined message |
| `openspec/specs/powershell-search-bridge/spec.md` | Modified | Rewrote "Subprocess Transport and Output Contract" for JSON Lines; added "Truncated Stream Is a Result, Not an Error" requirement with scenarios; updated the "Both-Transports-Exhausted Messaging" scenario for the punctuation fix |
| `openspec/changes/archive/2026-08-26-ps-bridge-jsonl-hotfix/{proposal,tasks,apply-progress}.md` | Created | This hotfix's record |

## Deviations from Design

- No change to `FileSearchPort.search()`/`get_info()` signatures or
  `FileSearchResponse.results_truncated` wiring. The bridge's own
  truncation signal (`_parse_bridge_stdout()`'s `results_truncated`
  return value) is computed and directly unit-tested, but intentionally
  NOT threaded up through `PowerShellSearchBridge.search()`'s return type
  or the tool layer — the `file-search` spec currently defines
  `results_truncated` strictly in terms of the filesystem walk, and
  widening that contract across all three `FileSearchPort`
  implementations (including `FakeFileSearchAdapter`, not owned by this
  hotfix) is out of scope for a targeted fix. Recorded as deferred future
  polish in `proposal.md`.
- Repurposed rather than deleted
  `test_bridge_search_single_row_collapsed_to_bare_object_still_parses`:
  its premise (PowerShell 5.1's array-to-object collapse) is structurally
  impossible under JSON Lines, but the basic single-row coverage it
  provided was still worth keeping under a new name/rationale.

## Issues Found

None beyond the two defects this hotfix targets. The row-cap concern
cowork's report raised as a hypothesis ("the bridge SQL carries no row
cap") was investigated and found to be already false — both transports
share `_build_search_sql`/`_build_get_info_sql`, which always apply
`SELECT TOP <n>` — so Phase 1 added regression tests rather than a code
fix.

## Status

18/18 tasks complete (Phases 0-4). Full suite green: 464 passed (456
baseline + 8 net new). Ready for sdd-verify / archive.
