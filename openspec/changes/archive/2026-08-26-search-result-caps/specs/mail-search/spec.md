# Delta for mail-search

## ADDED Requirements

### Requirement: Result Limit Parameter

The `mail_search` tool MUST accept an optional `limit` (integer) request
parameter bounding the number of `MessageSummary` rows returned. When
omitted, `limit` defaults to `50`. When provided and less than or equal
to `0`, the tool MUST reject the call as a `ValueError` before any
adapter call. When provided and greater than `200`, the tool MUST clamp
it to `200` (never reject) — `200` is the hard maximum, matching
`file_search`'s existing cap convention. The adapter MUST apply the
(defaulted/clamped) limit at the source — bounding item iteration/COM
retrieval — never fetching an unbounded set and truncating client-side.

#### Scenario: Default limit applied when omitted

- GIVEN a mocked `win32com.client` Inbox `Items` collection seeded with 120 messages all matching `subject="a"`
- WHEN `mail_search` is called with `folder="inbox"`, `subject="a"`, `limit` omitted
- THEN exactly 50 `MessageSummary` items are returned

#### Scenario: Oversized subject search is bounded and flagged

- GIVEN a mocked `win32com.client` Inbox `Items` collection seeded with 1000 messages matching `subject="a"`
- WHEN `mail_search` is called with `folder="inbox"`, `subject="a"` (`limit` omitted, default 50 applies)
- THEN the response is bounded to 50 rows
- AND `results_truncated` is `true`

#### Scenario: limit above hard max is clamped, not rejected

- GIVEN a mocked adapter seeded with 500 matching messages
- WHEN `mail_search` is called with `folder="inbox"`, `subject="a"`, `limit=10000`
- THEN the adapter's `search()` is invoked with a limit of `200`, not `10000`, and no error is raised

#### Scenario: Non-positive limit is rejected

- WHEN `mail_search` is called with `folder="inbox"`, `subject="a"`, `limit=0`
- THEN the tool raises a `ValueError` before calling the adapter

### Requirement: Newest-First Ordering

`mail_search` results MUST be ordered newest-first by the same `date`
field used in `MessageSummary` (`ReceivedTime` for `inbox`,
`SentOn` for `sent`), so that when the cap truncates results the
returned page is the most recent, most useful subset.

#### Scenario: Out-of-order source items are returned newest-first

- GIVEN a mocked Inbox `Items` collection seeded with 3 messages received out of chronological order (e.g. Aug 10, Aug 1, Aug 20)
- WHEN `mail_search` is called with `folder="inbox"`, `subject` matching all three
- THEN the returned `MessageSummary` list is ordered Aug 20, Aug 10, Aug 1 (newest first)

## MODIFIED Requirements

### Requirement: Search Output Shape

The tool MUST return `MessageSummary` objects containing `entryId`,
`subject`, `sender` (display name), `senderAddress`, `date` (a single
ISO 8601 timestamp normalized from `ReceivedTime` for `inbox` or
`SentOn` for `sent`), and `hasAttachments` (boolean). It MUST NOT
include the message body — this is unchanged by this change and MUST
NOT regress; bodies remain available only via `mail_get_message`. The
response MUST additionally convey a `results_truncated` boolean value
that is `true` when the effective `limit` cut the true match count, and
`false` (or absent, treated as falsy) otherwise. The exact response
shape carrying `results_truncated` alongside the row list is an
implementation decision left to `design.md`.
(Previously: returned a plain list of `MessageSummary` with no
truncation signal and no documented cap.)

#### Scenario: Empty result set

- GIVEN a fake adapter whose `search()` returns an empty list for the given filters
- WHEN `mail_search` is called with `folder="inbox"`, `subject="Nonexistent"`
- THEN the tool returns an empty result with `results_truncated` falsy, not an error

#### Scenario: Filterless-of-cap search is not marked truncated

- GIVEN a mocked Inbox `Items` collection seeded with 10 messages matching `subject="factura"`
- WHEN `mail_search` is called with `folder="inbox"`, `subject="factura"`, `limit=50`
- THEN all 10 `MessageSummary` items are returned
- AND `results_truncated` is `false`

#### Scenario: Rows never carry body content

- GIVEN a mocked Inbox `Items` collection seeded with a message that has a large `Body` property
- WHEN `mail_search` is called with `folder="inbox"`, `subject` matching that message
- THEN the returned `MessageSummary` contains no body field of any kind
