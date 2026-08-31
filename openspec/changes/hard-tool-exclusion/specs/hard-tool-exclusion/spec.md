# Hard Tool Exclusion Specification

**Baseline**: none — new capability. No existing `openspec/specs/hard-tool-exclusion/`.

## Purpose

Two-tier share model: checked = shipped AND default-enabled; unchecked
= physically absent — "not selected" means "cannot run," not "off by
default." Capability governance for confidential business data and
PII, not access-control or anti-redistribution. Full/default builds
stay unaffected and all-inclusive.

## Requirements

### Requirement: Family Is the Unit of Physical Exclusion

A share build MUST determine physical exclusion at FAMILY granularity,
never per-tool: a zero-selected family MUST be physically absent from
the zip — its modules, `.ps1` bridge(s), and family-only assets
omitted. Shared infrastructure (transport bridge, settings, schemas,
errors, `server.py`) MUST ship regardless of family selection.

#### Scenario: Zero-selection family is physically absent

- GIVEN a share build where the operator selects zero `onenote` tools
- WHEN the zip is inspected
- THEN it contains no `onenote` module, `.ps1` bridge, or family-only asset

#### Scenario: Shared infrastructure always ships

- GIVEN a share build excluding every family but one
- WHEN the zip is inspected
- THEN `ps_bridge_transport.py`, `settings.py`, `models/schemas.py`, `errors.py`, and `server.py` are all present

### Requirement: A Partially-Selected Family's Unselected Tools Are Unenableable

When a family has at least one selected tool, every file still needed
by that selected tool MUST stay staged (a file with no unselected
tool depending on it is never a candidate for omission regardless of
mechanism granularity). Independent of which files physically ship,
any unselected tool of that family MUST be unenableable through any
non-file surface: absent from `tools/shipped-tools.json`, never
offered by the installer, and refused at server registration even if
hand-added to `config/installed-tools.yaml`.

#### Scenario: Unselected sibling tool cannot be enabled via config edit

- GIVEN a share build selecting only `onenote_search` from the 4-tool `onenote` family, and a recipient hand-edits `config/installed-tools.yaml` to add `onenote_update_page`
- WHEN the server starts
- THEN only `onenote_search` registers; `onenote_update_page` is refused, being absent from the shipped manifest

#### Scenario: Installer never offers an unselected sibling tool

- GIVEN the same share build
- WHEN the installer runs, interactively or not
- THEN `onenote_update_page` never appears in any prompt or output

### Requirement: Registration Allowlist Is the Intersection of Shipped and Installed

The server MUST register only tools BOTH shipped and installed-enabled
(full precedence table owned by `mcp-server-bootstrap`); a name enabled
in `installed-tools.yaml` but absent from `shipped-tools.json` is
silently excluded — never registered, never an error. This holds for a
whole hard-excluded family too.

#### Scenario: Hand-edited config cannot resurrect an excluded family

- GIVEN a share package with `mail` hard-excluded, and a recipient adds `mail_search` to `config/installed-tools.yaml`
- WHEN the server starts
- THEN `mail_search` is not registered

### Requirement: Import Safety Under Any Family Subset

Server startup MUST succeed with any subset of family modules
physically absent, including a share package built with only one
family selected.

#### Scenario: Single-family share package starts and serves exactly its tools

- GIVEN a share package with only `onenote` selected (all other families' files absent)
- WHEN the server starts
- THEN startup succeeds with no import error, and the tool list shows exactly the shipped `onenote` tools

### Requirement: Full Build Is Unaffected By Hard Exclusion

Physical exclusion applies ONLY to share builds. A full/default build
MUST stay byte-identical to its pre-change output; every existing
`installed-tools.yaml` back-compat guarantee holds unchanged.

#### Scenario: Full build ships every family regardless of any exclusion logic

- GIVEN a full/default build (no share flag)
- WHEN the zip is inspected
- THEN every family's files are present, identical to the pre-hard-tool-exclusion build

### Requirement: Protection Limits Are Documented

The README (or equivalent) MUST plainly state what hard exclusion does
NOT protect against: a recipient obtaining a fuller package elsewhere
is not blocked, and shipped code remains fully readable — this
prevents *running* an unselected capability, not *reading* it.

#### Scenario: Documentation states the honesty limits

- GIVEN the shipped README
- WHEN its hard-exclusion section is read
- THEN it states redistribution of a fuller package and reading shipped code are both unprotected
