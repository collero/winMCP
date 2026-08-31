"""Tests for tools/onenote.py — the tool-layer functions for the four
OneNote MCP tools (onenote_search, onenote_get_page, onenote_create_page,
onenote_update_page), exercised against `FakeOneNoteAdapter`
(add-onenote-adapter change).

Phase 5: onenote_search (onenote-search spec)
Phase 6: onenote_get_page (onenote-get-page spec)
Phase 7: writable-notebook allowlist (onenote-write-page spec's
    "Writable Notebook Allowlist" requirement) — exercised through
    onenote_create_page/onenote_update_page directly (Phase 8), since the
    allowlist has no MCP-tool shape of its own.
Phase 8: onenote_create_page / onenote_update_page (onenote-write-page
    spec)
"""
from datetime import datetime, timezone

import pytest

from models.schemas import (
    CreatePageRequest,
    GetPageRequest,
    ListPagesRequest,
    OneNoteSearchRequest,
    PageDetail,
    UpdatePageRequest,
)
from tools.errors import (
    OneNotePageConflictError,
    OneNotePageNotFoundError,
    OneNoteSectionNotFoundError,
    OneNoteUnavailableError,
    OneNoteWriteNotAllowedError,
)
from tools.fake_onenote_adapter import FakeOneNoteAdapter
from tools.onenote import (
    onenote_list_pages,
    onenote_list_sections,
    onenote_create_page,
    onenote_get_page,
    onenote_search,
    onenote_update_page,
)
from tools.onenote_adapter import NotebookNode, SectionNode


def _page(
    page_id: str,
    title: str,
    body_text: str = "",
    *,
    notebook_name: str = "z - Test Notebook",
    section_name: str = "General",
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


def _hierarchy(*notebooks: tuple[str, str, list[tuple[str, str]]]) -> list[NotebookNode]:
    """Build a `list[NotebookNode]` from `(notebook_id, notebook_name,
    [(section_id, section_name), ...])` tuples."""
    return [
        NotebookNode(
            notebook_id=notebook_id,
            name=notebook_name,
            sections=[SectionNode(section_id=sid, name=sname) for sid, sname in sections],
        )
        for notebook_id, notebook_name, sections in notebooks
    ]


# ---------------------------------------------------------------------------
# Phase 5: onenote_search
# ---------------------------------------------------------------------------


def test_search_returns_matching_pages():
    pages = [
        _page("PAGE-1", "Factura de luz", notebook_name="Notebook A"),
        _page("PAGE-2", "Factura de agua", notebook_name="Notebook B"),
        _page("PAGE-3", "Reunión semanal", notebook_name="Notebook A"),
    ]
    adapter = FakeOneNoteAdapter(pages=pages)
    request = OneNoteSearchRequest(query="factura")

    result = onenote_search(request, adapter)

    assert {page.page_id for page in result} == {"PAGE-1", "PAGE-2"}
    by_id = {page.page_id: page for page in result}
    assert by_id["PAGE-1"].notebook_name == "Notebook A"
    assert by_id["PAGE-2"].notebook_name == "Notebook B"


def test_search_rejects_empty_query(mocker):
    adapter = FakeOneNoteAdapter()
    spy = mocker.spy(adapter, "search")
    request = OneNoteSearchRequest(query="")

    with pytest.raises(ValueError):
        onenote_search(request, adapter)

    spy.assert_not_called()


def test_search_no_matches_returns_empty_list():
    adapter = FakeOneNoteAdapter(pages=[_page("PAGE-1", "Reunión semanal")])
    request = OneNoteSearchRequest(query="noexiste")

    result = onenote_search(request, adapter)

    assert result == []


def test_search_default_limit_is_50():
    pages = [_page(f"PAGE-{i}", f"Nota {i}") for i in range(80)]
    adapter = FakeOneNoteAdapter(pages=pages)
    request = OneNoteSearchRequest(query="a")

    result = onenote_search(request, adapter)

    assert len(result) == 50


def test_search_oversized_limit_clamped_to_200(mocker):
    pages = [_page(f"PAGE-{i}", f"Nota {i}") for i in range(5)]
    adapter = FakeOneNoteAdapter(pages=pages)
    spy = mocker.spy(adapter, "search")
    request = OneNoteSearchRequest(query="a", limit=10000)

    onenote_search(request, adapter)

    spy.assert_called_once_with("a", 200)


def test_search_zero_limit_rejected():
    adapter = FakeOneNoteAdapter()
    request = OneNoteSearchRequest(query="a", limit=0)

    with pytest.raises(ValueError):
        onenote_search(request, adapter)


def test_search_unavailable_raises_tool_error():
    adapter = FakeOneNoteAdapter(unavailable=True)
    request = OneNoteSearchRequest(query="a")

    with pytest.raises(OneNoteUnavailableError):
        onenote_search(request, adapter)


# ---------------------------------------------------------------------------
# Phase 6: onenote_get_page
# ---------------------------------------------------------------------------


def test_get_page_successful_fetch():
    page = _page(
        "PAGE-1",
        "Reunión semanal",
        "Notas de la reunión.",
        notebook_name="Notebook A",
        section_name="General",
        last_modified=datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
    )
    adapter = FakeOneNoteAdapter(pages=[page])
    request = GetPageRequest(page_id="PAGE-1")

    result = onenote_get_page(request, adapter)

    assert result.title == "Reunión semanal"
    assert result.body_text == "Notas de la reunión."
    assert result.notebook_name == "Notebook A"
    assert result.section_name == "General"
    assert result.last_modified == datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)


