# Proposal: Selective Tool Deployment

## Intent

WinMCP ships all 13 tools unconditionally today. Some are
alpha-quality. Need two-step selection: build-time — pick tools for
the deploy zip; install-time — on Windows, pick which shipped tools
to enable, defaulting away from alpha.

## Scope

### In Scope
- `tools/catalog.yaml`: name, family, maturity (alpha/beta/stable),
  deps — read by `make-deploy-package.sh` (build) and `install.ps1`
  (install).
- Build-time selection in `make-deploy-package.sh`: stage chosen
  tools; default excludes alpha; emit a shipped-tools manifest.
- Install-time selection in `install.bat`/`install.ps1`: hierarchical
  family→tool prompt; non-interactive mode (flag/preset) defaults to
  "enable everything shipped", keeping `deploy-qa.sh`/`promote-pro.sh`
  unattended and never blocking on stdin. Writes
  `config/installed-tools.yaml` into the installed copy.
- `server.py`: config-driven registration from that installed-tools
  file; absent = register all (back-compat).
- `smoke_test.py`: derive `EXPECTED_TOOLS` from that same file.

### Out of Scope
GUI wizard beyond text prompts; licensing checks; automated
alpha-to-stable promotion; per-selection test runs (full suite still
runs on the whole repo).

## Capabilities

### New Capabilities
- `tool-catalog`: name/family/maturity/deps; feeds packaging,
  install, registration, smoke test.
- `selective-deploy-packaging`: build-time include/exclude by catalog
  + maturity default; writes shipped-tools manifest.
- `selective-install-provisioning`: hierarchical selection against
  the manifest; non-interactive fallback installs everything.

### Modified Capabilities
- `mcp-server-bootstrap`: registration reads installed-tools file.
- `smoke-test-coverage`: `EXPECTED_TOOLS` computed, not hardcoded.
- `qa-pro-deploy-workflow`: pass "install everything" through
  non-interactively; behavior unchanged.

## Affected Areas

| Area | Impact |
|---|---|
| `tools/catalog.yaml` (new) | Source of truth |
| `make-deploy-package.sh` | Selection + manifest |
| `install.bat`, `install.ps1` | Selection UI, non-interactive preset, writes installed-tools file |
| `server.py` | Config-driven registration |
| `smoke_test.py` | Derived `EXPECTED_TOOLS` |
| `deploy-qa.sh`, `promote-pro.sh`, `README.md` | Pass "install all" through; document catalog |

## Risks

| Risk | Mitigation |
|---|---|
| Excluding a module breaks static imports (High) | Gate registration, not import — lazy-adapter seam keeps imports side-effect-free |
| Non-interactive installer regresses QA/PRO (Med) | Default "install all"; both scripts smoke-tested here |
| Catalog drifts from real tools (Med) | One file feeds all surfaces; smoke test fails loudly |

## Rollback Plan

Config-gated, additive: absent `config/installed-tools.yaml` keeps
`server.py`/`smoke_test.py` as today. Revert by deleting
`tools/catalog.yaml` and the added code in `make-deploy-package.sh`,
`install.ps1`, `server.py`, `smoke_test.py` — no data migration.

## Dependencies

Windows-runtime only: the selection UI and `installed-tools.yaml`
matter only on Windows. Catalog parsing, packaging selection, and
registration are testable on Linux dev/CI (WSL2) via the existing
fake-adapter pattern — no COM/win32com involved.

## Success Criteria

- [ ] Catalog lists all 13 tools, matching `server.py`
- [ ] Package build can exclude a tool; manifest reflects it
- [ ] Installer offers hierarchical selection plus a non-blocking "install all" path
- [ ] `server.py`/`smoke_test.py` read the installed-tools file (all when absent); `pytest -q` passes
