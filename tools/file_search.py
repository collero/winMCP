"""Tool-layer functions for the file-search MCP tools (`file_search`,
`file_get_info`) — file-search / file-search-resilience changes.

Mirrors `tools/mail.py`'s structure: validate/normalize the Pydantic
request, apply roots policy (live-read via `load_settings()` every call —
never cached), delegate to a `FileSearchPort` adapter (the real
`FallbackSearchAdapter` — ADO then the PowerShell bridge — or, in tests,
`FakeFileSearchAdapter`), and let typed errors (`tools/errors.py`)
propagate to the caller uncaught. Mapping those onto FastMCP's tool-error
wrapper is `server.py`'s job — this module only raises/propagates the
stable `CalendarToolError` taxonomy (plus a plain `ValueError` for the
mandatory-filter input-validation failure that never reaches the adapter
at all).

Roots-enforcement layering (design.md decision #3): this module owns ALL
roots policy, never the adapter —
  (a) pre-call: normalize + reject a request whose `scope`/`path` is not
      contained within a configured or default root, BEFORE any adapter
      call or walk — raises `SearchRootNotAllowedError`;
  (b) post-call defense-in-depth: drop any row the adapter/walk returns
      that normalizes outside the allowed roots, since the adapter's own
      `SCOPE=`/`CONTAINS()` SQL is a best-effort filter, not a security
      boundary by itself (Batch 2's apply-progress handoff note).
The post-call check is always against the configured/default
`allowed_roots` — never against the narrower per-call `scope` — mirroring
task 4.4's "post-call drop any row outside allowed roots" wording.

Path normalization (design.md decision #4): `_normalize_path` compares via
`casefold()` + separator-normalized form (NTFS paths are case-insensitive
and mix `/`/`\\` in practice), boundary-aware so a sibling directory
sharing a name prefix (`ana2` vs `ana`) is never mistaken for a contained
subpath. It also decodes a `file:///`-style URL first, since
`file_get_info`'s `path` MAY arrive in that form (the file-get-info spec's
"Get Info Input Parameters" requirement) while `file_search`'s `scope`
never does — decoding is a no-op for a plain native path. This mirrors
(but is not shared with) `tools/settings.py`'s
`_casefold_normalized`/`_is_nested_under` and
`tools/fake_file_search_adapter.py`'s `_casefold_normalized`/
`_is_contained` — Batch 1/2's precedent of small, module-scoped
normalization helpers over premature sharing. `_normalize_path`'s
casefolded form is ALSO reused (Phase 5) as the key for the combined
filename+phrase intersection (design.md's "Combined Query Algorithm").

`file_get_info` does NOT pre-normalize `path` before the adapter's
enrichment call itself (only for the containment check) —
`FileSearchPort.get_info()` matches the raw string as-is against either
indexed column, per `tools/file_search_adapter.py`'s own docstring /
Batch 2's handoff note. Its universal, always-populated facts
(`path`/`name`/`size`/`lastModified`/`createdTime`/`extension`) are now
sourced from `os.stat()` on the resolved native path instead (Phase 5,
file-search-resilience change) — the index is enrichment-only
(`kind`/`snippet`), per the file-get-info spec's MODIFIED "Get Info Output
Shape" / ADDED "Path Not Found On Disk" / "Index Enrichment Failure Never
Surfaces" requirements.

Dispatch split (Phase 5, file-search-resilience change, design.md's
"Technical Approach"): a `filename`-only query is answered ENTIRELY by
`tools/file_search_walk.py::walk_filename()` — the adapter is never
called, so the query is index-health-independent and works under
unindexed allowed roots (`C:\\usr`, `C:\\co`). A `phrase`-only query goes
through the adapter (`FallbackSearchAdapter`: ADO, then the PowerShell
bridge) unchanged. A combined `filename`+`phrase` query runs the walk
first (cheap, local) for candidate paths, short-circuits with no adapter
call at all when the walk finds zero candidates, otherwise runs the
`phrase` query against the adapter and returns only the intersection
(by `_normalize_path()`-normalized path) — see the file-search spec's
ADDED "Combined Filename and Phrase Query Rule" requirement. Whenever the
adapter's `search()` raises `WindowsSearchUnavailableError` (both the ADO
and PowerShell-bridge transports exhausted — `FallbackSearchAdapter`
itself stays message-neutral per its own docstring), THIS module is the
one place that adds the "filename search still works" text before
re-raising, per the file-search spec's MODIFIED "Windows Search
Unavailable" requirement and the powershell-search-bridge spec's
"Both-Transports-Exhausted Messaging" requirement.

"Map results to response schemas": `FileSearchPort.search()`/`get_info()`
already return `FileSummary`/`FileDetail` instances directly (see
`tools/file_search_adapter.py::FileSearchPort`); `file_search()` wraps its
final result list in `FileSearchResponse` (Batch 1's model, wired up here
per its own deviation note) alongside the response-level
`results_truncated` flag.
"""
import os
from datetime import datetime, timezone
from urllib.parse import unquote

