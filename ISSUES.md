# Known Issues

## ISSUE-001 — ~~OneNote tools see only one notebook under Claude Desktop~~ RESOLVED as misdiagnosis (2026-08-27)

- **Original report**: from Claude Desktop, OneNote tools appeared to
  surface only one notebook ("Informa - Team" seemed missing).
- **Correction (same day, user feedback from the live Desktop session)**:
  the hierarchy IS fully visible. Common search terms saturate the result
  cap (200 ceiling; default 50) and the hits cluster in
  "Informa - Governance", crowding every other notebook out of the list.
  A discriminating search term surfaces all notebooks — confirmed live:
  Governance, Team, Innovation and Projects, Stakeholder Management, and
  z - Test Notebook (including the same-day "QA live verification" pages).
- **No context/COM divergence exists** — the Desktop-spawned server sees
  the same hierarchy as WSL-launched runs.

### Follow-up enhancement candidate (OPEN): ENH-001 — onenote_search discoverability under broad queries

- **Problem**: `FindPages` returns hits in OneNote's own order; a broad
  term fills the capped result list from whichever notebook dominates,
  hiding the rest. The caller can't tell that results were saturated.
- **Candidate improvements** (pick at design time, not committed):
  1. Optional `notebook` (and/or `section`) filter parameter on
     `onenote_search` — FindPages accepts a hierarchy-scoped start ID, so
     this is cheap in the bridge.
  2. Surface a `results_truncated`-style flag when the cap was hit, so
     the caller knows to narrow the query (the transport already tracks
     truncation for the stream; this is result-cap truncation, distinct).
  3. Interleave results per notebook before applying the cap (fairness),
     or return per-notebook counts.
- **Priority**: low — workaround (discriminating terms) is effective and
  now known.

## ENH-002 — OneNote tool descriptions must state append/read semantics explicitly (DONE in repo 2026-08-28, rides the BUG-009 promote)

- **Reported**: 2026-08-28, from a live Claude Desktop session.
- **Problem**: the MCP-visible descriptions of `onenote_update_page` /
  `onenote_get_page` let a capable agent infer read-modify-write
  semantics ("sends the whole body, doesn't append") and refuse to write,
  fearing it would flatten a formatted page. Actual semantics
  (live-verified 2026-08-28, formatted-page round-trip, 6/6 structural
  checks): update APPENDS one paragraph and round-trips the page's
  original XML untouched — bullets/indent/bold all survive; the flattened
  plain text is only the READ representation.
- **Fix**: rewrite the `@app.tool` docstrings (server.py) for the two
  tools to state: (a) update appends, never replaces, formatting of
  existing content is preserved; (b) get_page's bodyText is a flattened
  reading view, not the storage format; (c) the expected-last-modified
  param is a conflict guard, not an invitation to write back the read
  body.
- **Blocked on**: selective-tool-deployment batch touching server.py —
  apply right after that change closes (or fold into its docs phase).
- **Partial progress (2026-08-28)**: the allowlist refusal message is now
  self-remediating (`tools/onenote.py::_check_writable` names the exact
  key, the deployment's own settings.yaml absolute path via
  `settings_file_path()`, and the no-restart-needed fact; test
  `test_write_refusal_message_carries_exact_remediation`). Remaining:
  the `@app.tool` docstring rewrites in server.py (append semantics,
  flattened-read note, conflict-guard framing).

## BUG-009 — OneNote update guard read the wrong timestamp source (CLOSED 2026-08-28: promoted 15:58Z, cowork battery 6/6 + all non-blocking checks PASS on PRO)

- **Reported**: 2026-08-28, cowork mailbox round (`_chatCowork/onenote/0001`–`0005`).
- **Severity, stated precisely**: could not EDIT any page older than
  OneNote's settle window (~10–20 min after last write); creating pages
  and editing fresh pages worked throughout. Not "cannot write".
- **Root cause (live-confirmed by prediction tests from both agents)**:
  OneNote keeps two last-modified values per page. The hierarchy XML's
  page attributes (`dateTime` = creation; `lastModifiedTime` goes stale
  indefinitely once a write settles) are what `get_page` returned and the
  bridge pre-check compared; COM's `UpdatePageContent` compares its
  `dateExpectedLastModified` for **equality** against the page XML root's
  own `lastModifiedTime`. Once the two diverged, no obtainable value
  could satisfy both checks.
