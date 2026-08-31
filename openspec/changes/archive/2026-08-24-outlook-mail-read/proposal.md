# Proposal: Outlook Mail (Read-Only)

## Intent

Extend WinMCP to Inbox/Sent Items so an agent can search and read mail
alongside calendar and tasks, with zero write risk — no send, drafts,
or mutation.

## Scope

### In Scope
- `mail_search`, `mail_get_message` — one folder per call (`folder`:
  `inbox`|`sent`)
- Fields: subject, sender/recipient, dates, plain-text `Body` (not
  `HTMLBody`), `hasAttachments: bool`
- Mandatory filter: at least one of `dateFrom`/`dateTo`/`subject`/`sender`
- `MailPort` adapter seam (real + fake), lazy `win32com` import
- Guard: skip `Class != 43` (non-`MailItem`) entries
- Fake-adapter-first unit tests (Strict TDD)

### Out of Scope
- Send, reply, forward, drafts, any mutation
- Attachment filenames/content (bool flag only)
- HTML body, folders beyond Inbox/Sent, multi-folder search per call

## Capabilities

### New Capabilities
- `mail-search`: filter Inbox/Sent by date, subject, sender
  (case-insensitive substring); DASL `Restrict()` on `[ReceivedTime]`
  (inbox) or `[SentOn]` (sent)
- `mail-get-message`: full detail for one message by `entryId`
- `outlook-mail-adapter`: `MailPort` Protocol + `OutlookMailAdapter`
  (mirrors `outlook-tasks-adapter`) + `FakeMailAdapter`

### Modified Capabilities
None

## Approach

Mirror tasks: `tools/mail.py` calls `MailPort` (`mail_adapter.py`),
implemented by `OutlookMailAdapter` (lazy `win32com` import,
`GetDefaultFolder(6)`=Inbox, `(5)`=Sent) and `FakeMailAdapter`
(in-memory). `errors.py` gains `MessageNotFoundError` (reuses
`CalendarToolError`/`OutlookUnavailableError`). `schemas.py` gains mail
schemas (camelCase via `_AliasedModel`). `server.py` gains a third
injectable `mail_adapter` param and two tool registrations;
`_map_error` unchanged. `settings.yaml` folder-id entries are omitted
(a conscious choice — prior changes left these dead/unread).

## Affected Areas

| Area | Impact |
|------|--------|
| `tools/mail.py`, `mail_adapter.py`, `fake_mail_adapter.py` | New |
| `errors.py`, `schemas.py`, `server.py` | Modified |
| `tests/test_mail_*.py` (3 files) | New |
| `README.md`, `make-deploy-package.sh` | Modified |

## Risks

| Risk | Lik. | Mitigation |
|------|------|------------|
| Non-`MailItem` entries crash iteration | Med | `Class != 43` guard + mixed-class fixture test |
| Sender filter differs inbox (`SenderName`) vs. sent (`To`) | Med | Document mapping; per-folder fixtures |
| Deploy exclusion regex missed → fake ships to Windows | Med | Task to update exclusion list |
| No real Outlook to validate DASL `Restrict()` | High | Manual Windows verification |
| Windows-only COM vs. Linux dev/CI | High | `MailPort` seam + fake; lazy import only |

## Rollback Plan

Purely additive; no change to calendar/tasks behavior. Delete the 3 new
`tools/*.py` files + 3 test files; revert the additive edits (or
`git revert`). No data migration.

## Dependencies

- None beyond MVP's `pywin32`, `pytest`, `pytest-mock`

## Success Criteria

- [ ] `mail_search`/`mail_get_message` registered, callable over stdio
- [ ] Full suite green via `pytest -q`, only `FakeMailAdapter` in tests
- [ ] No `win32com` import at module load time
- [ ] Real adapter skips non-`MailItem` entries without error
- [ ] Manual Windows smoke test confirms a real message resolves
