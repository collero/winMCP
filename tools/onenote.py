"""Tool-layer functions for the four OneNote MCP tools (`onenote_search`,
`onenote_get_page`, `onenote_create_page`, `onenote_update_page`) —
add-onenote-adapter change.

Mirrors `tools/mail.py`/`tools/file_search.py`'s structure: validate/
normalize the Pydantic request, apply policy live-read from
`config/settings.yaml` (via `tools/settings.py` — never cached), delegate
to a `OneNotePort` adapter (the real `OneNoteAdapter` or, in tests,
`FakeOneNoteAdapter`), and let typed errors (`tools/errors.py`) propagate
to the caller uncaught. Mapping those onto FastMCP's tool-error wrapper is
`server.py`'s job (a later batch) — this module only raises/propagates the
stable `CalendarToolError` taxonomy (plus a plain `ValueError` for the
input-validation failures that never reach the adapter at all).

Allowlist enforcement point (design.md's "Allowlist enforcement point"
decision, the onenote-write-page spec's "Writable Notebook Allowlist"
requirement): every `onenote_create_page`/`onenote_update_page` call is
checked, in Python, against `tools/settings.py::onenote_writable_notebooks()`
BEFORE the corresponding adapter WRITE method (`create_page`/`update_page`)
is ever invoked — never inside the adapter/bridge, which stays allowlist-
unaware (same "decide in exactly one place" precedent as `file_search`'s
roots check). Resolving the target's notebook name still requires a READ
call to the adapter first (`get_hierarchy()` for `onenote_create_page`'s
`sectionId`, `get_page()` for `onenote_update_page`'s `pageId`, since
`PageDetail` already carries `notebook_name`) — the spec's "before any
adapter/COM call" wording, and its scenario's "the adapter's create_page()/
update_page() is never called" assertion, are both about the WRITE call
specifically, not these read-only resolution lookups (design.md's own
Sequence Diagram calls a `get_hierarchy` read before the write for exactly
this reason).
"""
from models.schemas import (
    CreatePageRequest,
    GetPageRequest,
    OneNoteSearchRequest,
    PageDetail,
    PageSummary,
    SectionInfo,
    UpdatePageRequest,
)
from tools.errors import OneNoteSectionNotFoundError, OneNoteWriteNotAllowedError
from tools.onenote_adapter import OneNotePort
from tools.settings import (
    onenote_search_max_results,
    onenote_writable_notebooks,
    settings_file_path,
)


def onenote_search(request: OneNoteSearchRequest, adapter: OneNotePort) -> list[PageSummary]:
    """Full-text search over OneNote page content (`OneNote.Application`'s
    `FindPages`). `query` must be non-empty — rejected with a plain
    `ValueError` before any adapter call (the onenote-search spec's
    "Empty query is rejected before any adapter call" scenario).

    `limit` is resolved via `onenote_search_max_results()` (default `50`,
    hard max `200`, `ValueError` when `<= 0`) before the adapter call —
    the onenote-search spec's "Result Limit Parameter" requirement. An
    empty result is not an error (the "Empty Result Is Not an Error"
    requirement) — `[]` round-trips straight through."""
    if not request.query:
        raise ValueError("onenote_search requires a non-empty query")
    limit = onenote_search_max_results(request.limit)
    return adapter.search(request.query, limit)


def onenote_get_page(request: GetPageRequest, adapter: OneNotePort) -> PageDetail:
    """Fetch full, read-only text detail for a single page by `pageId`.
    Never mutates any notebook/section/page state (the onenote-get-page
    spec's "No Mutation on Fetch" requirement) — this function makes
    exactly one read-only adapter call and nothing else."""
    return adapter.get_page(request.page_id)


def _check_writable(notebook_name: str) -> None:
    """Raise `OneNoteWriteNotAllowedError` if `notebook_name` is not in
    `onenote_writable_notebooks()` — the onenote-write-page spec's
    "Writable Notebook Allowlist" requirement. Called BEFORE the adapter's
    `create_page()`/`update_page()` write method is ever invoked."""
    allowed = onenote_writable_notebooks()
    if notebook_name not in allowed:
        # The message is the agent-facing surface: the calling LLM sees
        # only this text, so it must carry the exact remediation — which
        # key, which file, and that the allowlist is re-read live on
        # every call (load_settings() is never cached), so no server
        # restart is required after editing.
        raise OneNoteWriteNotAllowedError(
            f"notebook {notebook_name!r} is not in the writable-notebook allowlist "
            f"{allowed!r}. To allow writes to it, add {notebook_name!r} to the "
            f"'onenote_writable_notebooks' list in {settings_file_path()} "
            f"(the allowlist is re-read on every call — no restart needed). "
            f"This gate exists so writes to live notebooks are an explicit, "
            f"per-notebook human decision.",
            notebook_name=notebook_name,
            allowed_notebooks=allowed,
        )


