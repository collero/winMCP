"""Bounded `os.scandir` walk powering `filename` search (file-search-
resilience change, Phase 2).

Implements `walk_filename()` per design.md's "Walk lives in a new
`tools/file_search_walk.py`" decision: a `filename` query never depends
on the Windows Search index, fixing both the BUG-001 outage and the fact
that some allowed roots (`C:\\usr`, `C:\\co`) are not indexed at all — see
the filesystem-walk-search spec.

The walk runs only over already-validated roots/scope (the tool layer's
roots-containment check runs before any walk, unchanged) — this module
never re-derives or widens scope, it just recurses breadth-first from the
given `roots`.

Caps (design.md's "Result and Resource Caps" requirement): `max_results`
(the existing `file_search_max_results` value, reused unchanged, passed
in by the caller — no new config key), plus two new resource budgets read
by the caller from `tools/settings.py`
(`file_search_walk_time_budget_seconds`, `file_search_walk_max_dirs`) and
passed in as `time_budget_s`/`max_dirs`. Hitting ANY cap while directories
remain unvisited stops the walk immediately and sets `results_truncated`
(the second element of the returned tuple) to `True`; a walk that
exhausts its queue naturally (no pending directories left when a cap is
reached) is NOT flagged truncated — see the "Walk completes within all
caps" scenario.

Reparse-point directories (`_is_reparse_point`, design.md's Reparse-Point
Check decision) are recognized but never descended into — this prevents
escaping an allowed root via a Windows junction, or looping via a cycle.
A directory that raises `PermissionError`/`OSError` on `os.scandir` is
skipped silently; the walk continues with the remaining tree rather than
raising (the "Unreadable Directories Are Skipped Silently" requirement).

Only file entries (`is_dir(follow_symlinks=False)` is `False`) are
candidate matches against `filename` — a directory whose own name happens
to match is never itself returned as a result, only descended into.
"""
import os
import stat as stat_module
import time
from datetime import datetime, timezone
from typing import Any

from models.schemas import FileSummary


def _is_reparse_point(entry: Any) -> bool:
    """True if `entry` (an `os.DirEntry`-like object) is a reparse point /
    junction / symlink and must not be descended into.

    `entry.is_symlink()` covers the common cross-platform case (also the
    case a test double sets explicitly, per design.md's decision). On
    Windows, a junction/reparse-point directory that reports
    `is_symlink() == False` is additionally caught via
    `entry.stat(follow_symlinks=False).st_file_attributes &
    stat.FILE_ATTRIBUTE_REPARSE_POINT` — that attribute is simply absent
    from a real Linux `stat_result`, so the check degrades to
    `is_symlink()` alone there (no real junction needed on WSL2 to test
    this)."""
    if entry.is_symlink():
        return True
    st = entry.stat(follow_symlinks=False)
    attributes = getattr(st, "st_file_attributes", 0)
    return bool(attributes & stat_module.FILE_ATTRIBUTE_REPARSE_POINT)


def _summary_from_entry(entry: Any) -> FileSummary:
    """Build a `FileSummary` from a matched file `os.DirEntry`-like
    `entry`, sourcing `size`/`last_modified` from `entry.stat()` — no
    Windows Search index involved. `extension` is derived from the name
    for parity with the index-backed adapter's `FileSummary.extension`
    (useful once a later batch intersects walk results with adapter
    results); `kind` has no filesystem-level equivalent and stays
    `None`."""
    st = entry.stat()
    extension = os.path.splitext(entry.name)[1] or None
    return FileSummary(
        path=entry.path,
        name=entry.name,
        size=st.st_size,
        last_modified=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
        extension=extension,
    )


def walk_filename(
    roots: list[str],
    filename: str,
    max_results: int,
    time_budget_s: float,
    max_dirs: int,
) -> tuple[list[FileSummary], bool]:
    """Breadth-first `os.scandir` walk starting at `roots`, matching
    `filename` as a case-insensitive substring against each file entry's
    name (mirroring the existing `System.FileName LIKE '%...%'`
    semantics).

    Returns `(results, results_truncated)`. `results_truncated` is `True`
    only when a cap (`max_results`/`time_budget_s`/`max_dirs`) was hit
    while directories were still pending — never when the walk simply ran
    out of tree to visit.
    """
    needle = filename.lower()
    results: list[FileSummary] = []
    dirs_visited = 0
    deadline = time.monotonic() + time_budget_s
    queue: list[str] = list(roots)
    truncated = False

    def _results_or_time_cap_hit() -> bool:
        return len(results) >= max_results or time.monotonic() >= deadline

    while queue:
        # The directory-count cap only gates STARTING another directory —
        # checking it inside the entry loop below would wrongly cut off
        # the entries of the very last directory the budget allows.
        if dirs_visited >= max_dirs or _results_or_time_cap_hit():
            truncated = True
            break

        current_dir = queue.pop(0)
        dirs_visited += 1

        try:
            entries = os.scandir(current_dir)
        except OSError:
            continue

        for entry in entries:
            if _results_or_time_cap_hit():
                truncated = True
                break

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue

            if is_dir:
                if not _is_reparse_point(entry):
                    queue.append(entry.path)
                continue

            if needle in entry.name.lower():
                results.append(_summary_from_entry(entry))

    return results[:max_results], truncated
