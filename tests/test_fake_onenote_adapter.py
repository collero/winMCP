"""RED tests for tools/fake_onenote_adapter.py — FakeOneNoteAdapter
(test-only `OneNotePort`, add-onenote-adapter change).

Covers: seed-by-`PageDetail` `search()` filtering (case-insensitive
substring on `title`/`body_text`) and `top_n` cap; `get_page()` hit/miss
(`OneNotePageNotFoundError`); `get_hierarchy()` returning the seeded
`NotebookNode` tree; `create_page()`/`update_page()` (including the
`update_page()` optimistic-concurrency conflict per the onenote-write-page
spec's "Conflicting Update Raises, Never Silently Overwrites"
requirement); and every method raising `OneNoteUnavailableError` when the
fake is constructed with `unavailable=True`.

Mirrors `tools/fake_file_search_adapter.py::FakeFileSearchAdapter`/
`tools/fake_adapter.py::FakeCalendarAdapter` — lets the full Strict TDD
RED-GREEN-REFACTOR cycle run on WSL2 Linux with zero `win32com`/
`powershell.exe` dependency (onenote-com-adapter spec's "Fake adapter
satisfies the interface" scenario).
"""
from datetime import datetime, timezone

import pytest

from models.schemas import PageDetail
from tools.errors import (
    OneNotePageConflictError,
    OneNotePageNotFoundError,
    OneNoteSectionNotFoundError,
    OneNoteUnavailableError,
)
from tools.fake_onenote_adapter import FakeOneNoteAdapter
from tools.onenote_adapter import NotebookNode, SectionNode


def _page(
    page_id: str,
    title: str,
    *,
    notebook_name: str = "z - Test Notebook",
    section_name: str = "Notas",
    body_text: str = "",
    last_modified: datetime | None = None,
) -> PageDetail:
    return PageDetail(
        page_id=page_id,
        title=title,
        body_text=body_text,
        notebook_name=notebook_name,
        section_name=section_name,
        last_modified=last_modified,
    )


INVOICE = _page(
    "PAGE-1", "Factura agosto", body_text="Detalle de la factura de agosto."
)
MEETING = _page(
    "PAGE-2", "Reunión semanal", body_text="Notas de la reunión.",
    last_modified=datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
)
HIERARCHY = [
    NotebookNode(
        notebook_id="NB-1",
        name="z - Test Notebook",
        sections=[SectionNode(section_id="SEC-1", name="Notas")],
    ),
    NotebookNode(
        notebook_id="NB-2",
        name="Informa - Proyectos",
        sections=[SectionNode(section_id="SEC-2", name="Reuniones")],
    ),
]


# --- search() ---


def test_search_matches_title_substring_case_insensitively():
    adapter = FakeOneNoteAdapter(pages=[INVOICE, MEETING])

    results = adapter.search("FACTURA", top_n=50)

    assert [summary.page_id for summary in results] == ["PAGE-1"]
    assert results[0].title == "Factura agosto"


def test_search_matches_body_text_substring():
    adapter = FakeOneNoteAdapter(pages=[INVOICE, MEETING])

    results = adapter.search("reunión", top_n=50)

    assert [summary.page_id for summary in results] == ["PAGE-2"]


def test_search_no_matches_returns_empty_list():
    adapter = FakeOneNoteAdapter(pages=[INVOICE, MEETING])

    results = adapter.search("noexiste", top_n=50)

    assert results == []


def test_search_caps_results_at_top_n():
    pages = [_page(f"PAGE-{i}", f"Nota {i}") for i in range(5)]
    adapter = FakeOneNoteAdapter(pages=pages)

    results = adapter.search("nota", top_n=2)

    assert len(results) == 2


def test_search_raises_when_unavailable():
    adapter = FakeOneNoteAdapter(pages=[INVOICE], unavailable=True)

    with pytest.raises(OneNoteUnavailableError):
        adapter.search("factura", top_n=50)


