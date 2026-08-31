# Selective Install Provisioning Specification

## Purpose

`install.bat`/`install.ps1` let the operator choose, at install time,
which of the package's shipped tools to enable — via a hierarchical
family-then-tool prompt when run interactively, or a non-blocking
"enable everything shipped" default when run non-interactively (as the
existing QA/PRO automation does). The result is written into the
installed copy as `config/installed-tools.yaml`.

## Requirements

### Requirement: Hierarchical Interactive Selection

When `install.ps1` runs with an interactive stdin (a real console, not
redirected), it MUST offer a family-then-tool selection scoped to the
tools present in the package's shipped-tools manifest, pre-checked
according to each tool's manifest default-enabled flag, with a
per-family "all" shortcut and per-tool toggles.

#### Scenario: Operator selects a subset across families

- GIVEN a package shipping 10 tools across 5 families, all flagged default-enabled per the manifest, run at an interactive console
- WHEN the operator picks "all" for 3 families and deselects one tool within a 4th family
- THEN the resulting selection contains those 3 families in full, the 4th minus the deselected tool, and no tools from the 5th family the operator skipped

### Requirement: Non-Interactive Default Installs the Manifest's Default-Enabled Set

When stdin is not an interactive terminal (e.g. redirected from
`/dev/null`) or an explicit non-interactive flag/preset is passed, the
installer MUST proceed without prompting and enable exactly the tools
the shipped-tools manifest flags default-enabled. Since a default/full
build's manifest flags every shipped tool default-enabled, this yields
"enable everything shipped" for that package — unchanged from before
this change. It MUST NOT block waiting for input.

#### Scenario: QA/PRO automation is unaffected

- GIVEN `deploy-qa.sh`/`promote-pro.sh` invoke `install.bat` with stdin redirected from `/dev/null`, exactly as before this change, against a default/full-build package
- WHEN the installer runs
- THEN it completes without blocking and enables every tool shipped in the package — outward behavior identical to before this change

### Requirement: installed-tools.yaml Written Into the Installed Copy

On completion, whether interactive or non-interactive, the installer
MUST write `config/installed-tools.yaml` into the installation
directory, listing exactly the enabled tool names.

#### Scenario: File reflects an interactive subset

- GIVEN an interactive run that enables 8 of 10 shipped tools
- WHEN `install.ps1` finishes
- THEN `config/installed-tools.yaml` lists exactly those 8 tool names

#### Scenario: File reflects a non-interactive install-all

- GIVEN a non-interactive run over a 10-tool package
- WHEN `install.ps1` finishes
- THEN `config/installed-tools.yaml` lists all 10 shipped tool names

### Requirement: Selection Scoped to Shipped Tools Only

Neither the interactive prompt nor the non-interactive default MUST ever
offer or enable a tool absent from the package's shipped-tools manifest.

#### Scenario: A tool excluded at build time never appears

- GIVEN a package built without one alpha tool
- WHEN the installer runs, interactively or not
- THEN that tool is never offered in the prompt and never appears in `config/installed-tools.yaml`

### Requirement: ASCII / PowerShell 5.1 Compatibility Preserved

Any prompt/selection code added to `install.bat`/`install.ps1` MUST
remain pure ASCII and MUST parse cleanly under PowerShell 5.1, per the
existing packaging gates.

#### Scenario: Updated install.ps1 still passes the packaging gates

- GIVEN the modified `install.ps1`
- WHEN `make-deploy-package.sh`'s ASCII gate and parse gate run
- THEN both still pass
