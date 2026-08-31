"""Tests for tools/file_search.py — the tool-layer functions for the two
file-search MCP tools (file_search, file_get_info), exercised against
FakeFileSearchAdapter (and, for adapter-misbehavior/unavailability
scenarios, a minimal hand-rolled stub — see below) plus a mocked
`walk_filename`/`os.stat` for the filesystem-facing legs.

Phase 4 (file-search change): tasks 4.1-4.6, covering the file-search and
file-get-info specs' "Search Input Parameters"/"Allowed-Roots Enforcement"/
"Path Normalization for Containment Check"/"Result Cap" requirements —
these are dispatch-agnostic (roots containment/mandatory-filter run
BEFORE any dispatch decision) and unaffected by Phase 5's rewrite.

Phase 5 (file-search-resilience change): tasks 5.1-5.9, covering the
dispatch split (`filename`-only -> walk only, never the adapter;
`phrase`-only -> adapter unchanged; both -> walk-then-intersect), the
`FileSearchResponse` envelope, the "filename search still works" message
augmentation, and the rewritten `os.stat`-first `file_get_info` (distinct
`path_not_found` vs. silently-swallowed enrichment failure).
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from models.schemas import FileDetail, FileSearchRequest, FileSearchResponse, FileSummary, GetFileInfoRequest
from tools.errors import (
    CalendarToolError,
    FileNotFoundInIndexError,
    PathNotFoundError,
    SearchRootNotAllowedError,
    WindowsSearchUnavailableError,
)
from tools.fake_file_search_adapter import FakeFileSearchAdapter
from tools.file_search import file_get_info, file_search


def _file(
    path: str,
    name: str,
    *,
    size: int = 1024,
    last_modified: datetime | None = None,
    created_time: datetime | None = None,
    kind: str | None = "Document",
    extension: str | None = None,
    snippet: str | None = None,
) -> FileDetail:
    return FileDetail(
        path=path,
        name=name,
        size=size,
        last_modified=last_modified or datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        created_time=created_time or datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
        kind=kind,
        extension=extension,
        snippet=snippet,
    )


def _summary(file_detail: FileDetail) -> FileSummary:
    """A bare FileSummary matching `file_detail`'s path/name/size/etc —
    what `walk_filename` would return for the same file (no `snippet`, and
    in practice no `kind`, since the walk never touches the index)."""
    return FileSummary(
        path=file_detail.path,
        name=file_detail.name,
        size=file_detail.size,
        last_modified=file_detail.last_modified,
        extension=file_detail.extension,
    )


def _fake_stat(
    *, size: int = 2048, mtime: float = 1_754_814_000.0, ctime: float = 1_754_037_600.0
) -> SimpleNamespace:
    """A minimal stand-in for `os.stat_result` carrying only the fields
    `tools/file_search.py::file_get_info` reads."""
    return SimpleNamespace(st_size=size, st_mtime=mtime, st_ctime=ctime)


REPORT = _file(
    "C:\\Users\\ana\\Documents\\report.docx",
    "report.docx",
    extension=".docx",
    snippet="quarterly results and budget forecast",
)
BUDGET = _file(
    "C:\\Users\\ana\\Documents\\budget.xlsx",
    "budget.xlsx",
    extension=".xlsx",
)
ONEDRIVE_DOC = _file(
    "C:\\Users\\ana\\OneDrive\\Docs\\notes.txt",
    "notes.txt",
    extension=".txt",
)


class _UnavailableAdapter:
    """Minimal FileSearchPort stub whose search()/get_info() simulate BOTH
    transports of the real `FallbackSearchAdapter` being exhausted — see
    the file-search / file-get-info / powershell-search-bridge specs'
    "Windows Search Unavailable" / "Both-Transports-Exhausted Messaging"
    requirements. `FakeFileSearchAdapter` has no such mode, so this is a
    small local double instead."""

    def search(self, filename, phrase, roots, top_n):
        raise WindowsSearchUnavailableError("Windows Search index unreachable")

    def get_info(self, path_or_url):
        raise WindowsSearchUnavailableError("Windows Search index unreachable")


class _OutsideRootsAdapter:
    """Minimal FileSearchPort stub whose search() ignores the `roots` it
    was given and always returns a row outside them — simulates a crafted/
    buggy SCOPE=/CONTAINS() match, exercising the tool layer's own
    post-call defense-in-depth drop (design.md decision #3b)."""

    def search(self, filename, phrase, roots, top_n):
        return [
            FileSummary(
                path="D:\\Shared\\outside.txt",
                name="outside.txt",
                size=10,
                last_modified=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
            )
        ]

    def get_info(self, path_or_url):
        raise NotImplementedError


class _AliasRowAdapter:
    """Minimal FileSearchPort stub returning ONE row whose `path` (the
    ItemPathDisplay-derived alias) and `alt_url_path` (the ItemUrl-
    derived native form) can independently be set inside or outside the
    allowed roots — exercises the tool layer's alias-aware containment
    fallback (alias-containment-hotfix): Windows Search can report a
    redirected-library alias in ItemPathDisplay while ItemUrl still
    carries the real, containable path."""

    def __init__(self, path: str, alt_url_path: str | None):
        self._path = path
        self._alt_url_path = alt_url_path

    def search(self, filename, phrase, roots, top_n):
        return [
            FileSummary(
                path=self._path,
                name="notes.txt",
                size=10,
                last_modified=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
                alt_url_path=self._alt_url_path,
            )
        ]

    def get_info(self, path_or_url):
        raise NotImplementedError


class _TruncatingAdapter:
    """Minimal FileSearchPort stub simulating `FallbackSearchAdapter`/
    `PowerShellSearchBridge` after a deadline-killed or early-dying child
    already streamed some rows (bridge-streaming-hotfix): `search()`
    returns `results` and sets the documented `last_search_truncated`
    attribute to `True`, exactly like the real bridge transport does —
    used to verify `tools/file_search.py` reads that attribute (via
    `getattr(adapter, "last_search_truncated", False)`) and ORs it into
    `FileSearchResponse.results_truncated`."""

    def __init__(self, results):
        self._results = results
        self.last_search_truncated = False

    def search(self, filename, phrase, roots, top_n):
        self.last_search_truncated = True
        return self._results

    def get_info(self, path_or_url):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 4.1: at least one of filename/phrase required (dispatch-agnostic)
# ---------------------------------------------------------------------------


def test_search_both_filename_and_phrase_omitted_raises_value_error(mocker):
    adapter = FakeFileSearchAdapter(files=[REPORT])
    spy = mocker.spy(adapter, "search")
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(scope="C:\\Users\\ana")

    with pytest.raises(ValueError, match="filename|phrase"):
        file_search(request, adapter)

    spy.assert_not_called()


def test_search_filename_and_phrase_both_absent_and_scope_absent_also_raises(mocker):
    """Triangulation: the mandatory-filter rule applies even when `scope`
    is also absent (a bare call)."""
    adapter = FakeFileSearchAdapter(files=[])
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest()

    with pytest.raises(ValueError):
        file_search(request, adapter)


# ---------------------------------------------------------------------------
# 4.2: roots containment (pre-call, before any dispatch decision)
# ---------------------------------------------------------------------------


def test_search_out_of_root_scope_raises_before_dispatch(mocker):
    adapter = FakeFileSearchAdapter(files=[])
    search_spy = mocker.spy(adapter, "search")
    walk_spy = mocker.patch("tools.file_search.walk_filename")
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(filename="x", scope="D:\\Shared")

    with pytest.raises(SearchRootNotAllowedError):
        file_search(request, adapter)

    search_spy.assert_not_called()
    walk_spy.assert_not_called()


def test_search_sibling_directory_shared_prefix_refused(mocker):
    adapter = FakeFileSearchAdapter(files=[])
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(filename="x", scope="C:\\Users\\ana2\\Documents")

    with pytest.raises(SearchRootNotAllowedError):
        file_search(request, adapter)


# ---------------------------------------------------------------------------
# 4.3: default roots resolved from environment when unconfigured
# ---------------------------------------------------------------------------


def test_search_unconfigured_roots_rejects_scope_outside_default_roots(mocker, monkeypatch):
    """Triangulation: an unconfigured-roots fallback still enforces
    containment — a scope outside the resolved defaults is refused."""
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.delenv("OneDriveCommercial", raising=False)
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\ana")
    mocker.patch("tools.file_search.load_settings", return_value={})
    adapter = FakeFileSearchAdapter(files=[])
    request = FileSearchRequest(filename="x", scope="D:\\Shared")

    with pytest.raises(SearchRootNotAllowedError):
        file_search(request, adapter)


# ---------------------------------------------------------------------------
# 5.1: filename-only never calls the adapter, even if it would raise
# ---------------------------------------------------------------------------


def test_search_filename_only_never_calls_adapter_even_if_it_would_raise(mocker):
    adapter = _UnavailableAdapter()  # would raise WindowsSearchUnavailableError if called
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    mocker.patch(
        "tools.file_search.walk_filename",
        return_value=([_summary(REPORT)], False),
    )
    request = FileSearchRequest(filename="report")

    response = file_search(request, adapter)

    assert isinstance(response, FileSearchResponse)
    assert [r.path for r in response.results] == [REPORT.path]
    assert response.results_truncated is False


# ---------------------------------------------------------------------------
# 5.2: filename-only succeeds under an unindexed scope (mocked walk)
# ---------------------------------------------------------------------------


def test_search_filename_only_succeeds_under_unindexed_scope(mocker):
    unindexed_match = FileSummary(
        path="C:\\usr\\WinMCP\\_chatCowork\\notes.md",
        name="notes.md",
        size=42,
        last_modified=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        extension=".md",
    )
    walk_spy = mocker.patch(
        "tools.file_search.walk_filename",
        return_value=([unindexed_match], False),
    )
    adapter = FakeFileSearchAdapter(files=[])  # unindexed: nothing seeded
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\usr"]},
    )
    request = FileSearchRequest(filename="notes", scope="C:\\usr\\WinMCP\\_chatCowork")

    response = file_search(request, adapter)

    assert [r.path for r in response.results] == [unindexed_match.path]
    # The walk starts at the validated `scope`, not the wider allowed root.
    assert walk_spy.call_args.args[0] == ["C:\\usr\\WinMCP\\_chatCowork"]
    assert walk_spy.call_args.args[1] == "notes"


