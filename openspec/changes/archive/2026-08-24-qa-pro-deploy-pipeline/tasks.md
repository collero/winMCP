# Tasks: QA→PRO Deployment Pipeline with Manual Validation Gate

## Phase 1: Aggregate Verdict Logic (Strict TDD)

- [x] 1.1 RED `tests/test_smoke_test.py`: `aggregate_verdict` truth table — all-PASS, WARN-degrades (no FAIL), FAIL-wins-over-WARN, mixed combos
- [x] 1.2 GREEN `deploy/smoke_test.py`: add pure `aggregate_verdict(family_results)` per spec table; keep the 3 verdict strings verbatim

## Phase 2: run_family Helper (Strict TDD, stub server)

- [x] 2.1 RED `tests/test_smoke_test.py`: stub-server class (`.send`/`.read_line`, in-file) — search hit chains matching detail call on `entryId` → PASS
- [x] 2.2 RED `::` empty search result → PASS, no chain call, "no items to chain" note
- [x] 2.3 RED `::` `OUTLOOK_UNAVAILABLE_HINTS`-matching error → WARN; other tools/call error → FAIL
- [x] 2.4 RED `::` family's `StepFailed` caught inside `run_family`, returns `("fail", [reason])`, doesn't propagate
- [x] 2.5 GREEN `deploy/smoke_test.py`: `Family` namedtuple, `run_family(server, id_gen, family)` — search+chain+classify, reuses `OUTLOOK_UNAVAILABLE_HINTS`

## Phase 3: Family Table, EXPECTED_TOOLS, tools/list Validation

- [x] 3.1 RED `::test_expected_tools_matches_server_registered_names` — static 7-name set vs `server.py` names (fake adapters)
- [x] 3.2 RED `::test_tools_list_missing_tool_fails_naming_it` — stub `tools/list` omits `mail_get_message` → fails, names it
- [x] 3.3 GREEN `deploy/smoke_test.py`: `EXPECTED_TOOLS`=7 names; `FAMILIES` table (calendar/tasks/mail-inbox/mail-sent); `TOTAL_STEPS=3+len(FAMILIES)`; `main()` loops `FAMILIES` via `run_family`+`aggregate_verdict`, drops `do_calendar_search`
- [x] 3.4 RED `::test_format_summary_one_line_per_family_and_final_verdict` — pure `format_summary(family_results, overall)`
- [x] 3.5 GREEN `deploy/smoke_test.py`: wire `format_summary()` into `main()`'s print block

## Phase 4: deploy-qa.sh (Script-Gate)

- [x] 4.1 Write `deploy-qa.sh` (root): zip arg or newest `dist/WinMCP-*.zip`; wipe `/mnt/c/usr/WinMCP-qa`; extract via `mktemp -d`, `mv .../WinMCP/`→`WinMCP-qa`; `cmd.exe /c install.bat </dev/null`; write `QA-VALIDATED.txt` (zip/sha256/`validated_utc`); print `test.bat` instruction; `set -euo pipefail`; UNC-cwd warning ≠ failure
- [x] 4.2 Script-gate: `bash -n deploy-qa.sh`; `shellcheck` if installed

## Phase 5: promote-pro.sh (Script-Gate)

- [x] 5.1 Write `promote-pro.sh` (root): zip arg or `QA-VALIDATED.txt`'s (refuse sha256 mismatch unless `--force`); `Get-CimInstance` gate on `C:\usr\WinMCP\.venv\*` python.exe, refuse if present; wipe `wheels/`, `unzip -o` onto `C:\usr\WinMCP` (preserves `.venv`); `cmd.exe /c install.bat </dev/null`; copy zip → `/mnt/c/co/od/_DEV/WinMCP/_OUT`; write `DEPLOYED.txt`; print restart reminder; `set -euo pipefail`; UNC-cwd warning ≠ failure
- [x] 5.2 Script-gate: `bash -n promote-pro.sh`; `shellcheck` if installed

## Phase 6: Legacy Removal & Docs

- [x] 6.1 Delete `dist/deploy.sh`
- [x] 6.2 Update `README.md`: replace `dist/deploy.sh` narrative with `deploy-qa.sh`→`test.bat`→`promote-pro.sh`; document the PRO lock gate and `QA-VALIDATED.txt`/`DEPLOYED.txt` markers

## Phase 7: Full Suite & Package Rebuild (Final Gate)

- [x] 7.1 Run `.venv/bin/python3.12 -m pytest -q` — full suite green (139 baseline + new `test_smoke_test.py` cases); fix regressions
- [x] 7.2 Run `./make-deploy-package.sh` end-to-end — gate 2 reruns tests; rebuilds `dist/WinMCP-<date>.zip` with the new `smoke_test.py` staged, so Phase 8's QA deploy tests the NEW smoke test

## Phase 8: Manual Verification (closes change)

- [x] 8.1 [MANUAL — requires user on Windows host] Run `deploy-qa.sh` on the zip rebuilt in 7.2; confirm clean `WinMCP-qa` install, `QA-VALIDATED.txt` written, PRO untouched
- [x] 8.2 [MANUAL — requires user on Windows host] User double-clicks `test.bat` in `C:\usr\WinMCP-qa`, reports the 4 family lines + final verdict
- [x] 8.3 [MANUAL — requires user on Windows host] Run `promote-pro.sh` twice: PRO `python.exe` live → confirm refusal; then closed → confirm promotion, `.venv` preserved, `DEPLOYED.txt`+OneDrive copy written, restart reminder printed
