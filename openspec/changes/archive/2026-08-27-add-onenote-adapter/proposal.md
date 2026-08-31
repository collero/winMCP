# Proposal: OneNote Access via COM Bridge

## Intent

Windows Search's `SystemIndex` has zero `onenote:` items (spike-verified)
— `file_search` never sees OneNote content; `OneNote.Application` COM is
the only path. Add MCP tools to read, search, write OneNote pages
alongside calendar/mail/tasks/files.

**Runtime split**: adapter + bridge run only on Windows (COM, pinned
`powershell.exe` 5.1). Dev/CI is WSL2 Linux — no COM, no `powershell.exe`;
COM sits behind a seam with a fake adapter (never `pip install pywin32`).

## Scope

### In Scope
- `onenote_search` (`FindPages`), `onenote_get_page` (text + metadata).
- `onenote_create_page` / `onenote_update_page`, restricted to a
  configurable writable-notebook allowlist (default `"z - Test Notebook"`
  only; the 8 live Informa notebooks stay read-only until relaxed).
- `OneNotePort` Protocol + `OneNoteAdapter` (JSON-op-in/JSON-Lines-out
  bridge, dumb executor, mirrors `ps_bridge_search.ps1`) +
  `FakeOneNoteAdapter`.
- Dynamic XML namespace detection; `dateExpectedLastModified` passthrough
  for optimistic concurrency.

### Out of Scope
- Deleting/moving pages/sections/notebooks; ink/image content; sync
  notifications.
- Relaxing the writable allowlist beyond the test notebook (a separate,
  user-approved change).

## Capabilities

### New Capabilities
- `onenote-search`: full-text page search via `FindPages`.
- `onenote-get-page`: one page's text + hierarchy metadata.
- `onenote-write-page`: create/update pages, allowlist-guarded.
- `onenote-com-adapter`: `OneNotePort` Protocol + real/fake adapters.

### Modified Capabilities
None.

## Approach

Mirror `file_search`'s bridge pattern, not Outlook's direct-Dispatch:
`OneNoteAdapter` writes one `{"op": ...}` JSON request to a pinned
`powershell.exe` running `ps_bridge_onenote.ps1`, which runs that op
against `OneNote.Application` and streams JSON Lines + `{"done": true}`,
or `{"error": ...}` + nonzero exit. `tools/onenote.py` owns the allowlist
check, same split as `file_search`'s roots enforcement.

## Affected Areas

| Area | Impact |
|------|--------|
| `models/schemas.py`, `tools/errors.py` | Modified — new models, typed errors |
| `tools/onenote_adapter.py`, `tools/fake_onenote_adapter.py` | New — `OneNotePort` + real/fake |
| `tools/ps_bridge_onenote.ps1` | New — dumb-executor bridge |
| `tools/onenote.py` | New — tools, allowlist enforcement |
| `tools/settings.py`, `config/settings.yaml` | Modified — allowlist, timeout/result caps |
| `server.py` | Modified — register tools, resolver, errors |
| `tests/`, `README.md` | New/Modified — fake-adapter coverage, docs |

## Risks

| Risk | Mitigation |
|------|------------|
| Accidental write to a live Informa notebook | Allowlist defaults to test notebook |
| No real COM/PowerShell on WSL2 dev/CI | Fake adapter; no COM in unit tests |
| XML namespace drift across versions | Detect ns from document element |
| Silent overwrite via `[DateTime]::MinValue` | Pass real last-modified; typed conflict error |

## Rollback Plan

Purely additive. Revert by removing `server.py` registrations and
deleting the new modules/script/tests.

## Dependencies

- `OneNote.Application` COM + pinned
  `C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe`.

## Success Criteria

- [ ] Four tools registered, callable via FastMCP.
- [ ] Writes outside the allowlist refused with a typed error.
- [ ] Fake-adapter tests cover search/read/create/update, no real COM.
- [ ] `python3.12 -m pytest -q` passes on WSL2.
