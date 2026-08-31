# Delta for Smoke Test Coverage

## MODIFIED Requirements

### Requirement: Expected Tool Set Matches Registered Tools

`EXPECTED_TOOLS` MUST be derived from the same tool-selection source
`server.py` uses for registration: every tool name in
`config/installed-tools.yaml`'s enabled list, if that file exists in the
deployed copy, or every tool in `tools/catalog.yaml` — the current full
13-tool set (`calendar_search`, `calendar_get_event`,
`calendar_get_notes`, `task_search`, `task_get_task`, `mail_search`,
`mail_get_message`, `file_search`, `file_get_info`, `onenote_search`,
`onenote_get_page`, `onenote_create_page`, `onenote_update_page`) — if
the file is absent. `tools/list` MUST be validated against this set; a
missing tool fails the step, extras are only noted.
(Previously: a fixed, hardcoded literal set.)

#### Scenario: A registered tool is missing from tools/list

- GIVEN a fake server whose `tools/list` response omits `mail_get_message`
- WHEN the tools/list step validates the response
- THEN the step fails, naming `mail_get_message` as missing

#### Scenario: EXPECTED_TOOLS narrows when installed-tools.yaml is present

- GIVEN a deployed copy whose `config/installed-tools.yaml` enables only the calendar and file tools
- WHEN `smoke_test.py` computes `EXPECTED_TOOLS`
- THEN it equals exactly `{calendar_search, calendar_get_event, calendar_get_notes, file_search, file_get_info}`

#### Scenario: EXPECTED_TOOLS is the full catalog when the file is absent

- GIVEN a deployed copy with no `config/installed-tools.yaml`
- WHEN `smoke_test.py` computes `EXPECTED_TOOLS`
- THEN it equals the full 13-tool set from `tools/catalog.yaml`, matching today's hardcoded literal

## ADDED Requirements

### Requirement: Per-Family Live Checks Scoped to Enabled Families

The set of families exercised by the live per-family steps
(`run_family()`/`run_files_family()`) MUST be limited to families with
at least one tool enabled per the same installed-tools source as
`EXPECTED_TOOLS`. A family with zero enabled tools MUST be skipped
rather than attempted, and its absence MUST NOT fail the run.

#### Scenario: A fully-disabled family is skipped, not failed

- GIVEN `config/installed-tools.yaml` enables no task tools (`task_search` and `task_get_task` both disabled)
- WHEN `smoke_test.py` runs its family steps
- THEN no task-family live step runs, and the run's overall verdict is unaffected by the task family's absence

#### Scenario: All families run when the config file is absent

- GIVEN no `config/installed-tools.yaml`
- WHEN `smoke_test.py` runs
- THEN every family with a live step today (calendar, tasks, mail-inbox, mail-sent, mail-drafts, files) still runs, unchanged from current behavior
