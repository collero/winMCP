"""RED tests for tools/onenote_adapter.py's `OneNoteAdapter` — the real,
`PsBridgeTransport`-backed `OneNotePort` implementation (add-onenote-adapter
change).

Unlike `PowerShellSearchBridge` (tested only indirectly, via
stdin-capture assertions against a mocked `subprocess.Popen`, since no
real PowerShell exists on WSL2), these tests mock `PsBridgeTransport.invoke()`
directly — the transport's own spawn/deadline/JSON-Lines-parsing mechanics
are already covered by `tests/test_ps_bridge_transport.py`; what this
module needs proving is `OneNoteAdapter`'s OWN contract: the exact
`{"op": ...}` request shape it sends per method (onenote-com-adapter
spec's "Dumb-Executor Bridge Transport" requirement), its row-to-model
mapping (including the "Dynamic XML Namespace Detection"/"Page Content
Extraction" requirements — deliberately done in Python, not PowerShell,
for exactly this reason: it is unit-testable without a real bridge), and
its `PsBridgeTransportError` -> typed-error mapping (onenote-com-adapter
spec's "Failure Mapping" requirement; onenote-write-page spec's
"Conflicting Update Raises, Never Silently Overwrites" requirement).

Deviation from design.md's Decision 7 ("the script ... Returns plain
{title, text} JSON — Python never parses OneNote XML"): the bridge script
instead returns the page's raw XML (`pageXml`) for `GetPageContent`/
`CreateNewPage`/`UpdatePageContent`, and `OneNoteAdapter` itself extracts
title/body via `xml.etree.ElementTree` with the dynamic namespace
detection the onenote-com-adapter spec's own scenario describes as "the
adapter" doing ("WHEN the adapter parses it"). This is the ONE place that
extraction logic lives, unit-tested directly here, rather than living
un-unit-testable inside a `.ps1` script — the same "escape/parse in
exactly one place" precedent `_escape_like_value`/`_build_search_sql`
already established for file-search's SQL construction.
"""
from datetime import datetime, timedelta, timezone

import pytest

from models.schemas import PageDetail, PageSummary
from tools.errors import (
    OneNotePageConflictError,
    OneNotePageNotFoundError,
    OneNoteUnavailableError,
)
from tools.onenote_adapter import (
    _PS_BRIDGE_ONENOTE_SCRIPT,
    NotebookNode,
    OneNoteAdapter,
    SectionNode,
)
from tools.ps_bridge_transport import PsBridgeTransportError


def _page_xml(title: str, paragraphs: list[str], *, ns_uri: str) -> str:
    """Build a minimal but structurally real OneNote page XML document:
    a `Title/OE/T` CDATA node plus one `Outline/OEChildren/OE/T` CDATA
    node per paragraph — matching the onenote-com-adapter spec's "Page
    Content Extraction" requirement's shape. `ns_uri` is deliberately a
    parameter (not a hardcoded constant) so the namespace-independence
    tests below can exercise a non-default namespace URI."""
    body_oes = "".join(
        f"<one:OE><one:T><![CDATA[{paragraph}]]></one:T></one:OE>" for paragraph in paragraphs
    )
    return (
        f'<?xml version="1.0"?>'
        f'<one:Page xmlns:one="{ns_uri}" ID="PAGE-XML-ID">'
        f"<one:Title><one:OE><one:T><![CDATA[{title}]]></one:T></one:OE></one:Title>"
        f"<one:Outline><one:OEChildren>{body_oes}</one:OEChildren></one:Outline>"
        f"</one:Page>"
    )


_DEFAULT_NS = "http://schemas.microsoft.com/office/onenote/2013/onenote"


def _page_row(
    *,
    page_id: str = "PAGE-1",
    title: str = "Reunión semanal",
    paragraphs: list[str] | None = None,
    notebook_name: str = "z - Test Notebook",
    section_name: str = "Notas",
    last_modified: str | None = "2026-08-20T09:00:00+00:00",
    ns_uri: str = _DEFAULT_NS,
) -> dict:
    return {
        "pageId": page_id,
        "pageXml": _page_xml(title, paragraphs if paragraphs is not None else ["Notas de la reunión."], ns_uri=ns_uri),
        "notebookName": notebook_name,
        "sectionName": section_name,
        "lastModified": last_modified,
    }


