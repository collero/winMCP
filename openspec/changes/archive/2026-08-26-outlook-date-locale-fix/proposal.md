# Proposal: Fix Locale-Ambiguous Date Filters in Outlook Restrict() Calls

## Intent

BUG-003 (CRITICAL, live-confirmed): `tools/outlook_adapter.py:50` and
`tools/mail_adapter.py:108` format `Items.Restrict()` date bounds with
`strftime("%m/%d/%Y %I:%M %p")`, which Outlook parses per machine locale.
Under es-ES (this machine), it reads as `DD/MM/YYYY`, so whenever a
bound's day is `<= 12` (~40% of dates), day/month silently transpose per
bound. A 4-day June request returned 240 events across June-September; a
12-Mar->12-Apr request returned 3 events on 3 December. No error, no
signal. `tools/task_adapter.py` is unaffected (Python-side filtering, no
`Restrict()`).

## Scope

### In Scope
- Replace the locale-ambiguous `_dasl_datetime()` literal in both
  `tools/outlook_adapter.py` and `tools/mail_adapter.py` with a
  locale-invariant format, chosen and justified in design.md.
- Regression tests reproducing the confirmed live failures (calendar +
  mail, transposition-prone and immune date shapes) plus a
  locale-independence unit test on the emitted filter string.

### Out of Scope
- `tools/task_adapter.py` (already immune, no `Restrict()` call).
- Adapter-side-filtering rewrite of calendar/mail search (only adopted if
  the invariant-literal approach proves unreliable; see design.md).
- New tool parameters or output shape changes.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `outlook-com-adapter`: calendar `Restrict()` date literals MUST be
  locale-invariant.
- `outlook-mail-adapter`: mail (inbox/sent/drafts) `Restrict()` date
  literals MUST be locale-invariant.

## Approach

Stop emitting a locale-parsed date string. Evaluate Jet/DASL-invariant
literal formats (e.g. `yyyy-mm-dd HH:MM`) vs. adapter-side Python filtering
against correctness and large-mail-folder performance cost; document the
chosen format's evidence in design.md. Apply identically to both
`_dasl_datetime()` implementations.

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `tools/outlook_adapter.py` | Modified | `_dasl_datetime()` emits locale-invariant literal |
| `tools/mail_adapter.py` | Modified | `_dasl_datetime()` emits locale-invariant literal (mirrors above) |
| `tests/test_outlook_adapter.py` | Modified | Regression + locale-invariance tests |
| `tests/test_mail_adapter.py` | Modified | Regression + locale-invariance tests |
| `openspec/specs/outlook-com-adapter/spec.md` | Modified (via archive) | New locale-invariant date requirement |
| `openspec/specs/outlook-mail-adapter/spec.md` | Modified (via archive) | New locale-invariant date requirement |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Chosen literal format not actually invariant across Outlook/Jet locales | Med | design.md documents evidence; tests assert the exact literal |
| Large mail folders make adapter-side filtering too slow, if chosen | Med | Prefer invariant Restrict() literal first; Python filtering is fallback only |

## Rollback Plan

Redeploy the previous zip — the fix is confined to two pure functions, no
data/schema migration.

## Dependencies

None.

## Success Criteria

- [ ] `calendar_search`/`mail_search` return correct results for all three
      live-confirmed date shapes (symmetric-safe, transposition-prone,
      full-month-crossing) under a mocked es-ES-style Restrict parse
- [ ] A locale-invariance unit test asserts the emitted literal is
      identical regardless of assumed locale
- [ ] `tools/task_adapter.py` untouched, unaffected
- [ ] Full test suite green, zero regressions
