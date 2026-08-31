# Calendar Get Event Specification

## Purpose

Fetch full detail — subject, body, start, and end — for a single calendar item
identified by its Outlook `entryId`, typically after a `calendar_search` call.

## Requirements

### Requirement: Get Event Input/Output

The `calendar_get_event` tool MUST accept `entryId` (string, required) and MUST
return an object with `entryId`, `subject`, `body`, `start`, and `end`.

#### Scenario: Successful fetch

- GIVEN a fake adapter whose `get_event("ABC123")` returns an `EventDetail` with
  subject "Tareas (...)" and body "Política ADN\nMarco IA Responsable..."
- WHEN `calendar_get_event` is called with `entryId="ABC123"`
- THEN the tool returns `subject`, `body`, `start`, and `end` matching the adapter's result

### Requirement: Event Not Found

The tool MUST return a clear not-found error, not a crash, when `entryId` does not
resolve to an item.

#### Scenario: Unknown or invalid entryId

- GIVEN a fake adapter whose `get_event("BAD-ID")` raises `EventNotFoundError`
  (simulating Outlook's `GetItemFromID` returning nothing/raising for a bad ID)
- WHEN `calendar_get_event` is called with `entryId="BAD-ID"`
- THEN the tool returns an MCP tool error indicating the event was not found

### Requirement: Empty Body Handling

The tool MUST return an empty string for `body` (not an error) when the calendar
item has no body/notes text.

#### Scenario: Appointment with no notes

- GIVEN a fake adapter whose `get_event("XYZ789")` returns an `EventDetail` with `body=""`
- WHEN `calendar_get_event` is called with `entryId="XYZ789"`
- THEN the tool returns successfully with `body=""` and the correct `subject`/`start`/`end`