# --- search() ---


def test_search_sends_findpages_request_with_query_only(mocker):
    transport = mocker.Mock()
    transport.invoke.return_value = ([], False)
    adapter = OneNoteAdapter(transport=transport)

    adapter.search("factura", top_n=50)

    args, kwargs = transport.invoke.call_args
    assert args[0] == _PS_BRIDGE_ONENOTE_SCRIPT
    assert args[1] == {"op": "FindPages", "query": "factura"}
    assert "timeout" in kwargs


def test_search_maps_rows_to_page_summaries(mocker):
    transport = mocker.Mock()
    transport.invoke.return_value = (
        [
            {
                "pageId": "PAGE-1",
                "title": "Factura agosto",
                "notebookName": "z - Test Notebook",
                "sectionName": "Notas",
                "lastModified": "2026-08-20T09:00:00+00:00",
            },
            {
                "pageId": "PAGE-2",
                "title": "Factura julio",
                "notebookName": "Informa - Proyectos",
                "sectionName": "Reuniones",
                "lastModified": None,
            },
        ],
        False,
    )
    adapter = OneNoteAdapter(transport=transport)

    results = adapter.search("factura", top_n=50)

    assert [summary.page_id for summary in results] == ["PAGE-1", "PAGE-2"]
    assert isinstance(results[0], PageSummary)
    assert results[0].notebook_name == "z - Test Notebook"
    assert results[0].last_modified == datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    assert results[1].last_modified is None


def test_search_truncates_to_top_n_client_side(mocker):
    transport = mocker.Mock()
    rows = [
        {
            "pageId": f"PAGE-{i}",
            "title": f"Nota {i}",
            "notebookName": "z - Test Notebook",
            "sectionName": "Notas",
            "lastModified": None,
        }
        for i in range(5)
    ]
    transport.invoke.return_value = (rows, False)
    adapter = OneNoteAdapter(transport=transport)

    results = adapter.search("nota", top_n=2)

    assert len(results) == 2


def test_search_transport_error_raises_onenote_unavailable(mocker):
    transport = mocker.Mock()
    transport.invoke.side_effect = PsBridgeTransportError("PowerShell onenote bridge blocked")
    adapter = OneNoteAdapter(transport=transport)

    with pytest.raises(OneNoteUnavailableError):
        adapter.search("factura", top_n=50)


# --- get_hierarchy() ---


def test_get_hierarchy_sends_bare_request(mocker):
    transport = mocker.Mock()
    transport.invoke.return_value = ([], False)
    adapter = OneNoteAdapter(transport=transport)

    adapter.get_hierarchy()

    args, _kwargs = transport.invoke.call_args
    assert args[1] == {"op": "GetHierarchy"}


def test_get_hierarchy_groups_rows_into_notebook_tree(mocker):
    transport = mocker.Mock()
    transport.invoke.return_value = (
        [
            {
                "notebookId": "NB-1",
                "notebookName": "z - Test Notebook",
                "sectionId": "SEC-1",
                "sectionName": "Notas",
            },
            {
                "notebookId": "NB-1",
                "notebookName": "z - Test Notebook",
                "sectionId": "SEC-2",
                "sectionName": "Archivo",
            },
            {
                "notebookId": "NB-2",
                "notebookName": "Informa - Proyectos",
                "sectionId": "SEC-3",
                "sectionName": "Reuniones",
            },
        ],
        False,
    )
    adapter = OneNoteAdapter(transport=transport)

    tree = adapter.get_hierarchy()

    assert tree == [
        NotebookNode(
            notebook_id="NB-1",
            name="z - Test Notebook",
            sections=[
                SectionNode(section_id="SEC-1", name="Notas"),
                SectionNode(section_id="SEC-2", name="Archivo"),
            ],
        ),
        NotebookNode(
            notebook_id="NB-2",
            name="Informa - Proyectos",
            sections=[SectionNode(section_id="SEC-3", name="Reuniones")],
        ),
    ]


