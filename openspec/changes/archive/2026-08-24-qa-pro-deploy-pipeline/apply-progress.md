# Apply Progress: qa-pro-deploy-pipeline

## Batch 1 of 3 — Phases 1, 2, 3 (COMPLETE)

Mode: **Strict TDD** (test runner: `.venv/bin/python3.12 -m pytest -q`). Baseline confirmed before starting: **139/139 passed**.

### Completed Tasks

- [x] 1.1 RED `tests/test_smoke_test.py`: `aggregate_verdict` truth table — all-PASS, WARN-degrades (no FAIL), FAIL-wins-over-WARN, mixed combos
- [x] 1.2 GREEN `deploy/smoke_test.py`: added pure `aggregate_verdict(family_results)` — `family_results` is a dict mapping family name → per-family verdict string; returns one of the 3 verdict strings verbatim
- [x] 2.1 RED `tests/test_smoke_test.py`: `StubServer` class (`.send`/`.read_line`, in-file, duck-typed to `ServerProcess`) — search hit chains matching detail call on `entryId` → PASS
- [x] 2.2 RED `::` empty search result → PASS, no chain call, "no items to chain" note
- [x] 2.3 RED `::` `OUTLOOK_UNAVAILABLE_HINTS`-matching error → WARN; other tools/call error → FAIL
- [x] 2.4 RED `::` family's `StepFailed` caught inside `run_family`, returns `("fail", [reason])`, doesn't propagate
- [x] 2.5 GREEN `deploy/smoke_test.py`: `Family` namedtuple, `_FamilyWarning` internal signal, `_call_tool`/`_extract_list_result` helpers, `run_family(server, id_gen, family)` — search+chain+classify, reuses `OUTLOOK_UNAVAILABLE_HINTS`
- [x] 3.1 RED `::test_expected_tools_matches_server_registered_names` — static `EXPECTED_TOOLS` set vs `server.py`'s registered names (fake adapters, FastMCP in-process `Client`)
- [x] 3.2 RED `::test_tools_list_missing_tool_fails_naming_it` — stub `tools/list` omits `mail_get_message` → `do_tools_list` raises `StepFailed` naming it
- [x] 3.3 GREEN `deploy/smoke_test.py`: `EXPECTED_TOOLS` widened to the 7 registered tools; `FAMILIES` table (calendar/tasks/mail-inbox/mail-sent); `TOTAL_STEPS = 3 + len(FAMILIES)`; `do_initialize`/`do_tools_list` now take a shared `id_gen`; `main()` loops `FAMILIES` via `run_family` + `aggregate_verdict`; dropped `do_calendar_search`
- [x] 3.4 RED `::test_format_summary_one_line_per_family_and_final_verdict` (+ `test_format_summary_all_pass_final_line`) — pure `format_summary(family_results, overall)`
- [x] 3.5 GREEN `deploy/smoke_test.py`: wired `format_summary()` into `main()`'s print block

### Files Created / Modified