def test_get_page_unknown_id_raises_not_found():
    adapter = FakeOneNoteAdapter(pages=[])
    request = GetPageRequest(page_id="BAD-ID")

    with pytest.raises(OneNotePageNotFoundError):
        onenote_get_page(request, adapter)


def test_get_page_empty_body_returns_empty_string_not_error():
    page = _page("PAGE-2", "Página vacía", "")
    adapter = FakeOneNoteAdapter(pages=[page])
    request = GetPageRequest(page_id="PAGE-2")

    result = onenote_get_page(request, adapter)

    assert result.body_text == ""
    assert result.title == "Página vacía"


def test_get_page_unavailable_raises_tool_error():
    adapter = FakeOneNoteAdapter(unavailable=True)
    request = GetPageRequest(page_id="PAGE-1")

    with pytest.raises(OneNoteUnavailableError):
        onenote_get_page(request, adapter)


def test_get_page_fetch_does_not_mutate_and_is_repeatable(mocker):
    page = _page("PAGE-3", "Estable")
    adapter = FakeOneNoteAdapter(pages=[page])
    create_spy = mocker.spy(adapter, "create_page")
    update_spy = mocker.spy(adapter, "update_page")
    request = GetPageRequest(page_id="PAGE-3")

    first = onenote_get_page(request, adapter)
    second = onenote_get_page(request, adapter)

    assert first == second
    create_spy.assert_not_called()
    update_spy.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 7 / 8: onenote_create_page / onenote_update_page (allowlist +
# optimistic concurrency)
# ---------------------------------------------------------------------------


def test_create_page_to_default_test_notebook_succeeds(mocker):
    hierarchy = _hierarchy(("NB-1", "z - Test Notebook", [("SEC-1", "General")]))
    adapter = FakeOneNoteAdapter(hierarchy=hierarchy)
    spy = mocker.spy(adapter, "create_page")
    request = CreatePageRequest(section_id="SEC-1", title="Nueva pagina", body_text="Contenido")

    result = onenote_create_page(request, adapter)

    spy.assert_called_once_with("SEC-1", "Nueva pagina", "Contenido")
    assert result.page_id.startswith("FAKE-PAGE-")
    assert result.notebook_name == "z - Test Notebook"


def test_create_page_to_live_notebook_refused_before_adapter_call(mocker):
    hierarchy = _hierarchy(("NB-2", "Informa - Proyectos", [("SEC-2", "General")]))
    adapter = FakeOneNoteAdapter(hierarchy=hierarchy)
    spy = mocker.spy(adapter, "create_page")
    request = CreatePageRequest(section_id="SEC-2", title="No permitido", body_text="x")

    with pytest.raises(OneNoteWriteNotAllowedError) as excinfo:
        onenote_create_page(request, adapter)

    assert excinfo.value.notebook_name == "Informa - Proyectos"
    spy.assert_not_called()


def test_write_refusal_message_carries_exact_remediation(mocker):
    """The refusal is the agent-facing surface: the calling LLM only sees
    the error text, so it MUST spell out the exact action that lifts the
    gate — add '<notebook>' to the `onenote_writable_notebooks` list in
    the server's own settings.yaml (absolute path) — and note that no
    restart is needed (the allowlist is re-read live on every call)."""
    hierarchy = _hierarchy(("NB-2", "Informa - Proyectos", [("SEC-2", "General")]))
    adapter = FakeOneNoteAdapter(hierarchy=hierarchy)
    request = CreatePageRequest(section_id="SEC-2", title="No permitido", body_text="x")

    with pytest.raises(OneNoteWriteNotAllowedError) as excinfo:
        onenote_create_page(request, adapter)

    message = str(excinfo.value)
    from tools.settings import settings_file_path

    assert "add 'Informa - Proyectos' to the 'onenote_writable_notebooks' list" in message
    assert settings_file_path() in message
    assert "no restart needed" in message


def test_create_page_configured_allowlist_widens_writable_set(mocker):
    hierarchy = _hierarchy(("NB-3", "Sandbox", [("SEC-3", "General")]))
    adapter = FakeOneNoteAdapter(hierarchy=hierarchy)
    mocker.patch(
        "tools.onenote.onenote_writable_notebooks",
        return_value=["z - Test Notebook", "Sandbox"],
    )
    spy = mocker.spy(adapter, "create_page")
    request = CreatePageRequest(section_id="SEC-3", title="Permitido", body_text="x")

    onenote_create_page(request, adapter)

    spy.assert_called_once_with("SEC-3", "Permitido", "x")


def test_create_page_unknown_section_raises_section_not_found():
    adapter = FakeOneNoteAdapter(hierarchy=[])
    request = CreatePageRequest(section_id="MISSING", title="x", body_text="x")

    with pytest.raises(OneNoteSectionNotFoundError):
        onenote_create_page(request, adapter)


def test_create_page_returns_page_detail_with_new_page_id(mocker):
    hierarchy = _hierarchy(("NB-1", "z - Test Notebook", [("SEC-1", "General")]))
    adapter = FakeOneNoteAdapter(hierarchy=hierarchy)
    request = CreatePageRequest(section_id="SEC-1", title="Titulo", body_text="Cuerpo")

    result = onenote_create_page(request, adapter)

    assert isinstance(result, PageDetail)
    assert result.title == "Titulo"
    assert result.body_text == "Cuerpo"


def test_create_page_unavailable_raises_tool_error():
    hierarchy = _hierarchy(("NB-1", "z - Test Notebook", [("SEC-1", "General")]))
    adapter = FakeOneNoteAdapter(hierarchy=hierarchy, unavailable=True)
    request = CreatePageRequest(section_id="SEC-1", title="x", body_text="x")

    with pytest.raises(OneNoteUnavailableError):
        onenote_create_page(request, adapter)


def test_update_page_matching_date_succeeds():
    modified = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    page = _page("PAGE-1", "Original", "Cuerpo original", last_modified=modified)
    adapter = FakeOneNoteAdapter(pages=[page])
    request = UpdatePageRequest(
        page_id="PAGE-1", body_text="Cuerpo nuevo", expected_last_modified=modified
    )

    result = onenote_update_page(request, adapter)

    assert result.body_text == "Cuerpo nuevo"


def test_update_page_stale_date_raises_conflict_and_no_write_recorded():
    modified = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    stale = datetime(2026, 8, 19, 9, 0, tzinfo=timezone.utc)
    page = _page("PAGE-1", "Original", "Cuerpo original", last_modified=modified)
    adapter = FakeOneNoteAdapter(pages=[page])
    request = UpdatePageRequest(
        page_id="PAGE-1", body_text="Intento fallido", expected_last_modified=stale
    )

    with pytest.raises(OneNotePageConflictError):
        onenote_update_page(request, adapter)

    assert adapter.get_page("PAGE-1").body_text == "Cuerpo original"


def test_update_page_to_live_notebook_refused_before_adapter_call(mocker):
    modified = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    page = _page(
        "PAGE-1", "Original", "Cuerpo", notebook_name="Informa - Proyectos", last_modified=modified
    )
    adapter = FakeOneNoteAdapter(pages=[page])
    spy = mocker.spy(adapter, "update_page")
    request = UpdatePageRequest(
        page_id="PAGE-1", body_text="x", expected_last_modified=modified
    )

    with pytest.raises(OneNoteWriteNotAllowedError):
        onenote_update_page(request, adapter)

    spy.assert_not_called()


def test_update_page_unknown_id_raises_not_found():
    adapter = FakeOneNoteAdapter(pages=[])
    request = UpdatePageRequest(
        page_id="BAD-ID",
        body_text="x",
        expected_last_modified=datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(OneNotePageNotFoundError):
        onenote_update_page(request, adapter)


def test_update_page_unavailable_raises_tool_error():
    adapter = FakeOneNoteAdapter(unavailable=True)
    request = UpdatePageRequest(
        page_id="PAGE-1",
        body_text="x",
        expected_last_modified=datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(OneNoteUnavailableError):
        onenote_update_page(request, adapter)


# ---------------------------------------------------------------------------
# onenote/0002-0005 mailbox round (2026-08-28): equality guard, unguarded
# escape hatch, onenote_list_sections, diagnostic section-not-found message
# ---------------------------------------------------------------------------


def test_update_page_newer_date_is_also_a_conflict():
    """OneNote's own check is EQUALITY (live-confirmed): a value NEWER
    than the page's stored time is just as doomed as a stale one, and the
    message says which direction (cowork's 0005 Q1)."""
    modified = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    newer = datetime(2026, 8, 21, 9, 0, tzinfo=timezone.utc)
    page = _page("PAGE-1", "Original", "Cuerpo original", last_modified=modified)
    adapter = FakeOneNoteAdapter(pages=[page])
    request = UpdatePageRequest(
        page_id="PAGE-1", body_text="Intento fallido", expected_last_modified=newer
    )

    with pytest.raises(OneNotePageConflictError) as excinfo:
        onenote_update_page(request, adapter)

    assert "NEWER" in str(excinfo.value)
    assert adapter.get_page("PAGE-1").body_text == "Cuerpo original"


def test_update_page_omitted_date_is_unguarded_overwrite():
    """The escape hatch (onenote/0005): an omitted
    `dateExpectedLastModified` skips the concurrency check entirely —
    without it, a caller whose freshly-read value is still refused (the
    lazy-stamp flicker) is permanently locked out of the page."""
    modified = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    page = _page("PAGE-1", "Original", "Cuerpo original", last_modified=modified)
    adapter = FakeOneNoteAdapter(pages=[page])
    request = UpdatePageRequest(page_id="PAGE-1", body_text="Sin guarda")

    result = onenote_update_page(request, adapter)

    assert result.body_text == "Sin guarda"


def test_update_page_unguarded_still_checks_allowlist(mocker):
    """The escape hatch skips the CONCURRENCY check, never the
    writable-notebook allowlist."""
    page = _page("PAGE-1", "Original", notebook_name="Informa - Governance")
    adapter = FakeOneNoteAdapter(pages=[page])
    spy = mocker.spy(adapter, "update_page")
    request = UpdatePageRequest(page_id="PAGE-1", body_text="x")

    with pytest.raises(OneNoteWriteNotAllowedError):
        onenote_update_page(request, adapter)

    spy.assert_not_called()


def test_list_sections_returns_every_notebook_section_pair():
    adapter = FakeOneNoteAdapter(
        hierarchy=_hierarchy(
            ("{NB-1}{1}{B0}", "z - Test Notebook", [("{SEC-1}{1}{B0}", "New Section 1")]),
            (
                "{NB-2}{1}{B0}",
                "Informa - Governance",
                [("{SEC-2}{1}{B0}", "Actas"), ("{SEC-3}{1}{B0}", "Planes")],
            ),
        )
    )

    rows = onenote_list_sections(adapter)

    assert [(r.notebook_name, r.section_name, r.section_id) for r in rows] == [
        ("z - Test Notebook", "New Section 1", "{SEC-1}{1}{B0}"),
        ("Informa - Governance", "Actas", "{SEC-2}{1}{B0}"),
        ("Informa - Governance", "Planes", "{SEC-3}{1}{B0}"),
    ]
    assert rows[0].notebook_id == "{NB-1}{1}{B0}"


def test_list_sections_unavailable_raises_tool_error():
    adapter = FakeOneNoteAdapter(unavailable=True)

    with pytest.raises(OneNoteUnavailableError):
        onenote_list_sections(adapter)


def test_create_page_section_not_found_message_is_diagnostic():
    """The old bare message cost a debugging round (onenote/0003 defect
    2): the caller could not tell a wrong-id-form from a broken resolver.
    The message must say what was searched and what a real id looks
    like."""
    adapter = FakeOneNoteAdapter(
        hierarchy=_hierarchy(
            ("{NB-1}{1}{B0}", "z - Test Notebook", [("{SEC-1}{1}{B0}", "New Section 1")]),
        )
    )
    request = CreatePageRequest(
        section_id="New Section 1", title="T", body_text="B"
    )

    with pytest.raises(OneNoteSectionNotFoundError) as excinfo:
        onenote_create_page(request, adapter)

    text = str(excinfo.value)
    assert "1 section(s)" in text
    assert "1 notebook(s)" in text
    assert "{GUID}{1}{B0}" in text
    assert "onenote_list_sections" in text


# ---------------------------------------------------------------------------
# onenote_list_pages (add-onenote-list-pages: index-independent enumeration —
# onenote/0039+0041, seconded twice by cowork; FindPages silently omits
# unindexed pages, so search cannot be the only page-id route)
# ---------------------------------------------------------------------------


def _seeded_section_pages() -> FakeOneNoteAdapter:
    hierarchy = _hierarchy(
        ("{NB-1}{1}{B0}", "z - Test Notebook", [("{SEC-1}{1}{B0}", "New Section 1")]),
        ("{NB-2}{1}{B0}", "Informa - Governance", [("{SEC-2}{1}{B0}", "Actas")]),
    )
    pages = [
        PageDetail(
            page_id="PAGE-COS",
            title="COS - test table with formatting",
            body_text="Title 1",
            notebook_name="",  # bridge rows carry no notebook on this route
            section_name="New Section 1",
            section_id="{SEC-1}{1}{B0}",
            last_modified=datetime(2026, 8, 31, 11, 22, 47, tzinfo=timezone.utc),
        ),
        PageDetail(
            page_id="PAGE-NW",
            title="overnight control NW",
            body_text="",
            notebook_name="",
            section_name="New Section 1",
            section_id="{SEC-1}{1}{B0}",
        ),
        PageDetail(
            page_id="PAGE-OTHER",
            title="Acta enero",
            body_text="",
            notebook_name="",
            section_name="Actas",
            section_id="{SEC-2}{1}{B0}",
        ),
    ]
    return FakeOneNoteAdapter(pages=pages, hierarchy=hierarchy)


def test_list_pages_returns_section_pages_with_resolved_notebook():
    adapter = _seeded_section_pages()
    request = ListPagesRequest(section_id="{SEC-1}{1}{B0}")

    rows = onenote_list_pages(request, adapter)

    assert [r.page_id for r in rows] == ["PAGE-COS", "PAGE-NW"]
    # notebook_name is resolved by the tool layer via get_hierarchy — the
    # section-scoped bridge rows cannot carry it themselves.
    assert {r.notebook_name for r in rows} == {"z - Test Notebook"}
    assert rows[0].last_modified == datetime(2026, 8, 31, 11, 22, 47, tzinfo=timezone.utc)


def test_list_pages_empty_section_returns_empty_list():
    hierarchy = _hierarchy(
        ("{NB-1}{1}{B0}", "z - Test Notebook", [("{SEC-1}{1}{B0}", "New Section 1")]),
    )
    adapter = FakeOneNoteAdapter(pages=[], hierarchy=hierarchy)
    request = ListPagesRequest(section_id="{SEC-1}{1}{B0}")

    assert onenote_list_pages(request, adapter) == []


def test_list_pages_unknown_section_raises_diagnostic_section_not_found():
    """Same diagnostic contract as onenote_create_page (onenote/0003
    defect 2): the message must say what was searched and what a real id
    looks like — resolved BEFORE the adapter's list call."""
    adapter = _seeded_section_pages()
    request = ListPagesRequest(section_id="New Section 1")  # a NAME, not an id

    with pytest.raises(OneNoteSectionNotFoundError) as excinfo:
        onenote_list_pages(request, adapter)

    text = str(excinfo.value)
    assert "2 section(s)" in text
    assert "2 notebook(s)" in text
    assert "{GUID}{1}{B0}" in text
    assert "onenote_list_sections" in text


def test_list_pages_unavailable_raises_tool_error():
    adapter = FakeOneNoteAdapter(unavailable=True)
    request = ListPagesRequest(section_id="{SEC-1}{1}{B0}")

    with pytest.raises(OneNoteUnavailableError):
        onenote_list_pages(request, adapter)


def test_list_pages_rows_carry_resolved_notebook_id():
    """onenote/0043 defect: `notebookId` came back as "" on every live
    list_pages row while the same page's get_page/search rows carried the
    real id — the tool layer resolved the notebook NAME onto rows but not
    its ID. Both come from the same hierarchy walk; both must land."""
    adapter = _seeded_section_pages()
    request = ListPagesRequest(section_id="{SEC-1}{1}{B0}")

    rows = onenote_list_pages(request, adapter)

    assert {r.notebook_id for r in rows} == {"{NB-1}{1}{B0}"}


def test_list_pages_row_equals_search_row_for_an_indexed_page():
    """cowork's 0043 acceptance recipe for this defect class: fetch the
    same page by both routes and assert FULL-ROW equality — a set-level
    check (count, membership) cannot see a wrong field."""
    hierarchy = _hierarchy(
        ("{NB-1}{1}{B0}", "z - Test Notebook", [("{SEC-1}{1}{B0}", "New Section 1")]),
    )
    page = PageDetail(
        page_id="PAGE-FMT",
        title="Formatting survival test",
        body_text="Top-level bullet with bold text",
        notebook_name="z - Test Notebook",
        section_name="New Section 1",
        notebook_id="{NB-1}{1}{B0}",
        section_id="{SEC-1}{1}{B0}",
        last_modified=datetime(2026, 8, 28, 10, 23, 41, tzinfo=timezone.utc),
    )
    adapter = FakeOneNoteAdapter(pages=[page], hierarchy=hierarchy)

    [list_row] = onenote_list_pages(ListPagesRequest(section_id="{SEC-1}{1}{B0}"), adapter)
    [search_row] = onenote_search(OneNoteSearchRequest(query="Formatting"), adapter)

    assert list_row == search_row