def test_search_case_separator_variant_of_allowed_root_accepted(mocker):
    """Triangulation: a case/separator variant of the allowed root is
    still accepted for the roots check even though dispatch now goes to
    the (mocked) walk instead of the adapter."""
    mocker.patch(
        "tools.file_search.walk_filename",
        return_value=([_summary(REPORT)], False),
    )
    adapter = FakeFileSearchAdapter(files=[])
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(filename="report", scope="c:/users/ana/Documents")

    response = file_search(request, adapter)

    assert [r.path for r in response.results] == [REPORT.path]


def test_search_default_roots_resolved_from_environment_when_unconfigured(mocker, monkeypatch):
    monkeypatch.delenv("OneDriveCommercial", raising=False)
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\ana")
    monkeypatch.setenv("OneDrive", "C:\\Users\\ana\\OneDrive")
    mocker.patch("tools.file_search.load_settings", return_value={})
    mocker.patch(
        "tools.file_search.walk_filename",
        return_value=([_summary(ONEDRIVE_DOC)], False),
    )
    adapter = FakeFileSearchAdapter(files=[])
    request = FileSearchRequest(filename="notes", scope="C:\\Users\\ana\\OneDrive\\Docs")

    response = file_search(request, adapter)

    assert [r.path for r in response.results] == [ONEDRIVE_DOC.path]


