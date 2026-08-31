# WinMCP Server (MVP)

A minimal [MCP](https://modelcontextprotocol.io) server that exposes
thirteen tools over **stdio** for reading your Outlook calendar's "note"
appointments (subject + body), your Outlook Tasks / Microsoft To Do items,
your Outlook Inbox/Sent Items mail, via Outlook COM, local/OneDrive files
indexed by Windows Search, and OneNote pages via a `OneNote.Application`
COM bridge:

- `calendar_search` — search the default Outlook calendar folder by date
  range and/or subject substring.
- `calendar_get_event` — fetch full detail (including body) for a single
  event by its Outlook `entryId`.
- `calendar_get_notes` — resolve the single note-appointment matching a
  `date` + `subject` and return its full detail in one call.
- `task_search` — search the default Outlook Tasks folder (synced with
  Microsoft To Do) by due-date range, subject substring, and/or status; all
  filters are optional.
- `task_get_task` — fetch full detail (including body) for a single task by
  its Outlook `entryId`.
- `mail_search` — search the default Outlook Inbox or Sent Items folder by
  date range, subject substring, and/or sender substring; at least one
  filter is required.
- `mail_get_message` — fetch full detail (including body) for a single
  Inbox/Sent Items message by its Outlook `entryId`.
- `file_search` — search the Windows Search index by a case-insensitive
  `filename` substring and/or a full-text `phrase` match, optionally
  restricted to an absolute `scope` subtree; at least one of
  `filename`/`phrase` is required, and any `scope` given must fall within an
  allowed search root.
- `file_get_info` — fetch full indexed metadata (size, timestamps, kind,
  extension, content snippet) for a single file by its native path or the
  `file:///`-style URL previously returned by `file_search`; the path must
  also fall within an allowed search root.
- `onenote_search` — full-text search over OneNote page content
  (`FindPages`); `query` is required, `limit` is optional (default 50,
  hard max 200).
- `onenote_get_page` — fetch full, read-only text detail (title + body)
  for a single OneNote page by its `pageId`.
- `onenote_create_page` — create a new page in a given `sectionId`;
  restricted to a configurable writable-notebook allowlist (default only
  `"z - Test Notebook"`).
- `onenote_update_page` — update an existing page's body by `pageId`,
  guarded by required optimistic concurrency (`dateExpectedLastModified`)
  and the same writable-notebook allowlist as `onenote_create_page`.

No authentication, no network listener — the server is launched as a local
subprocess by an MCP client (e.g. Claude Desktop) and speaks stdio only.

## Platform requirement: Windows + Outlook (runtime), WSL2/Linux (dev only)

The real adapter talks to Outlook via COM (`pywin32`/`win32com`), which is
**Windows-only** and requires a working Outlook installation/profile. This
project is therefore developed and tested on WSL2 Linux using a
**`FakeCalendarAdapter`** (in-memory, no Outlook needed), but it **runs**
only on Windows, under a Windows Python 3.12 interpreter — not inside WSL2.

- `win32com` is never imported at module load time anywhere in this
  codebase (see `tools/outlook_adapter.py`); it is imported lazily, inside
  `OutlookCalendarAdapter`'s own methods, the first time a tool actually
  needs Outlook. This is what lets the full test suite import and run on
  Linux with zero Windows dependencies.
- Do **not** `pip install pywin32` on Linux/WSL2 — it is a Windows-only
  package and is declared in `pyproject.toml` with an environment marker
  (`pywin32; sys_platform == 'win32'`) so it is skipped automatically on
  non-Windows installs.
- The four OneNote tools take a different route entirely: Windows
  Search's index has zero `onenote:` items, so there is no ADO/Windows
  Search fallback the way `file_search` has one — `OneNoteAdapter`
  (`tools/onenote_adapter.py`) is the **only** path, and it never imports
  `win32com` at all. It spawns a pinned Windows PowerShell 5.1
  (`powershell.exe`, never `pwsh`) child running `tools/ps_bridge_onenote.ps1`,
  which drives `New-Object -ComObject OneNote.Application` — this requires
  the **classic desktop OneNote application** to be installed on the
  Windows host (the "OneNote for Windows 10"/Microsoft Store app does not
  expose this COM object model, same caveat as the Outlook tools). Dev/CI
  on WSL2 uses **`FakeOneNoteAdapter`** (in-memory) instead — no
  `powershell.exe`, no COM, needed to run the test suite.

## Install (on the Windows host)

The supported install path uses a prebuilt, self-contained distribution zip
(`WinMCP-<date>.zip`) that bundles the app, the launcher scripts, and every
dependency wheel (including `pywin32`) — no internet access is needed on the
Windows machine and no Windows Python packages are required beforehand
beyond Python 3.12/3.13 itself.

1. Get `WinMCP-<date>.zip` (built via `./make-deploy-package.sh` — see
   "Building the package" below, or ask whoever built it for a copy) onto
   the Windows machine.
2. **Right-click the zip → Properties → tick "Unblock" → OK.** This clears
   Windows' "Mark of the Web" flag for the whole package in one gesture, so
   the launcher scripts inside aren't blocked from running.
3. Extract it, e.g. to `C:\WinMCP`.
4. Double-click **`install.bat`** inside the extracted folder. It will:
   - locate a Windows Python 3.12/3.13 interpreter (`py -3.12`, or `python`
     on PATH),
   - create a private `.venv` next to itself,
   - install WinMCP and all dependencies from the bundled `wheels\` folder
     (fully offline),
   - **ask which tools to enable** — a short prompt walks the tool
     families (calendar, tasks, mail, files, OneNote) with the package's
     recommended set pre-selected; press Enter to accept the defaults, or
     toggle individual tools on/off. Your choices are saved to
     `config\installed-tools.yaml` and only the enabled tools will appear
     in Claude Desktop. (Scripted installs can skip the prompt with
     `install.bat -Preset <file>`; see "Selective tool deployment" below.
     You can re-run `install.bat` any time to change the selection.) **If
     you received a curated `--share` package rather than the default
     build, this prompt — and the installed copy as a whole — only ever
     lists the families/tools that package actually shipped; a tool the
     builder excluded never appears here to toggle on, no matter what you
     pick.**
   - smoke-check that `server.py` and `win32com.client` both import
     cleanly, and
   - print a ready-to-paste JSON snippet for Claude Desktop.
   The window stays open (press Enter to close it) so you can read any
   error before it disappears.
5. **Test before configuring Claude Desktop:** double-click **`test.bat`**
   inside the extracted folder. It launches `WinMCP.bat` exactly the way
   Claude Desktop will and runs the real MCP handshake against it
   (`initialize`, `tools/list`, and one live call per installed tool
   family — families you didn't enable in step 4 are skipped, not
   failed), so a broken install shows up here instead of as a silent
   "server disconnected" inside Claude Desktop. The window stays open (press Enter
   to close it) so you can read the result:
   - **`SMOKE TEST PASSED`** — the server starts, speaks MCP correctly, and
     found your `calendar_search` results. You're ready for step 6.
   - **`SMOKE TEST PASSED WITH WARNINGS`** — the MCP plumbing itself is
     fine (steps 1-3 passed), but Outlook wasn't reachable when the calendar
     call ran (not installed, not running, or no profile configured). Make
     sure Outlook is installed and running, then re-run `test.bat`; it's
     still safe to proceed to step 6 in the meantime.
   - **`SMOKE TEST FAILED`** — something is actually broken (bad `.venv`,
     corrupted stdout, missing tools). Fix the issue described in the
     output (re-running `install.bat` fixes most causes) before configuring
     Claude Desktop.
6. Paste the printed JSON snippet into Claude Desktop's
   `claude_desktop_config.json`, under the top-level `mcpServers` key
   (merge it in if the file already has other servers configured). It
   points `command` at the absolute path of `WinMCP.bat` in your install
   folder, e.g.:

   ```json
   {
     "mcpServers": {
       "win-mcp": {
         "command": "C:\\WinMCP\\WinMCP.bat"
       }
     }
   }
   ```

7. Restart Claude Desktop; it will launch `WinMCP.bat` (which execs the
   bundled `.venv`'s `server.py` over stdio) and discover `calendar_search`,
   `calendar_get_event`, `calendar_get_notes`, `task_search`,
   `task_get_task`, `mail_search`, `mail_get_message`, `file_search`,
   `file_get_info`, `onenote_search`, `onenote_get_page`,
   `onenote_create_page`, and `onenote_update_page` — the full default-build
   list. From a hard-excluded `--share` package, only the tools that
   package actually shipped (and that you enabled in step 4) can ever
   appear; there is no way to enable an excluded tool after the fact.

If you ever need to reinstall or repair the `.venv` (e.g. after a Windows
Python upgrade), just re-run `install.bat` — it recreates `.venv` from the
bundled wheels each time.

### Alternative: manual / dev install (from source, on Windows)

If you're working from a source checkout on Windows instead of the
packaged zip (e.g. to develop against a live `win32com`/Outlook install),
you can install directly with `uv` or `pip`. Run these from a **Windows**
terminal (PowerShell/cmd), not from WSL2, using a Python 3.12 interpreter
that has Outlook available on the same machine:

```powershell
# from the project root, using uv:
uv sync

# or, using plain pip:
python -m venv .venv
.venv\Scripts\activate
pip install .
```

Either install path pulls in `fastmcp`, `pydantic`, `pyyaml`, and (on
Windows only) `pywin32`.

Then configure Claude Desktop by hand, pointing at the Windows Python
interpreter you installed into and this project's `server.py`:

```json
{
  "mcpServers": {
    "win-mcp": {
      "command": "C:\\path\\to\\WinMCP\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\WinMCP\\server.py"]
    }
  }
}
```

(If you installed with `uv sync`, you can instead use
`"command": "uv", "args": ["--directory", "C:\\path\\to\\WinMCP", "run", "server.py"]`.)

Restart Claude Desktop; it will launch `server.py` as a subprocess over
stdio and discover the same thirteen tools.

## Configuration

`config/settings.yaml` controls:

- `lookback_days` — default lookback window used by `calendar_search` when
  `from`/`to` are omitted (subject-only search).
- `mail_lookback_days` — default lookback window used by `mail_search` when
  `dateFrom`/`dateTo` are omitted or only one is given; a distinct, live
  setting from `lookback_days` (mail is typically searched much further
  back than calendar notes, so it defaults to `90` days rather than `7`).
- `calendar_folder_id` — Outlook `GetDefaultFolder()` constant used by
  `calendar_search`/`calendar_get_event`; `9` is `olFolderCalendar` (the
  default calendar folder).
- `tasks_folder_id` — Outlook `GetDefaultFolder()` constant used by
  `task_search`/`task_get_task`; `13` is `olFolderTasks` (synced with
  Microsoft To Do).
- `inbox_folder_id` — Outlook `GetDefaultFolder()` constant used by
  `mail_search`/`mail_get_message` on `folder=inbox`; `6` is
  `olFolderInbox`.
- `sent_folder_id` — Outlook `GetDefaultFolder()` constant used by
  `mail_search`/`mail_get_message` on `folder=sent`; `5` is
  `olFolderSentMail`.
- `drafts_folder_id` — Outlook `GetDefaultFolder()` constant used by
  `mail_search`/`mail_get_message` on `folder=drafts`; `16` is
  `olFolderDrafts`.
- `timezone_override` — optional IANA timezone name (e.g. `"Europe/Madrid"`)
  used instead of the host's local timezone when converting Outlook's naive
  local-time datetimes to timezone-aware datetimes. Leave `null` to use the
  Windows host's local timezone.
- `file_search_allowed_roots` — list of absolute paths `file_search`/
  `file_get_info` are restricted to; a `scope`/`path` outside every entry is
  rejected before any Windows Search query runs, and any result row that
  somehow falls outside these roots is dropped as well. Default `[]`
  (empty/unconfigured): in that case, `tools/settings.py`'s
  `default_search_roots()` resolves the roots live from the environment
  instead, trying `%USERPROFILE%`, then whichever of `%OneDrive%`,
  `%OneDriveCommercial%`, `%OneDriveConsumer%` are set, in that order,
  dropping any candidate nested inside (or identical to) one already kept
  (e.g. a plain OneDrive-under-profile setup collapses to just
  `%USERPROFILE%`, while a KFM-redirected OneDrive on another drive stays
  as an extra root).
- `file_search_max_results` — cap on the number of rows `file_search`
  returns, passed to the Windows Search query as a `TOP n` bound (results
  are never fetched unbounded and then truncated). Default `200`.
- `onenote_writable_notebooks` — list of OneNote notebook names
  `onenote_create_page`/`onenote_update_page` are allowed to write to,
  checked in Python (`tools/onenote.py`) before any adapter/COM call. When
  absent, the default is exactly `["z - Test Notebook"]` — every other
  live Informa notebook stays read-only until this list is widened.
- `onenote_search_max_results` — default row cap for `onenote_search`
  when the caller omits `limit`; a caller-supplied `limit` over `200` is
  still clamped to that fixed ceiling regardless of this setting. Default
  `50`.
- `onenote_ps_bridge_timeout_seconds` — overall wall-clock deadline (in
  seconds) for each `powershell.exe` child spawned by `OneNoteAdapter`.
  Default `20`.

Every key above is live: each is read from `config/settings.yaml` at
COM-access/index-access time by its adapter (`tools/outlook_adapter.py`,
`tools/task_adapter.py`, `tools/mail_adapter.py`, `tools/onenote_adapter.py`)
or tool layer (`tools/file_search.py`, `tools/onenote.py`), falling back to
the documented default only when the key is absent or the file is
unreadable.

## Development (WSL2 / Linux)

All development and the automated test suite run entirely against
`FakeCalendarAdapter` (`tools/fake_adapter.py`), `FakeTaskAdapter`
(`tools/fake_task_adapter.py`), `FakeMailAdapter`
(`tools/fake_mail_adapter.py`), `FakeFileSearchAdapter`
(`tools/fake_file_search_adapter.py`), and `FakeOneNoteAdapter`
(`tools/fake_onenote_adapter.py`) — no Outlook, no Windows, no `win32com`,
no `powershell.exe`, no COM of any kind needed:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python3.12 -m pytest -q
```

