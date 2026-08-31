# Proposal: Mail Reading Depth

## Intent

`mail_search`/`mail_get_message` only see Inbox/Sent, never show attachment
names, and only return plain-text body. Users need Drafts, named custom
folders, and optional HTML body — read-only, no new mutation surface.

## Scope

### In Scope
- `MessageDetail.attachment_names` (detail-only; `hasAttachments` unchanged)
- `include_html_body` -> `html_body` (opt-in; plain-text `body` always present)
- `MailFolder.DRAFTS` (`GetDefaultFolder(16)`), date fallback ReceivedTime
  -> SentOn -> LastModificationTime
- `folder_path` (exclusive with `folder`) — default-store-scoped
  `/`-delimited traversal by name
- New `MailFolderNotFoundError` (code `mail_folder_not_found`)
- One `mail-drafts` smoke-test FAMILIES tuple
- README limitations/extensions updated

### Out of Scope
- Shared/delegated mailboxes (Exchange-only) — deferred
- Attachment content/download — filenames only
- Generic folder discovery/listing tool
- Smoke coverage for `folderPath`/`includeHtmlBody` (same call path as existing chain)

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `mail-get-detail`: adds `attachmentNames`, opt-in `includeHtmlBody` -> `htmlBody`
- `outlook-mail-adapter`: adds `DRAFTS`, path traversal, attachments/HTMLBody reads, date fallback
- `mail-search`: `folder` optional, adds `folderPath`, validator, `MailFolderNotFoundError`
- `smoke-test-coverage`: adds `mail-drafts` to `FAMILIES`

## Approach

Extend the `MailPort` seam, no new tools/adapters. `_FOLDER_MAP` gains
`drafts`; a traversal helper resolves `folder_path` via `Folders`
name-indexing rooted at the default store's subtree (never namespace
top-level). `FakeMailAdapter` mirrors both. `tools/mail.py` threads the new
kwargs and maps `MailFolderNotFoundError` like `EventNotFoundError`.

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `models/schemas.py` | Modified | New fields; `folder` optional; validator |
| `tools/mail_adapter.py` | Modified | `DRAFTS` map, traversal helper, attachments/HTMLBody, date fallback |
| `tools/fake_mail_adapter.py` | Modified | Mirror new behavior |
| `tools/mail.py` | Modified | Thread kwargs; map new error |
| `tools/errors.py` | Modified | `MailFolderNotFoundError` |
| `config/settings.yaml` | Modified | `drafts_folder_id: 16` |
| `deploy/smoke_test.py` | Modified | `mail-drafts` FAMILIES tuple |
| `README.md` | Modified | Limitations / extensions |
| `tests/` | Modified | mail tools/adapter/fake/schemas tests |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `LastModificationTime` untested on real Outlook | Med | Design-time assumption, verified at deploy validation |
| Folder-path ambiguity (dup names, case) | Low | Default-store subtree only, exact-segment match, typed error on failure |
| Validator breaks existing callers | Low | `folder` alone stays valid; rejects only both-or-neither |

## Rollback Plan

All changes are additive/optional — nothing removed/renamed. Revert commits
touching "Affected Areas"; no migration, no settings keys removed.

## Dependencies

None — no new packages; win32com/pythoncom stay lazy-only.

## Success Criteria

- [ ] `mail_get_message` always returns `attachmentNames`; `htmlBody` only when requested
- [ ] `folder="drafts"` and `folderPath` resolve via fake adapter
- [ ] Invalid `folderPath` raises `MailFolderNotFoundError`, not a crash
- [ ] `deploy/smoke_test.py` FAMILIES includes `mail-drafts`, tests pass
- [ ] Full suite green (baseline 174 passed, no regressions)
