# Proposal: Outlook Calendar MVP MCP Server

## Intent

Enable AI clients (Claude Desktop, VSCode Agent, etc.) to query the user's Outlook
calendar in natural language — e.g. "show my notes from Monday's Tareas block" —
without any Graph/Azure setup. Outlook COM sees exactly what the desktop app sees,
so this MVP delivers a local, zero-auth MCP server that reads calendar items
(including personal appointments used as note blocks) via `pywin32`.

## Scope

### In Scope
- FastMCP server (`server.py`) running over stdio, localhost-only, no auth
- Three tools: `calendar_search`, `calendar_get_event`, `calendar_get_notes`
- Outlook COM adapter (`tools/outlook.py` or `tools/calendar.py` + adapter seam)
  wrapping `win32com.client.Dispatch("Outlook.Application")` / default calendar folder (9)
- Pydantic/dataclass schemas (`models/schemas.py`) for search results and event detail
- `config/settings.yaml` for MVP settings (e.g. default lookback window)
- `pyproject.toml` bootstrap + pytest + pytest-mock as dev dependencies (Strict TDD gate)
- Mockable COM seam so all logic is unit-testable on Linux (WSL2 dev host)

### Out of Scope
- ToDo, OneNote (V2 — Graph-based)
- Teams, SharePoint, Planner, email search (V3)
- Any authentication/authorization layer
- Non-localhost networking, remote deployment
- Real Outlook/Windows E2E testing (manual verification only, on target Windows host)

## Capabilities

### New Capabilities
- `calendar-search`: Search Outlook calendar items by date range and/or subject substring, returning a lightweight list (entryId, subject, start, end)
- `calendar-get-event`: Fetch full detail (subject, body, start/end) of a single calendar item by `entryId`
- `calendar-get-notes`: Convenience lookup combining date + subject to fetch note-style appointment bodies directly (shortcut over search + get-event)
- `outlook-com-adapter`: Mockable adapter/port around `win32com.client` Outlook access, isolating COM calls behind an interface so tests run without Windows/Outlook

### Modified Capabilities
- None (greenfield project, no existing specs)

## Approach

Python 3.12 + FastMCP server exposing the three MCP tools over stdio. All Outlook
access goes through a single adapter class (e.g. `OutlookCalendarAdapter`) implementing
a small protocol (`search(from, to, subject) -> list[EventSummary]`,
`get_event(entry_id) -> EventDetail`). Production implementation uses `win32com.client`
(imported lazily, only reached on Windows); tests inject a fake adapter implementing the
same protocol, enabling full RED-GREEN-REFACTOR on Linux. Server wiring instantiates the
real adapter only when `win32com` is importable; otherwise tools fail with a clear
runtime error (expected outcome when run outside Windows).

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `server.py` | New | FastMCP app entrypoint, registers the 3 tools, stdio transport |
| `tools/calendar.py` | New | Tool implementations calling the adapter |
| `tools/outlook_adapter.py` | New | COM adapter + fake/mock implementation seam |
| `models/schemas.py` | New | Request/response schemas for the 3 tools |
| `config/settings.yaml` | New | MVP config (e.g. default search window) |
| `pyproject.toml` | New | Project metadata, pytest + pytest-mock dev deps |
| `tests/` | New | Unit tests against the fake adapter (Strict TDD) |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| COM-dependent code accidentally imported/tested on Linux, breaking CI | Med | Lazy-import `win32com` only inside the real adapter; tests exclusively exercise the fake adapter |
| No real Windows/Outlook available to validate end-to-end | High | Document as manual verification step on target machine; keep adapter contract simple and COM calls minimal to reduce surface for drift |
| Outlook's "notes as calendar appointments" convention is ambiguous (recurring vs single items, folder scope) | Med | Scope MVP to the default calendar folder only (`GetDefaultFolder(9)`); document assumption in spec |
| pytest/pyproject bootstrap conflicts with future project tooling choices | Low | Keep `pyproject.toml` minimal (build-system + pytest config only) |

## Rollback Plan

The MVP is a new, self-contained server with no external dependents yet. Rollback =
delete `server.py`, `tools/`, `models/`, `config/`, `tests/`, and `pyproject.toml`
(or `git revert` the merge commit). No data migrations, no shared state to unwind.

## Dependencies

- `fastmcp` (or `mcp` SDK) — Python package
- `pywin32` — Windows-only, required at runtime on the target machine; NOT installed/importable in this WSL2 dev environment
- `pytest`, `pytest-mock` — dev/test dependencies (Strict TDD requirement)

## Success Criteria

- [ ] `calendar_search`, `calendar_get_event`, `calendar_get_notes` are registered and callable via FastMCP over stdio
- [ ] All three tools have unit tests passing against a fake Outlook adapter (`python3.12 -m pytest -q` green)
- [ ] No `win32com` import occurs at module load time outside the adapter's real implementation (verifiable via test run succeeding on Linux)
- [ ] Manual smoke test on a Windows host with Outlook confirms `calendar_get_notes` returns a personal-appointment body (e.g. "Tareas (...)")
