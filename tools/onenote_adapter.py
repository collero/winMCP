"""OneNotePort — the seam between tool logic and OneNote COM access
(add-onenote-adapter change).

Defines the `OneNotePort` Protocol satisfied by both the real,
`PsBridgeTransport`-backed `OneNoteAdapter` (Phase 4, below) and the
test-only `FakeOneNoteAdapter` (`tools/fake_onenote_adapter.py`). Mirrors
`FileSearchPort` (`tools/file_search_adapter.py`) / `CalendarPort`
(`tools/outlook_adapter.py`) — see design.md's "Mirror the mail seam
exactly" approach and the onenote-com-adapter spec's "Adapter Interface"
requirement.

Windows Search's `SystemIndex` has zero `onenote:` items (spike-verified —
see `openspec/changes/add-onenote-adapter/design.md`'s Purpose section), so
`OneNoteAdapter` is the only route to OneNote content, not a fallback
transport the way `PowerShellSearchBridge` is for file search.

The adapter is config-unaware: writable-notebook allowlist enforcement
happens at the tool layer (`tools/onenote.py`, a later batch), not here —
see the onenote-write-page spec's "Writable Notebook Allowlist"
requirement and design.md's "Allowlist enforcement point" decision.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from xml.etree import ElementTree

from models.schemas import PageDetail, PageSummary
from tools.errors import (
    OneNotePageConflictError,
    OneNotePageNotFoundError,
    OneNoteUnavailableError,
)
from tools.ps_bridge_transport import PsBridgeTransport, PsBridgeTransportError
from tools.settings import onenote_ps_bridge_timeout_seconds


@dataclass(frozen=True)
class SectionNode:
    """One section inside a `NotebookNode`, as returned by
    `OneNotePort.get_hierarchy()`. Internal-only — never an MCP tool
    response shape (onenote-com-adapter spec's "Adapter Interface"
    requirement notes `get_hierarchy()` is "internal, not an MCP tool")
    — so this is a plain dataclass, not an aliased pydantic model."""

    section_id: str
    name: str


@dataclass(frozen=True)
class NotebookNode:
    """One notebook and its sections, as returned by
    `OneNotePort.get_hierarchy()` — used by the tool layer (a later
    batch) to resolve a `sectionId` and check its notebook against
    `onenote_writable_notebooks` before any write (design.md's
    "Allowlist enforcement point" decision)."""

    notebook_id: str
    name: str
    sections: list[SectionNode]


class OneNotePort(Protocol):
    """Interface both the real (`OneNoteAdapter`) and fake
    (`FakeOneNoteAdapter`) adapters satisfy."""

    def search(self, query: str, top_n: int) -> list[PageSummary]:
        """Return page summaries whose title/content matches `query`
        (OneNote's own `FindPages` full-text search), capped at `top_n`
        rows.

        Raises OneNoteUnavailableError if OneNote/the bridge cannot be
        reached at all. An empty result is not an error.
        """
        ...

    def get_hierarchy(self) -> list[NotebookNode]:
        """Return the full notebook/section tree. Internal — never an MCP
        tool response shape; used by the tool layer to resolve
        `sectionId`s and enforce the writable-notebook allowlist.

        Raises OneNoteUnavailableError if OneNote/the bridge cannot be
        reached at all.
        """
        ...

    def get_page(self, page_id: str) -> PageDetail:
        """Return full text detail for the page identified by `page_id`.

        Raises OneNotePageNotFoundError if `page_id` does not resolve to
        a page, OneNoteUnavailableError if OneNote/the bridge cannot be
        reached at all.
        """
        ...

    def create_page(self, section_id: str, title: str, body_text: str) -> PageDetail:
        """Create a new page in the section identified by `section_id`
        with the given `title`/`body_text`, returning the created page's
        full detail (including its new `page_id`).

        Raises OneNoteUnavailableError if OneNote/the bridge cannot be
        reached at all.
        """
        ...

    def update_page(
        self, page_id: str, body_text: str, expected_last_modified: datetime | None
    ) -> PageDetail:
        """Append `body_text` as a new paragraph to the page identified
        by `page_id`, guarded by optimistic concurrency when
        `expected_last_modified` is given: it MUST equal the page's real
        last-modified time or the write is refused — design.md's
        "Optimistic concurrency" decision. `None` is the documented
        escape hatch (onenote/0005): an UNGUARDED overwrite with no
        concurrency check at all.

        Raises OneNotePageConflictError if `expected_last_modified` does
        not match, OneNotePageNotFoundError if `page_id` does not resolve
        to a page, OneNoteUnavailableError if OneNote/the bridge cannot
        be reached at all.
        """
        ...


# --- Real adapter (Phase 4) ---

# Absolute path to the deployed script, resolved next to this module —
# never a relative path, so `PsBridgeTransport.invoke()`'s `-File` value
# is always absolute regardless of the process's current working
# directory. Mirrors `tools/file_search_adapter.py::_PS_BRIDGE_SCRIPT`.
_PS_BRIDGE_ONENOTE_SCRIPT = Path(__file__).resolve().parent / "ps_bridge_onenote.ps1"

# Substring markers (case-insensitive) this adapter looks for in a
# `PsBridgeTransportError`'s message text to distinguish "the target
# page/section does not exist" from a generic bridge/COM failure —
# `ps_bridge_onenote.ps1` folds its own `{"error": "page not found: ..."}`
# line into that message via `PsBridgeTransport`'s stderr-excerpt
# diagnostic suffix (see `_pump_stderr`'s "script error: ..." handling in
# `tools/ps_bridge_transport.py`).
_NOT_FOUND_MARKERS = ("not found",)

# Substring markers for an `UpdatePageContent` optimistic-concurrency
# conflict. design.md's Open Question is now resolved by live-QA evidence
# (2026-08-27): a stale `dateExpectedLastModified` makes the COM call
# throw `Exception from HRESULT: 0x80042010`
# (hrLastModifiedDateDidNotMatch), whose raw text carries none of the
# wordy markers — the HRESULT itself is the authoritative marker. The
# broader wordings stay for the bridge's own pre-check throw ("page
# modified since expectedLastModified: ...").
_CONFLICT_MARKERS = (
    "conflict",
    "modified since",
    "expectedlastmodified",
    "0x80042010",
)


def _to_utc_z(value: datetime) -> str:
    """Render `value` as a Z-suffixed UTC ISO-8601 string for the bridge
    wire format. An aware datetime is converted to the same instant in
    UTC; a naive one is taken as already-UTC (the bridge's own
    `lastModified` outputs are UTC, so a round-tripped value stays
    correct either way). Never emit an offset form ("+00:00") — see the
    `expectedLastModified` comment in `update_page()`."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat() + "Z"


def _is_marked(exc: PsBridgeTransportError, markers: tuple[str, ...]) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in markers)


