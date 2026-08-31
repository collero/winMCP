# Design: Mail Reading Depth

## Technical Approach

Extend the existing `MailPort` seam — no new tools/adapters/ports.
`MailSearchRequest` gains an exclusive `folder`/`folder_path` pair enforced
by a `model_validator`; `_FOLDER_MAP` gains `drafts`; both adapters grow a
path-traversal branch plus attachment-name/HTML-body reads. `tools/mail.py`
threads the new fields through, unchanged validation ordering. `server.py`'s
mail tool registrations expose the new request fields (`folder` optional,
`folderPath`, `includeHtmlBody`) — added as the Phase 7 orchestrator-directed
amendment after apply Batches 1-2 flagged the wiring gap; `_map_error` itself
is unchanged — `MailFolderNotFoundError(CalendarToolError)` is caught by the
existing generic catch, and request construction sits inside the `try` so the
exclusivity `ValidationError` surfaces as a clean tool error.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|---|---|---|---|
| **Path root** | `namespace.DefaultStore.GetRootFolder()`. | `GetDefaultFolder(6).Parent`; `namespace.Folders` (all stores). | One call scopes exactly to the default mailbox ("default store's subtree ONLY"); `Folders` would reach other mailboxes/PSTs — shared mailboxes are explicitly deferred. |
| **Segment resolution** | Split `folder_path` on `"/"`; each segment via `current.Folders.Item(segment)`, any exception → unresolved segment. | Call-syntax `Folders(segment)`; iterate matching `.Name`. | `.Item(name)` is win32com's explicit member — directly mockable per segment with `side_effect`. |
| **folderPath date filtering** | Skip DASL `Restrict()` for path-resolved folders; fetch full `Items`, filter dates in Python via the same `_resolve_date()` chain `get_message()` uses (`ReceivedTime`→`SentOn`→`LastModificationTime`). Mapped folders keep their single-field `Restrict()`. | One fixed DASL field for all custom folders; OR-combined DASL clause. | A custom folder's item types are unknown ahead of time — no single field is reliably populated. Correct over efficient; matches proposal's "no smoke coverage for folderPath" (lower-risk path). |
| **`search()` signature** | Add `folder_path: str \| None = None` beside `folder: MailFolder \| None = None`; exclusivity enforced once at the schema, not re-checked in the adapter. | Two adapter methods; a discriminated union. | Keeps `FakeMailAdapter` symmetrical with one `search()`; re-validating in the adapter would duplicate the Pydantic invariant. |
| **Exclusivity + errors** | `MailSearchRequest.model_validator(mode="after")` raises `ValueError` on both-or-neither. Path-resolution failure raises new `MailFolderNotFoundError(CalendarToolError)`, code `mail_folder_not_found`, carrying `path`/`failing_segment`. | Validate in `tools/mail.py`; reuse `EventNotFoundError`. | Fails fast at construction. A distinct error gives callers a folder-specific `code`, per `AmbiguousMatchError`'s precedent of carrying structured context. |
| **Drafts date field** | `_FOLDER_MAP[DRAFTS] = (16, "[LastModificationTime]", "drafts_folder_id")`. | `[CreationTime]`. | Drafts are edited repeatedly before send; last-modified best reflects recency. Real-Outlook reliability unverified here — flagged as a deploy-validation check below. |
| **Attachment names** | 1-indexed `for i in range(1, item.Attachments.Count + 1): item.Attachments.Item(i).FileName`; `has_attachments` unchanged. | `.DisplayName`; Python-iterate `Attachments`. | Outlook `Attachments` is explicitly 1-indexed; `FileName` is the on-disk name callers want, `DisplayName` can differ for inline items. |
| **HTML body opt-in** | `get_message()` reads `item.HTMLBody` only when `include_html=True`; plain-text `body` always populated. | Always fetch both; a separate tool. | `HTMLBody` can be large (styles, inline data URIs); opt-in keeps the existing response shape stable and the tool count at 2. |

## Data Flow

    mail_search(folder="drafts" | folder_path="Proyectos/2026", ...)
                    │  (folder XOR folder_path enforced by the schema)
                    ▼
              MailPort.search(folder, folder_path, ...)
             /                                        \
    folder given (mapped)                     folder_path given
    _resolve_folder_id → GetDefaultFolder      DefaultStore.GetRootFolder()
    Restrict([DASL field], bounds)             → split("/") → Folders.Item(seg)*
                    │                            (failure → MailFolderNotFoundError)
                    │                          items = folder.Items (no Restrict)
                    │                          Python-filter via _resolve_date()
                    └───────────────┬──────────────────┘
                                    ▼
               per item: _is_mail_item guard → subject/sender substring
                                    ▼
                           list[MessageSummary]

`get_message(entry_id, include_html=False)`: `GetItemFromID` →
`_is_mail_item` guard → `_resolve_date()` chain → build `MessageDetail`
with `attachment_names` always populated, `html_body` only if requested.

## File Changes