This exercises tool-layer logic (`tools/calendar.py`, `tools/tasks.py`,
`tools/mail.py`, `tools/file_search.py`, `tools/onenote.py`), schema
validation (`models/schemas.py`), the error taxonomy (`tools/errors.py`),
the real adapters' date/tz/error-mapping/status-mapping/SQL-building logic
with `win32com`/`pythoncom`/ADODB mocked via `pytest-mock`
(`tests/test_outlook_adapter.py`, `tests/test_task_adapter.py`,
`tests/test_mail_adapter.py`, `tests/test_file_search_adapter.py`), the
shared `PsBridgeTransport`'s spawn/deadline/JSON-Lines-parse logic and
`OneNoteAdapter`'s request-shape/XML-extraction logic with
`subprocess.Popen` mocked, never a real `powershell.exe`/COM
(`tests/test_ps_bridge_transport.py`, `tests/test_onenote_adapter.py`,
`tests/test_fake_onenote_adapter.py`, `tests/test_onenote_tools.py`), and
FastMCP tool registration/wiring against all five fake adapters
(`tests/test_server.py`). `win32com` itself is never installed and never
touched in this environment — every test that would need it injects a fake
`win32com.client`/`pythoncom` module into `sys.modules` instead; OneNote's
tests never need to, since `OneNoteAdapter` never imports `win32com` in
the first place.