# ---------------------------------------------------------------------------
# Result shape / caps: filename-only (walk) and phrase-only (adapter)
# ---------------------------------------------------------------------------


def test_search_filename_only_happy_path_returns_mapped_summaries(mocker):
    mocker.patch(
        "tools.file_search.walk_filename",
        return_value=([_summary(REPORT)], False),
    )
    adapter = FakeFileSearchAdapter(files=[])
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(filename="report")

    response = file_search(request, adapter)

    assert isinstance(response, FileSearchResponse)
    assert len(response.results) == 1
    assert isinstance(response.results[0], FileSummary)
    assert response.results[0].path == REPORT.path
    assert response.results[0].name == "report.docx"
    assert response.results_truncated is False


def test_search_filename_only_empty_result_returns_empty_list_not_error(mocker):
    mocker.patch("tools.file_search.walk_filename", return_value=([], False))
    adapter = FakeFileSearchAdapter(files=[])
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(filename="doesnotexist")

    response = file_search(request, adapter)

    assert response.results == []
    assert response.results_truncated is False


def test_search_filename_only_truncated_walk_is_flagged(mocker):
    mocker.patch(
        "tools.file_search.walk_filename",
        return_value=([_summary(REPORT)], True),
    )
    adapter = FakeFileSearchAdapter(files=[])
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(filename="report")

    response = file_search(request, adapter)

    assert response.results_truncated is True


