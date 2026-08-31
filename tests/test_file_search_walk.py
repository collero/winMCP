"""RED+GREEN tests for `tools/file_search_walk.py` — the bounded
`os.scandir` walk powering `filename` search (file-search-resilience
change, Phase 2).

Covers the filesystem-walk-search spec's requirements: case-insensitive
substring match, result/time/directory-count caps + `results_truncated`
flagging, no reparse-point traversal, and a silent skip of an unreadable
directory (siblings still walked). `os.scandir`/`time.monotonic` are
mocked throughout — no real filesystem access, mirroring the other
adapter/walk-layer tests' mocked-transport convention (e.g.
tests/test_file_search_adapter.py's mocked win32com/ADODB).

Each scenario in tasks.md's Phase 2 is labeled "RED+GREEN" (combined),
unlike Phase 1's split RED/GREEN task pairs — this file is written and
run against the not-yet-existing module first (confirmed as a collection
ImportError, i.e. RED), then `tools/file_search_walk.py` is implemented
to turn every test GREEN in one pass, since `walk_filename` is a single
cohesive algorithm rather than independently-implementable slices.
"""
import stat as stat_module

from tools.file_search_walk import walk_filename


class _FakeStat:
    """Minimal `os.stat_result`-like double — only the attributes
    `walk_filename`/`_is_reparse_point` actually read."""

    def __init__(self, size: int = 100, mtime: float = 0.0, reparse: bool = False):
        self.st_size = size
        self.st_mtime = mtime
        self.st_file_attributes = (
            stat_module.FILE_ATTRIBUTE_REPARSE_POINT if reparse else 0
        )


class _FakeEntry:
    """Minimal `os.DirEntry`-like test double with settable
    `is_dir()`/`is_symlink()`/`stat()` — mirrors design.md's Reparse-Point
    Check decision ("no real junction needed on WSL2")."""

    def __init__(
        self,
        name: str,
        path: str,
        *,
        is_dir: bool = False,
        is_symlink: bool = False,
        reparse: bool = False,
        size: int = 100,
        mtime: float = 0.0,
    ):
        self.name = name
        self.path = path
        self._is_dir = is_dir
        self._is_symlink = is_symlink
        self._stat = _FakeStat(size=size, mtime=mtime, reparse=reparse)

    def is_dir(self, follow_symlinks: bool = True) -> bool:
        return self._is_dir

    def is_symlink(self) -> bool:
        return self._is_symlink

    def stat(self, follow_symlinks: bool = True) -> _FakeStat:
        return self._stat


def _dir(name: str, path: str, *, reparse: bool = False, is_symlink: bool = False) -> _FakeEntry:
    return _FakeEntry(name, path, is_dir=True, is_symlink=is_symlink, reparse=reparse)


def _file(name: str, path: str, *, size: int = 100, mtime: float = 0.0) -> _FakeEntry:
    return _FakeEntry(name, path, is_dir=False, size=size, mtime=mtime)


def _scandir_from(tree: dict):
    """Build an `os.scandir` replacement from a `{path: [entries]}` map.
    A path mapped to the string `"PERMISSION_ERROR"` raises
    `PermissionError` instead of yielding entries."""

    def _fake_scandir(path):
        entries = tree.get(path, [])
        if entries == "PERMISSION_ERROR":
            raise PermissionError(f"Permission denied: {path!r}")
        return iter(entries)

    return _fake_scandir


# ---------------------------------------------------------------------------
# 2.1: case-insensitive substring match (+ recursion into subdirectories)
# ---------------------------------------------------------------------------


def test_walk_matches_filename_case_insensitive_substring(mocker):
    tree = {
        "C:\\scope": [
            _file("Report.md", "C:\\scope\\Report.md"),
            _file("notes.txt", "C:\\scope\\notes.txt"),
        ],
    }
    mocker.patch("tools.file_search_walk.os.scandir", side_effect=_scandir_from(tree))

    results, truncated = walk_filename(
        roots=["C:\\scope"], filename=".md", max_results=200, time_budget_s=5, max_dirs=5000
    )

    assert [r.name for r in results] == ["Report.md"]
    assert truncated is False


def test_walk_match_is_case_insensitive_on_the_query_too(mocker):
    tree = {
        "C:\\scope": [_file("Report.MD", "C:\\scope\\Report.MD")],
    }
    mocker.patch("tools.file_search_walk.os.scandir", side_effect=_scandir_from(tree))

    results, _ = walk_filename(
        roots=["C:\\scope"], filename=".md", max_results=200, time_budget_s=5, max_dirs=5000
    )

    assert [r.name for r in results] == ["Report.MD"]


