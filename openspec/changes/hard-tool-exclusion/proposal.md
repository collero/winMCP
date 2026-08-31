# Proposal: Hard Tool Exclusion

## Intent

`selective-tool-deployment` ships every tool's code always; selection
only sets `default_enabled` — a recipient can enable ANY tool via
`config/installed-tools.yaml` or the installer. This is capability
governance, not access control, and must cover two overlapping risks:
confidential business data (mail, calendar, file search, OneNote
writes) and personal data/PII the same tools surface on the
recipient's machine — "code absent" is a data-protection/GDPR
control here, not only a confidentiality one. Share packages need
excluded tools physically absent, not merely off by default.

## Scope

### In Scope
- `make-deploy-package.sh --share`: mark families HARD-EXCLUDED (omit
  modules, family `.ps1` bridges, family-only assets from the zip).
- Import-tolerant `server.py` registration so an absent family doesn't
  break import for the rest.
- `shipped-tools.json`/installer surface only shipped families.
- `tools/catalog.yaml`: exclusion fields (schema decided in design).
- Written limits on what exclusion does NOT protect against.

### Out of Scope
- Full/default build (unaffected, byte-identical, all-inclusive).
- Obfuscation, signing, licensing, runtime sandboxing.
- `smoke-test-coverage`: no spec change needed — `EXPECTED_TOOLS`
  already treats an absent family like a disabled one.

## Capabilities

### New Capabilities
- `hard-tool-exclusion`: family-granularity exclusion, import-safety
  when family files are absent, explicit protection limits.

### Modified Capabilities
- `selective-deploy-packaging`: `--share` gains hard-exclude alongside
  `default_enabled`.
- `selective-install-provisioning`: manifest/installer show only
  shipped families.
- `tool-catalog`: records exclusion granularity, drives omittable files.
- `mcp-server-bootstrap`: registration tolerates an absent family.

## Approach

Exclusion is FAMILY-granular (calendar/task/mail/file/onenote) — a
family's modules are shared internally (e.g. `tasks.py`+
`task_adapter.py` serve both task tools). Shared infra
(`ps_bridge_transport.py`, `settings.py`, `models/schemas.py`,
`errors.py`) always ships.

`server.py` wraps each family's imports + registrations in a
per-family `try/except ImportError`: inert on a full build (identical
to today); on a hard-excluded family, catches the error, registers
zero tools. No server.py rewrite; unit-testable on WSL2 via simulated
absence. `--share` gains an exclude marker; Gate 7 becomes mode-aware
(excluded families' deps verified ABSENT); manifest omits them
entirely.

**DECISION FORK — flagged, not resolved here:**
- **Model A (recommended):** three-tier per family — enabled-by-default
  / optional (shipped, off) / excluded (absent). Keeps today's on/off
  tier; adds exclusion orthogonally.
- **Model B (simpler):** share builds hard-exclude everything not
  selected, repurposing today's checkbox as presence/absence — no
  shipped-but-off tier for share builds. Simpler, but can't ship an
  optional off-by-default family.

## Affected Areas

| Area | Impact |
|---|---|
| `tools/catalog.yaml`, `catalog.py` | Modified — exclusion fields |
| `make-deploy-package.sh` | Modified — exclude selection, omission, Gate 7 |
| `server.py` | Modified — per-family import guard |
| `shipped-tools.json`, `install.ps1` | Modified — shipped-only listing/offer |
| `smoke_test.py`, `deploy-qa.sh`, `promote-pro.sh` | Unaffected |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Recipient obtains a full package elsewhere | Med | Document as an honest, unsolved limit |
| Included tools' code stays fully readable | High (by design) | State: protects *running*, not *reading* |
| Broad-audience build ships a data-touching family by mistake | Med | Pre-select least data-touching set by default; builder opts in |
| `except ImportError` masks a real bug as "absent" | Med | Narrow the guard — design detail |

## Rollback Plan

Additive/config-gated: full/default build stays byte-identical
regardless. Revert by removing the import guards, exclude branch, and
any added catalog/manifest fields — no data migration.

## Dependencies

Builds on `selective-tool-deployment`'s catalog/manifest/gating
machinery. Installer surface is Windows-only; import-guard/packaging
logic testable on WSL2, no COM.

## Success Criteria

- [ ] A share build can hard-exclude a family; its files are absent from the zip
- [ ] `server.py` imports successfully with an excluded family's files absent
- [ ] `shipped-tools.json`/installer never list or offer an excluded family
- [ ] Full/default build remains byte-identical to pre-change output
- [ ] README documents exclusion's explicit protection limits
