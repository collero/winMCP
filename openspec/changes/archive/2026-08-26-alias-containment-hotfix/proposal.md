# Proposal: Alias-Aware Allowed-Roots Containment, Sentinel-Keyed Failure Rule, and Error-Line Preservation

## Intent

Live evidence (`/mnt/c/usr/WinMCP/_chatCowork/0065`): on the Desktop
route, `file_search {"phrase": "Informa"}` returns `{"results": [],
"resultsTruncated": true}` — a silent wrong answer. Tracing the bridge
invocation log showed the bridge child actually streamed **50 real
rows** (exit code 1, no sentinel, 5.6s — the OleDb rowset dies fetching
its SECOND chunk; the first ~50-row chunk always arrives cleanly), the
parent parsed all 50 into `FileSummary` objects, and then
`tools/file_search.py`'s post-call "drop any row outside the allowed
roots" defense-in-depth filter dropped every single one.

Root cause, confirmed via a probe script
(`/mnt/c/usr/winmcp_ps_search_probe.ps1`): for a redirected `Documents`
library location, Windows Search reports
`System.ItemPathDisplay = "C:\Documents\OneDrive - Informa\..."` (a
library ALIAS — `C:\Documents` is not itself a real, allowed-roots
path) while `System.ItemUrl = "file:C:/co/OneDrive - Informa/..."` (the
REAL path, correctly inside the allowed root `C:\co`). Both
`tools/file_search_adapter.py::_row_to_summary`/`_row_from_mapping` and
`tools/file_search.py::_drop_outside_allowed_roots` only ever looked at
the single, already-collapsed `path` field — which preferred
`ItemPathDisplay` — so every row hit the alias, failed containment, and
was silently dropped, even though the real underlying file was exactly
where it was supposed to be.

Auditing the same code path surfaced two smaller, related gaps:
(2) the "zero rows and no sentinel is a failure" rule needed an explicit
regression test pinning that it is keyed on the sentinel, not the exit
code (a clean `exit code 0` with zero rows and no sentinel must still
raise) — reviewed and confirmed ALREADY correct in
`PowerShellSearchBridge._invoke_impl`, now locked in by a dedicated
test; (3) a script-reported `{"error": ...}` line's text already
reached a raised exception's message via the `stderr_excerpt` channel,
but was NOT separately recorded in the bridge invocation debug log —
so the partial-success shape (real rows streamed, THEN an error line,
so `search()` returns normally without raising) left that diagnostic
text completely unrecorded, exactly the shape this incident's own 50-
row case took.

## Fix

1. **Alias-aware containment + path preference.** `FileSummary` gets a
   new internal-only field `alt_url_path` (`exclude=True` — never
   serialized), populated by `tools/file_search_adapter.py::_row_to_summary`/
   `_row_to_detail`/`_row_from_mapping` from a new `_decode_item_url()`
   helper that decodes `System.ItemUrl` UNCONDITIONALLY (independent of
   whether `System.ItemPathDisplay` is also present, unlike the existing
   display-preferred `_normalize_path`). `tools/file_search.py::_drop_outside_allowed_roots`
   now keeps a row if EITHER `result.path` OR `result.alt_url_path` is
   contained within an allowed root; when only the latter passes, the
   row is kept with its returned `path` rewritten to that real,
   `ItemUrl`-derived form — never left as the unopenable alias. A row
   whose display-derived path already passes containment is returned
   completely unchanged.
2. **Sentinel-keyed failure rule, locked in by a regression test.**
   Reviewed `PowerShellSearchBridge._invoke_impl`'s existing "zero rows
   parsed AND sentinel never reached -> raise" rule: it was ALREADY
   keyed purely on the sentinel (`done`), never on `process.returncode`
   — a new test (`test_bridge_search_zero_rows_no_sentinel_raises_even_with_clean_exit_code_zero`)
   pins this explicitly (clean `exit code 0`, zero rows, no sentinel,
   still raises) so a future change can't accidentally re-key the rule
   on the exit code instead.
