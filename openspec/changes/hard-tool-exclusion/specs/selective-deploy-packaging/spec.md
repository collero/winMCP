# Delta for Selective Deploy Packaging

**Baseline**: `openspec/changes/selective-tool-deployment/specs/selective-deploy-packaging/spec.md`
(pending — selective-tool-deployment is not yet archived, so this delta
modifies THAT pending spec, not `openspec/specs/selective-deploy-packaging/`,
which does not exist yet). At archive time, both changes' deltas must be
folded together into one new main spec file.

## MODIFIED Requirements

### Requirement: Shipped-Tools Manifest With Per-Mode Default-Enabled Flags

Every build MUST emit a manifest listing included tool names, each with
a `default_enabled` flag. A default build sets it `true` for every
catalog tool, regardless of maturity. A share build, under the
two-tier model, MUST list ONLY the builder's final selection — every
listed tool's `default_enabled` is unconditionally `true`; an
unselected tool MUST NOT appear at all, whether from a zero-selected
family or a partially-selected one. The installer trusts the
manifest's list and flags as-is, staying maturity-agnostic.
(Previously: a share build's manifest was implemented to list all
catalog tools in every mode, only varying `default_enabled` — a
shipped-but-disabled tier this change removes for share builds.)

#### Scenario: Default build's manifest is unconditionally all-enabled

- GIVEN a default build over a mixed-maturity 13-tool catalog
- WHEN the zip is inspected
- THEN every manifest tool is `default_enabled=true`, regardless of maturity

#### Scenario: Share build's manifest lists only the selected tools

- GIVEN a share build whose final selection is 9 of 13 tools, spanning 3 whole families plus 2 tools from a 4th family
- WHEN the zip is inspected
- THEN the manifest lists exactly those 9 tools, each `default_enabled=true`, with no entry at all for the other 4

## ADDED Requirements

### Requirement: Dependency Files Are Omitted Only When No Owning Tool Is Selected

A share build MUST stage a catalog dependency file (`deps.modules` or
`deps.ps1`) iff at least one tool declaring it is selected; omit it
when every declaring tool is unselected. Family-level omission is thus
derived: a zero-selected family loses every family-specific file, while
a partially-selected family keeps whatever its selected tool(s) still
need — an unselected sibling's exclusive file MAY also be omitted.
Shared infrastructure (transport bridge, settings, schemas, errors,
`server.py`) is never a catalog dependency and always stages.

#### Scenario: Zero-selection family's files are never staged

- GIVEN a share build selecting zero tools from the `onenote` family
- WHEN the build completes
- THEN no staged file matches `onenote`'s catalog `deps.modules`/`deps.ps1`

#### Scenario: Partially-selected family keeps files its selected tool still needs

- GIVEN a share build selecting 1 of 4 `onenote` tools, and that tool declaring a shared bridge dependency also declared by another unselected `onenote` tool
- WHEN the build completes
- THEN the shared bridge stages, because at least one of its owning tools is selected

### Requirement: Gate 7 Verifies Excluded-Dependency Absence

Gate 7 MUST become mode-aware: for a full/default build, its existing
equality check (catalog/server.py/manifest name-sets, staged-deps
presence) is unchanged. For a share build, Gate 7 MUST ADDITIONALLY run
a negative check — for every catalog `deps.modules`/`deps.ps1` file
whose entire owner set (per the `tool-catalog` spec) is outside the
final selection, that file may not appear anywhere among the files
staged into the zip. A single stray excluded file MUST fail the gate.

#### Scenario: Gate 7 fails if an excluded family's file leaks into staging

- GIVEN a share build excluding the `mail` family (none of its tools' owner sets intersect the selection), where a staging bug leaves `tools/mail.py` in the zip
- WHEN Gate 7 runs
- THEN it fails, naming `tools/mail.py` as a file with no selected owner

#### Scenario: Gate 7 passes on a clean share build

- GIVEN a share build excluding 2 of 5 families, with staging correctly omitting both
- WHEN Gate 7 runs
- THEN it passes: the existing equality check succeeds AND the negative check finds no excluded-family file present