def test_get_hierarchy_transport_error_raises_onenote_unavailable(mocker):
    transport = mocker.Mock()
    transport.invoke.side_effect = PsBridgeTransportError("boom")
    adapter = OneNoteAdapter(transport=transport)

    with pytest.raises(OneNoteUnavailableError):
        adapter.get_hierarchy()


# --- get_page() ---


def test_get_page_sends_getpagecontent_request(mocker):
    transport = mocker.Mock()
    transport.invoke.return_value = ([_page_row()], False)
    adapter = OneNoteAdapter(transport=transport)

    adapter.get_page("PAGE-1")

    args, _kwargs = transport.invoke.call_args
    assert args[1] == {"op": "GetPageContent", "pageId": "PAGE-1"}


def test_get_page_extracts_title_and_body_from_nested_cdata(mocker):
    transport = mocker.Mock()
    transport.invoke.return_value = (
        [_page_row(title="Reunión semanal", paragraphs=["Primer párrafo.", "Segundo párrafo."])],
        False,
    )
    adapter = OneNoteAdapter(transport=transport)

    detail = adapter.get_page("PAGE-1")

    assert isinstance(detail, PageDetail)
    assert detail.title == "Reunión semanal"
    assert detail.body_text == "Primer párrafo.\nSegundo párrafo."
    assert detail.notebook_name == "z - Test Notebook"
    assert detail.section_name == "Notas"
    assert detail.last_modified == datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)


def test_get_page_extracts_correctly_with_a_non_default_namespace(mocker):
    """onenote-com-adapter spec's "Dynamic XML Namespace Detection"
    requirement: the namespace is read from the document's own root
    element, never hardcoded."""
    transport = mocker.Mock()
    transport.invoke.return_value = (
        [
            _page_row(
                title="Página antigua",
                paragraphs=["Contenido antiguo."],
                ns_uri="http://schemas.microsoft.com/office/onenote/2010/onenote",
            )
        ],
        False,
    )
    adapter = OneNoteAdapter(transport=transport)

    detail = adapter.get_page("PAGE-1")

    assert detail.title == "Página antigua"
    assert detail.body_text == "Contenido antiguo."


def test_get_page_empty_result_raises_not_found(mocker):
    transport = mocker.Mock()
    transport.invoke.return_value = ([], False)
    adapter = OneNoteAdapter(transport=transport)

    with pytest.raises(OneNotePageNotFoundError):
        adapter.get_page("BAD-ID")


def test_get_page_transport_not_found_error_raises_page_not_found(mocker):
    transport = mocker.Mock()
    transport.invoke.side_effect = PsBridgeTransportError(
        "PowerShell onenote bridge produced no usable output "
        "(exit: exit code 1; stderr: script error: page not found: BAD-ID)"
    )
    adapter = OneNoteAdapter(transport=transport)

    with pytest.raises(OneNotePageNotFoundError):
        adapter.get_page("BAD-ID")


def test_get_page_transport_generic_error_raises_onenote_unavailable(mocker):
    transport = mocker.Mock()
    transport.invoke.side_effect = PsBridgeTransportError("PowerShell onenote bridge blocked")
    adapter = OneNoteAdapter(transport=transport)

    with pytest.raises(OneNoteUnavailableError):
        adapter.get_page("PAGE-1")


# --- create_page() ---


def test_create_page_sends_section_id_title_and_body(mocker):
    transport = mocker.Mock()
    transport.invoke.return_value = (
        [_page_row(title="Nueva página", paragraphs=["Cuerpo nuevo."])],
        False,
    )
    adapter = OneNoteAdapter(transport=transport)

    adapter.create_page("SEC-1", "Nueva página", "Cuerpo nuevo.")

    args, _kwargs = transport.invoke.call_args
    assert args[1] == {
        "op": "CreateNewPage",
        "sectionId": "SEC-1",
        "title": "Nueva página",
        "bodyText": "Cuerpo nuevo.",
    }


def test_create_page_returns_page_detail_with_new_page_id(mocker):
    transport = mocker.Mock()
    transport.invoke.return_value = (
        [_page_row(page_id="PAGE-NEW", title="Nueva página", paragraphs=["Cuerpo nuevo."])],
        False,
    )
    adapter = OneNoteAdapter(transport=transport)

    detail = adapter.create_page("SEC-1", "Nueva página", "Cuerpo nuevo.")

    assert detail.page_id == "PAGE-NEW"
    assert detail.title == "Nueva página"
    assert detail.body_text == "Cuerpo nuevo."


