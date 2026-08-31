# Mail Get Detail Specification

## Purpose

Fetch full, read-only detail for a single Inbox or Sent Items message
identified by its Outlook `entryId`, typically after a `mail_search` call.
Fetching a message MUST NOT mutate any mailbox state (no send, move,
delete, or read-flag change).

## Requirements

### Requirement: Get Message Input/Output

The `mail_get_message` tool MUST accept `entryId` (string, required) and
MUST return a `MessageDetail` object with `entryId`, `subject`, `sender`,
`senderAddress`, `date`, `hasAttachments`, `to` (recipient names/addresses),
and `body`. `body` MUST be the plain-text `MailItem.Body`, never
`HTMLBody`.

#### Scenario: Successful fetch

- GIVEN a fake adapter whose `get_message("MSG-1")` returns a `MessageDetail` with
  subject "Factura agosto", `sender="Ana Gómez"`, `to=["yo@example.com"]`, `body="Adjunto la factura."`
- WHEN `mail_get_message` is called with `entryId="MSG-1"`
- THEN the tool returns `subject`, `sender`, `senderAddress`, `date`, `to`, `hasAttachments`, and `body` matching the adapter's result

### Requirement: Message Not Found

The tool MUST return a clear not-found error, not a crash, when `entryId`
does not resolve to an item.

#### Scenario: Unknown or invalid entryId

- GIVEN a fake adapter whose `get_message("BAD-ID")` raises `MessageNotFoundError`
  (code `message_not_found`, simulating Outlook's `GetItemFromID` returning
  nothing/raising for a bad ID)
- WHEN `mail_get_message` is called with `entryId="BAD-ID"`
- THEN the tool returns an MCP tool error with code `message_not_found` indicating the message was not found

### Requirement: Empty Body Handling

The tool MUST return an empty string for `body` (not an error) when the
message has no body text.

#### Scenario: Message with no body text

- GIVEN a fake adapter whose `get_message("MSG-2")` returns a `MessageDetail` with `body=""`
- WHEN `mail_get_message` is called with `entryId="MSG-2"`
- THEN the tool returns successfully with `body=""` and the correct `subject`/`sender`

### Requirement: Outlook Unavailable

The tool MUST surface a clear, catchable error (not an unhandled crash) when
the underlying adapter cannot reach Outlook.

#### Scenario: COM dispatch failure

- GIVEN a fake adapter configured to raise `OutlookUnavailableError` from `get_message()`
  (simulating `win32com.client.Dispatch("Outlook.Application")` failing because
  Outlook is not installed or not running)
- WHEN `mail_get_message` is called with any `entryId`
- THEN the tool returns an MCP tool error whose message identifies Outlook as unavailable

### Requirement: No Mutation on Fetch

Fetching a message's detail MUST NOT change any mailbox state: it MUST NOT
mark the message read/unread, move it, delete it, or send anything.

#### Scenario: Fetch does not alter the message's read state

- GIVEN a fake adapter whose seeded `MessageDetail` for `entryId="MSG-3"` has no mutable read-state tracked by the fake
- WHEN `mail_get_message` is called with `entryId="MSG-3"` twice in a row
- THEN both calls return identical `MessageDetail` content and the fake adapter records no mutating call (no `Save`/`Move`/`Delete`/`UnRead` assignment)
