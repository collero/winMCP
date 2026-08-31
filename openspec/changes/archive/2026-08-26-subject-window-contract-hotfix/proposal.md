# Proposal: Subject-Only Search Window Contract Hotfix

## Intent

A live-Outlook bug report (BUG-008, 2026-08-26, cowork -> cc, es-ES) plus a
correction to an earlier report (0041): `calendar_search`'s `subject` filter
is not dead — it works — but a subject-only query (no explicit `from`/`to`)
silently applies the `lookback_days`-derived backward-only window as the
adapter's bounding range. This has two live-evidence failures and one
honesty problem:

1. **Cannot see the future.** The window only ever reaches back from "now"
   to "now" — never forward. "AGC-COS" (tomorrow, 27 August) can never be
   found by subject alone, which breaks the single most common calendar
   question: "when is my next X?".
2. **Cannot see far enough back.** "Cumpleanos Ada" (22 June, ~2 months
   before the report date) fell outside the 7-day `lookback_days` window
   and returned `[]`.
3. **Silent.** `{"results":[],"resultsTruncated":false}` is byte-identical
   whether the appointment does not exist or whether it exists just outside
   an undocumented window. `resultsTruncated: false` actively asserts
   completeness the tool never delivered.

The earlier `date-dasl-and-recurrence-hotfix` change (BUG-005 part 1) fixed
a *different* symptom (the Python-side boundary re-check dropping matches
outside the auto-filled window) but left the window itself
backward-only/undocumented — this change fixes the window's shape and
honesty, not the boundary-recheck skip (which remains correct and
untouched).

## Scope

- `config/settings.yaml` — two new keys:
  `calendar_subject_search_lookback_days` (default `90`),
  `calendar_subject_search_lookahead_days` (default `365`).
- `tools/settings.py` — `calendar_subject_search_lookback_days()`/
  `calendar_subject_search_lookahead_days()` live-read accessors, mirroring
  `resolve_search_limit()`'s discipline.
- `tools/calendar.py` — `calendar_search`: a subject-only request (no
  explicit `from`/`to`) now resolves its adapter-bounding window via a new
  `_subject_search_window()` (symmetric, forward-leaning) instead of
  `_normalize_search_bounds()`'s backward-only branch, and populates the
  new `window_applied` field on the response. A `_now()` seam replaces the
  inline `datetime.now(timezone.utc)` call so tests can freeze "now"
  deterministically.
- `models/schemas.py` — new `SearchWindow` model; `CalendarSearchResult`
  gains an optional `window_applied` field (alias `windowApplied`, default
  `None`), populated only for an auto-windowed subject-only query.
- `server.py` — `calendar_search` tool description documents the default
  window and that explicit `from`/`to` override it (the description is the
  only contract an agent caller sees).
- `openspec/specs/calendar-search/spec.md` — new requirement + scenarios.
- Out of scope: `tools/outlook_adapter.py`'s `enforce_date_bounds` skip
  (BUG-005 part 1, already correct and untouched); `_normalize_search_bounds()`'s
  partial-explicit-range behavior (only one of `from`/`to` given — unaffected,
  still uses `lookback_days`).

## Non-Goals

- No change to `lookback_days`'s value or its use for partially-explicit
  ranges.
- No change to `resultsTruncated`'s existing semantics (search-result-caps,
  BUG-002) — `windowApplied` is a separate field, not an overload.
- No live-Outlook (es-ES) manual verification from this Linux dev host —
  all scenarios below are mocked/faked, per project convention.
