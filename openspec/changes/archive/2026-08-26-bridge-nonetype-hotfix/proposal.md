# Proposal: PowerShell Bridge NoneType Stdout Hotfix

## Intent

Live evidence from the promoted build
(`/mnt/c/usr/WinMCP/_chatCowork/0049-cowork-bug-007-phrase-untyped-crash.md`,
cowork's BUG-007, HIGH) found that `file_search {"phrase": "Informa"}` — a
broad phrase producing a large result payload — crashes with:

```
Error calling tool 'file_search': 'NoneType' object has no attribute 'splitlines'
```

A rare phrase (`"zzqqxxyyw"`) still returns a clean, valid, empty result;
`filename` search is unaffected. This is worse than the bug it replaced
(BUG-006, `ps-bridge-jsonl-hotfix`): the error is untyped (a caller cannot
branch on it), the degrade path (typed `windows_search_unavailable` naming
`filename` as a fallback) never runs, and it leaks a raw Python internals
string to the caller.

## Root Cause

`PowerShellSearchBridge._invoke()` (`tools/file_search_adapter.py`) called
`_parse_bridge_stdout(completed.stdout)`, which does
`stdout.splitlines()`. `completed.stdout` was `None` on the failing path —
despite `subprocess.run(..., capture_output=True, text=True)` — the same
volume-dependent condition BUG-006 hit (a large, snippet-heavy result set
stressing the read path), but manifesting as "no captured output at all"
rather than "one malformed JSON document." The reader was written only for
the string case; nothing in `_invoke()` guarded against `None`, and no
blanket exception handler existed around the spawn/read/parse sequence to
catch it (or anything else unforeseen) and map it to the typed
`WindowsSearchUnavailableError` contract.

A second, related gap: the tool layer (`tools/file_search.py`) only caught
`WindowsSearchUnavailableError` (and, for `file_get_info`'s enrichment
leg, `FileNotFoundInIndexError`) around adapter calls — an adapter that
violated its own `FileSearchPort` contract by raising anything else, or by
returning `None` instead of a list/`FileDetail`, would still have leaked
an untyped exception (or an `AttributeError`/`TypeError` from iterating/
attribute-accessing the unexpected `None`) even after the bridge itself
was fixed.

## Fix

1. **Guard every stdout/stderr read.** `PowerShellSearchBridge._invoke()`
   now checks `completed.stdout` for `None`/empty BEFORE handing it to
   `_parse_bridge_stdout()`, raising `WindowsSearchUnavailableError` with
   a distinctly-worded message ("produced no output") — distinguishable
   from the "unparseable output" and "nonzero exit" messages. This is
   never a legitimate "zero results" response: even an empty result set
   still writes the `{"done": true, "count": 0}` sentinel line. The
   nonzero-exit-code branch guards `completed.stderr` with `(... or
   "").strip()` for the same reason.
2. **Blanket exception mapping at the bridge boundary.** The entire body
   of `_invoke()` (spawn, read, parse) is now wrapped in a broad
   `except Exception` that maps anything unforeseen to
   `WindowsSearchUnavailableError`, re-raising any
   `WindowsSearchUnavailableError` already raised by the specific
   branches unchanged. A subprocess spawn + pipe read + text parse fails
   in ways nobody enumerates in advance; the typed error is the contract
   at this boundary, and this is the actual enforcement of it.
3. **Tool-layer defense-in-depth.** `tools/file_search.py`'s
   `_search_phrase_only`/`_search_combined` now also catch a bare
   `Exception` around `adapter.search()` (beyond the documented
   `WindowsSearchUnavailableError`), mapping it into the same typed error
   with the existing "filename search still works" hint, and treat a
   `None` return from the adapter as an empty result list rather than
   crashing on the subsequent iteration. `file_get_info`'s enrichment
   block now catches `Exception` generally (widened from the two
   documented `FileSearchPort` exceptions) and moves the `detail.kind`/
   `detail.snippet` reads inside the `try`, so a hostile adapter
   returning `None` from `get_info()` (which does not raise) is caught by
   the same guard instead of raising an unguarded `AttributeError` in an
   `else` clause the `except` cannot reach — consistent with the
   file-get-info spec's existing "Index Enrichment Failure Never
   Surfaces" requirement.
4. **Contract-level property test.** Added a hostile-adapter test matrix
   (`tests/test_file_search_tools.py`) driving `file_search()`/
   `file_get_info()` with adapters that raise arbitrary non-taxonomy
   exceptions or return `None`, asserting every outcome is either a valid
   response model or a typed `CalendarToolError` subclass — never an
   untyped exception. Scoped to the two file-search tools only; extending
   this property test to every MCP tool (mail/calendar/tasks) is future
   work, not part of this hotfix.

## Deferred (noted, not implemented in this hotfix)

- Extending the hostile-adapter contract-level property test beyond
  `tools/file_search.py` to the mail/calendar/tasks tool layers. Those
  layers have their own adapters and error taxonomies; widening the
  property test to cover them is a separate, larger effort out of scope
  for a targeted hotfix.
- Threading the bridge's own `_parse_bridge_stdout` truncation signal
  through `FileSearchResponse.results_truncated` for phrase queries —
  already deferred by `ps-bridge-jsonl-hotfix`; unchanged by this fix.

## Risk

Low. No public interface changes: `PowerShellSearchBridge.search()`/
`get_info()`, `FileSearchPort`, and `file_search()`/`file_get_info()`'s
signatures and return types are unchanged. The fix only widens what is
caught and guarded at two existing boundaries (the bridge's own
spawn/read/parse sequence, and the tool layer's adapter calls) — no new
failure modes are introduced, and every existing typed-error message
wording is preserved verbatim.

## Rollback

Redeploy the previous zip. No data migration, no config/schema change.

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `tools/file_search_adapter.py` | Modified | `PowerShellSearchBridge._invoke()`: guard `completed.stdout`/`completed.stderr` against `None`; explicit `None`/empty-stdout check raising a distinctly-worded typed error before parsing; blanket `except Exception` wrapping the whole spawn/read/parse sequence |
| `tools/file_search.py` | Modified | `_search_phrase_only`/`_search_combined`: broaden the adapter-call `except` to also catch bare `Exception` (mapped to `WindowsSearchUnavailableError` + filename-hint), and guard against a `None` return from `adapter.search()`. `file_get_info`: widen the enrichment `except` to `Exception` and move the `detail.kind`/`detail.snippet` reads inside the `try` |
| `tests/test_file_search_adapter.py` | Modified | New tests: `stdout=None`/`stdout=""` mapping to a distinctly-worded typed error (search and get_info), a solely-malformed-stdout-is-truncation-not-error case, `stderr=None` on nonzero exit, `TimeoutExpired` with `stdout=None`, and a blanket-mapping test for an unforeseen exception type (search and get_info) |
| `tests/test_file_search_tools.py` | Modified | New hostile-adapter property test matrix (`_HostileAdapter`) across `AttributeError`/`RuntimeError`/`KeyError`/`TypeError`/`None`-return, exercised through `file_search()` (phrase-only, combined, filename-only-unaffected) and `file_get_info()` |
| `openspec/specs/powershell-search-bridge/spec.md` | Modified | "Timeout and Failure Mapping" requirement widened to cover `None`/empty stdout and the blanket exception mapping, with four new scenarios |
| `openspec/changes/archive/2026-08-26-bridge-nonetype-hotfix/{proposal,tasks,apply-progress}.md` | Created | This hotfix's record |

## Success Criteria

- [x] `file_search {"phrase": "Informa"}`-shaped calls (bridge stdout
      `None`/empty) no longer crash with a raw `AttributeError` — they
      raise the typed `windows_search_unavailable` degrade error naming
      `filename` search as a fallback
- [x] The bridge's blanket exception mapping covers anything unforeseen,
      not just the specifically-enumerated failure shapes
- [x] A hostile/buggy adapter can never make `file_search()`/
      `file_get_info()` raise an untyped exception — contract-level
      property test passing across a matrix of hostile behaviors
- [x] Full test suite green: 486 baseline + 30 new, zero regressions