from models.schemas import (
    FileDetail,
    FileSearchRequest,
    FileSearchResponse,
    FileSummary,
    GetFileInfoRequest,
)
from tools.errors import (
    PathNotFoundError,
    SearchRootNotAllowedError,
    WindowsSearchUnavailableError,
)
from tools.file_search_adapter import FileSearchPort
from tools.file_search_walk import walk_filename
from tools.settings import (
    default_search_roots,
    file_search_walk_max_dirs,
    file_search_walk_time_budget_seconds,
    load_settings,
)


def _allowed_roots(settings: dict) -> list[str]:
    """`file_search_allowed_roots` from `config/settings.yaml` when
    configured (non-empty); otherwise the environment-resolved defaults —
    see the file-search spec's "Allowed-Roots Enforcement" requirement."""
    configured = settings.get("file_search_allowed_roots")
    if configured:
        return list(configured)
    return default_search_roots()


def _max_results(settings: dict) -> int:
    """`file_search_max_results` from `config/settings.yaml`, default
    `200` when absent — see the file-search spec's "Result Cap"
    requirement."""
    return int(settings.get("file_search_max_results", 200))


def _normalize_path(path: str) -> str:
    """Case-insensitive, separator-normalized form of `path` for a
    containment comparison. Decodes a `file:///`-style URL to native form
    first (a no-op for a plain native path, which never has that prefix)."""
    if path.lower().startswith("file:///"):
        path = unquote(path[len("file:///") :]).replace("/", "\\")
    return path.replace("/", "\\").rstrip("\\").casefold()


def _is_contained(path_norm: str, root_norm: str) -> bool:
    """True if `path_norm` equals `root_norm` or is a subpath of it. Both
    arguments MUST already be normalized via `_normalize_path`.
    Boundary-aware (`root_norm + "\\"` prefix) so a sibling directory
    sharing a name prefix (e.g. `ana2` vs `ana`) is never mistaken for
    nested."""
    return path_norm == root_norm or path_norm.startswith(root_norm + "\\")


def _check_contained(path: str, allowed_roots: list[str]) -> None:
    """Raise `SearchRootNotAllowedError` if `path` is not contained within
    any of `allowed_roots` (case-insensitive, separator-normalized) —
    the pre-call containment check, before any adapter call."""
    path_norm = _normalize_path(path)
    root_norms = [_normalize_path(root) for root in allowed_roots]
    if not any(_is_contained(path_norm, root_norm) for root_norm in root_norms):
        raise SearchRootNotAllowedError(
            f"{path!r} is not contained within an allowed search root",
            requested_path=path,
            allowed_roots=allowed_roots,
        )


def _drop_outside_allowed_roots(
    results: list[FileSummary], allowed_roots: list[str]
) -> list[FileSummary]:
    """Post-call defense-in-depth (design.md decision #3b): drop any
    returned row whose normalized `path` does not fall under any of
    `allowed_roots`, regardless of the narrower `scope` (if any) the
    adapter was actually asked to search under.

    Alias-aware fallback (alias-containment-hotfix): Windows Search can
    report a redirected-library alias in `System.ItemPathDisplay` (what
    `result.path` normally preferred — see `FileSummary.alt_url_path`'s
    docstring) while `System.ItemUrl` still resolves to the real,
    containable path. A row therefore passes containment if EITHER
    `result.path` OR `result.alt_url_path` (when present) falls under an
    allowed root; when only the latter passes, the row is kept but its
    returned `path` is rewritten to that real (url-derived) form, never
    left as the unopenable alias. A row whose display-derived `path`
    already passes containment is returned completely unchanged."""
    root_norms = [_normalize_path(root) for root in allowed_roots]
    kept: list[FileSummary] = []
    for result in results:
        if any(_is_contained(_normalize_path(result.path), root_norm) for root_norm in root_norms):
            kept.append(result)
            continue
        alt_path = getattr(result, "alt_url_path", None)
        if alt_path and any(
            _is_contained(_normalize_path(alt_path), root_norm) for root_norm in root_norms
        ):
            kept.append(result.model_copy(update={"path": alt_path}))
    return kept


