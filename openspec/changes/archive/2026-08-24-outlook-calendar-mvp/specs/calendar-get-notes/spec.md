# Calendar Get Notes Specification

## Purpose

Convenience shortcut over `calendar_search` + `calendar_get_event`: given a
calendar `date` and a `subject` substring, resolve the single matching
personal-appointment "note block" for that day and return its body directly
(e.g. "Tareas (...)" -> "Política ADN...").

## Requirements

### Requirement: Notes Input Parameters

The `calendar_get_notes` tool MUST accept `date` (ISO 8601 date, e.g.
"2026-07-27", required) and `subject` (string, required, case-insensitive
substring match).

#### Scenario: Date expanded to full-day range

- GIVEN a fake adapter recording the arguments passed to `search()`
- WHEN `calendar_get_notes` is called with `date="2026-07-27"`, `subject="Tareas"`
- THEN the adapter's `search()` MUST be invoked with `from=2026-07-27T00:00:00`
  and `to=2026-07-27T23:59:59` in the server's configured local timezone,
  and `subject="Tareas"`

### Requirement: Single Match Returns Body

When exactly one event matches the date and subject filter, the tool MUST return
its `subject` and `body` (fetched via the same get-event path as
`calendar_get_event`).

#### Scenario: Exactly one match

- GIVEN a fake adapter whose `search()` returns one `EventSummary` (entryId "ABC123")
  for the given date/subject, and whose `get_event("ABC123")` returns body
  "Política ADN\nMarco IA Responsable..."
- WHEN `calendar_get_notes` is called with `date="2026-07-27"`, `subject="Tareas"`
- THEN the tool returns `subject="Tareas (...)"` and the matching body

### Requirement: No Match Is Not Found

The tool MUST return a not-found error when zero events match the date/subject filter.

#### Scenario: Zero matches

- GIVEN a fake adapter whose `search()` returns an empty list for the given date/subject
- WHEN `calendar_get_notes` is called with `date="2026-07-27"`, `subject="Nonexistent"`
- THEN the tool returns an MCP tool error indicating no matching event was found

### Requirement: Multiple Matches Is Ambiguous

The tool MUST return an ambiguous-match error (not an arbitrary pick) when more
than one event matches the date/subject filter, listing the candidate `entryId`s
so the client can disambiguate via `calendar_search` + `calendar_get_event`.

#### Scenario: Two events share the subject substring on the same day

- GIVEN a fake adapter whose `search()` returns two `EventSummary` items
  (entryIds "ABC123" and "ABC124") for the given date/subject
- WHEN `calendar_get_notes` is called with `date="2026-07-27"`, `subject="Tareas"`
- THEN the tool returns an MCP tool error listing both `entryId`s and does not call `get_event`
