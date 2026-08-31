# MCP Server Bootstrap Specification

## Purpose

Stand up the FastMCP server process (`server.py`) that registers the three
calendar tools and serves them over stdio, with no authentication and no network
exposure beyond localhost.

## Requirements

### Requirement: Tool Registration

The server MUST register `calendar_search`, `calendar_get_event`, and
`calendar_get_notes` as MCP tools at startup, each backed by the schemas in
`models/schemas.py` and the adapter seam in the Outlook COM Adapter spec.

#### Scenario: All three tools are discoverable

- GIVEN the server module is imported and initialized with a fake adapter injected
- WHEN an MCP client lists available tools
- THEN `calendar_search`, `calendar_get_event`, and `calendar_get_notes` are all present

### Requirement: Transport and Access Scope

The server MUST run over stdio transport only. It MUST NOT open any network
listener or require authentication, per the MVP's zero-auth, localhost-only design.

#### Scenario: No network port opened

- GIVEN the server process is started
- WHEN its runtime configuration is inspected
- THEN no TCP/HTTP listener is bound; communication occurs only via stdio

### Requirement: Import-Time Safety on Non-Windows Hosts

Importing `server.py` and its tool modules MUST NOT fail or attempt a `win32com`
import on a host where `win32com` is unavailable (e.g. this WSL2 dev/CI host).
Adapter selection MUST be deferred to first tool invocation.

#### Scenario: Module import succeeds on Linux

- GIVEN this WSL2 dev host, where `win32com` is not installed
- WHEN `server.py` is imported (e.g. by `python3.12 -m pytest -q` collecting tests)
- THEN the import succeeds with no `ModuleNotFoundError` for `win32com`