## Manual smoke test (on Windows, with Outlook running)

Automated CI/dev testing (WSL2) intentionally never exercises real Outlook
COM or real OneNote COM/PowerShell. The packaged `test.bat`/
`deploy/smoke_test.py` (see "Test before configuring Claude Desktop" above)
automates most of this against the real MCP stdio handshake and a live
`calendar_search` call - run it first (it deliberately does **not** cover
OneNote — see its own note in "Known limitations" below). The steps below
are the fully manual, Claude-Desktop-in-the-loop version, useful for
confirming `calendar_get_notes`, `task_search`/`task_get_task`,
`mail_search`/`mail_get_message`, `file_search`/`file_get_info`,
`onenote_search`/`onenote_get_page`/`onenote_create_page`/
`onenote_update_page`, and the Outlook-down/Windows-Search-down/
OneNote-bridge-down error paths specifically. Before relying on this
server, do the following once on the actual Windows host:

1. Make sure Outlook is installed, configured with a working profile, and
   running (or launchable) on the same Windows machine.
2. From the Windows `.venv`, run the server directly to confirm it starts
   without error:
   ```powershell
   .venv\Scripts\python.exe server.py
   ```
   It should sit idle waiting on stdio (no printed errors, no crash). Stop
   it with Ctrl+C.
3. Point Claude Desktop at it (see "Install (on the Windows host)" above),
   restart Claude Desktop, and confirm all thirteen tools (`calendar_search`,
   `calendar_get_event`, `calendar_get_notes`, `task_search`,
   `task_get_task`, `mail_search`, `mail_get_message`, `file_search`,
   `file_get_info`, `onenote_search`, `onenote_get_page`,
   `onenote_create_page`, `onenote_update_page`) appear in its tool list.
4. Ask it to search: e.g. "search my calendar for events with subject
   'Tareas' in the last 7 days" — confirm it returns real entries from your
   Outlook calendar (or an empty list if none match, not an error).
