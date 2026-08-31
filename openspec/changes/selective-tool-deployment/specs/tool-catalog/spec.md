# Tool Catalog Specification

## Purpose

`tools/catalog.yaml` is the single source of truth enumerating every tool
WinMCP ships: its family, maturity, and file/module/bridge dependencies.
Build-time packaging, install-time provisioning, server registration, and
smoke-test expectations all derive their tool lists from this one file
instead of duplicating them.

## Requirements

### Requirement: Catalog Structure

`tools/catalog.yaml` MUST be parseable YAML listing every tool the
server registers, each entry giving: `name` (matching the `@app.tool`
name exactly), `family`, `maturity` (`alpha`/`beta`/`stable`), and `deps`
(every file required for that tool to function, including non-`.py`
assets like PowerShell bridge scripts).

#### Scenario: Catalog matches server.py's registered tools

- GIVEN `tools/catalog.yaml` and `server.py`'s 13 `@app.tool` names
- WHEN the two are compared
- THEN every registered tool name appears exactly once in the catalog, with no extras and no omissions

#### Scenario: A tool declares its bridge dependency

- GIVEN `onenote_search`'s catalog entry
- WHEN its `deps` list is read
- THEN it includes both `tools/onenote_adapter.py` and `tools/ps_bridge_onenote.ps1`

### Requirement: Maturity Drives the Share Build's Pre-Selection Only, Never a Hard Exclusion

Each tool's `maturity` MUST be one of `alpha`, `beta`, or `stable`. This
value MUST drive default pre-selection for exactly one consumer: the
share build's builder-facing tool picker (beta/stable pre-checked, alpha
unchecked). It MUST NOT be used to hard-exclude a tool from the
default/full build, which MUST include every tool regardless of
maturity, nor to block any consumer's explicit override. Downstream, the
shipped-tools manifest (selective-deploy-packaging spec) records each
shipped tool's install-time `default_enabled` flag: for a share build,
seeded from this same maturity value and builder-overridable; for a
default build, always true regardless of maturity. The installer trusts
`default_enabled` directly and stays maturity-agnostic.

#### Scenario: Alpha tool's share-build pre-selection defaults to unselected

- GIVEN a catalog entry with `maturity: alpha`
- WHEN a share build's pre-selection is computed
- THEN that tool defaults to unselected, but remains explicitly selectable

#### Scenario: Beta and stable tools default to pre-selected in a share build

- GIVEN catalog entries with `maturity: beta` and `maturity: stable`
- WHEN a share build's pre-selection is computed
- THEN both default to pre-selected

#### Scenario: A default/full build ignores maturity entirely

- GIVEN a catalog with a mix of alpha, beta, and stable tools
- WHEN a default/full build runs (no share-build flag)
- THEN every tool is included regardless of maturity — alpha tools are not excluded

### Requirement: Loadable Without Windows or COM

Parsing `tools/catalog.yaml` MUST succeed on the Linux dev/CI host with
no `win32com`/COM dependency — a plain YAML load.

#### Scenario: Catalog parses on WSL2

- GIVEN this WSL2 dev host
- WHEN a Python script loads `tools/catalog.yaml` via a stdlib/PyYAML parser
- THEN it succeeds, returning a structured list of entries, with no import errors

### Requirement: Consistent Family Grouping

The catalog MUST group tools by `family` consistently enough to drive a
family-then-tool hierarchical selection prompt with no duplicated or
inconsistently-spelled family names.

#### Scenario: Family names are spelled identically across entries

- GIVEN all catalog entries
- WHEN grouped by `family`
- THEN every tool belonging to the same family uses the exact same family string (e.g. always `onenote`, never a variant casing/spacing)