- **Fix (all in `tools/ps_bridge_onenote.ps1` + surface)**:
  - `get_page`/`create_page`/`update_page` responses now report the
    page-XML `lastModifiedTime` — the value a follow-up guarded update
    will actually be compared against. **Semantic change**: the field
    previously reported was effectively the creation time.
  - Bridge pre-check reads the same source and compares `!=` (equality,
    matching COM), with a directional, value-first, untruncated message.
  - `dateExpectedLastModified` is now OPTIONAL: omitted = documented
    UNGUARDED overwrite (one-argument `UpdatePageContent`) — the escape
    hatch for the lazy-stamp flicker window, when even a freshly-read
    value can be refused.
  - `0x80042010` decodes to `hrLastModifiedDateDidNotMatch` + remediation.
  - New `onenote_list_sections` tool + `sectionId`/`notebookId` on
    search/get_page rows (section ids are `{GUID}{1}{B0}`; nothing
    returned them, so `onenote_create_page` was un-callable in practice).
    Section-not-found error now says what was searched and the id form.
- **Known residual (OneNote design, documented in tool descriptions)**:
  the stored timestamp is stamped lazily and can flicker after a write;
  a guarded update can still conflict in that window — re-read, or use
  the unguarded escape hatch.
- **QA**: 7/7 live bridge battery PASS (`deploy/qa_onenote_bridge_live.py`),
  suite 737. Live fixture: cowork's page `round2 aging probe R 2026-08-28`
  stays in `z - Test Notebook` for divergence-onset measurement.

- **Post-close residuals (tracked, from `_chatCowork/onenote/0017`)**:
  1. Divergence trigger — near-resolved (onenote/0023-0025 + cc census
     0024, 2026-08-28 16:33Z): NOT elapsed time, NOT Desktop restart, NOT
     OneNote close, NOT OneNote full restart, NOT the creating code path
     (spike-era pages diverged too). Census of all 17 test pages: every
     08-27 page written-after-creation and not re-written today is
     diverged; every 08-28 page converged — including pages with multiple
     landed writes today whose stored value still reads CREATION time. So:
     writes don't advance the stored value during a live session; the true
     last-write time lands at the overnight/idle settle, which the
     hierarchy never follows. MORNING PREDICTION (acceptance test, stated
     2026-08-28; corrected per onenote/0027 — W was WRITTEN at 16:07Z, and
     cowork minted the missing never-written control `overnight control
     NW`, created 16:41:47Z, NEVER WRITE TO IT): on MONDAY 2026-08-31 before any
     OneNote access (moved from 08-29: it was Friday — ~64h idle, a
     stronger dose; HARD FREEZE all weekend: NOBODY touches OneNote —
     no census, no COM, no notebook writes — until cowork's scheduled
     Monday probe posts; cc's census runs AFTER it and also checks
     `Formatting survival test` for a table plus scores `COS - test table
     with formatting`), the written arm (v1, v6, L, R, W, criterion-6, cc's
     QA page) reads diverged (page-XML ≈ last 08-28 write time), the two
     never-written controls stay converged — NW (MCP-created 16:41:47Z)
     AND `COS - test table with formatting` (UI-created ~17:10Z by Carlos,
     onenote/0033; NOBODY writes to either) —
     and a guarded update with the fresh get_page value lands. CAVEAT
     (0033): creating COS was OneNote activity at ~17:10Z, so the idle
     clock re-baselined there (~60h to Monday, experiment stands) and the
     read-out must say "diverged at or after 17:10Z Friday", never
     "diverged overnight". If it holds,
     close item as EXPLAINED (normal idle-settle behavior, harmless by
     construction since the fix reads page-XML everywhere on the write
     path; only onenote_search's hierarchy-sourced value stays stale, as
     documented).
  2. bodyText structure handling — DECIDED (onenote/0027: cowork accepted
     cc's read-side shape) and BUILT (onenote/0028, build 5443f2ed5a4b,
     suite 748, QA-deployed 16:48Z): `bodyTextIncomplete: true` on
     get_page/create/update responses when the page XML holds
     Table/Image/InkDrawing/InkWord; writes stay allowed (update
     round-trips the original XML, ENH-002). Pending promote. ACCEPTANCE FIXTURE
     EXISTS (onenote/0033): `COS - test table with formatting` (2x2 table
     + three heading styles — tests both sides of the predicate: flag true
     BECAUSE of the table, headings must NOT trigger it). Verification is
     a READ on COS after Monday's probe, and needs 5443f2ed5a4b promoted
     first. `Formatting survival test` table check stays as a second
     data point.
  3. NEWER-branch remediation — LIVE and verified from the caller side
     (onenote/0021, build c40cb257187b).
  4. Excerpt-cap truncation of the remediation clause (onenote/0021): the
     longer messages outgrew the transport's 200-char stderr excerpt. FIXED
     2026-08-28 16:24Z (build f99d6cc9b84b, QA-verified whole in both
     directions): pageId dropped from conflict messages (caller already has
     it) + wording compacted — rank message parts by what the caller cannot
     reconstruct, let the cap eat from the bottom. CLOSED: promoted
     16:42Z (f99d6cc9b84b), caller-side acceptance PASS both directions
     (onenote/0029) — both messages arrive whole, pageId gone.

