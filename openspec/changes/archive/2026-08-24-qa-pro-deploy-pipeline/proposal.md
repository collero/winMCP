# Proposal: QA→PRO Deployment Pipeline with Manual Validation Gate

## Intent

`dist/deploy.sh` ships straight to the live PRO install with no
validation step. `smoke_test.py` only exercises calendar (stale
`EXPECTED_TOOLS`: 3 names, server registers 7), so a broken mail/task
path reaches Claude Desktop undetected. Add a QA stage a human validates
before promoting the same zip to PRO; cover all 4 tool families.

## Scope

### In Scope
- Extend `deploy/smoke_test.py`: calendar_search, task_search,
  mail_search (inbox+sent), chained detail calls off first hit;
  per-family PASS/WARN/FAIL; fix `EXPECTED_TOOLS`; pure
  `aggregate_verdict()` + search-and-chain helper, unit-tested in
  `tests/test_smoke_test.py` (stdlib, Linux-runnable)
- New `deploy-qa.sh`: wipe+install latest zip to `C:\usr\WinMCP-qa`
  (stdin redirected), print manual-verification instructions; no auto-promote
- New `promote-pro.sh`: gate on a live PRO `python.exe`; install to
  `C:\usr\WinMCP`, copy zip to OneDrive `_OUT`, write `DEPLOYED.txt`
- Delete `dist/deploy.sh`; rewrite `README.md` deploy section
- Verify `make-deploy-package.sh` gates 1/2/4 stay green

### Out of Scope
- Automating the manual validation step
- Touching Claude Desktop's config (stays pointed at `WinMCP.bat`) or
  `.bat` launcher files

## Capabilities

### New
- `smoke-test-coverage`: 4-family coverage, per-family verdicts, fixed
  `EXPECTED_TOOLS`, pure aggregation logic
- `qa-pro-deploy-workflow`: `deploy-qa.sh`/`promote-pro.sh`, PRO lock gate

### Modified
None.

## Approach

Verdict/chain logic is unit-tested on this Linux host first (duck-typed,
no win32com), then wired to live calls (strict TDD; Windows-runtime,
Linux-dev). Deploy scripts reuse the WSL2 `cmd.exe`/`powershell.exe`
bridge from `dist/deploy.sh`/`install.bat`, split QA (sandboxed) from PRO
(locked).

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `deploy/smoke_test.py` | Modified | 4-family coverage, verdict refactor |
| `tests/test_smoke_test.py` | New | Unit tests |
| `deploy-qa.sh` (root) | New | QA install |
| `promote-pro.sh` (root) | New | Locked PRO promotion |
| `dist/deploy.sh` | Removed | Superseded by QA gate |
| `README.md` | Modified | Deploy docs rewritten |
| `make-deploy-package.sh` | Verified | Gates 1/2/4 unaffected |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Verdict regression hides install breakage | Med | Unit-test verdict logic first |
| Read-Host blocks non-interactive install | Med | Always `< /dev/null` redirect |
| Promoting during live PRO corrupts install | High | Hard `Get-CimInstance` gate |
| Shell scripts untestable by pytest | Med | Script-gate + manual tasks |

## Rollback Plan

No server code touched. Revert via git: restore `dist/deploy.sh`, delete
`deploy-qa.sh`/`promote-pro.sh`, revert `smoke_test.py`/`README.md`.
Windows-side installs are unaffected; remove `C:\usr\WinMCP-qa` manually
if abandoning QA.

## Dependencies

- `powershell.exe`/`cmd.exe` from WSL2

## Success Criteria

- [ ] `tests/test_smoke_test.py` passes; verdict logic covers all
      PASS/WARN/FAIL combinations; `smoke_test.py` reports per-family
      results with fixed `EXPECTED_TOOLS`
- [ ] `deploy-qa.sh` installs non-interactively, never touching PRO/config
- [ ] `promote-pro.sh` refuses to run while PRO `python.exe` is live
- [ ] `make-deploy-package.sh` gates 1/2/4 pass unchanged