def test_search_filename_only_drops_walk_row_outside_allowed_roots(mocker):
    """Post-call defense-in-depth also applies to the walk's own output,
    not just the adapter's."""
    outside = FileSummary(
        path="D:\\Shared\\outside.txt",
        name="outside.txt",
        size=10,
        last_modified=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
    )
    mocker.patch("tools.file_search.walk_filename", return_value=([outside], False))
    adapter = FakeFileSearchAdapter(files=[])
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(filename="x")

    response = file_search(request, adapter)

    assert response.results == []


def test_search_phrase_only_unconfigured_cap_defaults_to_200(mocker):
    adapter = FakeFileSearchAdapter(files=[REPORT])
    spy = mocker.spy(adapter, "search")
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(phrase="quarterly")

    file_search(request, adapter)

    assert spy.call_args.kwargs["top_n"] == 200


def test_search_phrase_only_configured_cap_passed_through(mocker):
    """Triangulation: a configured `file_search_max_results` overrides the
    200 default."""
    adapter = FakeFileSearchAdapter(files=[REPORT])
    spy = mocker.spy(adapter, "search")
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={
            "file_search_allowed_roots": ["C:\\Users\\ana"],
            "file_search_max_results": 5,
        },
    )
    request = FileSearchRequest(phrase="quarterly")

    file_search(request, adapter)

    assert spy.call_args.kwargs["top_n"] == 5


def test_search_phrase_only_happy_path_returns_mapped_summaries(mocker):
    adapter = FakeFileSearchAdapter(files=[REPORT, BUDGET])
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(phrase="quarterly")

    response = file_search(request, adapter)

    assert len(response.results) == 1
    assert response.results[0].path == REPORT.path
    assert response.results_truncated is False


def test_search_phrase_only_drops_result_row_outside_allowed_roots(mocker):
    """Post-call defense-in-depth: even though the adapter was asked to
    scope its search, a row it returns outside the allowed roots must be
    dropped before reaching the caller."""
    adapter = _OutsideRootsAdapter()
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(phrase="x")

    response = file_search(request, adapter)

    assert response.results == []


def test_search_phrase_only_keeps_alias_row_when_url_derived_path_is_in_root(mocker):
    """alias-containment-hotfix: Windows Search can report a redirected-
    library alias (System.ItemPathDisplay, e.g. `C:\\Documents\\...`)
    outside the allowed roots while System.ItemUrl still resolves to the
    real, in-root path (e.g. `C:\\co\\...`). The row must be KEPT, and its
    returned `path` rewritten to the real (ItemUrl-derived) form — never
    the alias, which would not be an openable/allowed path for the
    caller."""
    adapter = _AliasRowAdapter(
        path="C:\\Documents\\OneDrive - Informa\\notes.txt",
        alt_url_path="C:\\co\\OneDrive - Informa\\notes.txt",
    )
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\co"]},
    )
    request = FileSearchRequest(phrase="informa")

    response = file_search(request, adapter)

    assert len(response.results) == 1
    assert response.results[0].path == "C:\\co\\OneDrive - Informa\\notes.txt"


def test_search_phrase_only_drops_row_when_both_display_and_url_forms_outside_roots(mocker):
    """The alias fallback is not a blanket bypass: a row still gets
    dropped when NEITHER the display-derived nor the url-derived path is
    contained within an allowed root."""
    adapter = _AliasRowAdapter(
        path="D:\\Shared\\notes.txt",
        alt_url_path="E:\\Other\\notes.txt",
    )
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\co"]},
    )
    request = FileSearchRequest(phrase="informa")

    response = file_search(request, adapter)

    assert response.results == []


def test_search_phrase_only_keeps_row_path_unchanged_when_display_already_in_root(mocker):
    """Preserve existing behavior when the display-derived path already
    passes containment on its own — the row's `path` must stay exactly as
    the adapter returned it, never overwritten by `alt_url_path` even
    when one happens to be present."""
    adapter = _AliasRowAdapter(
        path="C:\\co\\notes.txt",
        alt_url_path="C:\\co\\alternate\\notes.txt",
    )
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\co"]},
    )
    request = FileSearchRequest(phrase="informa")

    response = file_search(request, adapter)

    assert len(response.results) == 1
    assert response.results[0].path == "C:\\co\\notes.txt"