## ENH-003 — `server_info` deployment self-identification (LIVE: promoted to PRO 2026-08-28 16:17Z, build c40cb257187b)

- **Requested**: 2026-08-28 by the owner, after the BUG-009 round showed a
  client cannot tell which build answers after a promote without a client
  restart (behavioral tells were needed).
- **Shipped**: 15th tool `server_info` (family `server`, stable): package
  name, builtUtc, buildId (content fingerprint: sha256-of-sha256s over the
  staged tree, so identical code ⇒ identical id across rebuilds),
  buildMode, installRoot (PRO/QA/checkout), pythonVersion, enabledTools;
  `note` explains a missing stamp on pre-stamp packages. Stamp written by
  make-deploy-package.sh as `build-info.json`. Mailbox convention: battery
  reports open with the server_info line.

## ENH-004 — bridge hint for COM cold-start timeout `0x80042023` (BUILT 2026-08-31 13:03Z, QA 435b89e197b5; onenote/0045+0047)

- **Observed**: 2026-08-31 12:53Z by cowork. FIRST COM call after the
  12:52Z promote (`FindPages`) failed with HRESULT `0x80042023`, then the
  IDENTICAL query succeeded on re-issue; seven intervening calls clean.
  Characterised as first-call-after-quiet-period, not query- or
  term-dependent (full sequence in `_chatCowork/onenote/_WORKLOG-cowork.md`).
- **HRESULT named**: `0x80042023` = `hrTimeOut`, "The action timed out"
  (OneNote COM error table, MicrosoftDocs office-developer-client-docs
  `error-codes-onenote.md`). A timeout, not a missing object — retry-safe
  by definition, unlike "OneNote is closed".
- **Proposed** (cowork, explicitly not asking for a build yet): map
  `0x80042023` in the bridge/adapter error path to a distinct hint, e.g.
  "[onenote_unavailable] ... COM call timed out (cold start?); safe to
  re-issue once" — so callers can tell retry-me from ask-the-human.
- **Interim mitigation**: morning-read procedure (onenote/0045 §3): the
  first OneNote call after a quiet period may fail with 0x80042023; treat
  as artefact, re-issue once, record BOTH attempts.
- **Built** (cowork's 0047 spec, adapter layer `_to_unavailable`): the
  marker match PREPENDS "COM call timed out (0x80042023 hrTimeOut) -
  transient, typically the first OneNote call after a quiet period; safe
  to re-issue once." to the error, transport diagnostics kept verbatim
  behind it. Deliberately NO auto-retry — legible, not invisible. 5 unit
  tests (all read ops + a non-timeout control); suite 772.

## ENH-005 — pywintypes may mislabel Outlook COM local wall-clock datetimes as UTC (OPEN, question for cowork)

- **Observed**: 2026-08-31 15:10Z during mail_write_draft's live pre-check:
  a draft saved at 15:10:54Z real time came back with
  `LastModificationTime = 17:10:54+00:00` — local CEST wall-clock carrying
  a UTC label (2h error), already "aware" so `_to_aware()` passes it
  through untouched.
- **Scope question**: the same pywintypes shape feeds every Outlook-family
  date (mail ReceivedTime/SentOn, calendar, tasks). If systemic, all those
  timestamps are off by the UTC offset. Never flagged in any mailbox round
  — verify before believing: cowork can compare a mail_get_message date
  against the same message's time shown in the Outlook UI.
- **Not touched tonight** (experiment-eve discipline): mail_write_draft
  follows the existing `_to_aware` convention; investigation is a
  post-morning-read item with cowork.
