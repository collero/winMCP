# Apply Progress: Datetime Timezone-Comparison Hotfix

**Mode**: Strict TDD (runner: `.venv/bin/python3.12 -m pytest -q`)

## Baseline

`451 passed` confirmed before any change (Phase 0).

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1/1.2 Calendar adapter | `tests/test_outlook_adapter.py` | Unit | ✅ 23/23 (pre-fix, file total before these 2) | ✅ Written — aware-item/naive-bound test failed with `TypeError: can't compare offset-naive and offset-aware datetimes` at `outlook_adapter.py:162`; naive-item/aware-bound test failed on first bound-width attempt (`AssertionError: assert [] == ['ALLDAY1']`, a test-fixture width issue, not the bug — widened the bound window and it passed pre-fix, confirming it's a *defensive* case, not a RED case) | ✅ Both pass after normalizing `date_from`/`date_to` via `_to_aware()` | ✅ 2 cases (aware-item/naive-bound; naive-item/aware-bound) | ➖ None needed — 2-line addition at the top of `search()` |
| 2.1/2.2 Mail adapter | `tests/test_mail_adapter.py` | Unit | ✅ 43/43 (pre-fix) | ✅ Written — both new tests failed with the exact reported `TypeError` at `mail_adapter.py:177` inside `_matches_date_bounds` (inbox path and folder_path path both route through this one function) | ✅ Both pass after normalizing `date_from`/`date_to` inside `_matches_date_bounds()` | ✅ 2 cases (inbox boundary re-check; folder_path boundary-check + sort) | ➖ None needed |
| 3.1/3.2 Task adapter (defensive) | `tests/test_task_adapter.py` | Unit | ✅ 19/19 (pre-fix) | ✅ Written — failed with the identical `TypeError` at `task_adapter.py:126` inside `_passes_due_date_filter`, proving the same latent defect exists even though task_search wasn't the reported failure | ✅ Passes after normalizing `date_from`/`date_to` in `search()` before the filtering loop | ✅ 1 case (aware `DueDate` vs naive bound) | ➖ None needed |

### Test Summary
- **Total tests written**: 5 (2 calendar, 2 mail, 1 task)
- **Total tests passing**: 456 (451 baseline + 5 new)
- **Layers used**: Unit (5)
- **Approval tests** (refactoring): None
- **Pure functions created**: 0 — fix normalizes existing comparison sites, no new abstraction (per design.md's "duplicate the fix per module" precedent from the BUG-003 locale fix — consistency over novelty)

## Root Cause (confirmed via RED reproduction)

Real Outlook COM datetime properties (`item.Start`, `ReceivedTime`,
`SentOn`, `LastModificationTime`, `DueDate`) are timezone-**aware**
(`pywintypes.datetime`, fixed offset) on real Windows. `SearchRequest`/
`MailSearchRequest`/`TaskSearchRequest`'s `date_from`/`date_to` fields
(`models/schemas.py`) carry no tz-aware validator, so the request-bound
side of the comparison can be **naive**. Each adapter's `_to_aware()` was
applied only to the COM-item side, never to the bound side — comparing
aware `start`/`ReceivedTime`/`due_date` against a naive `date_from`/
`date_to` raised the exact reported `TypeError`. Confirmed which side was
naive by writing the RED test with the item side aware (matching real
pywintypes) and the bound side naive — this reproduced the production
traceback verbatim, on the first attempt, at the exact comparison line
named in each module.

## Command Log (RED confirmation)

```
$ .venv/bin/python3.12 -m pytest -q tests/test_outlook_adapter.py::test_search_aware_com_datetime_vs_naive_request_bound_does_not_raise
FAILED — TypeError: can't compare offset-naive and offset-aware datetimes
  at tools/outlook_adapter.py:162: if start < date_from or end > date_to:

$ .venv/bin/python3.12 -m pytest -q tests/test_mail_adapter.py::test_search_aware_com_received_time_vs_naive_request_bound_does_not_raise tests/test_mail_adapter.py::test_folder_path_search_aware_item_vs_naive_bound_sort_does_not_raise
2 failed — both: TypeError: can't compare offset-naive and offset-aware datetimes
  at tools/mail_adapter.py:177: if date_from is not None and aware < date_from:

$ .venv/bin/python3.12 -m pytest -q tests/test_task_adapter.py::test_search_aware_com_due_date_vs_naive_request_bound_does_not_raise
FAILED — TypeError: can't compare offset-naive and offset-aware datetimes
  at tools/task_adapter.py:126: if date_from is not None and due_date < date_from:

$ .venv/bin/python3.12 -m pytest -q
4 failed, 452 passed   # (the 5th new test — naive-item/aware-bound — was
                        # already green pre-fix; it's a defensive
                        # companion case, not a RED case)
```

## Command Log (GREEN + full suite)

```
$ .venv/bin/python3.12 -m pytest -q
456 passed in 2.28s
```

Zero regressions across the full suite.

## Files Changed

| File | Action | What Was Done |
|------|--------|----------------|
| `tools/outlook_adapter.py` | Modified | `search()`: `date_from = _to_aware(date_from, tz)`; `date_to = _to_aware(date_to, tz)`, added immediately after `tz = local_timezone()`, before the boundary re-check loop. |
| `tools/mail_adapter.py` | Modified | `_matches_date_bounds()`: wrapped `date_from`/`date_to` in `_to_aware(_, tz)` at both comparison points. Single fix covers inbox/sent/drafts (defense-in-depth) and folder_path (primary date filter). |
| `tools/task_adapter.py` | Modified | `search()`: `date_from = _to_aware(date_from, tz) if date_from is not None else None` (same for `date_to`), added right after `tz = local_timezone()`, before the filtering loop. Defensive — not the reported failure, but the identical latent defect. |
| `tests/test_outlook_adapter.py` | Modified | Added `timedelta` import; 2 new tests (aware-item/naive-bound RED case; naive-item/aware-bound defensive case). |
| `tests/test_mail_adapter.py` | Modified | Added `timedelta` import; 2 new tests (inbox aware-`ReceivedTime`/naive-bound; folder_path aware-items/naive-bound through the sort path). |
| `tests/test_task_adapter.py` | Modified | Added `timedelta` import; 1 new defensive test (aware `DueDate`/naive-bound). |
| `openspec/specs/outlook-com-adapter/spec.md` | Modified | New "Timezone-Aware Boundary Comparisons" requirement + 2 scenarios. |
| `openspec/specs/outlook-mail-adapter/spec.md` | Modified | New "Timezone-Aware Boundary Comparisons" requirement + 2 scenarios. |
| `openspec/changes/archive/2026-08-26-datetime-tz-hotfix/{proposal,tasks,apply-progress}.md` | Created | This hotfix's record. |

## Deviations from Design

- Scope was expanded beyond the two reported tools (`calendar_search`,
  `mail_search`) to also defensively fix `task_search`'s
  `_passes_due_date_filter`, after investigation showed it shares the
  exact same code shape and the exact same gap in
  `TaskSearchRequest`'s schema (no tz-aware validator on `date_from`/
  `date_to`). `task_search` not failing in the field QA session does not
  mean the path is safe — it means it wasn't exercised with an explicit
  `dueFrom`/`dueTo` bound. Fixed to the same standard as calendar/mail
  rather than leaving a known-identical latent bug in place.
- No cross-module shared helper was introduced. `tests/test_outlook_adapter.py`'s
  `test_calendar_and_mail_dasl_datetime_emit_identical_literal` docstring
  cites design.md's prior "Duplicate the fix per module, not extract a
  shared helper" decision from the BUG-003 locale fix; this hotfix follows
  the same precedent — each module's existing `_to_aware()` was reused for
  both sides of its own comparisons, no new abstraction.

## Issues Found

One test-authoring pitfall, not a production bug: the first draft of
`test_search_naive_all_day_item_vs_aware_request_bound_does_not_raise`
used a same-day UTC bound (`2026-07-27` to `2026-07-28`), which flipped to
an `AssertionError` (empty result) rather than the target `TypeError`
because the naive item's local-timezone attachment (`local_timezone()` —
this dev host reports `CEST`, UTC+2) shifted it just outside that narrow
window. Widened the bound to `2026-07-20`..`2026-08-03` so the test
isolates the naive/aware comparison behavior from an unrelated tz-shift
edge effect. No production code was affected by this correction.

## Status

11/11 tasks complete (Phases 0-4). Full suite green: 456 passed.
Ready for sdd-verify / archive.