| File | Action | What Was Done |
|------|--------|----------------|
| `deploy/smoke_test.py` | Modified (restructured) | Replaced the fixed 4-step/calendar-only flow with the data-driven design: `aggregate_verdict(family_results)` (pure), `Family` namedtuple, `_FamilyWarning` (internal-only signal, never escapes `run_family`), `_call_tool`/`_extract_list_result` helpers, `run_family(server, id_gen, family)` (pure-ish: I/O via `server`, but never raises), `FAMILIES` table (calendar/tasks/mail-inbox/mail-sent), `EXPECTED_TOOLS` widened from 3 to 7 tool names, `TOTAL_STEPS = 3 + len(FAMILIES)`, `format_summary(family_results, overall)` (pure), `step_result()` printer. `do_initialize`/`do_tools_list` now take a shared `id_gen` (`itertools.count(1)`, created once in `main()` and threaded through every JSON-RPC call including the family search/detail calls) instead of hardcoded ids 1/2/3. `do_calendar_search` deleted — its logic was absorbed into the generic `run_family`/`_call_tool`/`_extract_list_result` trio. `main()` now: handshake (initialize → notifications/initialized → tools/list, `StepFailed` here bypasses families and FAILS outright) → loop `FAMILIES` via `run_family` (each family's `StepFailed`/`_FamilyWarning` is caught *inside* `run_family`, so one broken family never aborts the others) → `aggregate_verdict()` → `format_summary()`. The 3 final verdict strings (`SMOKE TEST PASSED`, `SMOKE TEST PASSED WITH WARNINGS`, `SMOKE TEST FAILED`) are preserved byte-identical (now returned directly by `aggregate_verdict()` instead of chosen inline in `main()`). Module docstring updated to describe the family-driven design and name the new stdlib imports (`itertools`, `collections.namedtuple`). |
| `tests/test_smoke_test.py` | Created | 13 tests, stdlib + pytest only, no subprocess/win32com: 4 `aggregate_verdict` truth-table cases (all-pass, warn-degrades, fail-wins-over-warn, 5-way mixed combo), an in-file `StubServer` (duck-typed `.send()`/`.read_line()`, scripted per tool/method name) plus `_hit_result`/`_empty_result`/`_tool_error`/`_rpc_error` response builders, 5 `run_family` behavior tests (hit chains detail call with the correct `entryId`, empty result passes with a "no items to chain" note and zero detail calls, Outlook-unavailable-hinted error → warning, a different error → fail, and a raw JSON-RPC error is caught internally and never propagates as `StepFailed`), `test_expected_tools_matches_server_registered_names` (imports the real `server.py` + all 3 fake adapters, lists tools via FastMCP's in-process `Client`, compares to `smoke_test.EXPECTED_TOOLS`), `test_tools_list_missing_tool_fails_naming_it` (stub `tools/list` omitting `mail_get_message`), and 2 `format_summary` tests (one line per family + final verdict line last; matches `aggregate_verdict`'s own output for both the all-pass and warn-degraded cases). |

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1/1.2 | `tests/test_smoke_test.py` (4 aggregate_verdict tests) | Unit | ✅ 139/139 (full-suite baseline before this batch) | ✅ Written — `ImportError: cannot import name 'aggregate_verdict' from 'deploy.smoke_test'` (confirmed via a dedicated pre-implementation run) | ✅ 4/4 passed after implementation | ✅ 4 cases: all-pass, warn-degrades-no-fail, fail-wins-over-warn, 5-way mixed combo | ➖ None needed — 3-line if/elif/else over `dict.values()`, already minimal |
| 2.1-2.4 | `tests/test_smoke_test.py` (5 run_family tests + StubServer) | Unit | ✅ (joint run with 1.1/1.2, confirmed 4/4 passing before this sub-batch) | ✅ Written — `ImportError: cannot import name 'Family' from 'deploy.smoke_test'` (confirmed via a dedicated pre-implementation run) | ✅ 5/5 passed after `Family`/`run_family`/`_call_tool`/`_extract_list_result`/`_FamilyWarning` implementation | ✅ 5 distinct scenarios: hit-chains-detail (asserts exact `entryId` forwarded), empty-result-no-chain (asserts zero detail calls + note text), Outlook-hint → warning, other-error → fail (proves the hint/non-hint branch is genuinely conditional, not hardcoded), StepFailed-caught-internally (a raw JSON-RPC `error` object, a different code path than the `isError` content-block case) | ➖ None needed — `_call_tool`/`_extract_list_result` extracted as pure-ish helpers from the start, mirroring the original `do_calendar_search`'s already-proven parsing precedent |
| 3.1/3.2 | `tests/test_smoke_test.py` (2 tests) | Integration (3.1, FastMCP in-process `Client` against real `server.py`) / Unit (3.2, stub server) | ✅ 9/9 (full-suite-relevant baseline after 1.1-2.5 landed) | ✅ Written — 3.1 failed on `assert EXPECTED_TOOLS == names` (3-tool set vs server's 7 real names); 3.2 failed with `TypeError: do_tools_list() takes 1 positional argument but 2 were given` (confirmed via a dedicated pre-implementation run capturing both failure reasons) | ✅ 11/11 passed after widening `EXPECTED_TOOLS` to 7 and adding `id_gen` to `do_initialize`/`do_tools_list` | ➖ Single per test — 3.1 has one assertion shape (set equality against the real server); 3.2 has one assertion shape (`StepFailed` naming the omitted tool) | ➖ None needed |
| 3.3 | `deploy/smoke_test.py` (FAMILIES/TOTAL_STEPS/main rewire) | — | (same run as 3.1/3.2, see above) | (see above — the RED tests above also exercise this GREEN step) | ✅ 11/11 (full `tests/test_smoke_test.py`), 150/150 (full suite) | (see above) | ➖ None needed — `main()`'s family loop and the pre-existing handshake block read cleanly; verified manually end-to-end against the real `server.py` (no Outlook) — see Manual Verification below |
| 3.4/3.5 | `tests/test_smoke_test.py` (2 format_summary tests) | Unit | ✅ 11/11 (full-suite-relevant baseline after 3.1-3.3 landed) | ✅ Written — `ImportError: cannot import name 'format_summary' from 'deploy.smoke_test'` (confirmed via a dedicated pre-implementation run) | ✅ 13/13 passed after implementation + wiring into `main()` | ✅ 2 cases: 4-family mixed (warn-degraded) output shape, 2-family all-pass final line | ➖ None needed — one-line list-comprehension + `append`, already minimal |

### Test Summary

- **Total tests written this batch**: 13 (4 `aggregate_verdict` + 5 `run_family` + 2 tools/list-and-registration + 2 `format_summary`)
- **Total tests passing (full suite)**: 152/152 (baseline was 139/139 — zero regressions, +13 net new)
- **Layers used**: Unit (12), Integration/FastMCP-in-process (1, `test_expected_tools_matches_server_registered_names`)
- **Approval tests** (refactoring): None formally, but `_extract_list_result`'s zero-hits-on-parse-failure behavior deliberately preserves `do_calendar_search`'s original precedent (documented in its own docstring) — not a separate approval-test file since the old function was deleted outright, not incrementally refactored in place.
- **Pure functions created**: `aggregate_verdict` (pure), `format_summary` (pure), `_extract_list_result` (pure given its inputs, no I/O). `run_family`/`_call_tool` do I/O via `server` but are total (never raise) w.r.t. their caller.

### Deviations from Design

None. Implementation matches design.md's "Interfaces / Contracts" section:
- `Family = namedtuple("Family", "name search_tool search_args_fn detail_tool")` — verbatim field order.
- `run_family(server, id_gen, family) -> (verdict, lines)`, verdict in `{"pass","warning","fail"}`, catches `StepFailed` internally → `("fail", [reason])` — verbatim, plus the same internal-catch treatment extended to the Outlook-unavailable-hint case via `_FamilyWarning` (not explicitly named in design's sketch, but required by the "Per-Family Verdict Classification" spec table's WARN row, and necessarily internal-only since `_FamilyWarning` is never re-raised past `run_family`).
- `aggregate_verdict(results: dict[str, str]) -> str` — implemented exactly as a dict-keyed-by-family-name → verdict-string input (matching design's typed contract; the spec's own scenario prose uses list literals like `[PASS, WARN, FAIL]` purely as shorthand for the *values*, which is what the dict-based tests exercise via `.values()`).
- `calendar_get_event` (not `calendar_get_notes`) is the calendar family's detail tool, per design's explicit "Calendar detail tool" decision.
- Empty search result → `"pass"`, no chain call — per design's "Empty search result" decision.
- `itertools.count(1)` shared across all calls (handshake + every family's search/detail calls) — per design's "JSON-RPC ids" decision; confirmed by manual end-to-end run (ids 1-11 observed, monotonically increasing, no collisions, across `initialize`/`tools/list`/8 family tool calls).
- Handshake `StepFailed` aborts the run before any family runs; a family's own `StepFailed`/hint-error is caught inside `run_family` and does not abort the loop — per design's "Handshake vs. family failure" decision.
- `TOTAL_STEPS = 3 + len(FAMILIES)` — verbatim.

### Issues Found

None blocking. One documentation-only observation for `sdd-verify`: the smoke-test-coverage spec's own scenario prose for `aggregate_verdict` writes `family_results` as bracketed lists (e.g. `[PASS, WARN, FAIL]`), while design.md's "Interfaces / Contracts" section types the same parameter as `dict[str, str]`. This batch followed design.md's typed contract (a dict keyed by family name), since it is the more precise/authoritative source for the actual call signature, and the spec's list notation reads as shorthand for "the collection of verdict values" rather than a literal list-argument requirement — `aggregate_verdict`'s truth-table semantics (any fail → FAIL; elif any warning → WARN; else PASS) are identical either way. No behavior is affected; flagging only in case `sdd-verify` wants the spec's prose reworded for precision.

### Constraints Honored

- `deploy/smoke_test.py` remains stdlib-only — confirmed via `grep -n "^import\|^from" deploy/smoke_test.py`: `argparse`, `itertools`, `json`, `os`, `queue`, `subprocess`, `sys`, `threading`, `time`, `collections.namedtuple`, `datetime.datetime` — no third-party imports.
- `tests/test_smoke_test.py` uses only stub/duck-typed server objects (`StubServer`, an in-file class implementing `.send()`/`.read_line()`) for all `run_family`/`do_tools_list` tests — zero `subprocess`, zero `win32com`, zero real process spawn. The one test that imports `server.py` (`test_expected_tools_matches_server_registered_names`) uses the existing `FakeCalendarAdapter`/`FakeTaskAdapter`/`FakeMailAdapter` injection seam (already proven safe on Linux by the pre-existing `tests/test_server.py` suite) — no win32com import at collection or run time.
- The 3 verdict strings (`SMOKE TEST PASSED`, `SMOKE TEST PASSED WITH WARNINGS`, `SMOKE TEST FAILED`) survive byte-identical — confirmed by `aggregate_verdict`'s return values matching the pre-existing strings exactly, and by the manual end-to-end run below printing `SMOKE TEST PASSED WITH WARNINGS` verbatim.
- No file outside `deploy/smoke_test.py`/`tests/test_smoke_test.py`/`openspec/changes/qa-pro-deploy-pipeline/tasks.md` was touched this batch — `deploy-qa.sh`/`promote-pro.sh` (Phases 4-5), `dist/deploy.sh`/`README.md` (Phase 6), and `make-deploy-package.sh` (Phase 7, no-change per design) are all explicitly out of scope for this batch.
- No `pip install` was run.

### Manual Verification (confidence check, not a substitute for Phase 8's real Windows/Outlook run)

Ran the rewritten script against the real `server.py` on this Linux dev host (`win32com` genuinely absent, so all 4 families are expected to WARN, not PASS or FAIL):

```
.venv/bin/python3.12 deploy/smoke_test.py --command "/home/master/WinMCP/.venv/bin/python3.12 /home/master/WinMCP/server.py"
```

Output (abridged): `[1/7]` through `[7/7]` steps ran in order (initialize → notifications/initialized → tools/list, listing all 7 real tool names → 4 family steps, each `WARNING` with `Outlook/COM is not available right now: [outlook_unavailable] win32com is not available on this platform`), followed by:

```
  calendar: WARNING
  tasks: WARNING
  mail-inbox: WARNING
  mail-sent: WARNING
SMOKE TEST PASSED WITH WARNINGS
```

Confirms: dynamic `TOTAL_STEPS` (7, matches `3 + 4 families`), real `tools/list` returning all 7 registered names, all 4 families independently reaching `run_family`/`_call_tool` and correctly classifying the real `[outlook_unavailable]`-tagged `ToolError` as WARN (not FAIL), `format_summary()`'s one-line-per-family + final-verdict-last shape, and the exact verbatim verdict string.

### Test Results — full suite (Batch 1)

- **Full suite**: `.venv/bin/python3.12 -m pytest -q` → **152 passed** (0 failed, 0 skipped). Baseline at batch start: 139/139. Net delta: +13 tests, zero regressions.

### Remaining Tasks (for Batch 2: Phase 4-5, and Batch 3: Phases 6-8)

- [ ] 4.1 Write `deploy-qa.sh` (root): zip arg or newest `dist/WinMCP-*.zip`; wipe `/mnt/c/usr/WinMCP-qa`; extract via `mktemp -d`, `mv .../WinMCP/`→`WinMCP-qa`; `cmd.exe /c install.bat </dev/null`; write `QA-VALIDATED.txt`; print `test.bat` instruction; `set -euo pipefail`; UNC-cwd warning ≠ failure
- [ ] 4.2 Script-gate: `bash -n deploy-qa.sh`; `shellcheck` if installed
- [ ] 5.1 Write `promote-pro.sh` (root): zip arg or `QA-VALIDATED.txt`'s (refuse sha256 mismatch unless `--force`); `Get-CimInstance` PRO lock gate; wipe `wheels/`, `unzip -o` onto `C:\usr\WinMCP`; `cmd.exe /c install.bat </dev/null`; copy zip → OneDrive `_OUT`; write `DEPLOYED.txt`; print restart reminder; `set -euo pipefail`; UNC-cwd warning ≠ failure
- [ ] 5.2 Script-gate: `bash -n promote-pro.sh`; `shellcheck` if installed
- [ ] 6.1 Delete `dist/deploy.sh`
- [ ] 6.2 Update `README.md`: replace `dist/deploy.sh` narrative with `deploy-qa.sh`→`test.bat`→`promote-pro.sh`; document PRO lock gate + `QA-VALIDATED.txt`/`DEPLOYED.txt` markers
- [ ] 7.1 Run full suite — final gate before packaging
- [ ] 7.2 Run `./make-deploy-package.sh` end-to-end — rebuild `dist/WinMCP-<date>.zip` with the new `smoke_test.py` staged
- [ ] 8.1-8.3 [MANUAL — requires user on Windows host] `deploy-qa.sh` → `test.bat` → `promote-pro.sh` (twice: lock refused, then promoted)

### Status (Cumulative — as of Batch 1)

13/13 subtasks in Phases 1-3 batch scope complete. Full suite green (152/152). Ready for Batch 2 (Phases 4-5 — `deploy-qa.sh`/`promote-pro.sh` script-gate work, no pytest involved).

## Batch 2 of 3 — Phases 4, 5 (COMPLETE)

Mode: **Standard** (not Strict TDD). `openspec/config.yaml` sets `strict_tdd: true` project-wide, but Phases 4-5 are ops/infra bash scripts with no pytest layer — design.md's own Testing Strategy table lists them under "Script-gate: `bash -n` (+ `shellcheck` if available)", not TDD. No RED/GREEN/REFACTOR cycle applies; standard write-then-verify was used instead. Full pytest suite re-run at the end purely to confirm zero regressions (scripts don't touch Python).

### Completed Tasks

- [x] 4.1 Wrote `deploy-qa.sh` (repo root)
- [x] 4.2 Script-gate: `bash -n deploy-qa.sh` passed; `shellcheck` not installed on this host (confirmed via `which shellcheck` → not found; per task instructions, recorded absence, not installed)
- [x] 5.1 Wrote `promote-pro.sh` (repo root)
- [x] 5.2 Script-gate: `bash -n promote-pro.sh` passed; `shellcheck` not installed (same as above)

### Files Created / Modified

| File | Action | What Was Done |
|------|--------|----------------|
| `deploy-qa.sh` | Created | Root bash script, `set -euo pipefail`. Resolves zip from `$1` or newest `dist/WinMCP-*.zip` by mtime (`ls -1t`, matching `dist/deploy.sh`'s existing idiom). Fully wipes `/mnt/c/usr/WinMCP-qa` via `rm -rf`. Extracts to a scratch dir colocated with `QA_ROOT` via `mktemp -d "$(dirname "$QA_ROOT")/.winmcp-qa-extract.XXXXXX"` (same filesystem as the target, so the final `mv` is a rename, not a cross-device copy), verifies `$SCRATCH/WinMCP` exists (fails clearly on an unexpected zip layout instead of silently mis-nesting), then `mv`s it to `WinMCP-qa`. Runs `cmd.exe /c "C:\usr\WinMCP-qa\install.bat" < /dev/null` (stdin redirect present and load-bearing — `install.ps1`'s trailing `Read-Host "Press Enter to exit"` would otherwise hang forever), checked via `if ! cmd.exe ...; then fail; fi` so only the installer's own exit code decides success — the cosmetic UNC-cwd warning cmd.exe prints (WSL invokes it with a `\\wsl$\...` UNC cwd) never touches `$?` and is never grepped for, so it can never be misclassified as a failure. Writes `QA-VALIDATED.txt` (`zip:`/`sha256:`/`validated_utc:` lines, sha256 of the zip file itself via `sha256sum`, UTC via `date -u +%Y-%m-%dT%H:%M:%SZ`). Never references `/mnt/c/usr/WinMCP` (PRO) or any Claude Desktop config path. Ends by printing the `test.bat` manual-validation instruction naming the exact family lines + verdict strings to look for. |
| `promote-pro.sh` | Created | Root bash script, `set -euo pipefail`. Parses `$@` for an optional zip path and an optional `--force` flag (either order). Requires `/mnt/c/usr/WinMCP-qa/QA-VALIDATED.txt` to exist (refuses promotion with no QA run at all). Resolves the zip: explicit arg, else `dist/<marker's zip name>`. Computes the resolved zip's sha256 and **always** compares it to the marker's recorded sha256 (not just on the default path — catches drift if the on-disk `dist/` zip changed after QA validated it); mismatch refuses with a clear message unless `--force` (which only overrides the sha256 gate, explicitly documented in-script as NOT overriding the process lock gate). HARD lock gate: `powershell.exe -NoProfile -NonInteractive -Command` running a `Get-CimInstance Win32_Process \| Where-Object { $_.ExecutablePath -like "..." } \| Select-Object -ExpandProperty ProcessId` query for `C:\usr\WinMCP\.venv\*`; the PowerShell call's own exit code is checked separately from whether it returned any PIDs (`grep -E '^[0-9]+$'` isolates real numeric PIDs from any incidental stderr/warning text merged via `2>&1`), and any match refuses promotion naming the PIDs and telling the user to quit Claude Desktop — this gate is unconditional, `--force` does not bypass it. On a clean gate: `rm -rf` PRO's `wheels/`, `unzip -q -o` onto `/mnt/c/usr` (matches `dist/deploy.sh`'s exact proven semantics — zip's `WinMCP/` folder lands on `C:\usr\WinMCP`, preserving `.venv`), then the same non-interactive `cmd.exe /c "...\install.bat" < /dev/null` pattern (and same UNC-warning tolerance) as `deploy-qa.sh`. Copies the zip to `/mnt/c/co/od/_DEV/WinMCP/_OUT` (same `DEST` as the old `dist/deploy.sh`). Writes `DEPLOYED.txt` in PRO (`zip:`/`sha256:`/`deployed_utc:`, same schema as `QA-VALIDATED.txt` per design). Ends with a restart-Claude-Desktop reminder. |
| `openspec/changes/qa-pro-deploy-pipeline/tasks.md` | Modified | Marked 4.1, 4.2, 5.1, 5.2 complete. |

### Bug Found and Fixed During Verification

While unit-exercising the lock-gate's PowerShell query in isolation (read-only `Get-CimInstance` call, no `/mnt/c` mutation, no `cmd.exe` invocation — permitted by the batch's script-gate constraints), discovered the first draft was **broken**: `PS_QUERY` was assigned with single quotes in bash (`PS_QUERY='...C:\\usr\\WinMCP\\.venv\\*...'`), so bash passes the literal double backslashes straight through to PowerShell unchanged (single-quoted bash strings do zero interpretation). PowerShell's `-like` operator does **not** treat `\` as an escape character in double-quoted strings (that's a bare literal Windows path separator, not a regex/escape token) — so a `-like` pattern containing `\\` requires a literal double backslash in the target string, which real Windows `ExecutablePath` values never have (they use single backslashes). Confirmed the failure directly against this host's real `powershell.exe`: the buggy double-backslash query returned **empty** against this real host's actual running `C:\usr\WinMCP\.venv\python.exe` processes (PIDs 34252, 37124 were live on this host at verification time), while the corrected single-backslash version (`"C:\usr\WinMCP\.venv\*"`, unmodified by bash since the whole `PS_QUERY` is single-quoted) correctly returned both PIDs. Fixed in place before finishing the batch; a comment now explains why the string carries single backslashes despite being assigned in a shell context. This was a real safety gap — the buggy version would have silently let `promote-pro.sh` proceed against a live PRO process.

