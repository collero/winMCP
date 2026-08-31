"""FakeOneNoteAdapter — in-memory `OneNotePort` implementation used by
tests (add-onenote-adapter change).

Seeded via the constructor with a flat list of `PageDetail` (full text
detail, keyed internally by `page_id`) and a `NotebookNode` tree.
Implements the same `OneNotePort` Protocol as the real
`PsBridgeTransport`-backed adapter (`tools/onenote_adapter.py`), so tool
code under test never knows the difference — mirrors
`tools/fake_file_search_adapter.py::FakeFileSearchAdapter`/
`tools/fake_adapter.py::FakeCalendarAdapter`.

`search()` matches `query` (case-insensitive substring) against a seeded
page's `title` OR `body_text` — the closest stand-in this fake has for
OneNote's own `FindPages` full-text search — capped at `top_n`.

`update_page()` enforces the same optimistic-concurrency rule the real
`UpdatePageContent` call does (onenote-write-page spec's "Conflicting
Update Raises, Never Silently Overwrites" requirement): a seeded page with
no `last_modified` accepts any `expected_last_modified` (nothing to
conflict against yet); otherwise a stale `expected_last_modified` raises
`OneNotePageConflictError` and leaves the seeded page untouched.
"""
from datetime import datetime

from models.schemas import PageDetail, PageSummary
from tools.errors import (
    OneNotePageConflictError,
    OneNotePageNotFoundError,
    OneNoteSectionNotFoundError,
    OneNoteUnavailableError,
)
from tools.onenote_adapter import NotebookNode


def _to_summary(page: PageDetail) -> PageSummary:
    return PageSummary(
        page_id=page.page_id,
        title=page.title,
        notebook_name=page.notebook_name,
        section_name=page.section_name,
        notebook_id=page.notebook_id,
        section_id=page.section_id,
        last_modified=page.last_modified,
    )


class FakeOneNoteAdapter:
    """In-memory stand-in for `OneNoteAdapter`, satisfying `OneNotePort`."""

    def __init__(
        self,
        pages: list[PageDetail] | None = None,
        hierarchy: list[NotebookNode] | None = None,
        *,
        unavailable: bool = False,
    ):
        self._pages: dict[str, PageDetail] = {page.page_id: page for page in (pages or [])}
        self._hierarchy: list[NotebookNode] = list(hierarchy) if hierarchy else []
        self._unavailable = unavailable
        self._next_page_id = 1

    def _check_available(self) -> None:
        if self._unavailable:
            raise OneNoteUnavailableError(
                "OneNote is not available (fake adapter configured to fail)"
            )

    def search(self, query: str, top_n: int) -> list[PageSummary]:
        self._check_available()

        needle = query.lower()
        matches: list[PageSummary] = []
        for page in self._pages.values():
            if needle in page.title.lower() or needle in page.body_text.lower():
                matches.append(_to_summary(page))
            if len(matches) >= top_n:
                break
        return matches

    def get_hierarchy(self) -> list[NotebookNode]:
        self._check_available()
        return self._hierarchy

    def get_page(self, page_id: str) -> PageDetail:
        self._check_available()

        page = self._pages.get(page_id)
        if page is None:
            raise OneNotePageNotFoundError(f"No page with pageId {page_id!r}")
        return page

    def _resolve_section(self, section_id: str) -> tuple[str, str]:
        """Return `(notebook_name, section_name)` for `section_id`, or
        raise `OneNoteSectionNotFoundError` if it does not resolve
        against the seeded hierarchy."""
        for notebook in self._hierarchy:
            for section in notebook.sections:
                if section.section_id == section_id:
                    return notebook.name, section.name
        raise OneNoteSectionNotFoundError(f"No section with sectionId {section_id!r}")

    def create_page(self, section_id: str, title: str, body_text: str) -> PageDetail:
        self._check_available()

        notebook_name, section_name = self._resolve_section(section_id)
        page_id = f"FAKE-PAGE-{self._next_page_id}"
        self._next_page_id += 1
        page = PageDetail(
            page_id=page_id,
            title=title,
            body_text=body_text,
            notebook_name=notebook_name,
            section_name=section_name,
            last_modified=None,
        )
        self._pages[page_id] = page
        return page

    def update_page(
        self, page_id: str, body_text: str, expected_last_modified: datetime | None
    ) -> PageDetail:
        self._check_available()

        page = self._pages.get(page_id)
        if page is None:
            raise OneNotePageNotFoundError(f"No page with pageId {page_id!r}")
        # EQUALITY, not ordering — live-confirmed (onenote/0002 probe B +
        # cowork's probes F..Q): `UpdatePageContent` accepts exactly the
        # page's stored last-modified value; older AND newer both fail
        # with 0x80042010. `None` is the documented unguarded-overwrite
        # escape hatch (onenote/0005) — no check at all.
        if (
            expected_last_modified is not None
            and page.last_modified is not None
            and expected_last_modified != page.last_modified
        ):
            # Compact wording mirrors the real bridge's (onenote/0021): the
            # transport's 200-char stderr excerpt must hold the whole
            # message, so values first, direction + remediation last, and
            # NO pageId — the caller passed it in. Both branches say
            # re-read: a successful write can move the stored value
            # BACKWARDS (onenote/0017), so re-reading fixes NEWER too.
            direction = (
                "page modified after your value; re-read and retry"
                if expected_last_modified < page.last_modified
                else "value is NEWER; re-read and retry (a write can move it backwards)"
            )
            raise OneNotePageConflictError(
                f"conflict: expected {expected_last_modified.isoformat()}, "
                f"actual {page.last_modified.isoformat()} - {direction}"
            )
        updated = page.model_copy(
            update={
                "body_text": body_text,
                "last_modified": (
                    expected_last_modified
                    if expected_last_modified is not None
                    else page.last_modified
                ),
            }
        )
        self._pages[page_id] = updated
        return updated
