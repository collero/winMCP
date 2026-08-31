# Delta for QA-PRO Deploy Workflow

## MODIFIED Requirements

### Requirement: Non-Interactive Windows Installer Invocation

Both scripts MUST invoke the installer via `cmd.exe /c` with an absolute
Windows path, stdin redirected from `/dev/null` — MANDATORY, since the
installer's non-interactive branch (absent a TTY, it skips the
hierarchical family/tool prompt entirely) still ends by exiting after
its final step and would otherwise block on a trailing `Read-Host`
without a redirected stdin. Taking this non-interactive branch MUST
enable every tool shipped in the package (per
selective-install-provisioning's "Non-Interactive Default Installs the
Manifest's Default-Enabled Set" behavior — every tool in a default/full
build's manifest is flagged default-enabled); neither `deploy-qa.sh` nor
`promote-pro.sh` needs to pass any tool-selection argument to get that
outcome.
(Previously: invoking non-interactively only mattered for skipping the
trailing `Read-Host`; there was no tool-selection logic to bypass.)

#### Scenario: Installer completes without blocking

- WHEN either script invokes the installer with no attached TTY
- THEN stdin is redirected from `/dev/null` and it completes without hanging

#### Scenario: Non-interactive invocation enables every shipped tool

- GIVEN a package shipping 9 of the catalog's 13 tools
- WHEN `deploy-qa.sh` or `promote-pro.sh` invokes `install.bat` with stdin from `/dev/null`, exactly as before this change
- THEN `config/installed-tools.yaml` in the installed copy lists all 9 shipped tools, with no code change required in either script to achieve this