### Deviations from Design

None functionally. Two implementation choices not spelled out verbatim in design.md, both consistent with its stated intent:
- **Scratch dir location**: design says "extract via `mktemp -d`" without specifying where; this batch places the scratch dir as a hidden sibling of `QA_ROOT` (`$(dirname "$QA_ROOT")/.winmcp-qa-extract.XXXXXX`, i.e. under `/mnt/c/usr/`) rather than the default `/tmp`, so the final `mv` is a same-filesystem rename instead of a cross-device copy+delete. Functionally equivalent either way (GNU `mv` handles cross-device automatically), just faster and more clearly atomic.
- **sha256 comparison always runs** in `promote-pro.sh`, even when no explicit zip arg is given (i.e., resolving straight from the marker). Design/tasks only explicitly require checking on a passed argument ("refuse sha256 mismatch unless `--force`"), but always checking is strictly safer (catches the `dist/` zip having been overwritten or deleted-and-rebuilt after QA validated it) and costs one cheap `sha256sum` call.

### Issues Found

None blocking. Flagging for `sdd-verify`: this host's real `powershell.exe`/`cmd.exe` interop from WSL2 is genuinely live (see the bug-fix section above — real PRO `python.exe` processes were observed running under `C:\usr\WinMCP\.venv` during verification), so this appears to be an active production-adjacent machine, not an isolated sandbox. Per the batch's explicit scope limits, no mutating command was run against `/mnt/c` and `cmd.exe` was never invoked — only a read-only `Get-CimInstance` query (via `powershell.exe`) was exercised in isolation, twice, to validate and then prove the fix for the bug above. Phase 8's manual runs should be aware PRO is currently live and Claude Desktop likely needs to be quit before any real `promote-pro.sh` run is attempted.