# --- get_page() ---


def test_get_page_returns_seeded_detail():
    adapter = FakeOneNoteAdapter(pages=[MEETING])

    detail = adapter.get_page("PAGE-2")

    assert detail.title == "Reunión semanal"
    assert detail.body_text == "Notas de la reunión."


def test_get_page_unknown_id_raises_not_found():
    adapter = FakeOneNoteAdapter(pages=[MEETING])

    with pytest.raises(OneNotePageNotFoundError):
        adapter.get_page("BAD-ID")


def test_get_page_raises_when_unavailable():
    adapter = FakeOneNoteAdapter(pages=[MEETING], unavailable=True)

    with pytest.raises(OneNoteUnavailableError):
        adapter.get_page("PAGE-2")


# --- get_hierarchy() ---


def test_get_hierarchy_returns_seeded_tree():
    adapter = FakeOneNoteAdapter(hierarchy=HIERARCHY)

    tree = adapter.get_hierarchy()

    assert tree == HIERARCHY


def test_get_hierarchy_raises_when_unavailable():
    adapter = FakeOneNoteAdapter(hierarchy=HIERARCHY, unavailable=True)

    with pytest.raises(OneNoteUnavailableError):
        adapter.get_hierarchy()


# --- create_page() ---


def test_create_page_returns_detail_with_new_page_id_and_resolved_names():
    adapter = FakeOneNoteAdapter(hierarchy=HIERARCHY)

    created = adapter.create_page("SEC-1", "Nueva página", "Cuerpo nuevo.")

    assert created.title == "Nueva página"
    assert created.body_text == "Cuerpo nuevo."
    assert created.notebook_name == "z - Test Notebook"
    assert created.section_name == "Notas"
    assert created.page_id  # a new, non-empty id was assigned

    # The created page is now retrievable.
    assert adapter.get_page(created.page_id).title == "Nueva página"


def test_create_page_unknown_section_id_raises_section_not_found():
    adapter = FakeOneNoteAdapter(hierarchy=HIERARCHY)

    with pytest.raises(OneNoteSectionNotFoundError):
        adapter.create_page("BAD-SECTION", "Título", "Cuerpo")


def test_create_page_raises_when_unavailable():
    adapter = FakeOneNoteAdapter(hierarchy=HIERARCHY, unavailable=True)

    with pytest.raises(OneNoteUnavailableError):
        adapter.create_page("SEC-1", "Título", "Cuerpo")


# --- update_page() ---


def test_update_page_with_matching_date_succeeds():
    adapter = FakeOneNoteAdapter(pages=[MEETING])

    updated = adapter.update_page(
        "PAGE-2",
        "Cuerpo actualizado.",
        datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
    )

    assert updated.body_text == "Cuerpo actualizado."
    assert adapter.get_page("PAGE-2").body_text == "Cuerpo actualizado."


def test_update_page_unknown_id_raises_not_found():
    adapter = FakeOneNoteAdapter(pages=[MEETING])

    with pytest.raises(OneNotePageNotFoundError):
        adapter.update_page(
            "BAD-ID", "Cuerpo", datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
        )


def test_update_page_stale_date_raises_conflict_and_does_not_write():
    adapter = FakeOneNoteAdapter(pages=[MEETING])

    with pytest.raises(OneNotePageConflictError):
        adapter.update_page(
            "PAGE-2",
            "Cuerpo que no debería escribirse.",
            datetime(2026, 8, 19, 9, 0, tzinfo=timezone.utc),  # older than seeded
        )

    # No silent overwrite: the original body is untouched.
    assert adapter.get_page("PAGE-2").body_text == "Notas de la reunión."


def test_update_page_raises_when_unavailable():
    adapter = FakeOneNoteAdapter(pages=[MEETING], unavailable=True)

    with pytest.raises(OneNoteUnavailableError):
        adapter.update_page(
            "PAGE-2", "Cuerpo", datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
        )