# The transport folds the bridge script's own `{"error": "..."}` line into
# its message as "... (exit: ...; stderr: script error: <text>)". For a
# conflict/not-found — a NORMAL, actionable outcome — the caller must see
# only <text>: the transport's "produced no usable output" crash wording
# around it says the bridge died, the one thing that did NOT happen
# (onenote/0001 defect 3).
_SCRIPT_ERROR_PREFIX = "script error: "

# 0x80042010 is hrLastModifiedDateDidNotMatch — OneNote's own equality
# check on `UpdatePageContent`'s dateExpectedLastModified. A raw HRESULT
# sends the caller to a search engine; the decoded name sends them to the
# cause (onenote/0001 defect 3).
_HRESULT_CONFLICT = "0x80042010"
_HRESULT_CONFLICT_DECODED = (
    " [hrLastModifiedDateDidNotMatch (0x80042010): the page's stored "
    "lastModifiedTime did not equal dateExpectedLastModified — re-read the "
    "page with onenote_get_page and retry with the fresh value]"
)


def _bridge_error_text(exc: PsBridgeTransportError) -> str:
    """Extract the bridge script's own error text from a transport
    message, decoding the conflict HRESULT when present. Falls back to
    the full transport message when no script-error marker is found (a
    genuine crash keeps its full diagnostics)."""
    text = str(exc)
    idx = text.find(_SCRIPT_ERROR_PREFIX)
    if idx != -1:
        text = text[idx + len(_SCRIPT_ERROR_PREFIX):]
        # Drop the transport suffix's own closing paren, present unless
        # the 200-char stderr excerpt cap already ate it.
        if text.endswith(")"):
            text = text[:-1]
    if _HRESULT_CONFLICT in text.lower() and "hrlastmodifieddatedidnotmatch" not in text.lower():
        text += _HRESULT_CONFLICT_DECODED
    return text


