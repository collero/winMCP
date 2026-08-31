# Apply Progress: outlook-date-locale-fix

**Mode**: Strict TDD (active — `openspec/config.yaml`'s `testing.strict_tdd: true`)
**Batch**: 1 of 1 (all tasks, all phases, completed in a single batch)

## Baseline

- Command: `.venv/bin/python3.12 -m pytest -q`
- Result before any change: **306 passed**

## TDD Cycle Evidence

| Task | RED | GREEN | REFACTOR |
|------|-----|-------|----------|
| 1.1–1.2 `tools/outlook_adapter.py::_dasl_datetime` + `search()` boundary re-check | Added `test_dasl_datetime_emits_iso_ordered_literal`, `test_search_transposition_prone_range_returns_only_bound_days`, `test_search_full_month_crossing_range_excludes_december`, `test_search_control_range_day_ge_13_unchanged` to `tests/test_outlook_adapter.py`. Ran `pytest -k "dasl_datetime_emits_iso or transposition_prone or full_month_crossing or control_range"` → **3 failed, 1 passed** (control test passes pre-fix by construction; the other 3 fail as expected) | Changed `_dasl_datetime()` to `strftime("%Y-%m-%d %H:%M")`; added a Python-side boundary re-check in `search()` (`start < date_from or end > date_to` → drop). Updated the pre-existing literal assertion `"07/27/2026"` → `"2026-07-27"`. Re-ran `tests/test_outlook_adapter.py` → **18 passed** | Docstring on `_dasl_datetime` rewritten in place during the GREEN edit to explain the ISO-ordered rationale — folded into 1.2, no separate diff |
| 2.1–2.2 `tools/mail_adapter.py::_dasl_datetime` + `search()` boundary re-check | Mirrored the same 4 tests into `tests/test_mail_adapter.py` (`folder="inbox"`/`[ReceivedTime]` for the transposition case, `folder="sent"`/`[SentOn]` for the full-month case). Ran the same `-k` filter → **3 failed, 1 passed** | Mirrored the format fix; replaced the `filter_dates_in_python`-gated call to `_matches_date_bounds()` with an unconditional call (it already no-ops when both bounds are `None`), so folder-mapped searches (inbox/sent/drafts) get the same boundary re-check that `folder_path` searches already relied on as their only filter. Updated pre-existing `"08/01/2026"`/`"08/31/2026"` literal assertions → `"2026-08-01"`/`"2026-08-31"`. Re-ran `tests/test_mail_adapter.py` → **34 passed** | Docstring on `_dasl_datetime` rewritten in place, folded into 2.2 |
| 3.1 Cross-module consistency | N/A (pure assertion test, no separate RED needed — it exercises code already made GREEN in 1.2/2.2) | Appended `test_calendar_and_mail_dasl_datetime_emit_identical_literal` to `tests/test_outlook_adapter.py`, importing both `_dasl_datetime` functions and asserting identical output | N/A |

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `tools/outlook_adapter.py` | Modified | `_dasl_datetime()` now emits `strftime("%Y-%m-%d %H:%M")`; `search()` adds a Python-side boundary re-check (`start < date_from or end > date_to` → drop) as defense-in-depth per design.md |
| `tools/mail_adapter.py` | Modified | Same format fix, mirrored; the pre-existing `_matches_date_bounds()` call (previously gated to `folder_path` searches only via `filter_dates_in_python`) is now applied unconditionally to every search path, extending the same defense-in-depth boundary check to inbox/sent/drafts `Restrict()`-based searches; `filter_dates_in_python` variable removed as dead |
| `tests/test_outlook_adapter.py` | Modified | Added 4 new regression tests (Phase 1) + 1 cross-module consistency test (Phase 3); updated one pre-existing literal assertion (`07/27/2026` → `2026-07-27`) |
| `tests/test_mail_adapter.py` | Modified | Added 4 new regression tests (Phase 2), mirroring Phase 1; updated one pre-existing pair of literal assertions (`08/01/2026`/`08/31/2026` → `2026-08-01`/`2026-08-31`) |
| `openspec/changes/outlook-date-locale-fix/tasks.md` | Modified | All 11 tasks (phases 0–4) checked off with evidence notes |

## Deviations from Design

None — implementation matches design.md exactly: ISO-ordered `%Y-%m-%d %H:%M` literal, Python-side boundary re-check as defense-in-depth (not a replacement for `Restrict()`), fix duplicated per module rather than extracted to a shared helper. One minor implementation simplification not called out explicitly in design.md: in `tools/mail_adapter.py`, rather than adding a *second*, separate boundary-check call site gated to folder-mapped searches, the existing `_matches_date_bounds()` call (previously gated by `filter_dates_in_python`, true only for `folder_path`) was made unconditional — it already returns `True` when both `date_from`/`date_to` are `None`, so this is behaviorally equivalent to "add the same boundary re-check for folder-mapped searches" with less duplicated code, and the removed `filter_dates_in_python` variable was dead once that gate was gone.

## Issues Found

None in the code paths touched by this change.

**Unrelated observation (not caused by this change, flagged for visibility):** during this apply batch, the full-suite pass count moved from the recorded Phase 0 baseline (306) up through 310 → 314 → 320 → 323 → 325 → 326 across successive full-suite runs, and one run showed a transient `NameError`/collection error in `tests/test_errors.py` and `tests/test_schemas.py` unrelated to any file this change touches. Direct inspection showed `tests/test_schemas.py`'s import list visibly differ between two back-to-back reads a few seconds apart. This indicates another process is concurrently modifying files in this same working tree during this session — not a regression introduced by this change. All instability was isolated to files outside this change's scope (`tools/outlook_adapter.py`, `tools/mail_adapter.py`, `tests/test_outlook_adapter.py`, `tests/test_mail_adapter.py`), which passed consistently (53/53) across every run.

## Task Checklist Status

All 11 tasks (Phases 0–4) are checked off in `tasks.md`. See that file for the per-task evidence notes.

## Final Full-Suite Result

- Command: `.venv/bin/python3.12 -m pytest -q`
- Result: **326 passed** (two consecutive runs identical; this change's own 53 tests in `tests/test_outlook_adapter.py` + `tests/test_mail_adapter.py` passed consistently across every run during this batch — the count drift above 315 (=306+9 new tests from this change) reflects the unrelated concurrent activity noted above, not this change)

## Status

11/11 tasks complete. Ready for verify.