def test_create_page_transport_error_raises_onenote_unavailable(mocker):
    transport = mocker.Mock()
    transport.invoke.side_effect = PsBridgeTransportError("boom")
    adapter = OneNoteAdapter(transport=transport)

    with pytest.raises(OneNoteUnavailableError):
        adapter.create_page("SEC-1", "Título", "Cuerpo")


# --- update_page() ---


def test_update_page_passes_expected_last_modified_as_utc_z(mocker):
    """Live-QA defect (2026-08-27): the wire format MUST be Z-suffixed
    UTC, never `isoformat()`'s "+00:00" — .NET's RoundtripKind parse
    leaves a "Z" string as an unadjusted UTC value but ADJUSTS an
    offset-suffixed string to local time, which shifted the value passed
    to `UpdatePageContent` on any non-UTC host and made COM reject every
    honest update with HRESULT 0x80042010."""
    transport = mocker.Mock()
    transport.invoke.return_value = ([_page_row()], False)
    adapter = OneNoteAdapter(transport=transport)
    expected = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)

    adapter.update_page("PAGE-1", "Cuerpo actualizado.", expected)

    args, _kwargs = transport.invoke.call_args
    assert args[1] == {
        "op": "UpdatePageContent",
        "pageId": "PAGE-1",
        "bodyText": "Cuerpo actualizado.",
        "expectedLastModified": "2026-08-20T09:00:00Z",
    }
    # Never silently defaulted to [DateTime]::MinValue or any other
    # value that would bypass the concurrency check.
    assert args[1]["expectedLastModified"] != datetime.min.isoformat()


def test_update_page_converts_non_utc_expected_to_utc_z(mocker):
    """A caller-supplied zoned datetime (e.g. Europe/Madrid +02:00) is
    converted to the same instant in UTC, Z-suffixed, on the wire."""
    transport = mocker.Mock()
    transport.invoke.return_value = ([_page_row()], False)
    adapter = OneNoteAdapter(transport=transport)
    expected = datetime(2026, 8, 20, 11, 0, tzinfo=timezone(timedelta(hours=2)))

    adapter.update_page("PAGE-1", "Cuerpo actualizado.", expected)

    args, _kwargs = transport.invoke.call_args
    assert args[1]["expectedLastModified"] == "2026-08-20T09:00:00Z"


def test_update_page_returns_updated_detail(mocker):
    transport = mocker.Mock()
    transport.invoke.return_value = (
        [_page_row(paragraphs=["Cuerpo actualizado."])], False
    )
    adapter = OneNoteAdapter(transport=transport)

    detail = adapter.update_page(
        "PAGE-1", "Cuerpo actualizado.", datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    )

    assert detail.body_text == "Cuerpo actualizado."


def test_update_page_empty_result_raises_not_found(mocker):
    transport = mocker.Mock()
    transport.invoke.return_value = ([], False)
    adapter = OneNoteAdapter(transport=transport)

    with pytest.raises(OneNotePageNotFoundError):
        adapter.update_page(
            "BAD-ID", "Cuerpo", datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
        )


def test_update_page_conflict_error_raises_page_conflict(mocker):
    """design.md's Open Question: the exact HRESULT/message text
    `UpdatePageContent` raises on a stale `dateExpectedLastModified` is
    unconfirmed — `sdd-apply` maps any bridge failure whose message
    suggests a concurrency conflict to `OneNotePageConflictError` on a
    best-effort match."""
    transport = mocker.Mock()
    transport.invoke.side_effect = PsBridgeTransportError(
        "PowerShell onenote bridge produced no usable output "
        "(exit: exit code 1; stderr: script error: page modified since "
        "expectedLastModified)"
    )
    adapter = OneNoteAdapter(transport=transport)

    with pytest.raises(OneNotePageConflictError):
        adapter.update_page(
            "PAGE-1", "Cuerpo", datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
        )


