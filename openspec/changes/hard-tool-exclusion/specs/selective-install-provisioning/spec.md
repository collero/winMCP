# Delta for Selective Install Provisioning

**Baseline**: `openspec/changes/selective-tool-deployment/specs/selective-install-provisioning/spec.md`
(pending — selective-tool-deployment is not yet archived, so this delta
modifies THAT pending spec, not a main spec file, which does not exist
yet for this domain). At archive time, both changes' deltas must be
folded together into one new main spec file.

## MODIFIED Requirements

### Requirement: Non-Interactive Default Installs the Manifest's Default-Enabled Set

When stdin is not an interactive terminal (e.g. redirected from
`/dev/null`) or an explicit non-interactive flag/preset is passed, the
installer MUST proceed without prompting and enable exactly the tools
the shipped-tools manifest flags default-enabled. Since a default/full
build's manifest flags every shipped tool default-enabled, this yields
"enable everything shipped" for that package. Under the two-tier
model, a share build's manifest ALSO flags every shipped tool
default-enabled (unselected tools never appear in it at all), so a
non-interactive install of a share package likewise enables everything
that package shipped — there is no longer a shipped-but-disabled
subset for the non-interactive path to skip.
(Previously: only stated the default/full-build case explicitly; a
share build's manifest could carry a mix of true/false flags under the
three-tier model this change replaces.)

#### Scenario: QA/PRO automation is unaffected

- GIVEN `deploy-qa.sh`/`promote-pro.sh` invoke `install.bat` with stdin redirected from `/dev/null`, exactly as before this change, against a default/full-build package
- WHEN the installer runs
- THEN it completes without blocking and enables every tool shipped in the package — outward behavior identical to before this change

#### Scenario: Non-interactive install of a share package enables everything shipped

- GIVEN a share package whose manifest lists 6 tools across 3 families (the rest hard-excluded), installed with stdin redirected from `/dev/null`
- WHEN the installer runs
- THEN it completes without blocking and enables all 6 shipped tools, none left disabled

## ADDED Requirements

### Requirement: Absent Families Never Appear as Empty Prompt Groups

Neither the interactive family-then-tool prompt nor any summary output
MUST show a group, header, or entry for a family with zero tools in
the shipped-tools manifest. Only families with at least one shipped
tool may appear.

#### Scenario: Hard-excluded family produces no prompt artifact

- GIVEN a share package with the `mail` family hard-excluded (absent from the manifest entirely)
- WHEN the installer runs interactively
- THEN no `mail` family header, group, or placeholder appears anywhere in the prompt