_FILENAME_STILL_WORKS_HINT = (
    "filename search still works — retry the same call with only "
    "'filename' set (omit 'phrase')."
)


def _raise_unavailable_with_filename_hint(exc: WindowsSearchUnavailableError) -> None:
    """Re-raise `exc` — already raised by the adapter (`FallbackSearchAdapter`,
    or a fake standing in for it) once BOTH the ADO and PowerShell-bridge
    transports are exhausted — with a message explicitly stating that
    filename search still works, per the file-search spec's MODIFIED
    "Windows Search Unavailable" requirement and the
    powershell-search-bridge spec's "Both-Transports-Exhausted Messaging"
    requirement. The adapter seam itself deliberately stays message-neutral
    (see `FallbackSearchAdapter`'s own docstring) — this tool layer is the
    one place that adds the hint, for every `phrase`-involving query
    (phrase-only AND combined filename+phrase).

    Joined with '. ' rather than a bare space (BUG-006, cowork
    0043-cowork-bug-006-ps-bridge-malformed-json.md): `exc`'s own message
    never carries trailing punctuation, so a plain-space join produced
    two sentences run together with no separator (e.g. "...malformed
    JSON filename search still works...", misreadable as one garbled
    clause) — the exact string a caller sees at the moment they're
    already confused."""
    raise WindowsSearchUnavailableError(f"{exc}. {_FILENAME_STILL_WORKS_HINT}") from exc


def _walk(search_roots: list[str], filename: str, top_n: int) -> tuple[list[FileSummary], bool]:
    """Run the bounded filesystem walk with the live-read caps from
    `tools/settings.py` — never cached, mirroring every other settings
    reader in this module."""
    return walk_filename(
        search_roots,
        filename,
        top_n,
        file_search_walk_time_budget_seconds(),
        file_search_walk_max_dirs(),
    )


def _search_filename_only(
    filename: str, search_roots: list[str], allowed_roots: list[str], top_n: int
) -> FileSearchResponse:
    """A `filename`-only query is answered ENTIRELY by the filesystem walk
    — the adapter is NEVER called, regardless of index health (the
    file-search spec's ADDED "Filename Queries Do Not Require the Index"
    requirement)."""
    results, truncated = _walk(search_roots, filename, top_n)
    results = _drop_outside_allowed_roots(results, allowed_roots)
    return FileSearchResponse(results=results, results_truncated=truncated)