def test_update_page_com_hresult_0x80042010_raises_page_conflict(mocker):
    """Live-QA evidence (2026-08-27) resolved design.md's Open Question:
    a stale `dateExpectedLastModified` makes the COM call itself throw
    `Exception from HRESULT: 0x80042010` (hrLastModifiedDateDidNotMatch).
    That raw COM text carries none of the wordy markers, so the HRESULT
    itself is a conflict marker now."""
    transport = mocker.Mock()
    transport.invoke.side_effect = PsBridgeTransportError(
        "PowerShell onenote bridge produced no usable output "
        "(exit: exit code 1; stderr: script error: Exception calling "
        '"UpdatePageContent" with "2" argument(s): "Exception from '
        'HRESULT: 0x80042010")'
    )
    adapter = OneNoteAdapter(transport=transport)

    with pytest.raises(OneNotePageConflictError):
        adapter.update_page(
            "PAGE-1", "Cuerpo", datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
        )


def test_update_page_transport_not_found_error_raises_page_not_found(mocker):
    transport = mocker.Mock()
    transport.invoke.side_effect = PsBridgeTransportError(
        "PowerShell onenote bridge produced no usable output "
        "(exit: exit code 1; stderr: script error: page not found: PAGE-1)"
    )
    adapter = OneNoteAdapter(transport=transport)

    with pytest.raises(OneNotePageNotFoundError):
        adapter.update_page(
            "PAGE-1", "Cuerpo", datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
        )


def test_update_page_transport_generic_error_raises_onenote_unavailable(mocker):
    transport = mocker.Mock()
    transport.invoke.side_effect = PsBridgeTransportError("PowerShell onenote bridge blocked")
    adapter = OneNoteAdapter(transport=transport)

    with pytest.raises(OneNoteUnavailableError):
        adapter.update_page(
            "PAGE-1", "Cuerpo", datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
        )


# --- typed-error message hygiene (onenote/0002 mailbox round, 2026-08-28) ---
# A conflict or not-found is a NORMAL, actionable outcome — its message must
# carry only the bridge script's own error text, never the transport's
# "produced no usable output" crash wording (which tells the caller the
# bridge died, the one thing that did NOT happen). Generic failures keep the
# full transport diagnostics untouched.


def test_update_page_conflict_message_is_clean_and_hresult_decoded(mocker):
    """A COM 0x80042010 rejection must surface without the transport's
    crash wording and with the HRESULT decoded to its name — a raw HRESULT
    sends the caller to a search engine; the name sends them to the
    cause (live-QA round, onenote/0001 defect 3)."""
    transport = mocker.Mock()
    transport.invoke.side_effect = PsBridgeTransportError(
        "PowerShell onenote bridge produced no usable output "
        "(exit: exit code 1; stderr: script error: Exception calling "
        '"UpdatePageContent" with "2" argument(s): "Exception from '
        'HRESULT: 0x80042010")'
    )
    adapter = OneNoteAdapter(transport=transport)

    with pytest.raises(OneNotePageConflictError) as excinfo:
        adapter.update_page(
            "PAGE-1", "Cuerpo", datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
        )
    text = str(excinfo.value)
    assert "produced no usable output" not in text
    assert "hrLastModifiedDateDidNotMatch" in text
    assert "0x80042010" in text


def test_update_page_precheck_conflict_message_is_clean(mocker):
    """The bridge pre-check's own clean comparison text (expected vs
    actual) must reach the caller as-is, without the transport wrapper."""
    transport = mocker.Mock()
    transport.invoke.side_effect = PsBridgeTransportError(
        "PowerShell onenote bridge produced no usable output "
        "(exit: exit code 1; stderr: script error: conflict: page modified "
        "since/after expectedLastModified (expected 2026-08-27T11:52:14Z, "
        "actual 2026-08-27T12:12:07.0000000Z): PAGE-1)"
    )
    adapter = OneNoteAdapter(transport=transport)

    with pytest.raises(OneNotePageConflictError) as excinfo:
        adapter.update_page(
            "PAGE-1", "Cuerpo", datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
        )
    text = str(excinfo.value)
    assert "produced no usable output" not in text
    assert "expected 2026-08-27T11:52:14Z" in text
    assert "actual 2026-08-27T12:12:07.0000000Z" in text