def test_search_phrase_only_truncated_adapter_result_is_flagged(mocker):
    """bridge-streaming-hotfix: a phrase-only query whose adapter served a
    truncated result (a deadline-killed or early-dying bridge child that
    already streamed some rows) must surface that via
    `results_truncated=True` — there is no walk leg for this query shape,
    so this is the ONLY source of truncation on a phrase-only call."""
    adapter = _TruncatingAdapter([_summary(REPORT)])
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(phrase="quarterly")

    response = file_search(request, adapter)

    assert [r.path for r in response.results] == [REPORT.path]
    assert response.results_truncated is True


def test_search_phrase_only_fake_adapter_without_attribute_is_not_truncated(mocker):
    """Triangulation: `FakeFileSearchAdapter` (and a real `WindowsSearchAdapter`)
    never set `last_search_truncated` at all — `getattr(..., False)` must
    default cleanly rather than raising."""
    adapter = FakeFileSearchAdapter(files=[REPORT])
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(phrase="quarterly")

    response = file_search(request, adapter)

    assert response.results_truncated is False


# ---------------------------------------------------------------------------
# 5.3: phrase-only both-transports-fail message states filename search
# still works
# ---------------------------------------------------------------------------


def test_search_phrase_only_both_transports_fail_message_states_filename_still_works(mocker):
    adapter = _UnavailableAdapter()
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(phrase="quarterly report")

    with pytest.raises(WindowsSearchUnavailableError, match="filename search still works"):
        file_search(request, adapter)


def test_search_phrase_only_ado_then_bridge_failed_full_message_is_properly_punctuated(mocker):
    """BUG-006 (0043-cowork-bug-006-ps-bridge-malformed-json.md): the
    combined "both transports exhausted" message must join the adapter's
    own cause with the filename-still-works advice as two separate
    sentences ('. '), not a bare-space concatenation that reads as one
    garbled clause (e.g. "...malformed JSON filename search still
    works..."). Asserts the FULL rendered message, not just a substring
    -- message assembly is exactly where this bug lived."""
    adapter = _UnavailableAdapter()
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(phrase="quarterly report")

    with pytest.raises(WindowsSearchUnavailableError) as excinfo:
        file_search(request, adapter)

    assert str(excinfo.value) == (
        "Windows Search index unreachable. filename search still works — "
        "retry the same call with only 'filename' set (omit 'phrase')."
    )


# ---------------------------------------------------------------------------
# 5.4-5.6: combined filename+phrase query rule
# ---------------------------------------------------------------------------


def test_search_combined_intersects_walk_and_index_results(mocker):
    report_old = _summary(
        _file("C:\\Users\\ana\\Documents\\report-old.md", "report-old.md", extension=".md")
    )
    report_md = _file(
        "C:\\Users\\ana\\Documents\\report.md",
        "report.md",
        extension=".md",
        snippet="quarterly numbers",
    )
    mocker.patch(
        "tools.file_search.walk_filename",
        return_value=([_summary(report_md), report_old], False),
    )
    adapter = FakeFileSearchAdapter(files=[report_md])
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(filename="report", phrase="quarterly")

    response = file_search(request, adapter)

    assert [r.path for r in response.results] == [report_md.path]


def test_search_combined_or_semantics_true_when_only_phrase_leg_truncated(mocker):
    """bridge-streaming-hotfix: `results_truncated` on the combined leg is
    the OR of the walk's own flag and the adapter's `last_search_truncated`
    — here the walk completes cleanly (`False`) but the phrase leg's
    adapter reports a truncated bridge result, so the combined response
    must still be flagged."""
    report_md = _file(
        "C:\\Users\\ana\\Documents\\report.md",
        "report.md",
        extension=".md",
    )
    mocker.patch(
        "tools.file_search.walk_filename",
        return_value=([_summary(report_md)], False),
    )
    adapter = _TruncatingAdapter([_summary(report_md)])
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(filename="report", phrase="quarterly")

    response = file_search(request, adapter)

    assert response.results_truncated is True


