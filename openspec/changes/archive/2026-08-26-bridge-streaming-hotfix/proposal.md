# Proposal: PowerShell Search Bridge Streaming Hotfix

## Intent

BUG-006 (`/mnt/c/usr/WinMCP/_chatCowork/0059` and `0058`): on the
Claude-Desktop-descendant process route ONLY, `file_search
{"phrase": "<common word>"}` degrades with `"PowerShell search bridge
produced no output"` — a typed, correctly-degraded error, but with no
diagnostic detail an operator can act on. From every other spawn
context the identical SQL runs against the same script in well under a
second, exit code 0, 200 rows plus sentinel, empty stderr — ruling out
the `SELECT TOP <n>` cap and a simple fixed timeout as universal causes.

The leading mundane suspect: PowerShell buffers redirected stdout
inside the child process, so a child that is slow enough to hit the
bridge's timeout (and gets killed there) — or that dies mid-run for any
other reason — loses EVERYTHING sitting in that buffer, which surfaces
to Python as "no output" even though the child may have already found
and would have streamed many rows if only the parent had been reading
incrementally instead of waiting for the whole process to finish.

## Root Cause (pre-existing design gap, not a new regression)

`tools/file_search_adapter.py::PowerShellSearchBridge._invoke()` used
`subprocess.run(..., timeout=...)`, which — even though
`tools/ps_bridge_search.ps1` already flushes each JSON Lines row the
moment it is found (ps-bridge-jsonl-hotfix) — only ever hands the parent
process its captured stdout after the child process has fully exited
(or after `run()`'s own timeout/kill path, which does not attempt to
salvage partial output the way this hotfix's streaming reader does).
Any child that is killed by the timeout, or dies for any other reason
before writing the final sentinel, effectively loses its already-
streamed rows from the parent's point of view under the old blocking
read shape — the exact "PowerShell search bridge produced no output"
degrade a slow-but-alive query hits.

## Fix

1. **Streaming `Popen` read.** `_invoke()` now spawns the child via
   `subprocess.Popen` (stdin/stdout/stderr all piped, text mode) instead
   of a single blocking `subprocess.run()` call, and reads stdout
   INCREMENTALLY, line-by-line, via a background daemon reader thread
   feeding a `queue.Queue` that the main thread polls under an overall
   wall-clock deadline (`file_search_ps_bridge_timeout_seconds`, live-
   read, unchanged mechanism otherwise). A real Windows pipe's
   `readline()` has no per-call timeout of its own — the reader-thread-
   plus-queue shape is what lets the main thread still enforce one.
2. **Partial results on kill/early-exit, not a hard failure.** If the
   deadline elapses, or the child's stdout closes before the `{"done":
   true, ...}` sentinel is ever reached, the bridge kills the child (if
   the deadline triggered it) and returns whatever rows already parsed
   cleanly as a TRUNCATED result — never an error — as long as at least
   one row parsed. Only zero rows AND no sentinel still raises
   `WindowsSearchUnavailableError` (an empty-but-unconfirmed read is
   indistinguishable from a genuinely broken bridge).
3. **Truncation propagated to `FileSearchResponse.results_truncated`.**
   `PowerShellSearchBridge`/`FallbackSearchAdapter` now expose a
   documented `last_search_truncated` boolean attribute after every
   `search()` call, read by `tools/file_search.py` via
   `getattr(adapter, "last_search_truncated", False)` and OR'd into the
   phrase leg's (and, for a combined query, the walk's) truncation flag.
   Chosen over widening `FileSearchPort.search()`'s return type to
   `(rows, truncated)`: every other adapter (`WindowsSearchAdapter`,
   `FakeFileSearchAdapter`) and every test exercising either one expects
   a bare `list[FileSummary]` back, so a documented side-channel
   attribute — defaulting cleanly via `getattr(..., False)` for any
   transport that never sets it — is the least-invasive shape that still
   lets the signal reach the response envelope.
4. **Actionable failure diagnostics.** Every bridge failure message now
   names the exit condition — the child's real exit code, or
   `killed@Ns` when the deadline itself triggered the kill — and, when
   present, the first ~200 characters of stderr, so an operator seeing
   `windows_search_unavailable` never has to guess whether the child ran
   at all, finished, or was killed, or what (if anything) it printed to
   stderr first.
5. **Timeout default bumped 10 -> 30.** Now that a killed-at-the-deadline
   child degrades to partial results instead of a hard failure, a longer
   default budget costs less (a slow-but-alive query gets more time to
   finish cleanly) and gains more (fewer legitimately-slow queries get
   cut off at all).

`tools/ps_bridge_search.ps1` needed NO changes: its per-row
`WriteLine`+`Flush()` discipline (already present since
ps-bridge-jsonl-hotfix) is exactly what streaming needs on the Python
side — the flush-per-line contract was already correct; only the parent
process was still reading it all-at-once.

## Risk

Low-moderate. The read mechanism changed (Popen + threads instead of a
single blocking call), so this touches every code path through the
bridge — mitigated by a full rewrite of the bridge's test double
(mocking `Popen` with a small `_FakeProcess`/`_LineStream` pair instead
of `subprocess.run`) covering the same scenario matrix as before plus
the new streaming/truncation/diagnostic cases. No public interface
changes beyond the new `last_search_truncated` attribute (additive,
defaults cleanly via `getattr`): `PowerShellSearchBridge.search()`/
`get_info()` keep their existing signatures and return types;
`FileSearchPort` is untouched.

## Rollback

Redeploy the previous zip. No data migration, no config/schema change
beyond the `file_search_ps_bridge_timeout_seconds` default (a value
change, not a shape change — an explicit config value is unaffected).

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `tools/file_search_adapter.py` | Modified | `PowerShellSearchBridge._invoke()` rewritten around `subprocess.Popen` + a background reader-thread/queue pair under a wall-clock deadline; new `_pump_stdout`/`_pump_stderr`/`_reap`/`_diagnostic_suffix` helpers; `last_search_truncated` attribute added to `PowerShellSearchBridge`/`FallbackSearchAdapter` (and documented as always-`False` on `WindowsSearchAdapter`) |
| `tools/file_search.py` | Modified | `_search_phrase_only`/`_search_combined` read `adapter.last_search_truncated` (via `getattr(..., False)`) and fold it into `FileSearchResponse.results_truncated` |
| `tools/settings.py` / `config/settings.yaml` | Modified | `file_search_ps_bridge_timeout_seconds` default bumped 10 -> 30 |
| `tools/ps_bridge_search.ps1` | Unchanged (comment-only) | Documented that its existing per-row flush discipline is what the new streaming reader relies on |
| `tests/test_file_search_adapter.py` | Modified | Bridge test section rewritten to mock `subprocess.Popen` (`_FakeProcess`/`_LineStream`/`_FixedReadStream` doubles) instead of `subprocess.run`; new streaming/truncation/diagnostic-message test matrix; `_settings` default-timeout test bumped to 30 |
| `tests/test_file_search_tools.py` | Modified | New `_TruncatingAdapter` stub and truncation-propagation tests for the phrase-only and combined legs |
| `tests/test_settings.py` | Modified | Default timeout test updated 10 -> 30 |
| `openspec/specs/powershell-search-bridge/spec.md` | Modified | New "Wall-Clock Read Deadline and Partial Results on Kill" and "Exposes Whether Its Last Search Was Truncated" requirements; "Subprocess Transport..." and "Truncated Stream..." rewritten for the streaming design; "Timeout and Failure Mapping" replaced by "Failure Mapping and Diagnostic Detail" |
| `openspec/specs/file-search/spec.md` | Modified | "Search Output Shape" requirement widened to cover the phrase-leg's own truncation signal, OR'd into `results_truncated` |

## Success Criteria

- [x] A child that streams N rows then hangs (or dies) before the
      sentinel yields N results with `results_truncated: true`, not a
      hard failure
- [x] Zero rows and no sentinel still raises a typed error, never
      silently returned as an empty (non-truncated) result
- [x] Every bridge failure message names the exit condition
      (`killed@Ns` or a real exit code) and, when present, a stderr
      excerpt
- [x] Truncation on the phrase leg reaches `FileSearchResponse.results_truncated`,
      OR'd with the walk's own flag on a combined query
- [x] Default read deadline bumped 10 -> 30
- [x] Full test suite green, zero regressions
