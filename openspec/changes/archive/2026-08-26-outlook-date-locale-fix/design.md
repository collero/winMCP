# Design: Fix Locale-Ambiguous Date Filters in Outlook Restrict() Calls

## Technical Approach

Replace `_dasl_datetime()`'s `strftime("%m/%d/%Y %I:%M %p")` in both
`tools/outlook_adapter.py` and `tools/mail_adapter.py` with an
ISO-ordered, 24-hour literal (`"%Y-%m-%d %H:%M"`, e.g. `2026-03-12 00:00`).
As defense-in-depth against any residual Restrict()-parsing surprise
(unverifiable on this Linux dev host — real Outlook is Windows-only), each
adapter's `search()` adds one cheap Python-side boundary re-check after
`Restrict()` returns, dropping any item whose actual date falls outside
`[date_from, date_to]`. `tools/task_adapter.py` is untouched — it never
calls `Restrict()` on due date.

## Architecture Decisions

### Decision: ISO-ordered, year-first literal format

**Choice**: `"%Y-%m-%d %H:%M"` (e.g. `2026-03-12 09:00`), replacing
`"%m/%d/%Y %I:%M %p"`.
**Alternatives considered**: (a) keep `MM/DD/YYYY` but force it via a
Windows API locale override at process start — rejected, invasive,
affects the whole process, not testable on Linux CI. (b) Rewrite
calendar/mail date filtering as fully Python-side per-item filtering
(mirroring `task_adapter.py`) — rejected as the *sole* fix: correctness
would be fine, but the proposal flags mail folders as large, and losing
`Restrict()`'s server-side narrowing entirely is a real performance
regression for a fix that doesn't need it. (c) DASL `@SQL=` syntax with
an explicit OLE-DB date literal — more invasive rewrite of the filter
string builder for uncertain additional benefit.
**Rationale**: A 4-digit year in the leading position admits exactly one
valid calendar-date reading — no locale's short-date order places a
4-digit token in the day or month slot, so `yyyy-mm-dd` cannot be
transposed the way `mm/dd`/`dd/mm` can. This "unambiguous by construction"
property is why ISO 8601 exists and is the standard documented workaround
for this exact class of Jet/DASL date-literal ambiguity. Switching to a
24-hour clock also removes a second, smaller locale hazard: the AM/PM
marker itself is localized (e.g. es-ES renders "a.m."/"p.m."), which
`strftime("%p")` does not account for.

### Decision: Python-side post-filter as defense-in-depth, not a replacement

**Choice**: Keep `Restrict()` as the primary narrowing mechanism; add a
boundary re-check (`item.Start/End` or `item.ReceivedTime/SentOn` compared
to `date_from`/`date_to` in Python) on the items `Restrict()` returns.
**Alternatives considered**: No post-filter (trust the format alone) —
rejected because this fix cannot be verified against real Outlook from
this WSL2 dev host; a cheap correctness backstop over an already-narrowed
result set costs nothing.
**Rationale**: This only guards against Restrict() over-including items
(false positives), not under-including (a mis-parsed bound could still
silently narrow the server-side scan too far). That residual risk is
accepted and flagged under Open Questions — it cannot be resolved without
a real Windows/Outlook host.

### Decision: Duplicate the fix per module, not extract a shared helper

**Choice**: Edit each module's own `_dasl_datetime()` in place, keeping
the existing "Mirrors `tools/outlook_adapter.py::_dasl_datetime`" note.
**Rationale**: Matches the established pattern in this codebase (`_to_aware`
is already duplicated+mirrored across all three adapter modules). A shared
`tools/dasl.py` is out of scope for a CRITICAL, time-sensitive bug fix.

## Data Flow

    calendar_search/mail_search (tool layer, unchanged)
              │
              ▼
    adapter.search(date_from, date_to, ...)
              │
              ▼
    _dasl_datetime(dt)  ──►  "yyyy-mm-dd HH:MM" literal (was "mm/dd/yyyy hh:mm AMPM")
              │
              ▼
    Items.Restrict("[Field] >= '...' AND [Field] <= '...'")
              │
              ▼
    NEW: Python boundary re-check per returned item (drop if outside range)
              │
              ▼
    existing subject/sender/status filtering (unchanged)

## File Changes

| File | Action | Description |
|------|--------|--------------|
| `tools/outlook_adapter.py` | Modify | `_dasl_datetime()` format string; add boundary re-check in `search()` |
| `tools/mail_adapter.py` | Modify | Same, mirrored, for `folder`-mapped searches (`folder_path` already filters in Python, untouched) |
| `tests/test_outlook_adapter.py` | Modify | Regression scenarios (June/March-April/control), literal-format assertion |
| `tests/test_mail_adapter.py` | Modify | Same, mirrored |

## Interfaces / Contracts

```python
def _dasl_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")
```

No signature or return-type changes to any adapter method; `EventSummary`/
`MessageSummary` output shape is unaffected.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `_dasl_datetime()` output format | Direct assertion on the literal string for fixed inputs, incl. day-of-month values `06`, `09`, `12` |
| Integration (mocked COM) | `Restrict()` clause content + boundary re-check | Mocked `win32com` per existing `mocker.Mock` pattern; seed items both inside and outside the requested range to prove the Python re-check drops stragglers |
| Regression | The three live-confirmed date shapes, calendar + mail | Per the delta specs' scenarios (`06-06`/`06-09`, `03-12`/`04-12`, `06-20`/`06-25`) |
| E2E | Real Outlook, real es-ES locale | Not available in this dev environment (Windows-only); manual verification on the target machine, per `openspec/config.yaml`'s existing e2e note |

## Migration / Rollout

No migration required. Pure function/logic change; redeploy reverts fully
(see proposal's Rollback Plan).

## Open Questions

- [ ] Non-blocking: the ISO-literal fix is well-documented Jet/DASL
      behavior but cannot be confirmed against a real es-ES Outlook client
      from this Linux dev host. Recommend a manual live-Outlook smoke
      check (repeating the original bug report's Case 1/Case 4 queries)
      after deployment, before closing this out as fully verified.