def test_search_combined_or_semantics_true_when_only_walk_leg_truncated(mocker):
    """The other half of the OR: the phrase leg's adapter reports a clean,
    non-truncated result, but the walk itself hit its own cap — the
    combined response must still be flagged."""
    report_md = _file(
        "C:\\Users\\ana\\Documents\\report.md",
        "report.md",
        extension=".md",
        snippet="quarterly numbers",
    )
    mocker.patch(
        "tools.file_search.walk_filename",
        return_value=([_summary(report_md)], True),
    )
    adapter = FakeFileSearchAdapter(files=[report_md])
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(filename="report", phrase="quarterly")

    response = file_search(request, adapter)

    assert response.results_truncated is True


def test_search_combined_short_circuits_when_walk_finds_no_candidates(mocker):
    walk_spy = mocker.patch("tools.file_search.walk_filename", return_value=([], False))
    adapter = FakeFileSearchAdapter(files=[REPORT])
    search_spy = mocker.spy(adapter, "search")
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(filename="doesnotexist", phrase="quarterly")

    response = file_search(request, adapter)

    assert response.results == []
    walk_spy.assert_called_once()
    search_spy.assert_not_called()


def test_search_combined_propagates_unavailable_error_when_index_leg_exhausted(mocker):
    mocker.patch(
        "tools.file_search.walk_filename",
        return_value=([_summary(REPORT)], False),
    )
    adapter = _UnavailableAdapter()
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(filename="report", phrase="quarterly")

    with pytest.raises(WindowsSearchUnavailableError, match="filename search still works"):
        file_search(request, adapter)


# ---------------------------------------------------------------------------
# 4.6 / 5.7-5.9: file_get_info
# ---------------------------------------------------------------------------


def test_get_info_out_of_root_path_refused_before_stat_or_adapter_call(mocker):
    adapter = FakeFileSearchAdapter(files=[])
    get_info_spy = mocker.spy(adapter, "get_info")
    stat_spy = mocker.patch("tools.file_search.os.stat")
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = GetFileInfoRequest(path="D:\\Shared\\budget.xlsx")

    with pytest.raises(SearchRootNotAllowedError):
        file_get_info(request, adapter)

    get_info_spy.assert_not_called()
    stat_spy.assert_not_called()


def test_get_info_nonexistent_path_raises_path_not_found_error(mocker):
    mocker.patch(
        "tools.file_search.os.stat",
        side_effect=FileNotFoundError("no such file"),
    )
    adapter = FakeFileSearchAdapter(files=[REPORT])
    get_info_spy = mocker.spy(adapter, "get_info")
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = GetFileInfoRequest(path="C:\\Users\\ana\\ghost.txt")

    with pytest.raises(PathNotFoundError):
        file_get_info(request, adapter)

    # Index enrichment is never attempted once os.stat itself fails.
    get_info_spy.assert_not_called()


def test_get_info_real_unindexed_file_returns_stat_facts_no_error(mocker):
    mocker.patch("tools.file_search.os.stat", return_value=_fake_stat(size=555))
    adapter = FakeFileSearchAdapter(files=[])  # nothing indexed
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = GetFileInfoRequest(path="C:\\Users\\ana\\unindexed.txt")

    result = file_get_info(request, adapter)

    assert result.size == 555
    assert result.name == "unindexed.txt"
    assert result.kind is None
    assert result.snippet is None


def test_get_info_indexed_file_gets_enrichment_fields_populated(mocker):
    mocker.patch("tools.file_search.os.stat", return_value=_fake_stat())
    adapter = FakeFileSearchAdapter(files=[REPORT])
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = GetFileInfoRequest(path=REPORT.path)

    result = file_get_info(request, adapter)

    assert result.kind == REPORT.kind
    assert result.snippet == REPORT.snippet
    # Core facts still come from the (mocked) os.stat, not the index.
    assert result.name == "report.docx"


def test_get_info_index_unavailable_during_enrichment_does_not_fail_call(mocker):
    """Triangulation: file_get_info swallows an unreachable-index
    enrichment failure entirely — never propagates it, mirroring the
    file-get-info spec's ADDED "Index Enrichment Failure Never Surfaces"
    requirement."""
    mocker.patch("tools.file_search.os.stat", return_value=_fake_stat())
    adapter = _UnavailableAdapter()
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = GetFileInfoRequest(path="C:\\Users\\ana\\report.docx")

    result = file_get_info(request, adapter)

    assert result.kind is None
    assert result.snippet is None


