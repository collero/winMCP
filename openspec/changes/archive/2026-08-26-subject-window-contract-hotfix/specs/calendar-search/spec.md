# Delta for Calendar Search

## ADDED Requirements

### Requirement: Subject-Only Search Uses a Symmetric, Forward-Leaning Default Window, Reported Honestly

BUG-008 hotfix (2026-08-26): a `calendar_search` request that supplies
`subject` but neither `from` nor `to` MUST auto-apply a dedicated,
symmetric, forward-leaning default window —
`calendar_subject_search_lookback_days` (default `90`) days back and
`calendar_subject_search_lookahead_days` (default `365`) days forward
from now — rather than the backward-only `lookback_days` window used to
fill a *partially* explicit range. A backward-only default can never
answer "when is my next X?", the most common calendar question there is.

The tool MUST report the window it actually applied via an optional
`windowApplied` field (`{"from": ..., "to": ...}`) on the response,
populated ONLY when the request was subject-only and a window was
therefore auto-applied — never when explicit `from`/`to` were supplied.
`resultsTruncated` MUST NOT be overloaded to signal this; an empty
subject-only result MUST still carry `windowApplied` so a caller can
distinguish "no such appointment" from "outside a window it was never
told about". An explicit `from`/`to` (even alongside `subject`) always
takes full precedence over this default and MAY widen or narrow the
search — caller-controlled, unchanged from existing behavior.

#### Scenario: Subject-only search finds an appointment months in the past

- GIVEN a fake adapter seeded with an event dated 60 days before a frozen "now", matching subject "Cumpleanos Ada"
- WHEN `calendar_search` is called with `subject="Cumpleanos Ada"` and no `from`/`to`
- THEN the event is returned

#### Scenario: Subject-only search finds an appointment tomorrow

- GIVEN a fake adapter seeded with an event dated 1 day after a frozen "now", matching subject "AGC-COS"
- WHEN `calendar_search` is called with `subject="AGC-COS"` and no `from`/`to`
- THEN the event is returned

#### Scenario: Subject-only search reports the window it applied

- GIVEN a fake adapter seeded with no events
- WHEN `calendar_search` is called with `subject="Nonexistent"` and no `from`/`to`
- THEN the response's `results` list is empty
- AND the response's `windowApplied` field is populated with the resolved `from`/`to` bounds

#### Scenario: Explicit-bounds search never reports a window

- WHEN `calendar_search` is called with explicit `from`/`to` (with or without `subject`)
- THEN the response's `windowApplied` field is absent/null