### Constraints Honored

- `dist/deploy.sh` left untouched (its deletion is Phase 6, out of scope for this batch).
- No `/mnt/c` mutation performed: `deploy-qa.sh`/`promote-pro.sh` were verified via `bash -n` and by reading, never executed end-to-end; the only live command run against the real Windows host was the isolated, read-only `Get-CimInstance` query (no `cmd.exe`, no writes).
- No README changes (Phase 6).
- No package rebuild (Phase 7).
- `shellcheck` absence recorded, not installed.
- Both scripts made executable (`chmod +x`).

### Test Results — full suite (Batch 2)

- **Full suite**: `.venv/bin/python3.12 -m pytest -q` → **152 passed** (0 failed, 0 skipped) — identical to Batch 1's end state. Zero regressions; expected, since no Python file was touched this batch.
- **Script gate**: `bash -n deploy-qa.sh` → OK. `bash -n promote-pro.sh` → OK. `shellcheck` → not installed, skipped per instructions.

### Remaining Tasks (for Batch 3: Phases 6-8)

- [ ] 6.1 Delete `dist/deploy.sh`
- [ ] 6.2 Update `README.md`: replace `dist/deploy.sh` narrative with `deploy-qa.sh`→`test.bat`→`promote-pro.sh`; document PRO lock gate + `QA-VALIDATED.txt`/`DEPLOYED.txt` markers
- [ ] 7.1 Run full suite — final gate before packaging
- [ ] 7.2 Run `./make-deploy-package.sh` end-to-end — rebuild `dist/WinMCP-<date>.zip` with the new `smoke_test.py` staged
- [ ] 8.1-8.3 [MANUAL — requires user on Windows host] `deploy-qa.sh` → `test.bat` → `promote-pro.sh` (twice: lock refused, then promoted) — NOTE: PRO is currently live (see Issues Found above); user should quit Claude Desktop before attempting a real `promote-pro.sh` run.

