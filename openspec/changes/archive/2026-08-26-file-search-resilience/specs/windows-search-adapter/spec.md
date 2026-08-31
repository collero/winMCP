# Delta for Windows Search Adapter

## ADDED Requirements

### Requirement: Fallback Transport Ordering

For any query that needs the index (`phrase` search, or `file_get_info`
enrichment), the adapter-facing seam MUST attempt the ADO
(`WindowsSearchAdapter`) transport first. Only when ADO raises
`WindowsSearchUnavailableError` MUST it attempt the PowerShell bridge
(`powershell-search-bridge` capability) as a second transport. If the
bridge also raises `WindowsSearchUnavailableError`, that exception
propagates to the tool layer unchanged; the tool layer (not this seam)
is responsible for adding the filename-still-works messaging before it
reaches the caller (see the `file-search` delta's "Windows Search
Unavailable" requirement) — this seam stays config- and message-neutral,
consistent with the adapter's existing config-unaware design.

#### Scenario: ADO success skips the bridge entirely

- GIVEN a fake ADO adapter returning results and a bridge that would raise if invoked
- WHEN a `phrase` query executes
- THEN the bridge is never invoked

#### Scenario: ADO failure falls through to the bridge, which succeeds

- GIVEN a fake ADO adapter raising `WindowsSearchUnavailableError` and a mocked bridge returning results
- WHEN a `phrase` query executes
- THEN the bridge's results are returned and no error propagates

#### Scenario: Both transports exhausted propagates the typed error unchanged

- GIVEN a fake ADO adapter and a mocked bridge that both raise `WindowsSearchUnavailableError`
- WHEN a `phrase` query executes
- THEN `WindowsSearchUnavailableError` propagates to the tool layer, with no filename-still-works text added at this layer

### Requirement: Enrichment Lookups Use the Same Fallback Ordering

`file_get_info`'s index-enrichment lookup (for `kind`/`snippet`) MUST use
the same ADO-then-bridge ordering as `phrase` search, and MUST raise
`WindowsSearchUnavailableError` (not `FileNotFoundInIndexError`) when
both transports fail to reach the index — a miss (path not indexed) is
distinguished from unreachability at this seam so the tool layer can
treat both as "no enrichment available" without conflating them
internally.

#### Scenario: Enrichment lookup falls back to the bridge

- GIVEN a fake ADO adapter raising `WindowsSearchUnavailableError` for `get_info()`, and a mocked bridge returning enrichment data
- WHEN `file_get_info` attempts enrichment for an indexed path
- THEN the bridge's `kind`/`snippet` values are used

#### Scenario: Enrichment lookup exhausted raises the unavailable error, not not-found

- GIVEN both ADO and the bridge raising `WindowsSearchUnavailableError` for `get_info()`
- WHEN `file_get_info` attempts enrichment
- THEN `WindowsSearchUnavailableError` propagates from this seam, not `FileNotFoundInIndexError`