5. Ask it to fetch one event's notes by date+subject (`calendar_get_notes`)
   and confirm the returned body matches what's actually in that Outlook
   appointment.
6. Ask it to list your open tasks/To Do items (`task_search`), then fetch
   one by name to see its full body (`task_get_task`) — confirm both match
   what's actually in Outlook Tasks / Microsoft To Do for that account.
7. Ask it to search your inbox: e.g. "search my inbox for mail with subject
   'Factura' in the last 30 days" (`mail_search`), then fetch one by
   `entryId` to see its full body (`mail_get_message`) — confirm both match
   what's actually in Outlook, and repeat with `folder="sent"` to confirm
   the sender-filter-matches-recipient behavior on Sent Items.
8. To confirm error handling, temporarily quit Outlook entirely and repeat
   step 4 — the tool call should surface a clear
   `outlook_unavailable` error, not an unhandled crash of the server
   process.
9. Ask it to search for a file you know exists under your profile or
   OneDrive, e.g. "search my files for anything named 'report'"
   (`file_search`), then fetch its full metadata by path (`file_get_info`)
   — confirm both match what's actually indexed (size, timestamps,
   kind/extension). Also try a `scope` outside your allowed roots (e.g.
   `C:\Windows`) and confirm it's refused with a
   `search_root_not_allowed` error rather than silently searching anyway.
   (`deploy/smoke_test.py`'s `files` family already does a scripted
   version of both halves of this — the out-of-root refusal, and a
   tolerant `file_search`/`file_get_info` chain — but does not check the
   actual returned content, which this manual step does.)
10. To confirm error handling for the index itself, temporarily stop the
    "Windows Search" service (`services.msc`) and repeat step 9's search —
    the tool call should surface a clear `windows_search_unavailable`
    error, not an unhandled crash.
11. Ask it to search OneNote: e.g. "search my OneNote for pages mentioning
    'reunión'" (`onenote_search`), then fetch one by `pageId` to see its
    full title/body (`onenote_get_page`) — confirm both match what's
    actually in OneNote (or an empty list/`""` body if none match/the page
    is blank, not an error).
12. Ask it to create a page in the notebook named exactly
    `"z - Test Notebook"` (`onenote_create_page`) — confirm the new page
    actually appears there in the OneNote desktop app, then ask it to
    update that same page's body (`onenote_update_page`), passing back the
    `lastModifiedDateTime` the create call returned — confirm the update
    succeeds and the new body is visible in OneNote.
13. Ask it to create or update a page targeting one of your **other**,
    live notebooks (any notebook not in `onenote_writable_notebooks`) —
    confirm the call is refused with a clear `onenote_notebook_not_allowed`
    error, and that nothing was actually written to that notebook.
14. Ask it to update the same page from step 12 again, but pass a
    `dateExpectedLastModified` from *before* that update (a stale value) —
    confirm the call is refused with a clear `onenote_page_conflict`
    error, and that the page's real content in OneNote still shows step
    12's body, not silently overwritten.
15. To confirm error handling for the bridge itself, temporarily rename or
    move `tools/ps_bridge_onenote.ps1` out of the install folder (or block
    `powershell.exe` from launching) and repeat step 11 — the tool call
    should surface a clear `onenote_unavailable` error, not an unhandled
    crash. Restore the file afterward.

## Known limitations (MVP scope)

- Only the default Calendar folder (`GetDefaultFolder(9)`) is searched by
  the calendar tools, and only the default Tasks folder
  (`GetDefaultFolder(13)`) by the task tools — no other calendar/task
  folders are searched.
- `mail_search`/`mail_get_message` cover the default Inbox
  (`GetDefaultFolder(6)`), Sent Items (`GetDefaultFolder(5)`), and Drafts
  (`GetDefaultFolder(16)`) folders, plus an arbitrary custom folder via
  `folderPath` (a `/`-delimited path resolved from the default mail store's
  root folder). `folderPath` reaches only the **default store's** folder
  tree — shared/delegated mailboxes and other stores/PSTs are not
  reachable, since resolution starts from `DefaultStore.GetRootFolder()`.
  `mail_get_message` can also return each message's attachment file names
  (`attachmentNames`, always populated) and, opt-in via
  `includeHtmlBody=true`, the message's `HTMLBody` (`htmlBody`) — attachment
  *content* is not downloadable, and folder discovery (listing what
  `folderPath` values exist) is not exposed.
- `folderPath` and `includeHtmlBody` are covered by the automated test
  suite (fake + real-adapter layers) but have **no smoke-test coverage** —
  the `deploy/smoke_test.py` live check only exercises `folder="inbox"`,
  `folder="sent"`, and `folder="drafts"` with default (no `includeHtmlBody`)
  detail calls.
- Recurring-appointment expansion is a documented limitation, not solved:
  `Items.Restrict()` is used with `IncludeRecurrences = True` paired with a
  bounded `Sort("[Start]")`, which is the safe pattern for a bounded date
  range, but recurring-series edge cases beyond typical single
  "note-appointment" use are out of scope for this MVP.
- `task_search`/`task_get_task` are read-only: creating, completing, or
  updating tasks is out of scope for this MVP, as are To Do-only features
  with no COM equivalent (My Day, steps/subtasks).
- `mail_search`/`mail_get_message` are strictly read-only: no send, move,
  delete, or read-flag change is ever issued. Composing/sending mail is out
  of scope for this MVP.
- `file_search`/`file_get_info` depend entirely on the Windows Search
  index (`Search.CollatorDSO`) already having indexed the relevant
  location — a folder excluded from indexing, or one that hasn't finished
  being crawled yet, simply won't produce results, with no distinct error
  from "genuinely no matches." Only metadata is returned; file *content*
  itself is out of scope (the `snippet` field is a short indexer-provided
  preview, not the full file body), and there is no way to read, write, or
  delete a file through these tools. `file_search_allowed_roots`/
  `file_search_max_results` are covered by the automated test suite (fake
  + real-adapter layers); the `deploy/smoke_test.py` live check now also
  exercises `file_search`/`file_get_info` via a `files` family (a
  deterministic check that a fixed synthetic out-of-root `scope`
  (`C:\winmcp-smoke-denied-probe`) is refused with `search_root_not_allowed`,
  plus a tolerant `file_search`/`file_get_info` chain that passes on 0+
  hits), but that live check does not verify actual result content or the
  `windows_search_unavailable` path — see step 9/10 of the manual smoke
  test below for that.