### Status (Cumulative — as of Batch 2)

17/17 subtasks in Phases 1-5 batch scope complete (13 from Batch 1 + 4 from Batch 2). Full suite green (152/152). Both new scripts pass `bash -n`; `shellcheck` unavailable on this host. Ready for Batch 3 (Phases 6-8: legacy removal, README, final full-suite + package rebuild gate, then manual Windows verification).

## Batch 3 of 3 — Phases 6, 7 (COMPLETE); Phase 8 left unchecked (manual, not this agent's scope)

Mode: **Standard** (not Strict TDD). No new Python logic this batch — legacy-script removal, docs, a full-suite gate run, and an end-to-end package rebuild. TDD tasks were already completed in Batches 1-2; this batch's "gate" is the full pytest suite plus `make-deploy-package.sh`'s own gates.

### Completed Tasks

- [x] 6.1 Deleted `dist/deploy.sh`
- [x] 6.2 Updated `README.md`: added a new "Deploying from this dev machine (QA → PRO)" section
- [x] 7.1 Ran full pytest suite — 152/152 green, zero regressions
- [x] 7.2 Ran `./make-deploy-package.sh` end-to-end — all gates passed, zip rebuilt

### Files Created / Modified

| File | Action | What Was Done |
|------|--------|----------------|
| `dist/deploy.sh` | Deleted | Superseded by `deploy-qa.sh` + `promote-pro.sh`. |
| `README.md` | Modified | Added a new `## Deploying from this dev machine (QA → PRO)` section (after "Building the package") covering: build via `make-deploy-package.sh` → `deploy-qa.sh` (newest-`dist/WinMCP-*.zip`-by-mtime resolution, disposable `C:\usr\WinMCP-qa` sandbox, `QA-VALIDATED.txt` marker) → the manual `test.bat` gate (now covering all 4 tool families — calendar/tasks/mail-inbox/mail-sent — with the 3 verdict strings explained) → `promote-pro.sh` (quit Claude Desktop first because the PRO lock gate unconditionally refuses otherwise; sha256-vs-`QA-VALIDATED.txt` check, `--force` overrides only that check, never the lock gate; wipes `wheels/`, `unzip -o` onto `C:\usr\WinMCP` preserving `.venv`; copies zip to OneDrive `_OUT`; writes `DEPLOYED.txt`) → restart Claude Desktop reminder, with an explicit note that `claude_desktop_config.json` never changes across this flow. Also documented rollback (`./promote-pro.sh dist/WinMCP-<older-date>.zip --force`, since an older zip's sha256 won't match the current `QA-VALIDATED.txt`). **Note**: unlike what task 6.2's wording implies, the *existing* README had no `dist/deploy.sh` narrative to replace — that script was undocumented/dev-internal (only "Building the package" and "Install (on the Windows host)" existed, both about the zip itself, not how a dev pushes it to `C:\usr`). This batch therefore *added* the QA→PRO section as new content rather than rewriting an existing one; the "Install (on the Windows host)" third-party instructions were left completely untouched, per the batch's binding item 2. Grepped the repo for other `deploy.sh`/`dist/deploy` references: only `promote-pro.sh`'s own comment (`"Same mechanics as the retired dist/deploy.sh..."`), which was already written in Batch 2 in the correct past-tense/retired form — no update needed. |
| `openspec/changes/qa-pro-deploy-pipeline/tasks.md` | Modified | Marked 6.1, 6.2, 7.1, 7.2 complete. Phase 8 (8.1-8.3) left unchecked — manual, out of this batch's scope. |

