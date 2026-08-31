# Delta for MCP Server Bootstrap

## MODIFIED Requirements

### Requirement: Tool Registration

The server MUST register, at startup, exactly the tools enabled by
`config/installed-tools.yaml`: every tool listed in `tools/catalog.yaml`
whose name appears in that file's enabled list, if the file exists in
the deployed copy — or every catalog tool, if the file is absent
(back-compat with pre-selective-deploy behavior). Each registered tool
remains backed by its schema in `models/schemas.py` and the adapter seam
in its corresponding tool/adapter spec.
(Previously: unconditionally registered a fixed set of tools, with no
config file involved.)

#### Scenario: All catalog tools are discoverable when no config file exists

- GIVEN the server module is imported with no `config/installed-tools.yaml` present, and fake adapters injected
- WHEN an MCP client lists available tools
- THEN every tool in `tools/catalog.yaml` is present — current, pre-this-change behavior

#### Scenario: Only enabled tools are discoverable when the config file exists

- GIVEN `config/installed-tools.yaml` lists only the calendar and mail tools as enabled
- WHEN an MCP client lists available tools
- THEN only `calendar_search`, `calendar_get_event`, `calendar_get_notes`, `mail_search`, `mail_get_message` are present — task, file, and onenote tools are absent

## ADDED Requirements

### Requirement: Import Safety Independent of Registration Gating

Importing `server.py` MUST NOT depend on which tools
`config/installed-tools.yaml` enables or excludes. Whether an excluded
tool's module is still statically imported by `server.py` or not, the
import MUST succeed either way — registration gating MUST NOT be
achieved by making imports conditional in a way that could fail.

#### Scenario: Import succeeds with a narrowed config

- GIVEN `config/installed-tools.yaml` enables only 2 of 13 catalog tools
- WHEN `server.py` is imported (e.g. by `python3.12 -m pytest -q` collecting tests)
- THEN the import succeeds with no error, regardless of whether the 11 excluded tools' modules are also imported

#### Scenario: Import succeeds with the config file absent

- GIVEN no `config/installed-tools.yaml` file
- WHEN `server.py` is imported
- THEN the import succeeds exactly as it did before this change
