# Design: QA→PRO Deployment Pipeline with Manual Validation Gate

## Technical Approach

Replace `smoke_test.py`'s fixed 4-step/calendar-only flow with a
data-driven `FAMILIES` table (calendar, tasks, mail-inbox, mail-sent) run
through one generic `run_family()` helper, aggregated by a pure
`aggregate_verdict()`. Replace `dist/deploy.sh` with two root scripts
splitting the trust boundary: `deploy-qa.sh` installs non-interactively
into disposable `C:\usr\WinMCP-qa`; `promote-pro.sh` promotes only a
QA'd zip, gated on no live PRO process. Both reuse the WSL2↔Windows
bridge already proven in `dist/deploy.sh`/`install.bat`.

## Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Family model | `FAMILIES: list[Family(name, search_tool, args_fn, detail_tool)]`; `TOTAL_STEPS = 3 + len(FAMILIES)` | Scales to N vs. 4 copy-pasted `do_*` fns |
| Calendar detail tool | `calendar_get_event` (entryId), not `calendar_get_notes` (date+subject) | Uniform `{"entryId": <1st hit>}` contract; `get_notes` covered by README's manual test instead |
| Empty search result | Verdict `"pass"`, no chain call | Empty inbox/list is legitimate, not a defect |
| Verdict strings | Reuse `"pass"`/`"warning"`/`"fail"` verbatim, now per-family | Binding decision; no churn for consumers |
| JSON-RPC ids | `itertools.count(1)` shared across all calls | Must stay unique across a variable family count |
| Handshake vs. family failure | Handshake `StepFailed` aborts the run; a family's is caught in `run_family` | One broken family must not hide the rest |
| QA install target | `rm -rf WinMCP-qa`, extract to `mktemp -d`, `mv` zip's `WinMCP/` → `WinMCP-qa` | Zip's folder is always `WinMCP/`; in-place unzip would nest as `WinMCP-qa/WinMCP/`. Full wipe is safe — no `.venv` to preserve |
| PRO install target | `deploy.sh`'s mechanics: wipe `wheels/`, `unzip -q -o` onto `C:\usr\WinMCP` | Zip's `WinMCP/` matches the PRO folder name; proven overwrite-in-place preserves `.venv` |
| PRO lock gate | `Get-CimInstance Win32_Process \| Where ExecutablePath -like '...\.venv\*'`; any row ⇒ refuse | Distinguishes a live PRO server from an unrelated `python.exe` (e.g. QA's) |
| Marker format | Plain `key: value` lines — `QA-VALIDATED.txt`/`DEPLOYED.txt` | Greppable, no `jq`, stdlib-only bias |
| promote-pro.sh zip choice | Default = zip in `QA-VALIDATED.txt`; refuse sha256 mismatch unless `--force` | Enforces "only what QA validated reaches PRO" |
| Non-interactive install | `cmd.exe /c ...\install.bat < /dev/null` | `install.ps1`'s final `Read-Host` (line 256) reads EOF and returns; `install.bat`'s own `cd /d` makes the UNC-cwd warning cosmetic |

## Data Flow — smoke test

    init -> initialized -> tools/list (7 tools)
                                |
        run_family(calendar|tasks|mail-inbox|mail-sent):
          search_tool -> [1st hit?] -> detail_tool -> pass/warning/fail
                                |
                    aggregate_verdict(results)

## Data Flow — QA→PRO sequence

    make-deploy-package.sh -> dist/WinMCP-YYYYMMDD.zip
       -> deploy-qa.sh: wipe+unzip WinMCP-qa, install.bat </dev/null,
          write QA-VALIDATED.txt, print manual steps
       -> [human: test.bat + Claude Desktop checks on WinMCP-qa]
       -> promote-pro.sh: CIM lock gate (refuse if PRO python.exe live),
          unzip -o onto WinMCP (preserves .venv), install.bat </dev/null,
          copy zip -> OneDrive _OUT, write DEPLOYED.txt, restart reminder

## File Changes

| File | Action | Description |
|---|---|---|
| `deploy/smoke_test.py` | Modify | `FAMILIES` table, `run_family()`, `aggregate_verdict()`, 7-tool `EXPECTED_TOOLS`, dynamic `TOTAL_STEPS` |
| `tests/test_smoke_test.py` | Create | `aggregate_verdict` truth table, `run_family` via stub server |
| `deploy-qa.sh` (root) | Create | Wipe+extract+install to `WinMCP-qa`, write `QA-VALIDATED.txt` |
| `promote-pro.sh` (root) | Create | Lock gate, `deploy.sh`-style install, copy to OneDrive, write `DEPLOYED.txt` |
| `dist/deploy.sh` | Delete | Superseded by the two scripts above |
| `README.md` | Modify | Replace install/deploy narrative with QA→PRO flow |
| `make-deploy-package.sh` | No change | Gates 1/2/4 unaffected; markers live under `C:\usr\WinMCP*`, never staged |

## Interfaces / Contracts

```python
# deploy/smoke_test.py
Family = namedtuple("Family", "name search_tool search_args_fn detail_tool")
EXPECTED_TOOLS = {
    "calendar_search", "calendar_get_event", "calendar_get_notes",
    "task_search", "task_get_task", "mail_search", "mail_get_message",
}

def run_family(server, id_gen, family: Family) -> tuple[str, list[str]]:
    """(verdict, lines); verdict in {"pass","warning","fail"}; catches
    StepFailed internally -> ("fail", [reason])."""

def aggregate_verdict(results: dict[str, str]) -> str:
    """Pure: any "fail" -> "fail"; elif any "warning" -> "warning"; else "pass"."""
```

```
# QA-VALIDATED.txt / DEPLOYED.txt (same schema)
zip: WinMCP-20260824.zip
sha256: <64 hex chars>
validated_utc: 2026-08-24T10:15:00Z   # DEPLOYED.txt: deployed_utc
```

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | `aggregate_verdict` over all pass/warning/fail combos | `tests/test_smoke_test.py`, stdlib, Linux |
| Unit | `run_family`: pass (hit+chain), pass (empty), warning (Outlook-unavailable), fail (RPC error/timeout) | Stub server scripts `.send`/`.read_line`; no subprocess |
| Unit | `EXPECTED_TOOLS` matches `server.py`'s 7 names | Static assertion |
| Script-gate | `deploy-qa.sh`/`promote-pro.sh` syntax | `bash -n` (+ `shellcheck` if available) |
| Manual (closes change) | Real `deploy-qa.sh` run; manual `test.bat`; real `promote-pro.sh` incl. lock-gate refusal while QA's own `python.exe` is live | Windows host, by a human |

## Migration / Rollout

No server/tool code touched. First run replaces the ad hoc `dist/deploy.sh`
workflow; `C:\usr\WinMCP-qa` is new disk usage, removed manually if QA is
abandoned (proposal's rollback plan).

## Open Questions

- [ ] `calendar_get_notes` stays outside smoke-test chain coverage — doesn't
      fit the uniform entryId contract; README's manual test covers it.