### Test Results — full suite (Batch 3, task 7.1)

- **Full suite**: `.venv/bin/python3.12 -m pytest -q` → **152 passed** (0 failed, 0 skipped). Identical to Batch 1/2's end state — zero regressions, confirming Phases 4-6 (bash scripts + README + deletion) touched no Python.

### Package Rebuild Results (task 7.2)

Ran `./make-deploy-package.sh` end-to-end (build id `20260824`). All gates passed:

| Gate | Result |
|------|--------|
| Gate 1 (manifest files + launcher sources exist) | PASS |
| Gate 2 (full test suite) | PASS — 152 passed (rerun inside the script, matches 7.1) |
| Gate 3 (no module-level `win32com` import) | PASS |
| Gate 4 (launcher scripts pure ASCII) | PASS |
| Gate 4b (no unescaped parens in `.bat` echo lines) | PASS |
| Gate 5 (`install.ps1` parses cleanly via portable pwsh) | PASS |
| Gate 6 (every resolved win312+win313 requirement has a staged wheel; `pywin32-ctypes`/`colorama`/`setuptools`/`wheel` bootstrap wheels present; 79 wheel files staged) | PASS |

Result:
- **Zip**: `dist/WinMCP-20260824.zip`
- **Size**: 32,365,034 bytes (~30.9 MiB)
- **sha256**: `c9f1225eb0cd38f1cdc5d1cbbcefdba49e0b667a7953e801a0154afaaeb150f8`
- **104 files staged**, 32,962,127 bytes uncompressed per the script's own `unzip -l` summary.

