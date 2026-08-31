# QA→PRO Deploy Workflow Specification

## Purpose

Replace single-shot `dist/deploy.sh` with `deploy-qa.sh` (sandboxed QA
install, human-validated via `test.bat`) and `promote-pro.sh` (promotes
the validated zip to PRO, gated on PRO idle). Both run from WSL2 via
`cmd.exe`/`powershell.exe`; verified by inspection and manual runs, not
pytest.

## Requirements

### Requirement: Zip Resolution for Both Scripts

`deploy-qa.sh`'s zip argument is optional, defaulting to the newest
`dist/WinMCP-*.zip` by mtime. `promote-pro.sh`'s zip argument is
optional, defaulting to the QA-marker's zip (see below), and MUST be
refused if it mismatches the marker unless a force flag is passed.

#### Scenario: Defaults and mismatch-refusal resolve correctly

- GIVEN `dist/` has an older and a newer zip, the marker names the newer one
- WHEN each script runs argument-less, and `promote-pro.sh` is also run against the older zip
- THEN both pick their correct default, and the older-zip run is refused unless forced

### Requirement: QA Folder Fully Wiped, Top-Level Folder Renamed

`deploy-qa.sh` MUST fully wipe `/mnt/c/usr/WinMCP-qa` before extracting
(no stale `.venv`/wheels survive), then extract the zip's `WinMCP/` folder
to scratch and rename it to `WinMCP-qa`.

#### Scenario: Prior install wiped, contents unnested

- GIVEN a prior `WinMCP-qa` with a `.venv/`
- WHEN `deploy-qa.sh` runs
- THEN the prior folder is gone and `WinMCP-qa/server.py` exists directly, not double-nested

### Requirement: Non-Interactive Windows Installer Invocation

Both scripts MUST invoke the installer via `cmd.exe /c` with an absolute
Windows path, stdin redirected from `/dev/null` — MANDATORY, since
`install.ps1` ends in `Read-Host` and blocks without it.

#### Scenario: Installer completes without blocking

- WHEN either script invokes the installer with no attached TTY
- THEN stdin is redirected from `/dev/null` and it completes without hanging

### Requirement: QA Isolation, Marker, and Test Instruction

`deploy-qa.sh` MUST NOT write to `/mnt/c/usr/WinMCP` (PRO) or any Claude
Desktop config. It MUST write a marker (zip name + sha256) into the QA
folder, and end by telling the user to run `test.bat` there.

#### Scenario: PRO untouched, marker and instruction present

- WHEN `deploy-qa.sh` installs `WinMCP-20260824.zip` successfully
- THEN `/mnt/c/usr/WinMCP` is unchanged, the marker records that zip's name/sha256, and the final output names `test.bat` in the QA folder

### Requirement: Hard Gate on a Live PRO Process

`promote-pro.sh` MUST detect, via `powershell.exe Get-CimInstance` from
WSL, any `python.exe` under `C:\usr\WinMCP\.venv`, and refuse to promote
while one is present.

#### Scenario: Live process blocks; its absence allows promotion

- GIVEN `Get-CimInstance` reports a `python.exe` at `C:\usr\WinMCP\.venv\Scripts\python.exe`
- WHEN `promote-pro.sh` checks the gate
- THEN it refuses without touching PRO; absent that process, it proceeds

### Requirement: PRO Extraction and Promotion Side Effects

`promote-pro.sh` MUST preserve any existing `/mnt/c/usr/WinMCP/.venv`,
wipe `wheels/` first, then `unzip -o` (current `deploy.sh` semantics). On
success it MUST copy the zip to `/mnt/c/co/od/_DEV/WinMCP/_OUT`, write
`DEPLOYED.txt` in PRO (zip name, sha256, UTC date), and print a Claude
Desktop restart reminder.

#### Scenario: .venv preserved, wheels replaced, audit trail written

- GIVEN an existing `.venv` and a stale wheel absent from the new zip
- WHEN `promote-pro.sh` completes for `WinMCP-20260824.zip`
- THEN `.venv` is unmodified, `wheels/` matches the new zip exactly, the OneDrive `_OUT` copy and `DEPLOYED.txt` (name/sha256/date) exist, and the output reminds the user to restart Claude Desktop

### Requirement: Fail-Fast, but a UNC-CWD Warning Is Not a Failure

Both scripts MUST set `set -euo pipefail`, exiting non-zero with a clear
message on any real step failure — except a UNC-path cosmetic warning
from the installer subprocess (a known `cmd.exe`/PowerShell quirk), which
MUST NOT be treated as a failure.

#### Scenario: Real failure aborts; cosmetic UNC warning does not

- GIVEN `unzip` fails partway (corrupt zip) in one run, and the installer only emits a UNC-path stderr warning in another
- WHEN either script evaluates each outcome
- THEN the corrupt-zip run exits non-zero immediately, while the UNC-warning run continues and completes normally

### Requirement: Legacy Deploy Script Removed; Remaining Behavior Is Manual/Script-Verified

`dist/deploy.sh` MUST be removed, superseded by `deploy-qa.sh` +
`promote-pro.sh`. All requirements above describe shell/Windows-process
behavior not runnable under pytest here; verification is by script
inspection and manual execution on WSL2 + a Windows target.

#### Scenario: deploy.sh absent; full flow confirmed manually

- WHEN the repo is inspected after this change, `dist/deploy.sh` is absent
- AND a human runs `deploy-qa.sh`, validates via `test.bat`, then `promote-pro.sh` on a reachable Windows target
- THEN each requirement above is confirmed by observation, not by a pytest run
