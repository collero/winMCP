# Outlook COM Adapter Specification — Delta

## ADDED Requirements

### Requirement: Configurable Folder Ids

Every real Outlook adapter (`OutlookCalendarAdapter`, `OutlookTaskAdapter`,
`OutlookMailAdapter`) MUST resolve the Outlook `GetDefaultFolder()` id(s) it
uses from `config/settings.yaml` (via `tools/settings.py::load_settings()`)
at COM-access time — i.e., freshly on each `search()`/get-method call, not
cached at construction or module-import time — falling back to the
documented default when the corresponding key is absent from settings or
settings.yaml is unreadable:

- `OutlookCalendarAdapter` reads `calendar_folder_id` (default `9`,
  olFolderCalendar).
- `OutlookTaskAdapter` reads `tasks_folder_id` (default `13`,
  olFolderTasks).
- `OutlookMailAdapter` reads `inbox_folder_id` (default `6`, olFolderInbox)
  when resolving the inbox folder, and `sent_folder_id` (default `5`,
  olFolderSentMail) when resolving the sent folder.

#### Scenario: Configured calendar folder id is used

- GIVEN a fake `win32com.client` module injected into `sys.modules`, and
  `tools.outlook_adapter.load_settings` mocked to return
  `{"calendar_folder_id": 42}`
- WHEN `OutlookCalendarAdapter().search(...)` is called
- THEN `namespace.GetDefaultFolder(42)` is called, not the hardcoded
  default

#### Scenario: Absent calendar folder id key falls back to the default

- GIVEN a fake `win32com.client` module injected into `sys.modules`, and
  `tools.outlook_adapter.load_settings` mocked to return `{}`
- WHEN `OutlookCalendarAdapter().search(...)` is called
- THEN `namespace.GetDefaultFolder(9)` is called

#### Scenario: Configured tasks folder id is used

- GIVEN a fake `win32com.client` module injected into `sys.modules`, and
  `tools.task_adapter.load_settings` mocked to return
  `{"tasks_folder_id": 99}`
- WHEN `OutlookTaskAdapter().search()` is called
- THEN `namespace.GetDefaultFolder(99)` is called, not the hardcoded
  default

#### Scenario: Absent tasks folder id key falls back to the default

- GIVEN a fake `win32com.client` module injected into `sys.modules`, and
  `tools.task_adapter.load_settings` mocked to return `{}`
- WHEN `OutlookTaskAdapter().search()` is called
- THEN `namespace.GetDefaultFolder(13)` is called

#### Scenario: Configured inbox/sent folder ids are used

- GIVEN a fake `win32com.client` module injected into `sys.modules`, and
  `tools.mail_adapter.load_settings` mocked to return
  `{"inbox_folder_id": 61, "sent_folder_id": 51}`
- WHEN `OutlookMailAdapter().search(MailFolder.INBOX, ...)` is called
- THEN `namespace.GetDefaultFolder(61)` is called
- WHEN `OutlookMailAdapter().search(MailFolder.SENT, ...)` is called
- THEN `namespace.GetDefaultFolder(51)` is called

#### Scenario: Absent inbox/sent folder id keys fall back to the defaults

- GIVEN a fake `win32com.client` module injected into `sys.modules`, and
  `tools.mail_adapter.load_settings` mocked to return `{}`
- WHEN `OutlookMailAdapter().search(MailFolder.INBOX, ...)` is called
- THEN `namespace.GetDefaultFolder(6)` is called
- WHEN `OutlookMailAdapter().search(MailFolder.SENT, ...)` is called
- THEN `namespace.GetDefaultFolder(5)` is called

#### Scenario: settings.yaml declares every folder-id key live

- GIVEN the real, unmocked `config/settings.yaml`
- WHEN it is loaded via `tools.settings.load_settings()`
- THEN `calendar_folder_id` (`9`), `tasks_folder_id` (`13`),
  `inbox_folder_id` (`6`), and `sent_folder_id` (`5`) are all present with
  their documented default values