**Overwrite note**: this rebuild overwrote today's *existing* `dist/WinMCP-20260824.zip` (previously built earlier today for the unrelated mail change, 32,360,542 bytes). This is expected per the batch instructions — the new zip is a strict superset (same mail-change content plus the new family-driven `deploy/smoke_test.py`) and the old bytes are not otherwise referenced by name anywhere in the repo. `dist/WinMCP-20260731.zip` and `dist/WinMCP-20260729.zip` are untouched, still present as older fallbacks for rollback.

**Verification**:
- `unzip -l dist/WinMCP-20260824.zip | grep -i smoke_test` → `WinMCP/smoke_test.py`, 20505 bytes — byte-identical in size to `deploy/smoke_test.py` (`wc -c` also reports 20505), confirming the *new* family-driven smoke test (verified present: `FAMILIES`, `run_family`, `aggregate_verdict` all appear in it) is what's staged, not a stale copy.
- `unzip -l dist/WinMCP-20260824.zip | grep -iE "fake_|Fake[A-Z]"` → no matches (exit code 1) — confirms fake adapters are still correctly excluded from the package, unchanged from prior builds.

### Zip-Resolution Check (task 5 of the launch instructions — verification only, `deploy-qa.sh` NOT executed)

`deploy-qa.sh`'s resolution logic (line 26): `ls -1t "$DIST"/WinMCP-*.zip 2>/dev/null | head -1`. Ran the identical command by hand against the real `dist/` contents post-rebuild:

```
$ ls -1t dist/WinMCP-*.zip
dist/WinMCP-20260824.zip   <- newest mtime (13:41, just rebuilt)
dist/WinMCP-20260731.zip
dist/WinMCP-20260729.zip
```

`head -1` picks `WinMCP-20260824.zip` — the just-rebuilt zip containing the new `smoke_test.py`. The glob correctly matches all three zips in `dist/`, and `-t` (mtime, newest-first) correctly ranks the rebuild ahead of the two older files despite them all sharing the `WinMCP-*.zip` pattern and two of them having an earlier date embedded in the filename than "today". Confirmed correct with zero risk — no execution of `deploy-qa.sh` itself, no `/mnt/c` access, per the batch's explicit "do NOT run the script" instruction.

### Deviations from Design

None functionally. One clarification: design.md's File Changes table says `README.md` — "Replace install/deploy narrative with QA→PRO flow." As noted above, no existing `dist/deploy.sh`-specific narrative existed to replace (that script was never documented for end users or even for the dev workflow) — the "Install (on the Windows host)" section is about a third party installing a handed-off zip, not this dev machine's push-to-`C:\usr` flow. This batch interpreted the intent as adding the missing QA→PRO section rather than rewriting nonexistent content, per the launch instructions' own item 2 phrasing ("rewrite the deployment docs around the QA→PRO flow") and its explicit instruction to keep the third-party install-from-zip instructions intact.

### Issues Found

