# Design: Outlook Mail (Read-Only)

## Technical Approach

Mirror the calendar/tasks seam exactly: `tools/mail.py` validates input via
Pydantic schemas and calls a `MailPort` Protocol (`tools/mail_adapter.py`),
implemented by `OutlookMailAdapter` (lazy `win32com` import, real COM) and
`FakeMailAdapter` (`tools/fake_mail_adapter.py`, in-memory, test-only). A
single `folder: inbox|sent` parameter on both `MailPort` methods drives an
internal folder→(`GetDefaultFolder` id, DASL date field) lookup, so one
adapter/tool pair covers both folders instead of four. `server.py` gains a
third injectable adapter parameter and registers `mail_search`/
`mail_get_message`; errors reuse the existing `CalendarToolError` taxonomy
plus one new subclass, so `_map_error` needs no change.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| **Folder parameterization** | One `MailPort` + one `OutlookMailAdapter`; folder resolved via an internal `_FOLDER_MAP`. | Separate `InboxPort`/`SentPort`; 4 tools instead of 2. | Proposal mandates exactly 2 tools, one folder per call via an enum — a lookup table avoids duplicating Class-guard/filter logic across two adapters. |
| **Sender filter/field asymmetry** | Only the search **filter** haystack is folder-relative: inbox matches against `SenderName`+`SenderEmailAddress`; sent matches against `To`. The **returned** `sender`/`senderAddress` fields are NOT folder-relative — they always come from the item's own `SenderName`/`SenderEmailAddress`, in both folders, since a real Sent Items `MailItem` still exposes the account owner as its sender. | Always-present separate `sender`+`recipient` fields; reject `sender` on sent folder; make the returned field folder-relative too (recipient-as-sender on sent). | Proposal calls out the filter asymmetry explicitly. One reused, non-folder-relative field keeps `MessageSummary` stable across folders and matches real Outlook semantics; rejecting the filter on sent would break "at least one filter" uniformly. |
| **Non-MailItem guard** | `_is_mail_item(item) = getattr(item, "Class", None) == 43`. `search()` skips non-matches; `get_message()` raises `MessageNotFoundError`. | DASL `[MessageClass] = 'IPM.Note'`; trust folder contents. | Inbox/Sent can hold meeting requests, receipts, NDRs lacking `MailItem`-only properties. No real Outlook to validate a DASL alternative; skip (list) vs. raise (explicit lookup) matches each call's contract. |
| **Date bound handling** | Reuse `calendar_search`'s "at least one filter" + lookback-fill structure, duplicated into `tools/mail.py`, but backed by a NEW, mail-specific settings key: `mail_lookback_days` (via `tools/settings.py::load_settings()`, default `90` when absent) — NOT calendar's `lookback_days` (`7`). `Restrict()` always gets concrete bounds on the folder's DASL field. | Mirror `task_search`'s fully-optional filters; extract a shared helper; reuse calendar's `lookback_days` value as-is. | Proposal's "at least one filter" rule mirrors calendar's structure, not tasks' — `Restrict()` needs concrete bounds regardless. But email is searched much further back than calendar notes; reusing `lookback_days` (7 days) would silently miss most subject-only mail searches, so mail gets its own key and a 90-day default. Duplicating the fill function (not extracting a shared helper) still avoids touching `tools/calendar.py`. |
| **`settings.yaml` folder ids omitted** | Hardcode 6/5 as adapter constants, like `_DEFAULT_CALENDAR_FOLDER_ID`/`_DEFAULT_TASKS_FOLDER_ID`. | Add `inbox_folder_id`/`sent_folder_id`. | `grep` confirms `calendar_folder_id`/`tasks_folder_id` are never read by any `.py` file. A third dead entry compounds existing debt for no benefit. |
| **Error taxonomy** | `MessageNotFoundError(CalendarToolError)`, `code="message_not_found"`; reuse `OutlookUnavailableError`. | New `MailToolError` base. | Matches `TaskNotFoundError` precedent; `_map_error` already catches the shared base — no change needed there. |

## Data Flow

    Claude Desktop (stdio) ─▶ server.py (FastMCP)
                                   │
                        ┌──────────┴──────────┐
                        ▼                     ▼
                  mail_search           mail_get_message
                        │                     │
                        └──────────┬──────────┘
                                   ▼
                          tools/mail.py
                                   │
                                   ▼
                          MailPort (Protocol)
                            /                \
              OutlookMailAdapter          FakeMailAdapter
          (real, win32com, lazy import)  (tests only, per-folder store)
                    │
                    ▼
       Outlook.Application → GetNamespace("MAPI")
         → GetDefaultFolder(6|5) → Items.Restrict(date field, bounds)
             → Python: Class==43 guard, subject/sender substring filter
                                   / GetItemFromID(entryId) → Class==43 check

**Folder mapping** (resolves the DASL-field/sender asymmetry):

| `folder` | `GetDefaultFolder` id | DASL date field | sender **filter** haystack |
|---|---|---|---|
| `inbox` | 6 (`olFolderInbox`) | `[ReceivedTime]` | `SenderName` + `SenderEmailAddress` |
| `sent` | 5 (`olFolderSentMail`) | `[SentOn]` | `To` |

This "sender filter haystack" column describes the *search-side* `sender`
filter only. The *returned* `sender`/`senderAddress` fields are always the
item's own `SenderName`/`SenderEmailAddress` in both folders — see the
"Sender filter/field asymmetry" decision above.