| File | Action | Description |
|---|---|---|
| `models/schemas.py` | Modify | `MailFolder.DRAFTS`; `folder` optional + `folder_path` (alias `folderPath`) + exclusivity validator; `GetMessageRequest.include_html_body`; `MessageDetail.attachment_names`/`html_body` |
| `tools/errors.py` | Modify | `MailFolderNotFoundError(CalendarToolError)`, code `mail_folder_not_found`, carries `path`/`failing_segment` |
| `tools/mail_adapter.py` | Modify | `_FOLDER_MAP` += `drafts`; `_resolve_date()` extended; new path-traversal helper; `search()`/`get_message()` gain params + branches |
| `tools/fake_mail_adapter.py` | Modify | Store gains `drafts` + arbitrary-path dict keyed by path string; fixtures carry attachment names/html body |
| `tools/mail.py` | Modify | Thread `folder_path`/`include_html_body`; mandatory-filter rule and lookback fill unchanged, apply identically to both selectors |
| `config/settings.yaml` | Modify | Add `drafts_folder_id: 16` |
| `deploy/smoke_test.py` | Modify | New `mail-drafts` `Family` tuple in `FAMILIES` |
| `README.md` | Modify | Limitations (shared mailboxes deferred, folderPath default-store-only) / extensions |
| `tests/test_schemas.py`, `test_errors.py`, `test_mail_adapter.py`, `test_fake_mail_adapter.py`, `test_mail_tools.py`, `test_smoke_test.py` | Modify | Coverage per layer — see Testing Strategy |

## Interfaces / Contracts

```python
class MailFolder(str, Enum):
    INBOX = "inbox"; SENT = "sent"; DRAFTS = "drafts"

class MailSearchRequest(_AliasedModel):
    folder: MailFolder | None = None
    folder_path: str | None = Field(default=None, alias="folderPath")
    date_from: datetime | None = Field(default=None, alias="dateFrom")
    date_to: datetime | None = Field(default=None, alias="dateTo")
    subject: str | None = None
    sender: str | None = None

    @model_validator(mode="after")
    def _exactly_one_folder_selector(self) -> "MailSearchRequest":
        if (self.folder is None) == (self.folder_path is None):
            raise ValueError("exactly one of folder or folderPath is required")
        return self

class GetMessageRequest(_AliasedModel):
    entry_id: str = Field(alias="entryId")
    include_html_body: bool = Field(default=False, alias="includeHtmlBody")

class MessageDetail(MessageSummary):
    body: str
    to: list[str]
    attachment_names: list[str] = Field(default_factory=list, alias="attachmentNames")
    html_body: str | None = Field(default=None, alias="htmlBody")

class MailPort(Protocol):
    def search(self, folder: MailFolder | None = None, folder_path: str | None = None,
                date_from=None, date_to=None, subject=None, sender=None) -> list[MessageSummary]: ...
    def get_message(self, entry_id: str, include_html: bool = False) -> MessageDetail: ...
```

## Sequence Diagram — folderPath Resolution

```
tools/mail.py    OutlookMailAdapter          namespace / Folders
    │ search(folder_path="Proyectos/2026")│
    ├─────────────────────────────────────▶│
    │                    DefaultStore.GetRootFolder() ─▶ root folder
    │                    Folders.Item("Proyectos")     ─▶ "Proyectos" folder
    │                    Folders.Item("2026")          ─▶ "2026" folder
    │                    (any Item() raises → MailFolderNotFoundError)
    │◀──────── list[MessageSummary] ───────┤
```

## Testing Strategy

Strict TDD; unit tests per layer, mirroring existing conventions (fake
`win32com`/`pythoncom` in `sys.modules` per
`tests/test_mail_adapter.py::_install_fake_win32com`).

| Layer | What to Test | Approach |
|---|---|---|
| Schemas | `DRAFTS`; both/neither/exactly-one selector; new field aliasing/defaults | `test_schemas.py` |
| Errors | `MailFolderNotFoundError` code + carried context | `test_errors.py` |
| Tools | Exclusivity `ValueError` pre-adapter; pass-through of `folder_path`/`include_html_body`; lookback fill for both selectors | `test_mail_tools.py` via `FakeMailAdapter` |
| Fake adapter | Drafts store; arbitrary-path hit/miss; attachment/html fixtures | `test_fake_mail_adapter.py` |
| Real adapter | `GetDefaultFolder(16)` + `[LastModificationTime]` Restrict; root→segment traversal success/failure; no-Restrict Python date filter for `folder_path`; 1-indexed attachment loop; conditional `HTMLBody` | `test_mail_adapter.py`, mocked `win32com.client`/`pythoncom` |
| Live/manual | `mail-drafts` smoke family only — the sole live-Outlook coverage added; `folderPath`/`includeHtmlBody` explicitly not smoke-covered (same call path, per proposal) | `deploy/smoke_test.py` on Windows host |

## Migration / Rollout

No migration — purely additive/optional. `drafts_folder_id: 16` ships in
`config/settings.yaml`; absence falls back to `_FOLDER_MAP`'s default,
matching `inbox_folder_id`/`sent_folder_id`. The `LastModificationTime`-for-
drafts assumption is unverified against real Outlook here — the
`mail-drafts` smoke family (manual, Windows host) is the deploy-validation
check before first real use.

## Open Questions

- [ ] None blocking. Shared/delegated mailbox traversal is explicitly
      deferred — `DefaultStore.GetRootFolder()` never reaches a non-default
      store, so this is a scope boundary, not a design gap.
