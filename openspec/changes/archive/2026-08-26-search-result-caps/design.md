# Design: Search Result Caps (BUG-002)

## Technical Approach

Add a `limit` field to `MailSearchRequest`/`SearchRequest`/
`TaskSearchRequest` (default 50, hard max 200, validated in the tool
layer before any adapter call). Each adapter's `search()` gains
`limit: int`, orders results near the COM source, and stops collecting
once `limit + 1` post-filter matches are seen — enough to know whether
more existed (`results_truncated`) without a full unbounded fetch. Tool
functions wrap the row list in a small per-domain envelope, replacing
today's plain `list[XSummary]` return.

## Architecture Decisions

### Decision: Response envelope shape

**Choice**: One shared mixin `_TruncatableResult(_AliasedModel):
results_truncated: bool = Field(default=False, alias="resultsTruncated")`
in `models/schemas.py`, plus three concrete wrappers —
`MailSearchResult`/`CalendarSearchResult`/`TaskSearchResult`, each
`(_TruncatableResult)` with `results: list[XSummary]`. `server.py`'s
three search tools change return annotation from `list[XSummary]` to
the matching envelope.
**Alternatives**: generic `SearchResult[T]` — rejected, no generic
model exists anywhere in this codebase and FastMCP's schema generation
for generics is untested here; a side-channel — rejected, MCP tool
results have no reliable side channel.
**Rationale**: matches the existing "concrete per-domain model"
convention; the mixin keeps the flag DRY without generics.
**Consequence**: `tests/test_{mail,calendar,tasks}_tools.py` and
`server.py`'s 3 tool signatures change from `-> list[X]` to `-> XResult`
— expected fallout.

### Decision: limit default/max as config

**Choice**: New `config/settings.yaml` keys `search_default_limit`
(50) / `search_max_limit` (200), read via `tools/settings.py::
resolve_search_limit(limit: int | None) -> int` — one shared helper,
raises `ValueError` for `limit <= 0`, clamps `limit > max`.
**Alternatives**: hardcoded constants — rejected, inconsistent with
`file_search_max_results`'s config-driven precedent.
**Rationale**: one helper enforces identical semantics across all
three tools per the specs.

### Decision: Ordering strategy per adapter

| Adapter | Source-level ordering | Bounding |
|---|---|---|
| Mail (mapped folder) | `Sort("[ReceivedTime]/[SentOn]/[LastModificationTime]", True)` (descending) after existing `Restrict()` | iterate, filter subject/sender, stop at `limit+1` matches |
| Mail (`folderPath`) | none available (pre-existing full Python scan, unchanged cost) | sort collected matches by resolved date descending, slice `[:limit]` |
| Calendar | `Sort("[Start]", True)` descending, replacing today's ascending sort; kept after `IncludeRecurrences=True`/`Restrict()` | iterate, filter subject, stop at `limit+1` |
| Tasks | none today; folder already fully materialized in Python | sort by `(due_date is None, due_date)` ascending, slice `[:limit]` |

**Rationale**: mail/calendar sit behind a potentially huge `Restrict()`
result (the live BUG-002 case), so early-stop at `limit+1` avoids
materializing thousands of rows. Tasks are already fully materialized
and architecturally bounded (~25 today), so sort+slice is simplest,
matching the proposal's "defense in depth, not the live emergency"
framing.
**Residual limitation**: `folderPath`'s full scan cost is pre-existing
and unrelated to this change or the sibling fix — this change bounds
the *output*, not the scan cost (see Open Questions).

### Decision: Sibling-change collision boundary

`outlook-date-locale-fix` edits the `Restrict()` DASL date-string
construction inside the same `tools/mail_adapter.py::search()` /
`tools/outlook_adapter.py::search()` bodies. This change edits, in
those same methods, only: the `Sort()` descending argument, the
iteration/early-stop loop, and `limit`/`results_truncated` bookkeeping
— never the date-string values. `sdd-tasks` MUST sequence one change's
edit before the other lands and rebase rather than blind-overwrite.

## File Changes

| File | Action | Description |
|---|---|---|
| `models/schemas.py` | Modify | `limit` on 3 request models; `_TruncatableResult` + 3 envelope models |
| `tools/settings.py` | Modify | add `resolve_search_limit()` |
| `config/settings.yaml` | Modify | add `search_default_limit`/`search_max_limit` (optional) |
| `tools/mail.py`, `calendar.py`, `tasks.py` | Modify | resolve `limit`, wrap result in envelope |
| `tools/mail_adapter.py`, `outlook_adapter.py`, `task_adapter.py` | Modify | `search()` gains `limit`, ordering/bounding per table above; Protocol signatures updated |
| `tools/fake_mail_adapter.py`, `fake_adapter.py`, `fake_task_adapter.py` | Modify | mirror real adapters exactly (Strict TDD) |
| `server.py` | Modify | 3 tools gain `limit` param + envelope return type |
| `tests/test_{mail,calendar,tasks}_tools.py` | Modify | envelope-shape assertions + new scenarios |

## Data Flow (mail_search, oversized case)

```
client → _mail_search(limit=None) [server.py]
       → mail_search(request, adapter) [tools/mail.py]
           resolve_search_limit(None) → 50
       → OutlookMailAdapter.search(..., limit=50) [tools/mail_adapter.py]
           Restrict() by date → Sort("[ReceivedTime]", True)
           for item in restricted:          # descending
               if subject/sender match: collect
               if len(collected) > 50: break # early stop
           truncated = len(collected) > 50
       → MailSearchResult(results=collected[:50], results_truncated=True)
```

## Testing Strategy

| Layer | What | Approach |
|---|---|---|
| Unit (tool) | limit default/clamp/reject | fake adapters, per spec scenarios |
| Unit (adapter) | ordering + early-stop + truncation | mocked `win32com.client`, existing test patterns |
| Fake parity | fakes match real-adapter contract | new assertions in `test_fake_*.py` |
| Regression | the 5 required scenario families | new tests per delta-spec scenario, mocked COM |

## Migration / Rollout

No data migration. `limit` is optional/additive; the intended fix
changes return type (envelope) and default cap (50) — not a
compatibility break to avoid.

## Open Questions

- [ ] `folderPath` mail search's full-folder Python scan cost stays
      unbounded (output-bounded, not scan-bounded) — acceptable for
      now; revisit if a custom-folder complaint arises.