None blocking. Two non-blocking observations for `sdd-verify`/Phase 8:
1. Today's `dist/WinMCP-20260824.zip` was overwritten by this rebuild (see Overwrite note above) — flagging in case anything outside this change's scope expected today's earlier zip's exact bytes/sha256 to remain unchanged (e.g. an already-completed manual QA/PRO cycle for the unrelated mail change that hasn't yet been promoted). The new zip is a superset, so re-running that other change's QA/promote flow against the new zip should behave identically or better.
2. Per Batch 2's own flagged observation, PRO was live on this host during Batch 2's verification (real `python.exe` PIDs observed under `C:\usr\WinMCP\.venv`). This batch did not re-check PRO's live/quit state (no `/mnt/c` access was made this batch beyond nothing at all — this batch never touched `/mnt/c`). Phase 8's manual `promote-pro.sh` run should still expect to need Claude Desktop quit first, consistent with Batch 2's note.

### Constraints Honored

- Only `dist/deploy.sh` (deleted), `README.md` (docs section added), `openspec/changes/qa-pro-deploy-pipeline/tasks.md` (checkboxes), and this apply-progress file were touched for tasks 6.1/6.2. Task 7.2's rebuild additionally produced/overwrote `dist/WinMCP-20260824.zip` and its `.sha256`/`unzip -l` output as printed to stdout (the script itself doesn't write a separate `.sha256` file to disk — the design's marker files, `QA-VALIDATED.txt`/`DEPLOYED.txt`, are written by `deploy-qa.sh`/`promote-pro.sh` at runtime, not by `make-deploy-package.sh`).
- `deploy-qa.sh` and `promote-pro.sh` were NOT executed — only their zip-resolution logic was read and hand-verified against `dist/`'s real contents, per the batch's explicit scope limit.
- No `/mnt/c` access, no `cmd.exe`/`powershell.exe` invocation this batch.
- Phase 8's 3 manual tasks left unchecked in `tasks.md`, as instructed.

### Status (Cumulative — as of Batch 3, FINAL for this agent's scope)

22/25 subtasks in Phases 1-7 complete (13 from Batch 1 + 4 from Batch 2 + 4 from Batch 3 [6.1, 6.2, 7.1, 7.2] + the 5 already-complete Phase 4-5 subtasks counted once — i.e. all of Phases 1-7's 22 subtasks are done). Full suite green (152/152, zero regressions across all 3 batches). Package rebuilt end-to-end with all 6 gates passing; `dist/WinMCP-20260824.zip` (sha256 `c9f1225eb0cd38f1cdc5d1cbbcefdba49e0b667a7953e801a0154afaaeb150f8`) contains the new family-driven `smoke_test.py` and still excludes fake adapters. Only Phase 8 (3 manual tasks, requires a human on the Windows host with Outlook) remains — **not in this agent's scope**. Ready for hand-off to the user for manual verification, then `sdd-verify`/`sdd-archive`.

## Phase 8 — Manual Verification (COMPLETE, executed by orchestrator per user's autonomy directive, 2026-08-24)

- 8.1 `./deploy-qa.sh` run twice (pre- and post-hotfix zips): clean from-scratch `C:\usr\WinMCP-qa` install both times, installer non-interactive via cmd.exe with stdin redirect (UNC warning cosmetic as designed), `QA-VALIDATED.txt` written, PRO untouched.
- 8.2 Validation run via `C:\usr\WinMCP-qa\.venv\Scripts\python.exe smoke_test.py` (same entry as test.bat): first run **SMOKE TEST PASSED** (calendar 1 hit + chained get_event; tasks 25 hits + chained get_task; mail-inbox 21 hits + chained get_message; mail-sent 0 hits = pass-no-chain). Final post-hotfix run **SMOKE TEST PASSED** with mail-sent at 6 hits + chained detail — all chain paths exercised live. Verdict reported to and acknowledged by the user.
- 8.3 `./promote-pro.sh` refusal path: with Claude Desktop open it refused, printed live PIDs (34252, 37124) and the quit-Claude message, exit code 1 (verified). Promotion path: with Claude Desktop closed it promoted, preserved `.venv`, wrote `DEPLOYED.txt` (zip + sha256 + UTC date), copied the blessed zip to the OneDrive `_OUT` folder, printed the restart reminder. Post-promote smoke against PRO: **SMOKE TEST PASSED** (4/4 families).

Note: the first post-promote validation (pre-hotfix zip) returned PASSED WITH WARNINGS and exposed the latent per-thread `CoInitialize` bug — fixed in the follow-up change `com-coinitialize-hotfix` and re-promoted the same day. This is the new smoke test doing exactly its job.

## Post-verify remediation

Closes the verify-report's WARNING (initialize-failure short-circuit had no
dedicated automated test) and both SUGGESTIONs (spec wording).

- Added `test_main_fails_before_any_family_step_when_initialize_errors` to
  `tests/test_smoke_test.py`. It monkeypatches `smoke_test.ServerProcess` so
  `main()` itself runs against a `StubServer` (extended with no-op
  `close()`/`stderr_tail()` via a new `_StubServerWithLifecycle` subclass)
  instead of spawning a real subprocess, scripts an `initialize` JSON-RPC
  error, and asserts both `main()`'s exit code is `1` and that no
  `tools/call` for any family search tool (`calendar_search` etc.) was ever
  sent — directly exercising the `deploy/smoke_test.py:518-546`
  try/except-`StepFailed` short-circuit that was previously only
  code-inspection-verified.
- RED confirmed by temporarily disabling the `return 1` after
  `print("SMOKE TEST FAILED")` in `main()`'s except block (production code,
  reverted immediately after) — the test then failed with a `KeyError`
  inside the stub as `calendar_search` was actually invoked, proving the
  short-circuit is genuinely exercised. GREEN confirmed after revert.
- Reworded `openspec/changes/qa-pro-deploy-pipeline/specs/smoke-test-coverage/spec.md`:
  (a) the `aggregate_verdict` requirement/scenarios now describe
  `family_results` as a dict of family name -> verdict value, matching
  `design.md`'s `dict[str, str]` contract, instead of bracketed list
  literals; (b) the "Empty search result passes without chaining" scenario
  no longer bundles the initialize-failure claim — that claim is now its
  own "Initialize failure short-circuits all families" scenario, backed by
  the new test above.
- No production code changes. Full suite: 165 passed (161 baseline + 4 —
  this test plus 3 unrelated tests added for the `com-coinitialize-hotfix`
  remediation the same session), zero regressions.