def _extract_title_and_body(page_xml: str) -> tuple[str, str]:
    """Parse a OneNote page's full XML (as returned by `GetPageContent`)
    and extract its title and body text.

    Per the onenote-com-adapter spec's "Dynamic XML Namespace Detection"
    requirement, the `one` namespace URI is read from the document's own
    root element — never hardcoded to a fixed version string like
    `.../2013/onenote` — since it is OneNote-version dependent. Per the
    "Page Content Extraction" requirement, the title comes from the
    nested `Title/OE/T` CDATA text and the body is the concatenation of
    each top-level `Outline/OEChildren/OE` paragraph's `T` CDATA text,
    joined by `"\\n"`. `ElementTree` treats CDATA content the same as
    regular element text, so no special unwrapping is needed.

    This is the ONE place OneNote page XML is parsed (see the module
    docstring's deviation note) — done here in Python, unit-tested
    directly, rather than inside `ps_bridge_onenote.ps1` where it would
    be unreachable by any test on this WSL2 dev host.
    """
    root = ElementTree.fromstring(page_xml)
    ns_uri = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
    ns = {"one": ns_uri}

    title_el = root.find(".//one:Title//one:T", ns)
    title = (title_el.text or "") if title_el is not None else ""

    paragraphs: list[str] = []
    for oe in root.findall("one:Outline/one:OEChildren/one:OE", ns):
        text_el = oe.find("one:T", ns)
        if text_el is not None and text_el.text:
            paragraphs.append(text_el.text)
    body_text = "\n".join(paragraphs)

    return title, body_text


def _row_to_page_summary(row: dict[str, Any]) -> PageSummary:
    """Map one `FindPages` JSON row (flat `title`/`notebookName`/
    `sectionName` attributes read straight off the hierarchy XML by
    `ps_bridge_onenote.ps1` — no CDATA extraction needed, unlike a full
    page's content) into a `PageSummary`."""
    return PageSummary(
        page_id=row["pageId"],
        title=row["title"],
        notebook_name=row["notebookName"],
        section_name=row["sectionName"],
        notebook_id=row.get("notebookId"),
        section_id=row.get("sectionId"),
        last_modified=row.get("lastModified"),
    )


# Element local-names whose presence anywhere in a page's XML means the
# flattened `bodyText` read is LOSSY (onenote/0023's structure list,
# applied read-side per onenote/0024+0027): these three cannot survive
# any text rendering, while nested outlines/bullets degrade gracefully
# and stay unflagged.
_UNREPRESENTABLE_LOCAL_NAMES = frozenset({"Table", "Image", "InkDrawing", "InkWord"})


def _has_unrepresentable_structure(page_xml: str) -> bool:
    """True when the page XML contains tables, images or ink — structure
    the plain-text `bodyText` cannot represent. Namespace-independent:
    compares element LOCAL names, same discipline as
    `_extract_title_and_body`'s dynamic namespace detection. A page that
    fails to parse is reported un-flagged rather than erroring — the
    caller already got the parse failure from `_extract_title_and_body`
    if it mattered."""
    try:
        root = ElementTree.fromstring(page_xml)
    except ElementTree.ParseError:
        return False
    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1]
        if local_name in _UNREPRESENTABLE_LOCAL_NAMES:
            return True
    return False


def _row_to_page_detail(row: dict[str, Any]) -> PageDetail:
    """Map one `GetPageContent`/`CreateNewPage`/`UpdatePageContent` JSON
    row into a `PageDetail`, extracting title/body from the row's raw
    `pageXml` via `_extract_title_and_body`. All three ops return this
    same row shape (`pageId`/`pageXml`/`notebookName`/`sectionName`/
    `lastModified`) so this one mapping function serves all of them."""
    title, body_text = _extract_title_and_body(row["pageXml"])
    return PageDetail(
        page_id=row["pageId"],
        title=title,
        body_text=body_text,
        notebook_name=row["notebookName"],
        section_name=row["sectionName"],
        notebook_id=row.get("notebookId"),
        section_id=row.get("sectionId"),
        last_modified=row.get("lastModified"),
        body_text_incomplete=_has_unrepresentable_structure(row["pageXml"]),
    )