**`mail_search` sequence**: (1) resolve `folder` → id + DASL field; (2) fill
omitted `dateFrom`/`dateTo` via `mail_lookback_days` (settings default `90`
when the key is absent); (3)
`Items.Restrict(f"{field} >= '...' AND {field} <= '...'")`; (4) per restricted
item, skip if `not _is_mail_item(item)`; (5) subject substring match if given;
(6) sender substring match against the folder's haystack if given.

## File Changes

| File | Action | Description |
|---|---|---|
| `tools/mail.py` | Create | `mail_search`, `mail_get_message`; at-least-one-filter validation + lookback fill (mirrors `tools/calendar.py`) |
| `tools/mail_adapter.py` | Create | `MailPort` Protocol + `OutlookMailAdapter` (lazy `win32com` import, `_FOLDER_MAP`, `_is_mail_item` guard, per-folder sender haystack, `Attachments.Count > 0`) |
| `tools/fake_mail_adapter.py` | Create | `FakeMailAdapter`, test-only, per-folder in-memory store |
| `tools/errors.py` | Modify | Add `MessageNotFoundError(CalendarToolError)` |
| `models/schemas.py` | Modify | Add `MailFolder`, `MessageSummary`, `MessageDetail`, `MailSearchRequest`, `GetMessageRequest` |
| `server.py` | Modify | `create_server()` gains `mail_adapter` param; registers `mail_search`/`mail_get_message`; `_resolve_real_mail_adapter()` |
| `config/settings.yaml` | Modify | Add live `mail_lookback_days: 90` (read by `tools/mail.py`, same pattern as calendar's `lookback_days`); folder ids still intentionally omitted — see decision above |
| `make-deploy-package.sh` | Modify | Exclusion regex: `'tools/(fake_adapter\|fake_task_adapter\|fake_mail_adapter)\.py'` |
| `tests/test_mail_tools.py` | Create | Unit tests against `FakeMailAdapter` |
| `tests/test_fake_mail_adapter.py` | Create | Fake adapter's own per-folder filtering |
| `tests/test_mail_adapter.py` | Create | Real-adapter tests, `win32com.client` mocked into `sys.modules` (mirrors `tests/test_task_adapter.py::_install_fake_win32com`) |
| `tests/test_schemas.py`, `test_errors.py`, `test_server.py` | Modify | Extend for mail schemas/error/registration coverage |
| `README.md` | Modify | Move Mail out of the "future work" list |

## Interfaces / Contracts

```python
# models/schemas.py
class MailFolder(str, Enum):
    INBOX = "inbox"
    SENT = "sent"

class MessageSummary(_AliasedModel):
    entry_id: str = Field(alias="entryId")
    subject: str
    sender: str                    # NOT folder-relative; see "Sender filter/field asymmetry"
    date: datetime                 # ReceivedTime (inbox) / SentOn (sent)
    has_attachments: bool = Field(alias="hasAttachments")

class MessageDetail(MessageSummary):
    body: str                      # plain-text MailItem.Body

class MailSearchRequest(_AliasedModel):
    folder: MailFolder
    date_from: datetime | None = Field(default=None, alias="dateFrom")
    date_to: datetime | None = Field(default=None, alias="dateTo")
    subject: str | None = None
    sender: str | None = None

class GetMessageRequest(_AliasedModel):
    entry_id: str = Field(alias="entryId")

# tools/mail_adapter.py
class MailPort(Protocol):
    def search(self, folder: MailFolder, date_from=None, date_to=None,
                subject=None, sender=None) -> list[MessageSummary]: ...
    def get_message(self, entry_id: str) -> MessageDetail: ...
```

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit (schemas/errors) | `MailFolder`/`MessageSummary`/`MessageDetail` aliasing, `MessageNotFoundError.code` | `tests/test_schemas.py`, `tests/test_errors.py` |
| Unit (tools) | At-least-one-filter `ValueError`, folder dispatch, 90-day default fill (subject-only search → adapter receives `[now-90d, now]`), `mail_lookback_days` fallback-default when absent from settings | `FakeMailAdapter` via `create_server(mail_adapter=...)` |
| Unit (fake adapter) | Per-folder store, subject/sender substring, date bounds | `tests/test_fake_mail_adapter.py` |
| Unit (adapter) | `GetDefaultFolder(6/5)`, per-folder `Restrict()` field, `Class!=43` skip (search) / raise (get), sender haystack per folder, `hasAttachments` | `win32com.client` mocked into `sys.modules`; mixed-class fixture (`Class=43` + e.g. `Class=53`) required |
| Integration | Both tools registered, callable via FastMCP in-process client | Extend `tests/test_server.py` |
| E2E | Real inbox/sent message resolves | Manual only, on Windows host |

## Migration / Rollout

No migration — purely additive. Same rollout as calendar/tasks (Windows
Python 3.12 host; dev/CI stays on WSL2 with `FakeMailAdapter`). The
`make-deploy-package.sh` exclusion-regex update must land with
`fake_mail_adapter.py`'s creation, since the manifest discovers `tools/*.py`
dynamically — an unexcluded fake would ship to the Windows package.

## Open Questions

- [ ] None blocking. Remaining proposal risks (real Outlook `Restrict()`
      behavior, deploy exclusion regex) are implementation/verification
      tasks, not design gaps.