def _resolve_notebook_for_section(adapter: OneNotePort, section_id: str) -> str:
    """Resolve `section_id`'s owning notebook name by walking the
    adapter's `get_hierarchy()` tree (design.md's "Allowlist enforcement
    point" decision: Python resolves `section_id` via a `get_hierarchy`
    call BEFORE checking the allowlist/calling `create_page`). Raises
    `OneNoteSectionNotFoundError` if `section_id` does not resolve against
    the hierarchy — mirroring `FakeOneNoteAdapter._resolve_section()`'s
    own duplicate check, but this is the check that actually runs first in
    the write path (Batch 2's apply-progress deviation note #6)."""
    notebooks = adapter.get_hierarchy()
    section_count = 0
    for notebook in notebooks:
        for section in notebook.sections:
            section_count += 1
            if section.section_id == section_id:
                return notebook.name
    # Diagnostic by design (onenote/0003 defect 2): say what was searched
    # and what a real id looks like — the old bare "no section" message
    # cost a full debugging round because the caller could not tell a
    # wrong-id-form from a broken resolver.
    raise OneNoteSectionNotFoundError(
        f"No section with sectionId {section_id!r} among {section_count} "
        f"section(s) in {len(notebooks)} notebook(s). Section ids look like "
        f"'{{GUID}}{{1}}{{B0}}' — a bare GUID or a section NAME will never "
        f"match. Call onenote_list_sections to get the real ids."
    )


def onenote_list_sections(adapter: OneNotePort) -> list[SectionInfo]:
    """List every notebook/section pair with its canonical OneNote ids
    (onenote/0003 mailbox round, defect 2): `onenote_create_page` needs a
    real section id (`{GUID}{1}{B0}` form) and no other tool returned
    one, so callers had nothing to go on but guesswork. Read-only —
    exactly one `get_hierarchy()` adapter call."""
    return [
        SectionInfo(
            notebook_id=notebook.notebook_id,
            notebook_name=notebook.name,
            section_id=section.section_id,
            section_name=section.name,
        )
        for notebook in adapter.get_hierarchy()
        for section in notebook.sections
    ]


def onenote_create_page(request: CreatePageRequest, adapter: OneNotePort) -> PageDetail:
    """Create a new page in the section identified by `sectionId`. The
    section's owning notebook is resolved via `get_hierarchy()` and
    checked against the writable-notebook allowlist BEFORE
    `adapter.create_page()` is ever called (the onenote-write-page spec's
    "Writable Notebook Allowlist" requirement)."""
    notebook_name = _resolve_notebook_for_section(adapter, request.section_id)
    _check_writable(notebook_name)
    return adapter.create_page(request.section_id, request.title, request.body_text)


def onenote_update_page(request: UpdatePageRequest, adapter: OneNotePort) -> PageDetail:
    """Update the page identified by `pageId`, guarded by optimistic
    concurrency: a supplied `expectedLastModified` is passed through to
    the adapter unchanged — never replaced by a value that would bypass
    the concurrency check (the onenote-write-page spec's "Update Page
    Requires Optimistic Concurrency" requirement). An OMITTED value
    (`None`) is the caller's own documented choice of an unguarded
    overwrite (onenote/0005) and is likewise passed through unchanged.

    The page's owning notebook (`PageDetail.notebook_name`, from a
    read-only `adapter.get_page()` call) is checked against the writable-
    notebook allowlist BEFORE `adapter.update_page()` — the write call —
    is ever invoked (the "Writable Notebook Allowlist" requirement). This
    same `get_page()` call also naturally surfaces
    `OneNotePageNotFoundError` for an unresolved `pageId` before any write
    is attempted."""
    current = adapter.get_page(request.page_id)
    _check_writable(current.notebook_name)
    return adapter.update_page(
        request.page_id, request.body_text, request.expected_last_modified
    )