def _search_phrase_only(
    phrase: str,
    search_roots: list[str],
    allowed_roots: list[str],
    top_n: int,
    adapter: FileSearchPort,
) -> FileSearchResponse:
    """A `phrase`-only query goes through the adapter (`FallbackSearchAdapter`
    in production: ADO, then the PowerShell bridge) unchanged. There is no
    walk-cap truncation signal for this shape (no walk ever runs), but the
    adapter's own PowerShell-bridge leg can itself return a truncated
    result (bridge-streaming-hotfix: a deadline-killed or early-dying
    child that already streamed some rows) — that signal is read off
    `adapter.last_search_truncated` (a documented attribute
    `FallbackSearchAdapter`/`PowerShellSearchBridge` set after every
    `search()` call; absent on `WindowsSearchAdapter`/`FakeFileSearchAdapter`,
    which default to `False` via `getattr`) and carried straight through
    to `results_truncated`."""
    try:
        results = adapter.search(filename=None, phrase=phrase, roots=search_roots, top_n=top_n)
    except WindowsSearchUnavailableError as exc:
        _raise_unavailable_with_filename_hint(exc)
        raise  # pragma: no cover - _raise_unavailable_with_filename_hint always raises
    except Exception as exc:
        # BUG-007 hotfix (0049-cowork-bug-007-phrase-untyped-crash.md):
        # an adapter that violates its own FileSearchPort contract by
        # raising something other than WindowsSearchUnavailableError must
        # still surface as a typed error here, never as a raw exception —
        # this is the exact tool-boundary contract BUG-007 broke.
        _raise_unavailable_with_filename_hint(
            WindowsSearchUnavailableError(f"file search adapter failed unexpectedly: {exc}")
        )
        raise  # pragma: no cover - _raise_unavailable_with_filename_hint always raises
    # A hostile/buggy adapter may return None instead of a list without
    # raising at all — treat that the same as "no results" rather than
    # crashing on the iteration below.
    results = results or []
    phrase_truncated = bool(getattr(adapter, "last_search_truncated", False))
    results = _drop_outside_allowed_roots(results, allowed_roots)
    return FileSearchResponse(results=results, results_truncated=phrase_truncated)


def _search_combined(
    filename: str,
    phrase: str,
    search_roots: list[str],
    allowed_roots: list[str],
    top_n: int,
    adapter: FileSearchPort,
) -> FileSearchResponse:
    """Combined `filename`+`phrase` query rule (file-search spec's ADDED
    "Combined Filename and Phrase Query Rule"): the walk runs first for
    `filename` candidates; if it finds none, short-circuit with NO adapter
    call at all. Otherwise the `phrase` condition runs against the
    adapter, scoped to the same roots, and only rows present in BOTH sets
    (intersected by `_normalize_path()`-normalized path) are returned. If
    the index leg is exhausted (both transports fail), the combined query
    fails the same way a phrase-only query would — it never silently
    degrades to filename-only results.

    `results_truncated` is the OR of the walk's own truncation flag and
    the adapter's `last_search_truncated` (bridge-streaming-hotfix,
    same attribute `_search_phrase_only` reads) — either leg stopping
    early is enough to warn the caller there may be more."""
    walk_results, truncated = _walk(search_roots, filename, top_n)
    if not walk_results:
        return FileSearchResponse(results=[], results_truncated=truncated)

    try:
        phrase_results = adapter.search(filename=None, phrase=phrase, roots=search_roots, top_n=top_n)
    except WindowsSearchUnavailableError as exc:
        _raise_unavailable_with_filename_hint(exc)
        raise  # pragma: no cover - _raise_unavailable_with_filename_hint always raises
    except Exception as exc:
        # BUG-007 hotfix — see _search_phrase_only's identical guard.
        _raise_unavailable_with_filename_hint(
            WindowsSearchUnavailableError(f"file search adapter failed unexpectedly: {exc}")
        )
        raise  # pragma: no cover - _raise_unavailable_with_filename_hint always raises
    phrase_results = phrase_results or []
    phrase_truncated = bool(getattr(adapter, "last_search_truncated", False))

    walk_paths = {_normalize_path(result.path) for result in walk_results}
    intersected = [
        result for result in phrase_results if _normalize_path(result.path) in walk_paths
    ]
    results = _drop_outside_allowed_roots(intersected, allowed_roots)
    return FileSearchResponse(results=results, results_truncated=truncated or phrase_truncated)


def file_search(request: FileSearchRequest, adapter: FileSearchPort) -> FileSearchResponse:
    """Search files via `filename`/`phrase`, optionally restricted to
    `scope`. At least one of `filename`/`phrase` is required — see the
    file-search spec's "Search Input Parameters" requirement. Rejects an
    out-of-root `scope` before the adapter/walk is ever called; also drops
    any row the adapter/walk returns that falls outside the allowed roots
    (defense-in-depth).

    Dispatches by query kind (file-search-resilience change, Phase 5):
    `filename`-only never touches the adapter (filesystem walk only);
    `phrase`-only goes through the adapter unchanged; both together run
    the walk first and intersect its candidates with the adapter's
    `phrase` matches. Returns a `FileSearchResponse` envelope
    (`results` + `results_truncated`), not a bare list."""
    if not request.filename and not request.phrase:
        raise ValueError("file_search requires at least one of filename or phrase")

    settings = load_settings()
    allowed_roots = _allowed_roots(settings)
    top_n = _max_results(settings)

    if request.scope:
        _check_contained(request.scope, allowed_roots)
        search_roots = [request.scope]
    else:
        search_roots = allowed_roots

    if request.filename and not request.phrase:
        return _search_filename_only(request.filename, search_roots, allowed_roots, top_n)
    if request.phrase and not request.filename:
        return _search_phrase_only(request.phrase, search_roots, allowed_roots, top_n, adapter)
    return _search_combined(
        request.filename, request.phrase, search_roots, allowed_roots, top_n, adapter
    )


