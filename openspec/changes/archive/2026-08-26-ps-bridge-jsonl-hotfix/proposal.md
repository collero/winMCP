# Proposal: PowerShell Search Bridge JSON Lines Hotfix

## Intent

Live evidence from the promoted build
(`/mnt/c/usr/WinMCP/_chatCowork/0043-cowork-bug-006-ps-bridge-malformed-json.md`,
cowork's BUG-006) confirmed the PS bridge architecture itself is sound —
`file_search {"phrase": "zzqqxxyyw"}` (a rare phrase) round-tripped a
clean, valid, empty result from the Desktop-spawn process class where ADO
has never once succeeded. But a broad, common phrase
(`file_search {"phrase": "Informa"}`) degraded with:

```
[windows_search_unavailable] PowerShell search bridge returned malformed
JSON filename search still works - retry the same call with only
'filename' set (omit 'phrase').
```

Two distinct defects in one message:

1. **Malformed JSON at volume.** A large result payload (many rows, each
   carrying a full `System.Search.AutoSummary` snippet) serialized as one
   giant JSON document is fragile against a stream getting cut anywhere
   downstream — the entire response becomes unparseable, not just the
   tail. `_build_search_sql`/`_build_get_info_sql` already cap rows via
   `SELECT TOP <n>` (shared verbatim by the ADO adapter and the bridge),
   so it is not an uncapped `SELECT`; a capped-but-snippet-heavy result
   set can still be a lot of bytes.
2. **Sentence concatenation.** The "malformed JSON" cause and the
   "filename search still works" advice were joined with a bare space,
   not punctuation, producing the misreadable
   "...malformed JSON filename search still works..." — exactly the
   string a caller sees at the moment they're already confused about why
   the call failed.

## Root Cause

- `tools/ps_bridge_search.ps1` built one PowerShell array (`$rows`) across
  the whole `while ($reader.Read())` loop and serialized it as a SINGLE
  `ConvertTo-Json` document at the end. Any interruption to that one
  document — anywhere between the script and the Python side's
  `json.loads(completed.stdout)` — corrupts the entire response, and the
  more rows/snippet text a query returns, the larger and more fragile
  that one document is.
- `tools/file_search_adapter.py::PowerShellSearchBridge._invoke()` parsed
  stdout as exactly one JSON document and mapped ANY parse failure to
  `WindowsSearchUnavailableError("PowerShell search bridge returned
  malformed JSON")` — a truncated-but-otherwise-healthy response and a
  genuinely corrupt response were indistinguishable, and both were
  treated as a hard failure rather than "here are the rows I did get."
- `tools/file_search.py::_raise_unavailable_with_filename_hint()` built
  the combined message as `f"{exc} {_FILENAME_STILL_WORKS_HINT}"` — a
  bare-space join. `exc`'s own message never carries trailing
  punctuation (`"...timed out"`, `"...malformed JSON"`,
  `"...blocked or unavailable: ..."`), so the join always produced two
  sentences run together with no separator.

No explicit Python-side byte bound exists anywhere in this path —
`subprocess.run(capture_output=True)` reads to EOF/timeout with no size
cap of its own — so there was nothing to "raise"; the fragility was
structural (one document, cut anywhere = total loss), not a too-tight
constant.

## Fix

1. **JSON Lines output contract.** `tools/ps_bridge_search.ps1` now
   writes one compact JSON object per matched row, flushed immediately as
   each row is read from the `OleDbDataReader`, followed by a final
   sentinel line `{"done": true, "count": N}` marking a complete,
   non-truncated response. A stream cut anywhere now costs at most the
   trailing sentinel line or one partial row — never the whole document.
2. **Truncation is a RESULT, not an error.** The new
   `tools/file_search_adapter.py::_parse_bridge_stdout()` parses stdout
   line-by-line. If the sentinel line is never reached — missing
   entirely, or the last line is a partial JSON fragment (the exact shape
   a cut stream produces) — the rows that parsed cleanly are returned
   with no exception raised. Only a malformed line that is NOT the last
   line (the stream had every opportunity to finish writing it) is
   genuine corruption, raised as `WindowsSearchUnavailableError` with a
   message ("returned unparseable output (not valid JSON Lines)")
   distinguishable from a timeout/blocked/nonzero-exit failure.
3. **Message-assembly punctuation fix.**
   `_raise_unavailable_with_filename_hint()` now joins with `'. '`
   (`f"{exc}. {_FILENAME_STILL_WORKS_HINT}"`) instead of a bare space, so
   the combined message always reads as two properly separated
   sentences.
4. **Row-cap verified, not changed.** Confirmed both the ADO adapter and
   the PowerShell bridge already build their SQL through the one shared
   `_build_search_sql`/`_build_get_info_sql` pair, which always applies
   `SELECT TOP <n>` — `get_info` is always `TOP 1`. No uncapped `SELECT`
   exists on either transport; new regression tests lock this in.

## Deferred (noted, not implemented in this hotfix)

- Distinguishing "capped at `file_search_max_results`" vs. "the walk gave
  up early (time/dir budget)" within `results_truncated` for the
  filesystem-walk leg (`tools/file_search_walk.py`) — a caller currently
  cannot tell "narrow your scope" apart from "you hit the row cap,
  there may be more." Separate, pre-existing concern from this bridge
  fix; flagged by cowork's report as "minor, same family."
- Plumbing the PowerShell bridge's own `results_truncated` (from
  `_parse_bridge_stdout`) up through `FileSearchResponse.results_truncated`
  for phrase-involving queries. The `file-search` spec currently defines
  `results_truncated` strictly in terms of the filesystem walk stopping
  early ("Search Output Shape" requirement) and phrase-only queries are
  spec'd to always report `results_truncated: false`. Wiring the bridge's
  truncation signal through would require widening `FileSearchPort`'s
  `search()` contract across all three implementations
  (`WindowsSearchAdapter`, `PowerShellSearchBridge`,
  `FakeFileSearchAdapter`) plus the `file-search` spec itself — out of
  scope for a targeted hotfix. The behavior that matters most today is
  already fixed: a truncated bridge stream now returns partial results
  instead of raising `windows_search_unavailable`.

