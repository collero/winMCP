# Namespace registry

Registers the uppercase `{ORG}` / `{DOM}` / `{APP}` abbreviations used in ADR
ids (`ADR-{ORG}-{DOM}-{APP}-NNN`), per `adr-schema.md` §1.3 / validation V4.
Owned by the `adr-management` skill. Never coin a new abbreviation without
adding a row here first.

WinMCP is a **simple app repo** (single deployable MCP server, not yet part
of a domain monorepo — no `CONTEXT-MAP.md`, no `apps/`+`libs/`+`contracts/`
layout). Per `placement.md` — *Simple app repo*, a domain is enforced from
day one via the reserved provisional placeholder `unassigned` (`TBD`) until
the project migrates into a real domain monorepo.

| Abbreviation | Kind | Slug | Notes |
|---|---|---|---|
| `COL` | organization | `colleros` | No real multi-project organisation exists yet for this solo/personal repo — a project-chosen org slug was registered per `placement.md`'s "no org-less ids" rule, using the maintainer's own namespace rather than dropping the segment. |
| `TBD` | domain (placeholder) | `unassigned` | Reserved provisional placeholder per schema/placement convention — WinMCP has not yet been assigned to a real bounded-context domain or migrated into a domain monorepo. Rename on migration (cross-domain move — see `placement.md` — *Migration: moving an ADR between scopes*). |
| `WINMCP` | app | `win-mcp` | Extracted from `pyproject.toml`'s `[project].name` (`win-mcp`) per the canonical extraction order in `placement.md` — *Simple app repo*. |

## Change log

- 2026-08-26 — registry created; `COL`/`TBD`/`WINMCP` registered for the
  first two ADRs, `ADR-COL-TBD-WINMCP-001` and `ADR-COL-TBD-WINMCP-002`.
