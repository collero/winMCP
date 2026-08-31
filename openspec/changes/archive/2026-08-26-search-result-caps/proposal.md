# Proposal: Search Result Caps (BUG-002)

## Intent

`mail_search`/`calendar_search` have no result cap: `mail_search
{"folder":"inbox","subject":"a"}` returned 791,567 chars (thousands of
rows) live; a widened calendar window returned 240 events (~60KB). This
is denial-of-tool-by-success — no error, so no retry/narrowing helps;
the caller just loses the turn. `task_search {}` tops out at ~25 items
today (fine) but should be capped for defense-in-depth. Rows are
already summary-shaped (no bodies) — the payload is row COUNT, so the
fix is a limit, not a body trim.

## Scope

### In Scope
- Optional `limit` param on all three search tools; consistent default
  (50), hard max 200 (matches `file_search`'s cap convention).
- `results_truncated: true` when the cap cut results.
- Newest-first ordering (truncated page = the useful half).
- Explicit spec requirement that rows stay summary-shaped (no bodies).

### Out of Scope
- `entryId` shortening, X500→SMTP resolution, offset/cursor paging
  (future polish).
- Any `Restrict()` DASL date-filter string change — owned by the
  concurrent sibling change `outlook-date-locale-fix`.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `mail-search`, `calendar-search`, `task-search`: each adds a `limit`
  request param + `results_truncated` response signal + newest-first
  (or due-date-priority, for tasks) ordering guarantee.

## Approach

Thread an optional `limit` (default 50, max 200, validated before any
adapter call) through each tool into its adapter's `search()`, which
bounds at the source (sorted COM `Items`, limited during iteration —
not fetched unbounded and truncated client-side), mirroring
`file_search`'s `TOP n` precedent. Each response signals truncation via
`results_truncated`. Since today's three tools return a plain
`list[XSummary]` with no envelope, exposing that flag requires a
response-shape decision — left for `sdd-design`.

## Affected Areas

| Area | Impact |
|------|--------|
| `models/schemas.py` | Add `limit` to the 3 request models; add a response shape carrying `results_truncated` |
| `tools/mail.py`, `tools/calendar.py`, `tools/tasks.py` | Validate/default `limit`, pass to adapter, thread truncation signal |
| `tools/mail_adapter.py`, `tools/outlook_adapter.py`, `tools/task_adapter.py` | `search()` gains `limit` bound + newest-first/due-date ordering |
| `tools/fake_mail_adapter.py`, `fake_adapter.py`, `fake_task_adapter.py` | Fakes mirror real adapters' limit/order/truncation, per Strict TDD |
| `config/settings.yaml`, `server.py` | Possibly modified — config keys for default/max; MCP signature if envelope changes it |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| File-level collision with sibling `outlook-date-locale-fix` (also edits `tools/mail_adapter.py`/`tools/outlook_adapter.py`, fixing `Restrict()` date strings) | High | This change touches only ordering/limit logic, never date-string builders; land in small separable diffs; rebase whichever lands second |
| Windows-only COM runtime; dev/CI is WSL2 Linux, mocked COM | Certain | All new adapter behavior exercised via mocked `win32com.client` fakes; no real-Outlook verification here — manual smoke test flagged |
| Response envelope breaks plain-`list` return, could ripple into `server.py`/callers | Medium | Resolve explicitly in `sdd-design`; least-invasive shape; `*_get_*` tools untouched |
| Newest-first ordering could alter fixtures assuming insertion order | Low | Audit/update `tests/test_{mail,calendar,tasks}_tools.py` and fakes during `sdd-apply` |

## Rollback Plan

Each file is independently revertible via `git revert` — no data
migration, no persisted format change. `limit` is additive/optional
with a safe default, so rollback removes the param/flag with no
behavioral difference for callers that never passed `limit`.

## Dependencies

- Coordinate file-touch timing with `outlook-date-locale-fix` (same two
  adapter files) to avoid a large merge conflict.

## Success Criteria

- [ ] `mail_search {"folder":"inbox","subject":"a"}` returns a bounded
      response with `results_truncated: true`.
- [ ] A 3-month `calendar_search` window returns at most `limit` events.
- [ ] `task_search {}` keeps working, plus the new optional fields.
- [ ] All behavior covered by mocked-COM tests; `python3.12 -m pytest -q` passes.