class OneNoteAdapter:
    """Real, `PsBridgeTransport`-backed `OneNotePort` implementation.
    Invokes a pinned, absolute Windows PowerShell 5.1 executable against
    the deployed `tools/ps_bridge_onenote.ps1` script via the shared
    transport (design.md's Decision 1 — built on `PsBridgeTransport` from
    day one, unlike `PowerShellSearchBridge`, which was refactored onto
    it), passing a single `{"op": ..., ...}` JSON object over the child's
    stdin per call (design.md's Decision 5 — one script, `switch`-
    dispatched on `op`).

    Every op's actual COM call happens inside `ps_bridge_onenote.ps1`,
    faithful to `/mnt/c/usr/WinMCP/_spike_onenote.ps1`/
    `_spike_onenote_write.ps1`'s already-validated calls
    (`GetHierarchy`/`FindPages`/`GetPageContent`/`CreateNewPage`/
    `UpdatePageContent`) — not unit-tested directly (no real
    `OneNote.Application`/`powershell.exe` on WSL2), covered instead by
    this module's own request-shape/row-mapping assertions plus the
    change's manual verification phase (tasks.md Phase 11).
    """

    def __init__(self, transport: "PsBridgeTransport | None" = None) -> None:
        # Shared use-case-agnostic engine (design.md Decision 1) —
        # injectable for tests that want to double the transport
        # directly; defaults to a real one, mirroring
        # `PowerShellSearchBridge`'s own injection pattern.
        self._transport: PsBridgeTransport = transport if transport is not None else PsBridgeTransport()

    def _invoke(self, op: str, fields: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
        """Build the `{"op": op, **fields}` request (design.md's Decision
        5 — the dumb-executor contract) and delegate the actual
        spawn/deadline/JSON-Lines-parse sequence to the shared
        transport."""
        request = {"op": op, **fields}
        return self._transport.invoke(
            _PS_BRIDGE_ONENOTE_SCRIPT,
            request,
            timeout=onenote_ps_bridge_timeout_seconds(),
            log_label="onenote",
        )

    def search(self, query: str, top_n: int) -> list[PageSummary]:
        try:
            rows, _truncated = self._invoke("FindPages", {"query": query})
        except PsBridgeTransportError as exc:
            raise OneNoteUnavailableError(str(exc)) from exc
        return [_row_to_page_summary(row) for row in rows[:top_n]]

    def get_hierarchy(self) -> list[NotebookNode]:
        try:
            rows, _truncated = self._invoke("GetHierarchy", {})
        except PsBridgeTransportError as exc:
            raise OneNoteUnavailableError(str(exc)) from exc

        notebooks: dict[str, NotebookNode] = {}
        for row in rows:
            notebook_id = row["notebookId"]
            section = SectionNode(section_id=row["sectionId"], name=row["sectionName"])
            if notebook_id not in notebooks:
                notebooks[notebook_id] = NotebookNode(
                    notebook_id=notebook_id, name=row["notebookName"], sections=[]
                )
            notebooks[notebook_id].sections.append(section)
        return list(notebooks.values())

    def get_page(self, page_id: str) -> PageDetail:
        try:
            rows, _truncated = self._invoke("GetPageContent", {"pageId": page_id})
        except PsBridgeTransportError as exc:
            if _is_marked(exc, _NOT_FOUND_MARKERS):
                raise OneNotePageNotFoundError(_bridge_error_text(exc)) from exc
            raise OneNoteUnavailableError(str(exc)) from exc
        if not rows:
            raise OneNotePageNotFoundError(f"No page with pageId {page_id!r}")
        return _row_to_page_detail(rows[0])

    def create_page(self, section_id: str, title: str, body_text: str) -> PageDetail:
        try:
            rows, _truncated = self._invoke(
                "CreateNewPage",
                {"sectionId": section_id, "title": title, "bodyText": body_text},
            )
        except PsBridgeTransportError as exc:
            raise OneNoteUnavailableError(str(exc)) from exc
        if not rows:
            raise OneNoteUnavailableError("OneNote bridge returned no page after create")
        return _row_to_page_detail(rows[0])

    def update_page(
        self, page_id: str, body_text: str, expected_last_modified: datetime | None
    ) -> PageDetail:
        request_fields: dict[str, Any] = {"pageId": page_id, "bodyText": body_text}
        if expected_last_modified is not None:
            # The caller's value — never defaulted to
            # `[DateTime]::MinValue` or any other value that would bypass
            # `UpdatePageContent`'s optimistic-concurrency check when the
            # caller ASKED for one (onenote-write-page spec's "Update
            # Page Requires Optimistic Concurrency" requirement) —
            # normalized to Z-suffixed UTC on the wire: .NET's
            # RoundtripKind parse leaves "Z" as an unadjusted UTC value
            # but ADJUSTS an offset form ("+00:00", isoformat()'s output)
            # to local time, which shifted the value handed to COM on any
            # non-UTC host and made it reject every honest update with
            # HRESULT 0x80042010 (live-QA defect, 2026-08-27). An OMITTED
            # field is the documented unguarded-overwrite escape hatch
            # (onenote/0005): the bridge then calls the one-argument
            # `UpdatePageContent`, skipping OneNote's check entirely.
            request_fields["expectedLastModified"] = _to_utc_z(expected_last_modified)
        try:
            rows, _truncated = self._invoke("UpdatePageContent", request_fields)
        except PsBridgeTransportError as exc:
            if _is_marked(exc, _CONFLICT_MARKERS):
                raise OneNotePageConflictError(_bridge_error_text(exc)) from exc
            if _is_marked(exc, _NOT_FOUND_MARKERS):
                raise OneNotePageNotFoundError(_bridge_error_text(exc)) from exc
            raise OneNoteUnavailableError(str(exc)) from exc
        if not rows:
            raise OneNotePageNotFoundError(f"No page with pageId {page_id!r}")
        return _row_to_page_detail(rows[0])
