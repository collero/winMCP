# Selective Deploy Packaging Specification

## Purpose

`make-deploy-package.sh` supports two build modes: a **default build**
(no flags), identical to today's pipeline, and an explicit **share
build** where a builder picks which tools to include, pre-selected by
maturity but overridable. Every build emits a manifest recording what
shipped and each tool's `default_enabled` install state.

## Requirements

### Requirement: Default Build Includes Every Tool, Byte-Identical to Today

With no build-mode flag, `make-deploy-package.sh` MUST stage every
catalog tool regardless of maturity, matching the pipeline
`deploy-qa.sh`/`promote-pro.sh` depend on today.

#### Scenario: Default build includes alpha tools and matches today's pipeline

- GIVEN a catalog with 11 non-alpha and 2 alpha tools
- WHEN `make-deploy-package.sh` runs with no build-mode flag
- THEN all 13 are staged, including both alpha ones, matching the pre-change pipeline

### Requirement: Share Build Is Maturity-Prefilled but Builder-Overridable

`make-deploy-package.sh` MUST support a share-build mode letting the
builder choose which tools to stage, pre-selecting beta/stable tools
and leaving alpha unselected. Maturity MUST NOT hard-block an explicit
override either way.

#### Scenario: Pre-selection follows maturity by default

- GIVEN a share build over 11 non-alpha and 2 alpha tools
- WHEN the builder makes no changes
- THEN the resulting selection is exactly the 11 non-alpha tools

#### Scenario: Builder override always wins over maturity

- GIVEN the same share build
- WHEN the builder adds an alpha tool and removes a pre-selected stable one
- THEN the alpha tool ships and the stable one does not

### Requirement: A Non-Interactive Share Build Requires an Explicit Selection

A share build with no TTY MUST NOT fall back to any implicit default —
that would ship an uncurated package. It MUST succeed only with an
explicit selection, staging exactly that list; absent one, it MUST fail
loudly, producing no package. The default build is unaffected.

#### Scenario: Non-interactive share build with an explicit list succeeds

- GIVEN a share build with no TTY and an explicit selection naming 6 tools
- WHEN the build runs
- THEN it completes with no prompting, staging exactly those 6 tools

#### Scenario: Non-interactive share build without an explicit list fails loudly

- GIVEN a share build with no TTY and no explicit selection
- WHEN the build runs
- THEN it fails immediately, producing no package

### Requirement: Dependency Staging Consistency

A tool's catalog `deps` MUST stay staged as long as one included tool
still needs them.

#### Scenario: A shared bridge script stays staged

- GIVEN two tools sharing `tools/ps_bridge_onenote.ps1`, and a share build excludes only one
- WHEN the package is built
- THEN the script is still staged, since the other, included tool needs it

### Requirement: Shipped-Tools Manifest With Per-Mode Default-Enabled Flags

Every build MUST emit a manifest listing included tool names, each
with a `default_enabled` flag computed per mode, never a blanket true.
A default build sets it `true` for every tool, regardless of maturity;
a share build sets it per tool to match the final selection
(maturity-seeded, builder-overridable). The installer MUST trust only
`default_enabled`, staying maturity-agnostic.

#### Scenario: Default build's manifest is unconditionally all-enabled

- GIVEN a default build over a mixed-maturity 13-tool catalog
- WHEN the zip is inspected
- THEN every manifest tool is `default_enabled=true`, regardless of maturity

#### Scenario: Share build's manifest mirrors the final selection

- GIVEN a share build whose final selection is 9 of 13 tools
- WHEN the zip is inspected
- THEN the manifest lists exactly those 9, each `default_enabled=true`

### Requirement: Share Package Output Is Isolated From The Pipeline Zip

A share build MUST write its package to a location and name the
pipeline's unattended deploy scripts cannot mistake for their own input.
`deploy-qa.sh`/`promote-pro.sh` resolve their zip via a non-recursive
`dist/WinMCP-*.zip` glob (default build) or an exact filename recorded in
a QA marker; a share build MUST NOT write into that same glob's match set,
and MUST use a name distinct from the default build's
`WinMCP-<YYYYMMDD>.zip` pattern. The default build's output path and name
are unaffected.

#### Scenario: Share build writes outside the pipeline's zip glob

- GIVEN a share build and a same-day full/default build already present in `dist/`
- WHEN the share build completes
- THEN its zip is written under `dist/share/`, a location `dist/WinMCP-*.zip` never matches, under a name distinct from `WinMCP-<YYYYMMDD>.zip`

#### Scenario: Default build's output is unaffected

- GIVEN a default (no-flag) build
- WHEN it completes
- THEN its zip is still written to `dist/WinMCP-<YYYYMMDD>.zip`, exactly as before this requirement existed

### Requirement: Existing Build Gates Unaffected by Build Mode

The pre-existing build gates (test suite, no module-level `win32com`
import, ASCII launchers, `install.ps1` parse, wheels coverage) MUST keep
their current rules regardless of mode or selection.

#### Scenario: Gate sequence still runs under a share build

- GIVEN a share build excluding 2 of 13 tools
- WHEN `make-deploy-package.sh` runs
- THEN gates 1-6 still execute, failing per existing rules on any gate failure