## Risk

Low. The bridge's own output format and the Python-side parser change
together (an already-atomic deploy unit — the `.ps1` and the adapter ship
in the same package), so there is no partial-rollout skew between an old
script and a new parser or vice versa. No public interface changes:
`PowerShellSearchBridge.search()`/`get_info()` keep their existing
signatures and return types; `FileSearchPort` is untouched.

## Rollback

Redeploy the previous zip. No data migration, no config/schema change.

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `tools/ps_bridge_search.ps1` | Modified | Emits JSON Lines (one row per line + `{"done": true, "count": N}` sentinel) instead of one JSON document |
| `tools/file_search_adapter.py` | Modified | New `_parse_bridge_stdout()` + `_BridgeUnparseableLineError`; `_invoke()` rewritten to parse line-by-line, distinguishing truncation (result) from corruption (error) |
| `tools/file_search.py` | Modified | `_raise_unavailable_with_filename_hint()` joins cause + advice with `'. '` instead of a bare space |
| `tests/test_file_search_adapter.py` | Modified | JSONL test helper (`_jsonl`); rewrote stdout fixtures for the new contract; new tests for truncated-stream/partial-last-line (result, not error), genuine non-last-line corruption (error), full exact-message assertions per degrade variant, and row-cap regression guards |
| `tests/test_file_search_tools.py` | Modified | New full-message assertion for the "ADO-failed-then-bridge-failed" combined degrade message |
| `openspec/specs/powershell-search-bridge/spec.md` | Modified | "Subprocess Transport and Output Contract" rewritten for JSON Lines; new "Truncated Stream Is a Result, Not an Error" requirement; "Both-Transports-Exhausted Messaging" scenario updated for the punctuation fix |

## Success Criteria

- [x] A broad-phrase query against a large, snippet-heavy result set no
      longer raises `windows_search_unavailable` purely because of
      response size — a cut stream yields partial results
- [x] A genuinely corrupt (non-truncation) bridge response still raises
      `WindowsSearchUnavailableError`, with a message distinguishable
      from a truncation
- [x] The "both transports exhausted" message reads as two properly
      punctuated sentences, not a concatenated run-on
- [x] Both transports' SQL is confirmed row-capped via the one shared
      builder pair, with regression tests locking this in
- [x] Full test suite green: 456 baseline + 8 new, zero regressions
