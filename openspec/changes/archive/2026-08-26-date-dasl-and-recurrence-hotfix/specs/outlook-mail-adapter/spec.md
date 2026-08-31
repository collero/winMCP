# Delta for Outlook Mail Adapter

## ADDED Requirements

### Requirement: DASL `@SQL=` Restrict Date Literals, Not Jet Bracket Syntax

`OutlookMailAdapter.search()`'s `Items.Restrict()` date-range clause (for
`folder="inbox"`/`"sent"`/`"drafts"`) MUST compare `_dasl_datetime()`'s
ISO-ordered literal via DASL `@SQL=` syntax against a quoted property
URN — `"urn:schemas:httpmail:datereceived"` for inbox,
`"urn:schemas:httpmail:datesent"` for sent, and the MAPI property-tag URN
`"http://schemas.microsoft.com/mapi/proptag/0x30080040"` (
`PR_LAST_MODIFICATION_TIME`) for drafts — never Jet's bare
bracket-property syntax (`[ReceivedTime] >= '...'`). Live evidence
(BUG-004, 2026-08-26) showed that even an ISO-ordered literal is still
misparsed by Jet under an es-ES Outlook client when compared via bracket
syntax: the lower bound's day was read as transposed whenever it was
`<= 12`, inverting the range and returning `[]` with no error. This
applies only to `folder`-mapped searches; `folder_path` searches already
skip `Restrict()` entirely and are unaffected. `Sort()` (used to establish
newest-first COM-source order for the early-stop convention) keeps using
the bracket property name — sorting by property carries no date-literal
locale risk.

#### Scenario: Inbox Restrict() clause uses DASL @SQL= syntax with a quoted property URN

- GIVEN a mocked `win32com.client` module
- WHEN `OutlookMailAdapter().search(folder="inbox", date_from, date_to)` builds its `Restrict()` clause
- THEN the emitted string starts with `@SQL="urn:schemas:httpmail:datereceived" >=`
- AND never contains the bare bracket form `[ReceivedTime]`

#### Scenario: Lower bound with day <= 12 is not transposed

- GIVEN a mocked `win32com.client` module whose Inbox `Items` are seeded with a message on 2026-01-08 and one on 2026-02-06
- WHEN `OutlookMailAdapter().search(folder="inbox", date_from=2026-01-08T00:00:00, date_to=2026-02-08T23:59:59)` is called
- THEN both messages are returned (an inverted-range misread would have excluded the 2026-01-08 message or returned nothing at all)
