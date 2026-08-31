# Design: Outlook Calendar MVP MCP Server

## Technical Approach

A single FastMCP app (`server.py`) exposes three tools over **stdio**. All tools
call one seam class, `OutlookCalendarAdapter` (`tools/outlook_adapter.py`), via a
`CalendarPort` Protocol. The real implementation lazily imports `win32com.client`
inside its own methods (never at module scope), so `server.py`, `tools/calendar.py`,
and `models/schemas.py` remain importable on Linux. Tests inject `FakeCalendarAdapter`
(same Protocol, in-memory data) — this is what makes Strict TDD RED-GREEN-REFACTOR
possible on WSL2 with zero Windows dependency.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Transport | stdio | HTTP on 127.0.0.1 | Claude Desktop launches MCP servers as a local subprocess over stdio; zero listening socket = zero network attack surface, matches proposal's "sin puertos externos" |
| Auth | None | API key / localhost allowlist | stdio has no network identity to authenticate; process boundary (Windows session) is the trust boundary, per proposal |
| COM seam | `CalendarPort` Protocol + lazy import | Import `win32com` at module top, skip tests on non-Windows via `pytest.mark.skipif` | Protocol keeps `tools/calendar.py` COM-agnostic; lazy import (inside `__init__`/methods, not module header) guarantees `import tools.outlook_adapter` never raises on Linux, so the *same* test suite always runs, satisfying `strict_tdd: true` |
| Schemas | Pydantic `BaseModel` in `models/schemas.py` | Plain `dataclasses` | FastMCP derives tool JSON schemas from type-hinted parameters/return models; Pydantic gives validation + serialization for free and matches `fastmcp` idioms |
| Datetime handling | Tool I/O uses ISO-8601 strings with explicit UTC offset (`datetime` w/ `tzinfo`); adapter converts Outlook's naive local-time `pywintypes.datetime` using the local Windows tz (`tzlocal` or `datetime.now().astimezone().tzinfo`) | Assume all-UTC; assume naive local | Outlook COM returns times in the Outlook profile's local timezone with no explicit offset — must attach tz at the adapter boundary or comparisons/serialization silently corrupt |
| Error taxonomy | Typed exceptions in `tools/errors.py`: `OutlookUnavailableError`, `EventNotFoundError`, `AmbiguousMatchError`, caught at the tool layer and re-raised as FastMCP tool errors with a stable `code` field | Let raw `pywintypes.com_error` bubble up | Raw COM errors are opaque to the LLM caller; a small taxonomy lets `server.py` map each to a clear, actionable message |
| Project layout | Keep `server.py`, `tools/`, `models/`, `config/` from specs.md; drop `todo.py`/`onenote.py` files but keep the `tools/` package open for V2 additions | One flat `main.py` | Matches the narrative spec's structure (context in `config.yaml`) while not building unused V2 stubs |

## Data Flow

    Claude Desktop (stdio) ─▶ server.py (FastMCP)
                                   │
                     ┌─────────────┼─────────────────┐
                     ▼             ▼                 ▼
              calendar_search  calendar_get_event  calendar_get_notes
                     │             │                 │
                     └──────┬──────┴────────┬────────┘
                            ▼               │
                    tools/calendar.py ◀─────┘  (get_notes = search + get_event)
                            │
                            ▼
                  CalendarPort (Protocol)
                    /                \
   OutlookCalendarAdapter        FakeCalendarAdapter
   (real, win32com, lazy import)  (tests only)
            │
            ▼
   Outlook.Application → GetNamespace("MAPI")
     → GetDefaultFolder(9) → Items.Restrict(...) / GetItemFromID(entryId)

## File Changes

| File | Action | Description |
|---|---|---|
| `server.py` | Create | FastMCP app; registers 3 tools; stdio transport; builds real/fake adapter based on `win32com` importability |
| `tools/calendar.py` | Create | Tool functions: validate input via schemas, call adapter, map domain errors to tool errors |
| `tools/outlook_adapter.py` | Create | `CalendarPort` Protocol + `OutlookCalendarAdapter` (lazy `win32com` import inside methods) |
| `tools/fake_adapter.py` | Create | `FakeCalendarAdapter` implementing `CalendarPort` for tests |
| `tools/errors.py` | Create | `OutlookUnavailableError`, `EventNotFoundError`, `AmbiguousMatchError` |
| `models/schemas.py` | Create | Pydantic models: `EventSummary`, `EventDetail`, `SearchRequest`, `GetEventRequest`, `GetNotesRequest` |
| `config/settings.yaml` | Create | Default lookback window, folder id (9), timezone override (optional) |
| `pyproject.toml` | Create | `[project]` metadata, `fastmcp`/`pywin32` deps (`pywin32; sys_platform == 'win32'`), `pytest`/`pytest-mock` dev deps, `[tool.pytest.ini_options]` |
| `tests/test_calendar_tools.py` | Create | Unit tests against `FakeCalendarAdapter` for all 3 tools |
| `tests/test_outlook_adapter.py` | Create | Tests for adapter's date/tz/error mapping logic, COM objects mocked via `pytest-mock` |

## Interfaces / Contracts

```python
# tools/outlook_adapter.py
class CalendarPort(Protocol):
    def search(self, date_from: datetime, date_to: datetime,
               subject: str | None = None) -> list[EventSummary]: ...
    def get_event(self, entry_id: str) -> EventDetail: ...

# models/schemas.py
class EventSummary(BaseModel):
    entry_id: str
    subject: str
    start: datetime  # tz-aware
    end: datetime

class EventDetail(EventSummary):
    body: str
```

`GetItemFromID(entryId)` is used for `calendar_get_event` (not a re-`Restrict` scan).
`Items.Restrict` filters use the `[Start] >= '...' AND [End] <= '...'` DASL string
format; `IncludeRecurrences = True` MUST be set only when a bounded `Sort("[Start]")`
is also applied — otherwise recurring masters yield unbounded expansion. MVP restricts
to `GetDefaultFolder(9)` (non-recurring personal note-appointments are the target use
case); recurring-series edge cases are documented as a known limitation, not solved.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit (tools) | Input validation, error mapping, response shaping | `FakeCalendarAdapter` injected via constructor/DI in `server.py` |
| Unit (adapter) | Date/tz conversion, DASL restrict string building, error taxonomy mapping | `pytest-mock` fakes `win32com.client.Dispatch` return value; real adapter method logic exercised, COM itself never touched |
| Integration | Tool registration + stdio round-trip | FastMCP's in-process test client against the fake-backed server |
| E2E | Real Outlook returns note bodies | Manual only, on Windows host (out of CI scope per proposal) |

## Migration / Rollout

No migration required — greenfield. Rollout: run `pip install .` (or `uv sync`) under
**Windows Python 3.12** (not WSL), then point Claude Desktop's `claude_desktop_config.json`
`mcpServers` entry at that Windows Python interpreter with `server.py` as the stdio
command. Development/CI stays entirely on WSL2 using the fake adapter.

## Open Questions

- [ ] None blocking — recurring-appointment expansion behavior is deferred as a
      documented MVP limitation, not an open design question.
