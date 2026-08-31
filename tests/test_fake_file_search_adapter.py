"""RED tests for tools/fake_file_search_adapter.py — FakeFileSearchAdapter
(test-only `FileSearchPort`, file-search change).

Covers: seed-by-`FileDetail` `search()` filtering (filename substring on
`name`, phrase substring on the seeded `snippet`, roots containment) and
`top_n` cap; `get_info()` hit (exact/normalized path match, including a
`file:///`-style URL form), miss (`FileNotFoundInIndexError`), and
placeholder (seeded file with `snippet=None` still returns full metadata).

Mirrors `tools/fake_mail_adapter.py::FakeMailAdapter` — lets the full
Strict TDD RED-GREEN-REFACTOR cycle run on WSL2 Linux with zero `win32com`
dependency (see design.md's "Mirror the mail seam exactly" approach). The
adapter is config-unaware per the windows-search-adapter spec's "Adapter
Interface" requirement — roots enforcement/defense-in-depth belongs to the
tool layer (a later batch); here `roots` is just the SCOPE the adapter
searches under.
"""
from datetime import datetime, timezone

import pytest

from models.schemas import FileDetail, FileSummary
from tools.errors import FileNotFoundInIndexError
from tools.fake_file_search_adapter import FakeFileSearchAdapter


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
    snippet="expense tracking",
)
SHARED_MEMO = _file(
    "D:\\Shared\\memo.txt",
    "memo.txt",
    extension=".txt",
)
PLACEHOLDER = _file(
    "C:\\Users\\ana\\OneDrive\\placeholder.pdf",
    "placeholder.pdf",
    extension=".pdf",
    snippet=None,
)
SIBLING = _file(
    "C:\\Users\\ana2\\Documents\\other.docx",
    "other.docx",
    extension=".docx",
)


def _adapter() -> FakeFileSearchAdapter:
    return FakeFileSearchAdapter(files=[REPORT, BUDGET, SHARED_MEMO, PLACEHOLDER, SIBLING])


# ---------------------------------------------------------------------------
# search() filtering
# ---------------------------------------------------------------------------


def test_search_filters_by_filename_substring_case_insensitive():
    results = _adapter().search(
        filename="REPORT", phrase=None, roots=["C:\\Users\\ana"], top_n=200
    )

    assert [r.path for r in results] == [REPORT.path]
    assert isinstance(results[0], FileSummary)


def test_search_filters_by_phrase_substring_against_snippet():
    results = _adapter().search(
        filename=None, phrase="budget forecast", roots=["C:\\Users\\ana"], top_n=200
    )

    assert [r.path for r in results] == [REPORT.path]


def test_search_result_omits_created_time_and_snippet_fields():
    results = _adapter().search(
        filename="report", phrase=None, roots=["C:\\Users\\ana"], top_n=200
    )

    assert not hasattr(results[0], "created_time")
    assert not hasattr(results[0], "snippet")


def test_search_restricts_to_given_roots():
    results = _adapter().search(
        filename=None, phrase=None, roots=["D:\\Shared"], top_n=200
    )

    assert [r.path for r in results] == [SHARED_MEMO.path]


def test_search_root_containment_does_not_match_sibling_prefix():
    results = _adapter().search(
        filename=None, phrase=None, roots=["C:\\Users\\ana"], top_n=200
    )

    assert SIBLING.path not in [r.path for r in results]


def test_search_applies_top_n_cap():
    results = _adapter().search(
        filename=None, phrase=None, roots=["C:\\Users\\ana", "D:\\Shared"], top_n=1
    )

    assert len(results) == 1


def test_search_empty_result_returns_empty_list():
    results = _adapter().search(
        filename="doesnotexist", phrase=None, roots=["C:\\Users\\ana"], top_n=200
    )

    assert results == []


# ---------------------------------------------------------------------------
# get_info() hit / miss / placeholder
# ---------------------------------------------------------------------------


def test_get_info_returns_matching_detail_for_exact_path():
    detail = _adapter().get_info(REPORT.path)

    assert detail.path == REPORT.path
    assert detail.name == "report.docx"
    assert detail.snippet == "quarterly results and budget forecast"


def test_get_info_accepts_file_url_form_of_a_seeded_path():
    detail = _adapter().get_info(
        "file:///C:/Users/ana/OneDrive/placeholder.pdf"
    )

    assert detail.path == PLACEHOLDER.path


def test_get_info_raises_file_not_found_in_index_for_unknown_path():
    with pytest.raises(FileNotFoundInIndexError):
        _adapter().get_info("C:\\Users\\ana\\ghost.txt")


def test_get_info_placeholder_file_returns_metadata_with_snippet_none():
    detail = _adapter().get_info(PLACEHOLDER.path)

    assert detail.snippet is None
    assert detail.size == PLACEHOLDER.size
    assert detail.created_time == PLACEHOLDER.created_time
    assert detail.last_modified == PLACEHOLDER.last_modified