def test_walk_recurses_into_subdirectories(mocker):
    tree = {
        "C:\\scope": [_dir("sub", "C:\\scope\\sub")],
        "C:\\scope\\sub": [_file("deep.md", "C:\\scope\\sub\\deep.md")],
    }
    mocker.patch("tools.file_search_walk.os.scandir", side_effect=_scandir_from(tree))

    results, truncated = walk_filename(
        roots=["C:\\scope"], filename=".md", max_results=200, time_budget_s=5, max_dirs=5000
    )

    assert [r.path for r in results] == ["C:\\scope\\sub\\deep.md"]
    assert truncated is False


def test_walk_result_carries_size_and_last_modified_from_stat(mocker):
    tree = {
        "C:\\scope": [_file("report.md", "C:\\scope\\report.md", size=2048, mtime=1_700_000_000.0)],
    }
    mocker.patch("tools.file_search_walk.os.scandir", side_effect=_scandir_from(tree))

    results, _ = walk_filename(
        roots=["C:\\scope"], filename="report", max_results=200, time_budget_s=5, max_dirs=5000
    )

    assert results[0].size == 2048
    assert results[0].last_modified.timestamp() == 1_700_000_000.0


def test_walk_only_matches_files_not_directory_names(mocker):
    """Triangulation: a directory whose own name matches `filename` is
    never itself returned as a result — only descended into. Only file
    entries are candidate matches."""
    tree = {
        "C:\\scope": [_dir("report-folder", "C:\\scope\\report-folder")],
        "C:\\scope\\report-folder": [],
    }
    mocker.patch("tools.file_search_walk.os.scandir", side_effect=_scandir_from(tree))

    results, _ = walk_filename(
        roots=["C:\\scope"], filename="report", max_results=200, time_budget_s=5, max_dirs=5000
    )

    assert results == []


# ---------------------------------------------------------------------------
# 2.2: result cap truncates and flags the response
# ---------------------------------------------------------------------------


def test_walk_result_cap_truncates_and_flags_truncated(mocker):
    entries = [_file(f"report{i}.md", f"C:\\scope\\report{i}.md") for i in range(300)]
    tree = {"C:\\scope": entries}
    mocker.patch("tools.file_search_walk.os.scandir", side_effect=_scandir_from(tree))

    results, truncated = walk_filename(
        roots=["C:\\scope"], filename="report", max_results=200, time_budget_s=5, max_dirs=5000
    )

    assert len(results) == 200
    assert truncated is True


# ---------------------------------------------------------------------------
# 2.3: wall-clock budget stops the walk early
# ---------------------------------------------------------------------------