def test_get_page_not_found_message_is_clean(mocker):
    transport = mocker.Mock()
    transport.invoke.side_effect = PsBridgeTransportError(
        "PowerShell onenote bridge produced no usable output "
        "(exit: exit code 1; stderr: script error: page not found: BAD-ID "
        "(some COM detail))"
    )
    adapter = OneNoteAdapter(transport=transport)

    with pytest.raises(OneNotePageNotFoundError) as excinfo:
        adapter.get_page("BAD-ID")
    text = str(excinfo.value)
    assert "produced no usable output" not in text
    assert "page not found: BAD-ID" in text


def test_unavailable_error_keeps_full_transport_diagnostics(mocker):
    """A genuine bridge failure (no script-error marker match) keeps the
    transport's full message VERBATIM — for a crash, "produced no usable
    output" plus exit/stderr detail is exactly the diagnostic wanted."""
    transport = mocker.Mock()
    transport.invoke.side_effect = PsBridgeTransportError(
        "PowerShell onenote bridge produced no usable output (exit: killed@8s)"
    )
    adapter = OneNoteAdapter(transport=transport)

    with pytest.raises(OneNoteUnavailableError) as excinfo:
        adapter.get_page("PAGE-1")
    assert "produced no usable output (exit: killed@8s)" in str(excinfo.value)


# --- default construction ---


def test_default_construction_wires_a_real_transport():
    from tools.ps_bridge_transport import PsBridgeTransport

    adapter = OneNoteAdapter()

    assert isinstance(adapter._transport, PsBridgeTransport)


# --- bodyTextIncomplete flag (onenote/0024+0027: read-side lossiness flag) ---
# The flattened bodyText cannot represent tables, images or ink (cowork's
# structure list, onenote/0023). The lossy operation is the READ, so the
# flag lives on get_page's response — writes stay allowed, since update
# round-trips the original XML and cannot harm structure (ENH-002).


def _structured_page_row(inner_xml: str) -> dict:
    ns = _DEFAULT_NS
    return {
        "pageId": "PAGE-S",
        "pageXml": (
            f'<?xml version="1.0"?>'
            f'<one:Page xmlns:one="{ns}" ID="PAGE-S">'
            f"<one:Title><one:OE><one:T><![CDATA[T]]></one:T></one:OE></one:Title>"
            f"<one:Outline><one:OEChildren>"
            f"<one:OE><one:T><![CDATA[texto plano]]></one:T></one:OE>"
            f"{inner_xml}"
            f"</one:OEChildren></one:Outline>"
            f"</one:Page>"
        ),
        "notebookName": "z - Test Notebook",
        "sectionName": "Notas",
        "lastModified": "2026-08-28T16:41:47Z",
    }


@pytest.mark.parametrize(
    "inner_xml",
    [
        "<one:OE><one:Table borders=\"true\"><one:Row><one:Cell><one:OEChildren>"
        "<one:OE><one:T><![CDATA[celda]]></one:T></one:OE>"
        "</one:OEChildren></one:Cell></one:Row></one:Table></one:OE>",
        "<one:OE><one:Image format=\"png\"><one:Data>QUJD</one:Data></one:Image></one:OE>",
        "<one:OE><one:InkDrawing><one:Data>QUJD</one:Data></one:InkDrawing></one:OE>",
        "<one:OE><one:InkWord><one:Data>QUJD</one:Data></one:InkWord></one:OE>",
    ],
    ids=["table", "image", "ink-drawing", "ink-word"],
)
def test_get_page_flags_body_text_incomplete_for_structure(mocker, inner_xml):
    transport = mocker.Mock()
    transport.invoke.return_value = ([_structured_page_row(inner_xml)], False)
    adapter = OneNoteAdapter(transport=transport)

    detail = adapter.get_page("PAGE-S")

    assert detail.body_text_incomplete is True


def test_get_page_plain_text_page_is_not_flagged(mocker):
    """Nested outlines and bullets degrade gracefully in the flattened
    read (onenote/0023's line) — only table/image/ink set the flag."""
    transport = mocker.Mock()
    transport.invoke.return_value = ([_page_row()], False)
    adapter = OneNoteAdapter(transport=transport)

    detail = adapter.get_page("PAGE-1")

    assert detail.body_text_incomplete is False
