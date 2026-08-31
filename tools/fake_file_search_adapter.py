"""FakeFileSearchAdapter — in-memory FileSearchPort implementation used by
tests (file-search change).

Seeded via the constructor with a flat list of `FileDetail` (full
metadata, including `snippet` when the "file content" is modeled).
Implements the same `FileSearchPort` Protocol as the real win32com/ADODB-
backed adapter, so tool code under test never knows the difference —
mirrors `tools/fake_mail_adapter.py::FakeMailAdapter`.

Filter sequence for `search()`: (1) `filename` case-insensitive substring
match on `name` if given, (2) `phrase` case-insensitive substring match
against the seeded `snippet` if given (the closest stand-in this fake has
for full-text content — `content` itself is out of scope per the
proposal), (3) roots containment — a file's `path` must fall under at
least one entry in `roots` (case-insensitive, separator-normalized,
boundary-aware so a sibling directory sharing a name prefix, e.g. `ana2`
vs `ana`, is never mistaken for contained) — then (4) capped at `top_n`.
This mirrors what the real adapter's `SCOPE=`/`CONTAINS()`/`TOP n` SQL
would select, without any COM/ADODB access.

`get_info()` does an exact/normalized path lookup against the seeded
files: accepts either the native form or a `file:///`-style URL (decoded
and separator-normalized before comparison, mirroring the
windows-search-adapter spec's "Path Representation Normalization"
requirement), raising `FileNotFoundInIndexError` on no match. A seeded
file with `snippet=None` (e.g. an unhydrated OneDrive placeholder) still
returns full metadata — no special-casing needed, since `FileDetail`
already allows `snippet=None`.
"""
from urllib.parse import unquote

from models.schemas import FileDetail, FileSummary
from tools.errors import FileNotFoundInIndexError


def _normalize(path_or_url: str) -> str:
    """Decode a `file:///`-style URL to native form (if given one),
    unchanged otherwise."""
    if path_or_url.lower().startswith("file:///"):
        decoded = unquote(path_or_url[len("file:///") :])
        return decoded.replace("/", "\\")
    return path_or_url


def _casefold_normalized(path: str) -> str:
    """Case-insensitive, separator-normalized form of `path` for
    comparison — mirrors `tools/settings.py::_casefold_normalized`."""
    return path.replace("/", "\\").rstrip("\\").casefold()


def _is_contained(path_norm: str, root_norm: str) -> bool:
    """True if `path_norm` equals `root_norm` or is a subpath of it. Both
    arguments MUST already be normalized via `_casefold_normalized`."""
    return path_norm == root_norm or path_norm.startswith(root_norm + "\\")


def _to_summary(file: FileDetail) -> FileSummary:
    return FileSummary(
        path=file.path,
        name=file.name,
        size=file.size,
        last_modified=file.last_modified,
        kind=file.kind,
        extension=file.extension,
    )


class FakeFileSearchAdapter:
    """In-memory stand-in for `WindowsSearchAdapter`, satisfying
    `FileSearchPort`."""

    def __init__(self, files: list[FileDetail] | None = None):
        self._files: list[FileDetail] = list(files) if files else []

    def search(
        self,
        filename: str | None,
        phrase: str | None,
        roots: list[str],
        top_n: int,
    ) -> list[FileSummary]:
        filename_needle = filename.lower() if filename else None
        phrase_needle = phrase.lower() if phrase else None
        root_norms = [_casefold_normalized(root) for root in roots]

        matches: list[FileSummary] = []
        for file in self._files:
            if filename_needle is not None and filename_needle not in file.name.lower():
                continue
            if phrase_needle is not None and phrase_needle not in (file.snippet or "").lower():
                continue
            if root_norms:
                path_norm = _casefold_normalized(file.path)
                if not any(_is_contained(path_norm, root_norm) for root_norm in root_norms):
                    continue
            matches.append(_to_summary(file))
            if len(matches) >= top_n:
                break
        return matches

    def get_info(self, path_or_url: str) -> FileDetail:
        needle = _casefold_normalized(_normalize(path_or_url))
        for file in self._files:
            if _casefold_normalized(file.path) == needle:
                return file
        raise FileNotFoundInIndexError(f"No indexed file at {path_or_url!r}")
