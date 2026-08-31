# Delta for Tool Catalog

**Baseline**: `openspec/changes/selective-tool-deployment/specs/tool-catalog/spec.md`
(pending — selective-tool-deployment is not yet archived, so this delta
modifies THAT pending spec, not `openspec/specs/tool-catalog/`, which
does not exist yet). At archive time, both changes' deltas must be
folded together into one new main spec file.

## ADDED Requirements

### Requirement: A Dependency File's Retention Is Owner-Set Based

Each catalog `deps.modules`/`deps.ps1` file has an implicit "owner
set": every tool (of any family) whose entry declares it. This owner
set, not family membership, is the basis for a share build's staging
decisions: a file's owner set is derivable by scanning every tool
entry's `deps` for that file. No separate exclusivity constraint is
imposed on the catalog — a file MAY legitimately be declared by tools
in different families, in which case it is retained whenever any one
of its owners is selected, regardless of family boundaries.

#### Scenario: A file's owner set spans exactly the tools declaring it

- GIVEN `tools/ps_bridge_onenote.ps1`, declared in all 4 `onenote` tools' `deps.ps1`
- WHEN its owner set is computed by scanning the catalog
- THEN it is exactly those 4 tool names

#### Scenario: A file declared by tools in different families is retained if either is selected

- GIVEN a hypothetical catalog file declared by one tool in `mail` and one tool in `calendar`
- WHEN a share build selects only the `calendar` tool
- THEN the file's owner set still includes a selected tool, so it is retained

### Requirement: A Family's Minimum Retained Set Is the Union of Its Selected Tools' Deps

Whatever share build's build-side file-selection mechanism, the
`deps.modules`/`deps.ps1` of every SELECTED tool within a family MUST
remain part of the staged set — this is the floor the mechanism must
respect, independent of whether other, unselected tools' exclusive
files are also staged.

#### Scenario: Selected tool's full dependency set is never omitted

- GIVEN a share build selecting `onenote_search` from the 4-tool `onenote` family
- WHEN the build completes
- THEN every file in `onenote_search`'s own `deps.modules`/`deps.ps1` is staged