- `onenote_search`/`onenote_get_page`/`onenote_create_page`/
  `onenote_update_page` depend entirely on `OneNote.Application` COM,
  reached through a pinned `powershell.exe` 5.1 bridge — the classic
  desktop OneNote app must be installed (the Store app does not expose
  COM), and each call spawns a fresh PowerShell child (no persistent
  daemon), bounded by `onenote_ps_bridge_timeout_seconds` (default `20`s).
  Writes are restricted to `onenote_writable_notebooks` (default only
  `["z - Test Notebook"]`) — every other live notebook stays read-only
  until that list is widened, a deliberate MVP guardrail against an
  LLM-driven write landing somewhere unintended. `onenote_update_page`
  **appends** a new body paragraph rather than replacing the page's
  existing content wholesale (repeated updates accumulate, they don't
  overwrite) — a documented limitation of the underlying
  `UpdatePageContent` patch semantics, not a bug. Only plain text is
  extracted/written; ink, images, and other rich content are out of
  scope, and a `title`/`bodyText` containing the literal sequence `]]>`
  will break the page's CDATA construction (a rare edge case, not
  chunk-split in this MVP). `onenote_search`/`onenote_get_page` are
  covered by the automated test suite (fake + mocked-transport real-
  adapter layers) but have **no smoke-test coverage** — see "Manual smoke
  test" steps 11-15 above for the fully manual verification instead.
- The `onenote_update_page` conflict check (`dateExpectedLastModified`) has
  a live-confirmed blind spot: OneNote stamps a page's last-modified time
  **lazily**, at its own internal background save, not synchronously with
  the write call returning — the COM-visible timestamp was observed
  unchanged for 15+ seconds after a real write landed. A second write
  issued within that save-latency window can slip past the conflict check
  undetected, since there is no timestamp-based way (including OneNote's
  own native check) to see a change that hasn't been stamped yet. The
  guard is reliable for genuinely stale timestamps (seconds-to-minutes
  old — the realistic case for an LLM-driven caller), just not for two
  writes racing within that short window.
- No authentication/authorization — the process boundary (your Windows
  session) is the only trust boundary, per this MVP's stdio-only,
  zero-network design.

## Possible extensions: other services this server could expose

The calendar, task, and mail tools are built on a generic pattern — a
lazily-imported Outlook COM adapter opening a folder via
`GetDefaultFolder(<constant>)` — and that same pattern reaches **everything
the local Outlook profile stores**. Each of these could be added as new
`*_search` / `*_get` tools with no new dependencies, no network access, and
no authentication, exactly like the calendar, Tasks/To Do, and mail tools:

- **Sending mail** — the mail tools are strictly read-only (Inbox, Sent
  Items, Drafts, and arbitrary `folderPath` folders); sending mail is
  possible via COM, but that's a write operation with real-world side
  effects, so it deserves its own confirmation-oriented design.
- **Attachment content** — the mail tools already expose `attachmentNames`
  (file names), but not attachment content/download; that would be a
  natural follow-on to `mail_get_message`.
- **Folder discovery** — `folderPath` requires the caller to already know
  the exact `/`-delimited path; a `mail_list_folders`-style tool walking
  `Folders` under `DefaultStore.GetRootFolder()` would let a caller
  discover valid paths instead of guessing.
- **Shared/delegated mailboxes** — `folderPath` resolves only against the
  default store (`DefaultStore.GetRootFolder()`); reaching another
  mailbox/store the user has delegate access to would need walking
  `namespace.Folders` instead, plus a way to name the target store.
- **Contacts** — `olFolderContacts = 10`: lookup by name/company, return
  email addresses and phone numbers.
- **Sticky Notes (classic Outlook Notes)** — `olFolderNotes = 12`.
- **More calendars** — non-default and shared calendars, by walking the
  `Folders` collection instead of only `GetDefaultFolder(9)`; plus write
  support (creating/updating appointments) on the existing calendar.

The OneNote tools follow a related but distinct pattern — a
lazily-imported, PowerShell-bridged `OneNote.Application` COM adapter,
since OneNote never appears in an Outlook profile at all. Natural
follow-ons, all still zero-network/no-auth:

- **Widen or make the writable-notebook allowlist configurable per-call**
  — today `onenote_writable_notebooks` is one global, operator-set list;
  a future version could accept it as a request-time parameter (with its
  own confirmation-oriented design, mirroring the "sending mail" caveat
  above).
- **True overwrite semantics** for `onenote_update_page` — replacing a
  page's body wholesale instead of appending, once a safe "fetch full
  page XML, apply the change, rewrite" pattern is designed (see "Known
  limitations").
- **Delete/move pages, sections, or notebooks** — explicitly out of scope
  for this MVP (see the change proposal for `add-onenote-adapter`).
- **Rich content** — ink, images, and file attachments embedded in a
  page are not read or written today; only plain extracted text.

Two boundaries to keep in mind when picking from this list:

- Every Outlook-profile extension above requires **classic Outlook** —
  the "new Outlook" app does not expose the COM object model at all, same
  as for the current calendar tools. The OneNote tools have the same
  caveat for the **classic desktop OneNote app** specifically (see
  "Platform requirement" above).
- Anything *outside* what a local COM object model exposes — full-
  fidelity Microsoft To Do, Teams, OneDrive files/sharing — lives behind
  the **Microsoft Graph API**, which means network access and OAuth.
  That's a deliberate break from this project's zero-network, no-auth
  design and would be a different kind of server. (OneNote itself is
  reachable locally via `OneNote.Application` COM — see above — so it
  does *not* need Graph, unlike these.)

