# Delta for MCP Server Bootstrap

**Baseline**: `openspec/specs/mcp-server-bootstrap/spec.md` (main spec)
AS ALREADY MODIFIED by the pending delta at
`openspec/changes/selective-tool-deployment/specs/mcp-server-bootstrap/spec.md`
(that change is not yet archived). This delta's `MODIFIED Requirements`
below supersede that pending delta's "Tool Registration" block in full;
its "Import Safety Independent of Registration Gating" ADDED
requirement is untouched and still applies. At archive time, all three
layers (main spec, selective-tool-deployment's delta, this delta) must
be folded together into one new main spec file.

## MODIFIED Requirements

### Requirement: Tool Registration

The server MUST register, at startup, exactly the intersection of two
sets: (a) tools present in `tools/shipped-tools.json`, and (b) tools
enabled per `config/installed-tools.yaml`. Precedence when either or
both files are absent from the deployed copy:

| `shipped-tools.json` | `installed-tools.yaml` | Registered set |
|---|---|---|
| present | present | shipped ∩ installed |
| present | absent | every shipped tool (back-compat: "absent config = install all", scoped to what shipped) |
| absent | present | every catalog tool ∩ installed (legacy package, pre-selective-deploy manifest never existed) |
| absent | absent | every catalog tool (today's original, pre-selective-deploy behavior, unchanged) |

A name in `config/installed-tools.yaml` but absent from
`tools/shipped-tools.json` (when it exists) is silently excluded —
never registered, never an error. Each registered tool stays backed by
its schema in `models/schemas.py` and its adapter seam.
(Previously: gated on `installed-tools.yaml` alone against the full
catalog, no `shipped-tools.json` intersection — a hand-edited config
could enable any catalog tool regardless of what a share build shipped.)

#### Scenario: All catalog tools are discoverable when no manifest and no config file exist

- GIVEN the server module is imported with neither `tools/shipped-tools.json` nor `config/installed-tools.yaml` present, and fake adapters injected
- WHEN an MCP client lists available tools
- THEN every tool in `tools/catalog.yaml` is present — current, pre-this-change behavior

#### Scenario: Only enabled tools are discoverable when both files exist and agree

- GIVEN `tools/shipped-tools.json` lists 10 tools and `config/installed-tools.yaml` enables 8 of those 10
- WHEN an MCP client lists available tools
- THEN only those 8 are present

#### Scenario: A hand-edited config cannot resurrect a hard-excluded tool

- GIVEN a share package whose `tools/shipped-tools.json` omits `onenote_update_page` (its family was partially selected), and a recipient hand-adds `onenote_update_page` to `config/installed-tools.yaml`
- WHEN the server starts
- THEN `onenote_update_page` is not registered — it is absent from the shipped manifest, so the intersection excludes it regardless of the config file

#### Scenario: Legacy package with a manifest absent falls back to catalog-vs-config

- GIVEN an installed tree with no `tools/shipped-tools.json` but a `config/installed-tools.yaml` enabling 5 catalog tools
- WHEN the server starts
- THEN exactly those 5 are registered, exactly as under selective-tool-deployment's original behavior before this change

## ADDED Requirements

### Requirement: Import Safety Under Physical Family Absence

Importing `server.py` MUST succeed when an entire family's module
files are PHYSICALLY ABSENT from the installed tree (not merely
excluded by configuration) — the case a hard-excluded share build
produces. Each family's imports and registrations MUST be import-fault
tolerant: an absent family causes zero tools from that family to be
registered, but MUST NOT prevent any other family's tools from
importing or registering.

#### Scenario: A single-family share package imports and serves cleanly

- GIVEN a share package with only the `onenote` family's modules and bridge script physically present (all other families' modules absent from disk)
- WHEN `server.py` is imported and started
- THEN the import succeeds with no unhandled exception, and only `onenote`'s shipped tools are registered

#### Scenario: An absent family does not break a present family's registration

- GIVEN a share package missing the `mail` family's modules entirely, with `calendar`, `task`, `file`, and `onenote` all present
- WHEN the server starts
- THEN all shipped tools from the four present families register normally; no error surfaces from `mail`'s absence beyond zero `mail` tools being available