3. **Error-line text preservation in the debug log.** New
   `error_line_first_200` field on the bridge invocation debug log
   (`_log_bridge_invocation`), populated from the script's own
   `{"error": ...}` line's text whenever one was seen during the
   invocation — independently of `stderr_first_200` (which already
   carries the same text, prefixed, for the raised-exception message)
   and independently of whether the call actually raised, so the
   partial-success shape (rows already streamed before the error line
   arrived) still leaves the script's diagnostic text somewhere an
   operator can find it.
4. **Doc note.** `openspec/specs/powershell-search-bridge/spec.md`
   records, as a known platform limitation (not a defect): on this
   process ancestry the OleDb rowset's second chunk fetch reliably
   dies, so a broad `phrase` query caps at the provider's first chunk
   (~50 rows) with `results_truncated: true`, regardless of how many
   total matches exist in the index.

## Risk

Low. Piece 1 only widens what `_drop_outside_allowed_roots` accepts (a
row that already passed containment is untouched — see the "row whose
display path already passes containment is unchanged" scenario/test);
the new `FileSummary.alt_url_path` field is `exclude=True`, so it never
appears on the wire and cannot affect any existing consumer's
deserialization. Piece 2 is a test-only regression lock — no production
code changed (the rule was already correct). Piece 3 is purely
additive (`error_line_first_200`, default `""`) on an already
best-effort, config-gated, never-raising log. Piece 4 is documentation
only.

## Rollback

Redeploy the previous zip. No data migration. `alt_url_path` and
`error_line_first_200` are both new, additive fields with safe defaults
(`None`/`""`) — nothing downstream depends on their presence.

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `models/schemas.py` | Modified | `FileSummary` gains `alt_url_path: str \| None = Field(default=None, exclude=True)` |
| `tools/file_search_adapter.py` | Modified | New `_decode_item_url()` helper (unconditional `ItemUrl` decode); `_normalize_path` refactored to reuse it; `_row_to_summary`/`_row_to_detail`/`_row_from_mapping` populate `alt_url_path`; `_invoke`/`_invoke_impl`/`_log_bridge_invocation` gain `error_line_first_200` |
| `tools/file_search.py` | Modified | `_drop_outside_allowed_roots` tries `alt_url_path` when `path` fails containment, rewriting `path` on success |
| `tests/test_file_search_adapter.py` | Modified | New alias/`alt_url_path` mapping tests (ADO + bridge + get_info), sentinel-keyed regression test, `error_line_first_200` debug-log tests |
| `tests/test_file_search_tools.py` | Modified | New `_AliasRowAdapter` double + three containment-fallback tests (kept+rewritten, dropped-both-outside, unchanged-when-already-contained) |
| `openspec/specs/file-search/spec.md` | Modified | New "Alias-Aware Allowed-Roots Containment" requirement + 3 scenarios |
| `openspec/specs/powershell-search-bridge/spec.md` | Modified | Sentinel-keyed clarification, `error_line_first_200` in "Script-Reported Failure Line"/"Bridge Invocation Debug Log", known-platform-limitation note |

## Success Criteria

- [x] A row whose `System.ItemPathDisplay`-derived path is a
      redirected-library alias outside the allowed roots, but whose
      `System.ItemUrl`-derived path is inside them, is kept and returned
      with the real (url-derived) `path`
- [x] A row where neither form is contained is still dropped
- [x] A row whose display-derived path already passes containment is
      returned completely unchanged
- [x] Zero rows + no sentinel raises regardless of exit code (locked in
      by a regression test; no production code change was needed)
- [x] A script-reported error line's text is recorded in the bridge
      debug log's new `error_line_first_200` field, including in the
      partial-success shape where `search()` does not raise at all
- [x] The known second-chunk-fetch platform limitation is documented in
      the powershell-search-bridge spec
- [x] Full test suite green, zero regressions
