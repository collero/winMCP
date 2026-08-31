# Proposal: Live Folder-Id Configuration for All Outlook Adapters

## Intent

Three archived changes (`outlook-tasks-todo`'s verify-report WARNING,
`outlook-mail-read`'s design.md "settings.yaml folder ids omitted"
decision) have flagged the same dead-config debt: `config/settings.yaml`
defines `calendar_folder_id` and `tasks_folder_id`, but no code reads
either value — `OutlookCalendarAdapter`/`OutlookTaskAdapter` hardcode their
own `_DEFAULT_*_FOLDER_ID` module constants instead. Meanwhile
`OutlookMailAdapter` never got `inbox_folder_id`/`sent_folder_id` keys at
all, because adding them to a settings file that already had two proven-dead
entries would only have compounded the problem for no benefit.

This change closes the debt permanently: every real adapter resolves its
Outlook folder id from `config/settings.yaml` at COM-access time, falling
back to the documented default when the key is absent or the file is
unreadable. With that wiring in place, adding `inbox_folder_id`/
`sent_folder_id` no longer creates a fourth dead entry — it creates two
more genuinely live ones — so this change also adds them and wires
`OutlookMailAdapter`'s folder resolution to read them.

## Reversal: Why Mail Folder Ids Are No Longer Omitted

`outlook-mail-read`'s design.md explicitly chose to hardcode `6`/`5` as
adapter constants rather than add `inbox_folder_id`/`sent_folder_id` keys,
reasoning: "`grep` confirms `calendar_folder_id`/`tasks_folder_id` are
never read by any `.py` file. A third dead entry compounds existing debt
for no benefit." That rationale depended entirely on the surrounding keys
being dead. Once this change wires `calendar_folder_id`/`tasks_folder_id`
to their adapters, the premise disappears: adding `inbox_folder_id`/
`sent_folder_id` alongside two other now-live keys is consistent, not
compounding. This proposal therefore reverses that decision.

## Scope

1. **Wire existing keys**: `OutlookCalendarAdapter` reads
   `calendar_folder_id` (default `9`) and `OutlookTaskAdapter` reads
   `tasks_folder_id` (default `13`) from `config/settings.yaml` via
   `tools/settings.py::load_settings()`, read lazily at COM-access time —
   mirroring `tools/calendar.py::_lookback_days()` — not cached at
   construction/import. Module-level `_DEFAULT_*_FOLDER_ID` constants
   remain as the fallback defaults only.
2. **Add + wire mail keys**: add `inbox_folder_id: 6` and
   `sent_folder_id: 5` to `config/settings.yaml`. `OutlookMailAdapter`'s
   `_FOLDER_MAP`-driven resolution reads them (same lazy, default-on-absence
   pattern).
3. **Update settings docs**: `config/settings.yaml`'s header comments and
   the README "Configuration" section describe every key, all of which are
   now live.
4. **`pyproject.toml`**: update `[project].description` to mention all
   three tool families (calendar, tasks, mail) — a SUGGESTION flagged in
   `outlook-tasks-todo`'s verify-report.
5. No change to tool behavior otherwise. Deploy scripts, `smoke_test.py`,
   and `server.py` are untouched.

## Risk

Low. Each adapter's resolution falls back to the exact same default it
hardcoded before, so a settings.yaml with today's values (`calendar_folder_id:
9`, `tasks_folder_id: 13`) — or a missing/corrupt settings.yaml — produces
identical runtime behavior to before this change. The only new observable
behavior is that a user who *edits* `config/settings.yaml` now has that
edit take effect, which is the entire point.

## Rollback

Redeploy the previous zip. No data migration, no schema change — a
redeploy fully reverts the fix.

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `tools/outlook_adapter.py` | Modified | `_resolve_folder_id()` reads `calendar_folder_id` lazily at COM-access time |
| `tools/task_adapter.py` | Modified | `_resolve_folder_id()` reads `tasks_folder_id` lazily at COM-access time |
| `tools/mail_adapter.py` | Modified | `_resolve_folder_id(folder)` reads `inbox_folder_id`/`sent_folder_id` lazily |
| `config/settings.yaml` | Modified | Add `inbox_folder_id: 6`, `sent_folder_id: 5`, with doc comments |
| `README.md` | Modified | "Configuration" section documents the two new keys and notes all keys are live |
| `pyproject.toml` | Modified | `description` mentions calendar, tasks, and mail tool families |
| `tests/test_outlook_adapter.py` | Modified | New tests: configured-value-used, absent-key-default, literal-key-in-settings.yaml |
| `tests/test_task_adapter.py` | Modified | Same, mirrored |
| `tests/test_mail_adapter.py` | Modified | Same, mirrored (both folders) |
| `tests/test_mail_tools.py` | Modified | Stale comment referencing calendar/tasks folder ids as "dead" corrected |
| `openspec/specs/outlook-com-adapter/spec.md` | Modified (via archive) | New "Configurable Folder Ids" requirement |

## Success Criteria

- [ ] All three real adapters resolve their folder id(s) from
      `config/settings.yaml` at COM-access time, never cached
- [ ] Absent key or unreadable settings.yaml falls back to the documented
      default, matching pre-change hardcoded behavior exactly
- [ ] `config/settings.yaml` and `README.md` document every key as live
- [ ] `pyproject.toml`'s description mentions calendar, tasks, and mail
- [ ] Full test suite green: 165 pre-existing tests + new tests, zero
      regressions
