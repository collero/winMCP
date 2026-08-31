# Tasks: Hard Tool Exclusion

**Sequencing note**: `selective-tool-deployment` (still unarchived)
already shipped the current `server.py`, `make-deploy-package.sh`,
`tools/catalog.py`, `tools/settings.py` (incl. a 2026-08-28 fix adding
`ps_bridge_transport.py`/`ps_bridge_search.ps1` to a file family's
deps). It MUST archive before this change does. Every task below reads
the CURRENT file on disk first — never the design.md snippets, which
are illustrative only and may be stale.

Strict TDD: `source .venv/bin/activate && python3.12 -m pytest -q`
(baseline 705 passed). RED before GREEN for every Python unit.

## Phase 1: Infrastructure — catalog/settings foundations

- [x] 1.1 RED: in `tests/test_catalog.py`, add cases for a new
  `excluded_files(catalog, selected)`: a file owned only by a
  zero-selected family is excluded; a file shared by two families is
  kept if either has a selected tool.
- [x] 1.2 GREEN: read current `tools/catalog.py`, add `excluded_files()`
  (owner-set union over `deps.modules`+`deps.ps1`) matching its typing/
  docstring conventions.
- [x] 1.3 RED: in `tests/test_settings.py`, add cases for a new
  `shipped_tools()`: absent `tools/shipped-tools.json` → `None`; a
  tmp-path JSON with a tool-name list → that exact set.
- [x] 1.4 GREEN: read current `tools/settings.py` (mirror
  `installed_tools()`'s absent-file/`None` pattern), add `shipped_tools()`
  reading `tools/shipped-tools.json` next to it.

## Phase 2: Implementation — server import guards & ceiling

- [x] 2.1 RED: in `tests/test_server.py`, monkeypatch `find_spec` to
  simulate one family's modules absent; assert `create_server()` builds
  with no import error and registers zero tools of that family.
- [x] 2.2 GREEN: read current `server.py`'s module-level import block and
  per-family registration section; wrap each family's imports in a
  `find_spec`-presence guard, setting its tool callables to `None` when
  absent.
- [x] 2.3 RED: extend `tests/test_server.py` for `_tool_enabled()`:
  `shipped_tools()==None` falls back to installed-only (today's
  behavior); a sibling tool absent from a non-`None` `shipped_tools()`
  stays unenableable even when present in `installed_tools()`.
- [x] 2.4 GREEN: read current `_tool_enabled()` in `server.py`, update it
  to require `name` in (`shipped_tools()` or absent-ceiling) AND
  (`installed_tools()` or absent-ceiling) AND its family present.

## Phase 3: Implementation — packaging gates

- [x] 3.1 GREEN: read current `make-deploy-package.sh` MANIFEST staging
  block; in share mode, subtract `tools.catalog.excluded_files(catalog,
  selected)` before staging.
- [x] 3.2 GREEN: read current Gate 7 block; add a negative assertion —
  none of `excluded_files()` appear in the staged file list — alongside
  its existing positive per-tool dep check.
- [x] 3.3 GREEN (cheap): in Gate 7, grep `server.py`'s guarded per-family
  imports against `catalog.yaml`'s module deps; fail on a mismatch.

## Phase 4: Testing

- [x] 4.1 Shell: build `--share --tools=onenote_search` on WSL2; `unzip
  -l` asserts onenote's other files absent, shared infra
  (`ps_bridge_transport.py`, `settings.py`, `schemas.py`, `errors.py`,
  `server.py`) present.
- [x] 4.2 Shell: build `--share --tools=<all tools>`; diff its manifest
  listing against a full/default build's — confirm identical.
- [x] 4.3 Run `python3.12 -m pytest -q`; confirm only Phase 1-2 tests
  were added, zero regressions against the 705 baseline.
- [x] 4.4 Update `README.md`: hard exclusion does not block
  redistribution of a fuller package or reading shipped code.

## Phase 4 (Batch 4): Warning cleanup from sdd-verify

- [x] 4.5 Add a permanent regression test (`tests/test_server.py`) proving
  a genuine bug inside a PRESENT family module still propagates through
  `server.py`'s `find_spec` import guard, rather than being swallowed as
  "family absent" — closes verify-report.md WARNING 1. Plus the inverse
  control (genuinely absent module imports cleanly). Both run in a real
  subprocess against a hermetic `tmp_path` copy of `tools/`/`models/`/
  `server.py`; RED-verified against the exact `try/except ImportError`
  anti-pattern regression, then GREEN against the current guard.
- [x] 4.6 Extend `make-deploy-package.sh` Gate 7's check 5 (import-graph
  completeness) to also grep each catalog-declared dependency module for
  `ps_bridge_*.ps1` string references and require the referenced bridge
  script to be declared in the SAME tool's own `deps.ps1` — closes
  verify-report.md WARNING 2. Verified live: full build + share build
  both pass; a temporary (immediately restored) edit removing
  `tools/ps_bridge_search.ps1` from `file_search`'s `deps.ps1` in the real
  `catalog.yaml` made Gate 7 fail with a message naming the undeclared
  file; full pytest suite green (727) after restoring.

## Phase 5: Manual (Windows host, deferred)

- [ ] 5.1 On Windows: install a hard-excluded share package via
  `install.ps1`; confirm the picker never lists the excluded family,
  and hand-editing `config/installed-tools.yaml` can't enable it.
