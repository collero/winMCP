# Filesystem Walk Search Specification

## Purpose

Power `filename` search via a bounded `os.scandir` walk over already-
validated roots/scope, so a `filename` query never depends on the
Windows Search index — fixing both the BUG-001 outage and the fact that
some allowed roots (`C:\usr`, `C:\co`) are not indexed at all.

## Requirements

### Requirement: Walk Scope

The walk MUST run only over roots/scope already validated by the tool
layer's roots-containment check (unchanged, runs before any walk). It
MUST NOT independently re-derive or widen the search scope.

#### Scenario: Walk runs after the roots check

- GIVEN a validated `scope="C:\usr\WinMCP\_chatCowork"` inside an allowed root
- WHEN `filename` search executes
- THEN the walk starts at `scope`, not at any wider root

### Requirement: Case-Insensitive Substring Match

The walk MUST match `filename` as a case-insensitive substring against
each entry's name, mirroring the existing `System.FileName LIKE '%...%'`
semantics.

#### Scenario: Substring match on entry name

- GIVEN a mocked `os.scandir` yielding entries `Report.md`, `notes.txt`
- WHEN walked with `filename=".md"`
- THEN only `Report.md` is returned

### Requirement: Result and Resource Caps

The walk MUST cap returned rows at `file_search_max_results` (existing
key, reused unchanged). It MUST additionally enforce a wall-clock budget
(`file_search_walk_time_budget_seconds`, default `5`) and a
directory-count budget (`file_search_walk_max_dirs`, default `5000`).
When any cap is hit before the walk completes, it MUST stop immediately
and the response MUST set `results_truncated: true`. When the walk
completes within all caps, `results_truncated` MUST be `false`.

#### Scenario: Row cap truncates and flags the response

- GIVEN a mocked walk yielding 300 matching entries and `file_search_max_results=200`
- WHEN `filename` search executes
- THEN exactly 200 results are returned with `results_truncated: true`

#### Scenario: Time or directory budget stops the walk early

- GIVEN a mocked walk where the directory-count budget is exhausted before all directories are visited
- WHEN `filename` search executes
- THEN the walk stops, returns entries found so far, and `results_truncated: true`

#### Scenario: Walk completes within all caps

- GIVEN a mocked walk of 3 entries, all caps unhit
- WHEN `filename` search executes
- THEN `results_truncated` is `false`

### Requirement: No Reparse Point Traversal

The walk MUST NOT descend into a reparse point/junction (detected via a
mocked stat/`os.path.islink`-equivalent check), so it cannot escape an
allowed root or loop via a cycle.

#### Scenario: Reparse point directory is not descended into

- GIVEN a mocked `os.scandir` entry flagged as a reparse point/junction directory
- WHEN the walk reaches that entry
- THEN it is skipped without recursing into it, and the walk continues with siblings

### Requirement: Unreadable Directories Are Skipped Silently

A directory that raises `PermissionError` (or similar OS error) on
`os.scandir` MUST be skipped, and the walk MUST continue with the
remaining tree rather than raising.

#### Scenario: Permission error on one subdirectory does not abort the walk

- GIVEN a mocked `os.scandir` that raises `PermissionError` for one subdirectory and yields entries normally for siblings
- WHEN `filename` search executes
- THEN the failing subdirectory contributes no results and sibling results are still returned