# ---------------------------------------------------------------------------
# BUG-007 hotfix (0049-cowork-bug-007-phrase-untyped-crash.md): a hostile/
# buggy adapter -- one that violates the FileSearchPort contract by raising
# an arbitrary, non-taxonomy exception (simulating the exact class of bug
# BUG-007 was: a raw AttributeError leaking out of the bridge) or by
# returning None instead of a list/FileDetail -- must never let an untyped
# exception escape file_search()/file_get_info(). Every outcome must be
# either a valid response model or one of the typed CalendarToolError
# subclasses. Scoped to the file-search tools only; extending this
# contract-level property test to every MCP tool is future work.
# ---------------------------------------------------------------------------


class _HostileAdapter:
    """FileSearchPort double whose search()/get_info() either raise an
    arbitrary, non-taxonomy exception or return None -- simulating an
    adapter that violates its own contract, the exact shape of bug that
    let a raw `'NoneType' object has no attribute 'splitlines'`
    AttributeError leak out of the tool boundary in production."""

    def __init__(self, behavior):
        self._behavior = behavior

    def _resolve(self):
        if isinstance(self._behavior, BaseException):
            raise self._behavior
        return self._behavior

    def search(self, filename, phrase, roots, top_n):
        return self._resolve()

    def get_info(self, path_or_url):
        return self._resolve()


_HOSTILE_BEHAVIORS = [
    AttributeError("'NoneType' object has no attribute 'splitlines'"),
    RuntimeError("boom"),
    KeyError("x"),
    TypeError("bad"),
    None,
]


def _hostile_id(behavior):
    return type(behavior).__name__ if isinstance(behavior, BaseException) else "returns_None"


@pytest.mark.parametrize("behavior", _HOSTILE_BEHAVIORS, ids=_hostile_id)
def test_search_phrase_only_hostile_adapter_never_raises_untyped_error(mocker, behavior):
    adapter = _HostileAdapter(behavior)
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(phrase="Informa")

    try:
        response = file_search(request, adapter)
    except CalendarToolError:
        pass
    else:
        assert isinstance(response, FileSearchResponse)


@pytest.mark.parametrize("behavior", _HOSTILE_BEHAVIORS, ids=_hostile_id)
def test_search_combined_hostile_adapter_never_raises_untyped_error(mocker, behavior):
    mocker.patch(
        "tools.file_search.walk_filename",
        return_value=([_summary(REPORT)], False),
    )
    adapter = _HostileAdapter(behavior)
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(filename="report", phrase="quarterly")

    try:
        response = file_search(request, adapter)
    except CalendarToolError:
        pass
    else:
        assert isinstance(response, FileSearchResponse)


@pytest.mark.parametrize("behavior", _HOSTILE_BEHAVIORS, ids=_hostile_id)
def test_search_filename_only_hostile_adapter_is_unaffected(mocker, behavior):
    """Triangulation: a filename-only query never touches the adapter at
    all, so a hostile adapter must have zero effect on the response --
    always a valid FileSearchResponse, never an exception."""
    mocker.patch(
        "tools.file_search.walk_filename",
        return_value=([_summary(REPORT)], False),
    )
    adapter = _HostileAdapter(behavior)
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = FileSearchRequest(filename="report")

    response = file_search(request, adapter)

    assert isinstance(response, FileSearchResponse)


@pytest.mark.parametrize("behavior", _HOSTILE_BEHAVIORS, ids=_hostile_id)
def test_get_info_hostile_adapter_enrichment_failure_never_surfaces(mocker, behavior):
    """`file_get_info`'s own contract (file-get-info spec's "Index
    Enrichment Failure Never Surfaces" requirement) is unambiguous here,
    unlike search's either/or: a hostile adapter during enrichment must
    NEVER raise at all -- the call always succeeds with core os.stat
    facts and kind/snippet left None."""
    mocker.patch("tools.file_search.os.stat", return_value=_fake_stat())
    adapter = _HostileAdapter(behavior)
    mocker.patch(
        "tools.file_search.load_settings",
        return_value={"file_search_allowed_roots": ["C:\\Users\\ana"]},
    )
    request = GetFileInfoRequest(path="C:\\Users\\ana\\report.docx")

    result = file_get_info(request, adapter)

    assert isinstance(result, FileDetail)
    assert result.kind is None
    assert result.snippet is None