def _resolve_native_path(path: str) -> str:
    """Decode a `file:///`-style URL to its native, case-preserving form
    for the `os.stat()` call — a plain native path passes through
    unchanged. Mirrors `_normalize_path`'s URL-decoding step, but WITHOUT
    casefolding/trailing-slash-stripping, since `os.stat()` needs the
    actual path text, not a comparison-only normalized form."""
    if path.lower().startswith("file:///"):
        return unquote(path[len("file:///") :]).replace("/", "\\")
    return path


def _name_from_native_path(native_path: str) -> str:
    """Final path component, tolerating either separator — mirrors
    `tools/file_search_adapter.py::_row_to_summary`'s
    `path.rsplit("\\", 1)[-1]` fallback convention."""
    return native_path.replace("/", "\\").rsplit("\\", 1)[-1] or native_path


def file_get_info(request: GetFileInfoRequest, adapter: FileSearchPort) -> FileDetail:
    """Fetch full metadata for a single file by its `path` (native or
    `file:///` URL form). Rejects an out-of-root path before `os.stat` or
    the adapter is ever called — the same allowed-roots policy as
    `file_search`.

    Phase 5 (file-search-resilience change) rewrite: `path`/`name`/`size`/
    `lastModified`/`createdTime`/`extension` are ALWAYS sourced from
    `os.stat()` on the resolved native path — never from the index — so a
    real, unindexed file returns full core metadata (the file-get-info
    spec's MODIFIED "Get Info Output Shape" requirement). A path that does
    not resolve on disk raises `PathNotFoundError` (`path_not_found`)
    BEFORE any index enrichment is attempted (the ADDED "Path Not Found On
    Disk" requirement) — distinct from a real-but-unindexed path, which
    never raises. `kind`/`snippet` are enrichment-only: any failure
    reaching the index (unreachable — both transports exhausted — or
    simply a miss) is swallowed, leaving them `None` (the ADDED "Index
    Enrichment Failure Never Surfaces" requirement; design.md's "New
    `PathNotFoundError`" decision)."""
    settings = load_settings()
    allowed_roots = _allowed_roots(settings)

    _check_contained(request.path, allowed_roots)

    native_path = _resolve_native_path(request.path)
    try:
        stat_result = os.stat(native_path)
    except OSError as exc:
        raise PathNotFoundError(f"{request.path!r} does not exist on disk") from exc

    name = _name_from_native_path(native_path)
    extension = os.path.splitext(name)[1] or None

    kind: str | None = None
    snippet: str | None = None
    try:
        detail = adapter.get_info(request.path)
        kind = detail.kind
        snippet = detail.snippet
    except Exception:
        # Index enrichment failure never surfaces (file-get-info spec's
        # ADDED "Index Enrichment Failure Never Surfaces" requirement) —
        # broadened beyond the two documented FileSearchPort exceptions
        # (BUG-007 hotfix, 0049-cowork-bug-007-phrase-untyped-crash.md) so
        # a hostile/buggy adapter that raises something else entirely, or
        # returns None instead of a FileDetail (caught here by the
        # `detail.kind` attribute access above, inside this same try),
        # still leaves `kind`/`snippet` at their `None` default instead of
        # crashing the whole call.
        kind = None
        snippet = None

    return FileDetail(
        path=native_path,
        name=name,
        size=stat_result.st_size,
        last_modified=datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc),
        created_time=datetime.fromtimestamp(stat_result.st_ctime, tz=timezone.utc),
        kind=kind,
        extension=extension,
        snippet=snippet,
    )