## Building the package

The distributable zip described in "Install (on the Windows host)" above is
built from this repo on the WSL2/Linux dev host with:

```bash
./make-deploy-package.sh
```

This runs the full test suite as a gate, checks that `win32com` is never
imported at module level, checks that the launcher scripts are pure ASCII
and that `install.ps1` parses cleanly, then stages `server.py`, `tools/`,
`models/`, `config/settings.yaml`, `pyproject.toml`, `README.md`, and the
five launcher scripts - `install.bat`, `install.ps1`, `WinMCP.bat`,
`test.bat`, `smoke_test.py` (flattened from `deploy/`) - into a `WinMCP/`
folder.
It builds this project's own wheel and downloads every Windows dependency
wheel (`fastmcp`, `pydantic`, `pyyaml`, `pywin32`, and their transitive
deps) for Python 3.12 and, best-effort, 3.13, into `WinMCP/wheels/` — this
step needs network access on the machine running the script. The result is
written to `dist/WinMCP-<YYYYMMDD>.zip`, along with its sha256 and an
`unzip -l` listing printed at the end. `dist/` is a build output and is
never itself included in the package.

### Selective tool deployment: choosing which tools ship enabled

`tools/catalog.yaml` is the source of truth for every tool this server can
ship: which **family** it belongs to (`calendar`, `task`, `mail`, `file`,
`onenote`), its **maturity** (`onenote`'s 4 tools are `beta`; the other 9
calendar/task/mail/file tools are `alpha`), and the files it depends on
(Python modules, PowerShell bridge scripts, `config/settings.yaml` keys).
It is never read at runtime by `server.py` or `smoke_test.py` — it only
drives two generated, downstream artifacts: `tools/shipped-tools.json`
(written by `make-deploy-package.sh`, read by `install.ps1`) and
`config/installed-tools.yaml` (written by `install.ps1`, read by
`server.py`/`smoke_test.py`). Maturity seeds the `--share` build's default
pre-selection **only** — it never excludes a tool from the default build,
and the installer never re-derives it.

`make-deploy-package.sh` supports two build modes:

- **Default (no flags)** — today's behavior, unchanged: all 13 tools ship
  with `default_enabled=true`. This is the only mode `deploy-qa.sh`/
  `promote-pro.sh` use, and the file-selection/staging pipeline is
  byte-identical to before this feature existed.