def test_walk_time_budget_stops_early_and_flags_truncated(mocker):
    tree = {
        "C:\\scope": [_dir("sub", "C:\\scope\\sub")],
        "C:\\scope\\sub": [_file("deep.md", "C:\\scope\\sub\\deep.md")],
    }
    mocker.patch("tools.file_search_walk.os.scandir", side_effect=_scandir_from(tree))
    # First call establishes the deadline (t=0, budget=5 -> deadline=5).
    # Second call (top-of-loop budget check before the first directory) is
    # still within budget. Third call (top-of-loop check before the queued
    # "sub" directory) is past the deadline -> stop before visiting it.
    mocker.patch(
        "tools.file_search_walk.time.monotonic",
        side_effect=[0.0, 0.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
    )

    results, truncated = walk_filename(
        roots=["C:\\scope"], filename="deep", max_results=200, time_budget_s=5, max_dirs=5000
    )

    assert results == []
    assert truncated is True


# ---------------------------------------------------------------------------
# 2.4: directory-count budget stops the walk early
# ---------------------------------------------------------------------------


def test_walk_dir_count_budget_stops_early_and_flags_truncated(mocker):
    tree = {
        "C:\\scope": [_dir("a", "C:\\scope\\a"), _dir("b", "C:\\scope\\b")],
        "C:\\scope\\a": [_file("a.md", "C:\\scope\\a\\a.md")],
        "C:\\scope\\b": [_file("b.md", "C:\\scope\\b\\b.md")],
    }
    mocker.patch("tools.file_search_walk.os.scandir", side_effect=_scandir_from(tree))

    # max_dirs=1 -> only "C:\\scope" itself gets scanned; both "a" and "b"
    # (queued as a result of that scan) are never visited.
    results, truncated = walk_filename(
        roots=["C:\\scope"], filename=".md", max_results=200, time_budget_s=5, max_dirs=1
    )

    assert results == []
    assert truncated is True


def test_walk_completes_within_all_caps_when_dir_budget_exactly_suffices(mocker):
    """Triangulation: when the directory-count budget exactly covers every
    directory that exists, the walk completes naturally and is NOT flagged
    truncated."""
    tree = {
        "C:\\scope": [_file("a.md", "C:\\scope\\a.md")],
    }
    mocker.patch("tools.file_search_walk.os.scandir", side_effect=_scandir_from(tree))

    results, truncated = walk_filename(
        roots=["C:\\scope"], filename=".md", max_results=200, time_budget_s=5, max_dirs=1
    )

    assert [r.name for r in results] == ["a.md"]
    assert truncated is False


# ---------------------------------------------------------------------------
# Walk completes within all caps (3 entries, none hit)
# ---------------------------------------------------------------------------


def test_walk_completes_within_all_caps_returns_not_truncated(mocker):
    tree = {
        "C:\\scope": [
            _file("one.md", "C:\\scope\\one.md"),
            _file("two.md", "C:\\scope\\two.md"),
            _file("three.md", "C:\\scope\\three.md"),
        ],
    }
    mocker.patch("tools.file_search_walk.os.scandir", side_effect=_scandir_from(tree))

    results, truncated = walk_filename(
        roots=["C:\\scope"], filename=".md", max_results=200, time_budget_s=5, max_dirs=5000
    )

    assert len(results) == 3
    assert truncated is False


# ---------------------------------------------------------------------------
# 2.5: no reparse-point traversal
# ---------------------------------------------------------------------------


def test_walk_skips_reparse_point_directory_without_descending(mocker):
    tree = {
        "C:\\scope": [
            _dir("junction", "C:\\scope\\junction", reparse=True),
            _file("sibling.md", "C:\\scope\\sibling.md"),
        ],
        "C:\\scope\\junction": [_file("inside.md", "C:\\scope\\junction\\inside.md")],
    }
    scandir = mocker.patch(
        "tools.file_search_walk.os.scandir", side_effect=_scandir_from(tree)
    )

    results, truncated = walk_filename(
        roots=["C:\\scope"], filename=".md", max_results=200, time_budget_s=5, max_dirs=5000
    )

    assert [r.name for r in results] == ["sibling.md"]
    assert truncated is False
    scandir.assert_any_call("C:\\scope")
    assert mocker.call("C:\\scope\\junction") not in scandir.call_args_list


def test_walk_skips_symlinked_directory_without_descending(mocker):
    """Triangulation: a symlinked directory (is_symlink()=True) is also
    treated as a reparse point, independent of the Windows attribute
    check."""
    tree = {
        "C:\\scope": [
            _dir("link", "C:\\scope\\link", is_symlink=True),
            _file("sibling.md", "C:\\scope\\sibling.md"),
        ],
        "C:\\scope\\link": [_file("inside.md", "C:\\scope\\link\\inside.md")],
    }
    mocker.patch("tools.file_search_walk.os.scandir", side_effect=_scandir_from(tree))

    results, _ = walk_filename(
        roots=["C:\\scope"], filename=".md", max_results=200, time_budget_s=5, max_dirs=5000
    )

    assert [r.name for r in results] == ["sibling.md"]


# ---------------------------------------------------------------------------
# 2.6: unreadable directory is skipped silently, siblings still walked
# ---------------------------------------------------------------------------


def test_walk_permission_error_on_one_subdir_does_not_abort(mocker):
    tree = {
        "C:\\scope": [
            _dir("locked", "C:\\scope\\locked"),
            _dir("open", "C:\\scope\\open"),
        ],
        "C:\\scope\\locked": "PERMISSION_ERROR",
        "C:\\scope\\open": [_file("visible.md", "C:\\scope\\open\\visible.md")],
    }
    mocker.patch("tools.file_search_walk.os.scandir", side_effect=_scandir_from(tree))

    results, truncated = walk_filename(
        roots=["C:\\scope"], filename=".md", max_results=200, time_budget_s=5, max_dirs=5000
    )

    assert [r.name for r in results] == ["visible.md"]
    assert truncated is False