- **`--share`** — curates a *default* selection for a package you hand to
  someone else, without physically removing any tool's files (every tool
  is always staged in both modes — "shipped-but-disabled" — so no import
  ever breaks regardless of what's enabled). At an interactive terminal
  with `whiptail` on `PATH` (present on this dev host), tool selection is
  a single `whiptail --checklist` screen — one row per tool, labeled
  `[family] tool_name`, pre-checked from catalog maturity (`beta`/`stable`
  pre-checked, `alpha` unchecked) with the tool's maturity shown in the
  row description; toggle with Space, confirm with Enter, or Cancel to
  abort the build cleanly (nonzero exit, no zip). Pass `--no-tui` to force
  the older plain per-family/per-tool `y`/`n` `read -p` loop instead (also
  the automatic fallback when `whiptail` isn't found). Either way, your
  answer always wins over the maturity seed, in either direction.
  Add `--tools=a,b,c` to give the exact tool list up front (validated
  against `tools/catalog.yaml`'s names) and skip the prompt entirely —
  this works with or without a terminal attached. Running `--share`
  **without** a terminal and **without** `--tools=` fails loudly and
  writes no package, rather than silently guessing a selection from
  maturity.

  **Share package output is isolated from the pipeline zip.** A share
  build writes to `dist/share/WinMCP-share-<YYYYMMDD>-<HHMMSS>.zip`, never
  `dist/WinMCP-<YYYYMMDD>.zip` — `deploy-qa.sh`/`promote-pro.sh` resolve
  their zip via a non-recursive `dist/WinMCP-*.zip` glob (or an exact
  marker filename), which never matches anything under `dist/share/`, so a
  share build can never collide with or be auto-picked-up as the
  pipeline's own zip. The default build's output is unaffected:
  `dist/WinMCP-<YYYYMMDD>.zip`, exactly as before.

  The final report states the exact package path prominently in share
  mode, and step 1 of "Next steps" names the file (e.g. "Copy
  `WinMCP-share-20260828-131723.zip` to the target machine") rather than
  the generic "Copy the zip". At an interactive console (TTY, and only
  when the genuine interactive picker ran — not `--tools=`), the report is
  followed by an offer to copy the package now: default destination
  `/mnt/c/usr/tmp` (created if missing), or type an alternate directory.
  On copy, both the WSL path (`/mnt/c/...`) and the equivalent Windows
  path (`C:\...`) are printed. Declining just exits, as before. A non-TTY
  `--share --tools=...` build never prompts — it prints the path and
  stops.

Either mode writes `tools/shipped-tools.json` into the package, recording
each of the 13 tools' `maturity` and `default_enabled` flag — the default
build sets `default_enabled: true` for all 13; a `--share` build mirrors
exactly the resolved selection (never a blanket flag). A build-time Gate 7
checks name-set equality across `tools/catalog.yaml`, `server.py`'s
registered `@app.tool` names, and `shipped-tools.json`, and confirms every
enabled tool's catalog dependencies were actually staged — the build fails
before zipping if any of that drifts.

#### Hard exclusion: unchecked in a `--share` build means physically absent

The selective-deploy picker above only ever controlled *default
enablement* — every tool's files always shipped, "shipped-but-disabled"
for anything left unchecked. Hard tool exclusion makes an unchecked tool
in a `--share` selection a **two-tier** guarantee instead of one:

1. **Build-time physical omission.** `tools/catalog.py::excluded_files()`
   computes the owner-set union of every tool's declared
   `deps.modules`/`deps.ps1` files across the *entire* catalog, then omits
   from staging every file whose owners are **all** unselected. A file
   shared by two tools (in the same family or different ones — e.g.
   `tools/ps_bridge_transport.py`, used by both `file` and `onenote`) is
   kept as long as *either* owner was selected; only a file with zero
   selected owners is ever dropped. `--share --tools=onenote_search`
   therefore still ships all of `onenote`'s shared files (one selected
   tool keeps the whole family's code present), but a `--tools=` selection
   with zero `mail`/`calendar`/`task`/`file` tools omits every one of
   those families' files entirely.
2. **Runtime registration ceiling.** `tools/shipped-tools.json`'s
   tool-name set becomes a hard ceiling `server.py`'s `_tool_enabled()`
   enforces alongside the existing `config/installed-tools.yaml` check: a
   tool must be in **both** the shipped set (or the ceiling is absent —
   legacy/full packages) and the installed set (or absent) to register.
   This closes the hand-edit hole the first tier alone would leave open:
   even if someone edited `config/installed-tools.yaml` on a deployed copy
   to add back a tool name that was never shipped, `server.py` still
   refuses to register it, because that tool's own code was never staged
   in the first place and its name never appears in the ceiling either way.

A full/default build always selects every tool, so `excluded_files()`
returns nothing and both tiers are no-ops — file-for-file, byte-identical
output to a pre-hard-exclusion build.

**What this does *not* protect against.** Hard exclusion is a build-time
staging choice plus a runtime allow-list — not a security or DRM boundary:
it does nothing to stop someone who received a curated package from
separately obtaining (or being handed) a fuller one and redistributing
that instead, and it does nothing to stop anyone from reading the plain
Python/PowerShell source of whatever *did* ship (no signing, obfuscation,
or sandboxing here). Its actual purpose is narrower and more mundane: let
you hand a colleague a package that never even carries the code for tool
families that touch mail/calendar/file content they have no need to see,
so an idle read of the extracted folder — or an idle re-enable attempt —
can't expose PII or confidential data that was never there to expose.

### Choosing which tools install enabled

At install time, `install.bat`/`install.ps1` reads the package's
`tools/shipped-tools.json` and resolves the enabled-tool set with this
priority:

1. **`-Preset <path-to-json-file>`** — pass `install.bat -Preset
   C:\path\to\preset.json` (or `install.ps1 -Preset ...` directly), where
   the file is `{"tools": ["tool_a", "tool_b"]}`. Explicit and scripted;
   an unknown tool name fails the install loudly, naming the offending
   tool.
2. **Non-interactive (no `-Preset`, stdin redirected/no console)** —
   enables exactly the manifest's `default_enabled=true` set, no prompt,
   never blocks. This is what `deploy-qa.sh`/`promote-pro.sh` rely on for
   their unattended `install.bat < /dev/null` runs.
3. **Interactive** — a per-family `y`/`n`/`s` prompt (same three-way
   choice as the `--share` build picker above), pre-checked per each
   tool's `default_enabled` flag, ending in a selection summary you can
   accept or redo.

Whichever path resolves, `install.ps1` writes `config/installed-tools.yaml`
(a flat `tools:` list) into the installed copy. If the package predates
this feature (no `tools/shipped-tools.json` staged), this whole step is
skipped and no `installed-tools.yaml` is written at all — the exact
back-compat path below.

### Runtime effect of the installed-tools selection

`server.py`'s `create_server(installed=..., shipped=...)` gates each of the
13 `@app.tool` registrations individually against **both** sets — a tool
registers only if it's in `installed` (or `installed` is absent/`None`)
**and** in `shipped` (or `shipped` is absent/`None`) **and** its family's
files are actually present on disk (per-family `importlib.util.find_spec`
guard, so a hard-excluded family's absent modules never even attempt an
import, let alone raise). `shipped` comes from `tools/shipped-tools.json`
(hard-tool-exclusion's build-time ceiling, absent = legacy package, no
ceiling); `installed` comes from `config/installed-tools.yaml` exactly as
before. Every tool module for a family whose files *are* present is still
imported unconditionally regardless of the installed selection, so a
merely-disabled (but shipped) tool's code is present but simply never
registered with the MCP client:

- `config/installed-tools.yaml` **absent** — every *shipped* tool
  registers, byte for byte the same as before this feature existed on a
  full/default package (exact back-compat: nothing installed by this
  project's `install.ps1` before this change ever wrote that file).
- `tools:` **present and non-empty** — only the listed tool names
  register, and only if they're also shipped; an unrecognized name, or a
  name absent from `shipped-tools.json` on a hard-excluded package, is
  silently ignored either way — there is no way to hand-edit this file
  back into a tool that was never shipped.
- `tools: []` (empty list) — zero tools register.

`deploy/smoke_test.py` derives its own expectations from the same file (a
small stdlib `re` scrape, no `yaml` import needed): a fully-disabled
family (none of its tools enabled) reports verdict `"skipped"` rather than
running any live check against it — skips are verdict-neutral, so a
selective install can still finish with an overall `SMOKE TEST PASSED`.

### Building a share package end-to-end

```bash
./make-deploy-package.sh --share                        # interactive whiptail checklist (or plain y/n if whiptail is absent)
./make-deploy-package.sh --share --no-tui                # interactive, but force the plain y/n picker
./make-deploy-package.sh --share --tools=onenote_search,onenote_get_page  # explicit, no prompt
./make-deploy-package.sh --share --tools=onenote_search  # single tool: still ships onenote's whole shared file set
                                                          # (onenote.py/onenote_adapter.py/ps_bridge_transport.py/
                                                          # ps_bridge_onenote.ps1), but shipped-tools.json's manifest
                                                          # lists ONLY onenote_search — the other 3 onenote tools are
                                                          # hard-excluded (physically absent from the ceiling, not
                                                          # merely default_enabled=false) even though their code
                                                          # rides along as a shared-file side effect.
```

Any selection that leaves zero tools of a family checked physically omits
that family's files from the zip entirely — e.g. `--tools=onenote_search`
alone still ships every `mail`/`calendar`/`task`/`file` module you'd see
in a default build, but `--tools=onenote_search,file_search` omits
`tools/calendar.py`, `tools/outlook_adapter.py`, `tools/tasks.py`,
`tools/task_adapter.py`, `tools/mail.py`, and `tools/mail_adapter.py`
outright (verify with `unzip -l` on the resulting `dist/share/*.zip`).

### Manual verification: selective build/install (Windows host)

The automated suite covers the catalog, the registration gate, and the
smoke-test derivation logic (via fakes/stubs), but the actual interactive
prompts and a real install only get exercised by hand, on a Windows host
with an attached console:

1. Build with `--share` and install at an interactive console: confirm the
   `whiptail` checklist arrives with `onenote`'s 4 tools pre-checked and
   the 9 alpha tools unchecked (labels `[family] tool_name`, maturity in
   the description); toggle one alpha tool on and one onenote tool off,
   confirm, and check the resulting `installed-tools.yaml` matches your
   override, not the maturity seed. Also confirm Cancel aborts the build
   with a nonzero exit and no zip, and that `--share --no-tui` falls back
   to the plain per-family `y`/`n` `read -p` loop instead. After a
   successful build, confirm the post-report copy offer: accept the
   default `/mnt/c/usr/tmp` destination, then repeat and type an
   alternate directory, checking both the `/mnt/c/...` and `C:\...`
   paths it prints; then decline and confirm it just exits.
2. Build with `--share` and no TTY, no `--tools=`: confirm the build fails
   loudly and produces no package. Then build with `--share
   --tools=a,b` and no TTY: confirm it succeeds unattended, staging
   exactly the named tools with `shipped-tools.json` marking exactly those
   `default_enabled=true`.
3. Install a `--share` subset (e.g. `onenote` only), then run
   `smoke_test.py` against it: confirm live checks run only for `onenote`
   while every other family reports `"skipped"`, with the overall verdict
   unaffected by the skips.

## Deploying from this dev machine (QA → PRO)

The instructions above are for a third party installing a zip they were
handed. On *this* dev machine (WSL2 + a WSL2-mounted Windows host under
`/mnt/c`), two root scripts automate getting a freshly built zip in front
of a human validator and then, once approved, onto the live install —
without ever touching Claude Desktop's config:

1. **Build**: `./make-deploy-package.sh` (see "Building the package" above)
   produces `dist/WinMCP-<YYYYMMDD>.zip`.
2. **Deploy to QA**: `./deploy-qa.sh` (no argument needed — it picks the
   newest `dist/WinMCP-*.zip` by modification time; pass a path explicitly
   to deploy an older one). It wipes any prior QA install, extracts the
   zip into a disposable sandbox at `C:\usr\WinMCP-qa`, runs
   `install.bat` non-interactively, and writes a `QA-VALIDATED.txt`
   marker (zip name, sha256, UTC timestamp) inside that sandbox. This
   never touches `C:\usr\WinMCP` (the live PRO install) or Claude
   Desktop's config.
3. **Manual validation (the human gate)**: on the Windows host,
   double-click **`test.bat`** inside `C:\usr\WinMCP-qa`. This is the same
   `test.bat`/`deploy/smoke_test.py` described in "Install (on the Windows
   host)" above, except it now exercises **every registered tool family**
   (calendar, tasks, mail-inbox, mail-sent, mail-drafts, files), not just
   calendar, and prints one line per family plus a final overall verdict:
   - **`SMOKE TEST PASSED`** — every family's search+detail chain
     succeeded. Safe to promote.
   - **`SMOKE TEST PASSED WITH WARNINGS`** — the MCP plumbing is fine, but
     one or more families couldn't reach Outlook (not installed, not
     running, or no profile). Still safe to promote once you're satisfied
     the warning is environmental, not a real regression.
   - **`SMOKE TEST FAILED`** — something is actually broken. Do **not**
     promote; fix the issue (re-running `install.bat` in `WinMCP-qa`
     fixes most causes) and re-deploy to QA before trying again.
4. **Promote to PRO**: **quit Claude Desktop first** — it keeps the PRO
   server's `python.exe` (under `C:\usr\WinMCP\.venv`) alive as a
   subprocess for as long as it's running, and `promote-pro.sh` has a hard
   lock gate that refuses to run while that process is alive (this is
   unconditional; it is the one thing `--force` does *not* override). Once
   Claude Desktop is closed, run `./promote-pro.sh`. With no argument it
   resolves the zip named in `QA-VALIDATED.txt` and refuses to promote if
   that zip's sha256 no longer matches what was actually validated (pass
   `--force` to override *only* the sha256 check, e.g. if you rebuilt an
   identical package after QA passed). On a clean run it wipes
   `wheels/` and unzips onto `C:\usr\WinMCP` in place (the same
   overwrite-preserving-`.venv` mechanics the old `dist/deploy.sh` used),
   runs `install.bat` non-interactively, copies the zip to the OneDrive
   `_DEV\WinMCP\_OUT` audit folder, and writes a `DEPLOYED.txt` marker
   (same schema as `QA-VALIDATED.txt`, with `deployed_utc` instead of
   `validated_utc`).
5. **Restart Claude Desktop** to pick up the new PRO install.
   `claude_desktop_config.json` itself never changes across this flow —
   only the files under `C:\usr\WinMCP` do.

**Rollback**: if a promoted build turns out to be bad, promote an older
zip from `dist/` explicitly, e.g. `./promote-pro.sh dist/WinMCP-20260731.zip
--force`. `--force` is required here because that older zip's sha256 won't
match the current `QA-VALIDATED.txt` (which still names whatever was most
recently QA'd) — the lock gate and the actual install/copy/marker steps
all behave identically to a normal promotion.
