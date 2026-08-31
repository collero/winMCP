#!/usr/bin/env bash
# make-deploy-package.sh - build the WinMCP Windows deployment ZIP.
#
# Usage:
#   ./make-deploy-package.sh                       # full build (today's behavior): every tool, default_enabled=true for all
#   ./make-deploy-package.sh --share                # share build: interactive family->tool picker, seeded from catalog maturity
#   ./make-deploy-package.sh --share --tools=a,b,c   # share build: explicit tool list, no prompt (works with or without a TTY)
#   ./make-deploy-package.sh --share --no-tui        # share build: force the plain read-loop picker even if whiptail is present
#
# `--tools=` requires `--share` (a full build always ships every tool).
# A `--share` build with no TTY and no `--tools=` FAILS LOUDLY and produces
# no package - it never silently falls back to a maturity-only guess
# (selective-deploy-packaging spec's "A Non-Interactive Share Build
# Requires an Explicit Selection" requirement).
#
# Share builds write their zip to dist/share/ under a distinct name
# (WinMCP-share-<YYYYMMDD>-<HHMMSS>.zip), NOT dist/WinMCP-<YYYYMMDD>.zip -
# deploy-qa.sh/promote-pro.sh resolve their zip via a non-recursive
# `dist/WinMCP-*.zip` glob, which never matches anything under dist/share/.
# This keeps a share build from ever colliding with, or being auto-picked
# up as, the pipeline's own full-build zip. Full-build naming/location is
# unchanged: dist/WinMCP-<YYYYMMDD>.zip.
#
# When `--share` runs at an interactive terminal (no `--tools=`) and
# `whiptail` is available on PATH, tool selection uses a single
# `whiptail --checklist` screen (one row per tool, prefixed "[family]",
# pre-checked from the maturity seed, maturity shown in the description) -
# Cancel aborts the build cleanly (nonzero exit, no zip). Pass `--no-tui`
# to force the older plain per-family/per-tool `read -p` y/n loop instead
# (also the automatic fallback when whiptail is absent). Neither affects
# the non-TTY contracts above.
#
# The zip unpacks to a single WinMCP/ folder containing exactly what the
# Windows machine needs: server.py, tools/, models/, config/, pyproject.toml,
# README.md, the five launcher scripts (install.bat, install.ps1,
# WinMCP.bat, test.bat, smoke_test.py - flattened from deploy/ to the
# package root), and a wheels/ folder with every wheel needed to install
# fully offline. Dev-only files (tests/, .venv/, openspec/, .atl/, build
# artifacts) are never included.
#
# Every tool file is ALWAYS staged regardless of build mode/selection
# (design.md Decision 2: "shipped-but-disabled", never physically omitted -
# this sidesteps any import-breakage risk and keeps the default build
# byte-identical to today). The only thing that varies per mode/selection
# is `tools/shipped-tools.json`, a generated manifest recording each
# catalog tool's `default_enabled` flag that `install.ps1` reads at
# install time (never `maturity` directly - selective-deploy-packaging
# spec's "Shipped-Tools Manifest With Per-Mode Default-Enabled Flags").
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="$ROOT/dist"
STAMP="$(date +%Y%m%d)"
# OUT is resolved once BUILD_MODE is known (see "Resolve output package
# path" below, right before staging) - full builds keep today's
# dist/WinMCP-<STAMP>.zip; share builds write to dist/share/ under a
# distinct name so they can never collide with, or be auto-picked-up as,
# the pipeline's own zip (see header comment above).
VENV_PY="$ROOT/.venv/bin/python3.12"
CATALOG_YAML="$ROOT/tools/catalog.yaml"

fail() { echo "FAIL: $1" >&2; exit 1; }
pass() { echo "PASS: $1"; }

# Every mktemp'd scratch dir/file is registered here and removed on exit
# (replaces the old single-STAGE trap; STAGE/REQDIR/BUILD_TMP all
# accumulate into the same cleanup instead of clobbering each other's trap).
CLEANUP_PATHS=()
cleanup() { rm -rf "${CLEANUP_PATHS[@]}" 2>/dev/null || true; }
trap cleanup EXIT

echo "=== WinMCP deploy package build - build id $STAMP ==="
echo

# ── Build mode: parse --share / --tools= / --no-tui ─────────────────────────
BUILD_MODE="full"
TOOLS_OVERRIDE=""
USE_TUI=1
for arg in "$@"; do
  case "$arg" in
    --share) BUILD_MODE="share" ;;
    --tools=*) TOOLS_OVERRIDE="${arg#--tools=}" ;;
    --no-tui) USE_TUI=0 ;;
    *) fail "unknown argument: $arg (supported: --share, --tools=a,b,c, --no-tui)" ;;
  esac
done
if [[ -n "$TOOLS_OVERRIDE" && "$BUILD_MODE" != "share" ]]; then
  fail "--tools= requires --share (a full/default build always ships every tool)"
fi

# ── Catalog: load tools/catalog.yaml via tools/catalog.py ──────────────────
# TSV rows: family<TAB>name<TAB>maturity<TAB>preselected(0/1), in catalog
# (family-then-tool) order. This is the ONLY place the build reads the
# catalog - everything below (selection, shipped-tools.json, Gate 7) works
# off these bash arrays.
[[ -f "$CATALOG_YAML" ]] || fail "catalog: $CATALOG_YAML not found"
[[ -x "$VENV_PY" ]] || fail "catalog: $VENV_PY not found - create the dev .venv first"
if ! CATALOG_TSV="$(cd "$ROOT" && "$VENV_PY" - "$CATALOG_YAML" <<'PYEOF'
import sys
from tools.catalog import load_catalog, share_preselection

catalog = load_catalog(sys.argv[1])
preselected = share_preselection(catalog)
for e in catalog:
    print(f"{e['family']}\t{e['name']}\t{e['maturity']}\t{1 if e['name'] in preselected else 0}")
PYEOF
)"; then
  fail "catalog: failed to load tools/catalog.yaml via tools/catalog.py"
fi

ALL_TOOL_NAMES=()
FAMILY_ORDER=()
declare -A TOOL_FAMILY TOOL_MATURITY TOOL_PRESELECTED FAMILY_SEEN
while IFS=$'\t' read -r fam name mat presel; do
  [[ -n "$name" ]] || continue
  ALL_TOOL_NAMES+=("$name")
  TOOL_FAMILY["$name"]="$fam"
  TOOL_MATURITY["$name"]="$mat"
  TOOL_PRESELECTED["$name"]="$presel"
  if [[ -z "${FAMILY_SEEN[$fam]:-}" ]]; then
    FAMILY_ORDER+=("$fam")
    FAMILY_SEEN["$fam"]=1
  fi
done <<< "$CATALOG_TSV"
[[ "${#ALL_TOOL_NAMES[@]}" -gt 0 ]] || fail "catalog: tools/catalog.yaml produced zero tools"

# ── Selection: resolve which tools default_enabled=true covers ─────────────
SELECTED_TOOL_NAMES=()
SHARE_INTERACTIVE=0
if [[ "$BUILD_MODE" == "full" ]]; then
  SELECTED_TOOL_NAMES=("${ALL_TOOL_NAMES[@]}")
  echo "build mode: full (default) - all ${#ALL_TOOL_NAMES[@]} tools default_enabled=true"
elif [[ -n "$TOOLS_OVERRIDE" ]]; then
  declare -A _SEEN_OVERRIDE
  IFS=',' read -ra _RAW_TOOLS <<< "$TOOLS_OVERRIDE" || true
  for t in "${_RAW_TOOLS[@]}"; do
    t="$(echo "$t" | xargs)"
    [[ -n "$t" ]] || continue
    [[ -n "${TOOL_FAMILY[$t]:-}" ]] || fail "--tools=: unknown tool name '$t' (not in tools/catalog.yaml; known: ${ALL_TOOL_NAMES[*]})"
    if [[ -z "${_SEEN_OVERRIDE[$t]:-}" ]]; then
      SELECTED_TOOL_NAMES+=("$t")
      _SEEN_OVERRIDE["$t"]=1
    fi
  done
  [[ "${#SELECTED_TOOL_NAMES[@]}" -gt 0 ]] || fail "--tools=: no valid tool names given"
  echo "build mode: share (--tools= explicit list) - ${#SELECTED_TOOL_NAMES[@]} tool(s) default_enabled=true: ${SELECTED_TOOL_NAMES[*]}"
elif [[ -t 0 ]]; then
  SHARE_INTERACTIVE=1
  # newt/whiptail needs a terminfo entry for $TERM; terminals like WezTerm
  # set TERM=wezterm, which the system terminfo db often lacks ("Unknown
  # terminal: wezterm" — live-hit during Phase 9). WezTerm & friends are
  # xterm-compatible, so run the TUI under xterm-256color when $TERM has
  # no entry. If even that entry is missing, skip the TUI entirely.
  TUI_TERM="$TERM"
  if ! infocmp "$TUI_TERM" >/dev/null 2>&1; then
    if infocmp xterm-256color >/dev/null 2>&1; then
      TUI_TERM="xterm-256color"
    else
      USE_TUI=0
    fi
  fi
  if [[ "$USE_TUI" -eq 1 ]] && command -v whiptail >/dev/null 2>&1; then
    echo "build mode: share (interactive, whiptail TUI) - choose which tools default_enabled=true"
    echo "(pre-checked = catalog maturity beta/stable; your answer always wins)"
    CHECKLIST_ITEMS=()
    for fam in "${FAMILY_ORDER[@]}"; do
      for name in "${ALL_TOOL_NAMES[@]}"; do
        [[ "${TOOL_FAMILY[$name]}" == "$fam" ]] || continue
        status="OFF"
        [[ "${TOOL_PRESELECTED[$name]}" == "1" ]] && status="ON"
        CHECKLIST_ITEMS+=("[$fam] $name" "maturity: ${TOOL_MATURITY[$name]}" "$status")
      done
    done
    if WHIPTAIL_OUT="$(TERM="$TUI_TERM" whiptail --title "WinMCP share build - select tools" \
        --checklist $'Space=toggle, Enter=confirm, Esc/Cancel=abort build.\nPre-checked = catalog maturity beta/stable; your choice always wins.' \
        24 78 14 \
        "${CHECKLIST_ITEMS[@]}" \
        3>&1 1>&2 2>&3)"; then
      SELECTION_DONE=1
      if [[ -n "$WHIPTAIL_OUT" ]]; then
        eval "_WHIPTAIL_TAGS=($WHIPTAIL_OUT)"
        for tag in "${_WHIPTAIL_TAGS[@]}"; do
          name="${tag#*] }"
          SELECTED_TOOL_NAMES+=("$name")
        done
      fi
    elif [[ -n "$WHIPTAIL_OUT" ]]; then
      # Nonzero exit WITH output on the answer channel = whiptail itself
      # errored before/without the user (a genuine Cancel/Esc produces an
      # empty answer). Don't abort a human's build over a TUI problem —
      # report it and fall through to the plain y/n picker below.
      echo "WARN: whiptail failed ($WHIPTAIL_OUT) - falling back to the plain y/n picker" >&2
      USE_TUI=0
    else
      fail "share build cancelled at the tool-selection screen - no package produced"
    fi
  fi
  # Plain per-tool y/n picker: runs whenever the whiptail screen did not
  # complete a selection — --no-tui, whiptail absent, no usable terminfo,
  # or a whiptail runtime failure (a genuine user Cancel already aborted
  # above and never reaches here).
  if [[ "${SELECTION_DONE:-0}" -eq 0 ]]; then
    echo "build mode: share (interactive, plain y/n picker) - choose which tools default_enabled=true"
    echo "(pre-checked = catalog maturity beta/stable; your answer always wins)"
    for fam in "${FAMILY_ORDER[@]}"; do
      echo "-- family: $fam --"
      for name in "${ALL_TOOL_NAMES[@]}"; do
        [[ "${TOOL_FAMILY[$name]}" == "$fam" ]] || continue
        default="n"
        [[ "${TOOL_PRESELECTED[$name]}" == "1" ]] && default="y"
        while true; do
          read -r -p "   enable $name (maturity: ${TOOL_MATURITY[$name]})? [$default]: " ans
          ans="${ans:-$default}"
          case "$ans" in
            y|Y) SELECTED_TOOL_NAMES+=("$name"); break ;;
            n|N) break ;;
            *) echo "   please answer y or n" ;;
          esac
        done
      done
    done
  fi
  echo "share selection: ${#SELECTED_TOOL_NAMES[@]}/${#ALL_TOOL_NAMES[@]} tool(s) default_enabled=true: ${SELECTED_TOOL_NAMES[*]:-<none>}"
else
  fail "--share with no TTY and no --tools= given - refusing to guess a selection; pass --tools=a,b,c or run interactively (selective-deploy-packaging spec)"
fi

# ── Generate tools/shipped-tools.json (per-mode manifest) ───────────────────
# Full mode: ALWAYS lists all ${#ALL_TOOL_NAMES[@]} catalog tools, every
# `default_enabled=true`, byte-identical to pre-hard-tool-exclusion output
# (design.md Decision 2/Migration note). Share mode (hard-tool-exclusion
# change): lists ONLY the final selection under the two-tier model - an
# unselected tool (whether from a zero-selected family or a partially-
# selected one) does not appear at all, and a family with zero selected
# tools drops out of "families" entirely (selective-deploy-packaging
# spec's "Shipped-Tools Manifest With Per-Mode Default-Enabled Flags"
# requirement).
BUILD_TMP="$(mktemp -d)"
CLEANUP_PATHS+=("$BUILD_TMP")
SHIPPED_TOOLS_JSON="$BUILD_TMP/shipped-tools.json"
SELECTED_CSV="$(IFS=,; echo "${SELECTED_TOOL_NAMES[*]:-}")"
( cd "$ROOT" && "$VENV_PY" - "$CATALOG_YAML" "$BUILD_MODE" "$SELECTED_CSV" > "$SHIPPED_TOOLS_JSON" <<'PYEOF'
import json
import sys

from tools.catalog import families, load_catalog

catalog_path, build_mode, selected_csv = sys.argv[1], sys.argv[2], sys.argv[3]
selected = set(selected_csv.split(",")) if selected_csv else set()
catalog = load_catalog(catalog_path)
by_name = {e["name"]: e for e in catalog}

if build_mode == "share":
    out_families = []
    for fam, tool_names in families(catalog).items():
        shipped_names = [name for name in tool_names if name in selected]
        if not shipped_names:
            continue
        out_families.append(
            {
                "name": fam,
                "tools": [
                    {
                        "name": name,
                        "maturity": by_name[name]["maturity"],
                        "default_enabled": True,
                    }
                    for name in shipped_names
                ],
            }
        )
else:
    out_families = [
        {
            "name": fam,
            "tools": [
                {
                    "name": name,
                    "maturity": by_name[name]["maturity"],
                    "default_enabled": name in selected,
                }
                for name in tool_names
            ],
        }
        for fam, tool_names in families(catalog).items()
    ]

out = {"build_mode": build_mode, "families": out_families}
json.dump(out, sys.stdout, indent=2)
sys.stdout.write("\n")
PYEOF
) || fail "failed to generate tools/shipped-tools.json"
pass "generated tools/shipped-tools.json ($BUILD_MODE mode, ${#SELECTED_TOOL_NAMES[@]}/${#ALL_TOOL_NAMES[@]} default_enabled=true)"
echo

# ── Excluded files (hard-tool-exclusion): tools/catalog.py::excluded_files()
# ─────────────────────────────────────────────────────────────────────────
# Which catalog-declared dependency files (deps.modules/deps.ps1) the
# staging step below must OMIT: every file whose entire owner set (across
# every family) is outside the final selection (selective-deploy-packaging
# spec's "Dependency Files Are Omitted Only When No Owning Tool Is
# Selected" requirement). Computed unconditionally (cheap, pure, no FS
# writes) - a full build's `selected == ALL_TOOL_NAMES`, so this always
# resolves to the empty set there, matching design.md's byte-identical
# migration guarantee even though the subtraction step below always runs.
EXCLUDED_FILES=()
if ! EXCLUDED_FILES_TSV="$(cd "$ROOT" && "$VENV_PY" - "$CATALOG_YAML" "$SELECTED_CSV" <<'PYEOF'
import sys

from tools.catalog import excluded_files, load_catalog

catalog_path, selected_csv = sys.argv[1], sys.argv[2]
selected = set(selected_csv.split(",")) if selected_csv else set()
catalog = load_catalog(catalog_path)
for f in sorted(excluded_files(catalog, selected)):
    print(f)
PYEOF
)"; then
  fail "catalog: failed to compute excluded_files() via tools/catalog.py"
fi
while IFS= read -r f; do
  [[ -n "$f" ]] || continue
  EXCLUDED_FILES+=("$f")
done <<< "$EXCLUDED_FILES_TSV"
if [[ "$BUILD_MODE" == "share" ]]; then
  echo "share mode: ${#EXCLUDED_FILES[@]} dependency file(s) excluded from staging: ${EXCLUDED_FILES[*]:-<none>}"
  echo
fi

# ── Resolve output package path (BUILD_MODE is now fixed) ──────────────────
# Full builds: today's unchanged dist/WinMCP-<STAMP>.zip (deploy-qa.sh /
# promote-pro.sh's `dist/WinMCP-*.zip` glob is non-recursive, so a
# dist/share/ zip is never matched or auto-picked-up by either script).
# Share builds: a distinct name under dist/share/, timestamped to the
# second so repeated share builds on the same day never collide.
if [[ "$BUILD_MODE" == "share" ]]; then
  SHARE_DIR="$DIST/share"
  OUT="$SHARE_DIR/WinMCP-share-$STAMP-$(date +%H%M%S).zip"
else
  OUT="$DIST/WinMCP-$STAMP.zip"
fi

# ── Manifest ─────────────────────────────────────────────────────────────
# Files staged into the package, relative to $ROOT. tools/*.py and
# models/*.py are discovered dynamically (sorted) so a newly-added runtime
# module is never left out. fake_adapter.py, fake_task_adapter.py, and
# fake_mail_adapter.py are deliberately EXCLUDED: they are test-only
# CalendarPort/TaskPort/MailPort implementations that server.py never
# imports at runtime (confirmed:
# `grep -rn fake_adapter\|fake_task_adapter\|fake_mail_adapter server.py`
# finds nothing) - shipping them would be dead weight, not a functional gap.
MANIFEST=(
  "server.py"
  "pyproject.toml"
  "README.md"
)

while IFS= read -r f; do MANIFEST+=("$f"); done \
  < <(cd "$ROOT" && ls -1 tools/*.py | grep -vxE 'tools/(fake_adapter|fake_task_adapter|fake_mail_adapter)\.py' | sort)

# The PowerShell search bridge is a runtime asset (dumb SQL executor spawned
# by tools/file_search_adapter.py) - it must ship even though it is not *.py.
MANIFEST+=("tools/ps_bridge_search.ps1")

# add-onenote-adapter: the OneNote PowerShell/COM bridge is the same kind of
# runtime asset (dumb op-dispatch executor spawned by tools/onenote_adapter.py
# via the shared PsBridgeTransport) - must ship even though it is not *.py.
MANIFEST+=("tools/ps_bridge_onenote.ps1")

while IFS= read -r f; do MANIFEST+=("$f"); done \
  < <(cd "$ROOT" && ls -1 models/*.py | sort)

if [[ -f "$ROOT/config/settings.yaml" ]]; then
  MANIFEST+=("config/settings.yaml")
fi

# ── STAGED_MANIFEST: MANIFEST minus excluded_files() (hard-tool-exclusion)
# ─────────────────────────────────────────────────────────────────────────
# $MANIFEST itself stays the full, unfiltered source-of-truth list (every
# tool file always exists in the repo, regardless of build mode - that's
# what Gate 1 below now checks per-mode via this derived array).
# $STAGED_MANIFEST is what actually gets copied into the zip: identical to
# $MANIFEST in full mode; $MANIFEST minus $EXCLUDED_FILES in share mode.
STAGED_MANIFEST=("${MANIFEST[@]}")
OMITTED_FROM_STAGING=()
if [[ "$BUILD_MODE" == "share" && "${#EXCLUDED_FILES[@]}" -gt 0 ]]; then
  declare -A _EXCLUDED_SET
  for ex in "${EXCLUDED_FILES[@]}"; do _EXCLUDED_SET["$ex"]=1; done
  STAGED_MANIFEST=()
  for f in "${MANIFEST[@]}"; do
    if [[ -n "${_EXCLUDED_SET[$f]:-}" ]]; then
      OMITTED_FROM_STAGING+=("$f")
      continue
    fi
    STAGED_MANIFEST+=("$f")
  done
fi

# Launchers: staged AT THE PACKAGE ROOT (flattened from deploy/).
LAUNCHERS=(
  "deploy/install.bat:install.bat"
  "deploy/install.ps1:install.ps1"
  "deploy/WinMCP.bat:WinMCP.bat"
  "deploy/test.bat:test.bat"
  "deploy/smoke_test.py:smoke_test.py"
)

# ── Gate 1: every manifest file (and launcher source) that this mode will
# actually stage exists ─────────────────────────────────────────────────────
# Checks $STAGED_MANIFEST (per-mode - excludes an omitted share-mode
# dependency, which never needs to exist for THIS build to succeed),
# never the full unfiltered $MANIFEST.
for f in "${STAGED_MANIFEST[@]}"; do
  [[ -f "$ROOT/$f" ]] || fail "gate 1: missing manifest file: $f"
done
for entry in "${LAUNCHERS[@]}"; do
  src="${entry%%:*}"
  [[ -f "$ROOT/$src" ]] || fail "gate 1: missing launcher source: $src"
done
pass "gate 1: all ${#STAGED_MANIFEST[@]} manifest files + ${#LAUNCHERS[@]} launcher sources exist"
echo

# ── Gate 2: full test suite passes on this host ─────────────────────────────
[[ -x "$VENV_PY" ]] || fail "gate 2: $VENV_PY not found - create the dev .venv first"
if ( cd "$ROOT" && "$VENV_PY" -m pytest -q ); then
  pass "gate 2: full test suite passes"
else
  fail "gate 2: test suite failed - fix before packaging"
fi
echo

# ── Gate 3: win32com is never imported at module level ─────────────────────
# Real `import win32com...` statements must only appear indented (inside a
# function body, e.g. OutlookCalendarAdapter._dispatch_outlook), never at
# column 0. A column-0 match means win32com would be imported at module
# load time, which breaks `import server` (and the whole test suite) on
# this Linux host per the outlook-com-adapter spec's "Lazy COM Import"
# requirement. Docstring/comment mentions of the word "win32com" are fine;
# we only look for actual import statements.
OFFENDERS="$(
  set +e
  grep -nE '^(import win32com|from win32com)' "$ROOT"/server.py "$ROOT"/tools/*.py "$ROOT"/models/*.py 2>/dev/null
  true
)"
if [[ -n "$OFFENDERS" ]]; then
  echo "$OFFENDERS" >&2
  fail "gate 3: module-level win32com import found (see above) - must be lazy/indented"
fi
pass "gate 3: no module-level win32com import (only lazy, indented imports)"
echo

# ── Gate 4: launcher scripts are PURE ASCII ─────────────────────────────────
# Windows PowerShell 5.1 reads a no-BOM .ps1 as the ANSI code page (CP1252),
# not UTF-8. A UTF-8 em-dash/arrow then mis-decodes so a stray byte becomes
# a curly quote, which the tokenizer treats as a string delimiter -
# derailing the parse. Keeping install.bat/install.ps1/WinMCP.bat pure ASCII
# sidesteps this entirely regardless of which code page reads them.
for entry in "${LAUNCHERS[@]}"; do
  src="${entry%%:*}"
  if LC_ALL=C grep -qP '[^\x00-\x7F]' "$ROOT/$src"; then
    LC_ALL=C grep -nP '[^\x00-\x7F]' "$ROOT/$src" >&2
    fail "gate 4: $src contains non-ASCII bytes - mis-parses under Windows PowerShell 5.1"
  fi
done
for ps1 in "tools/ps_bridge_search.ps1" "tools/ps_bridge_onenote.ps1"; do
  if LC_ALL=C grep -qP '[^\x00-\x7F]' "$ROOT/$ps1"; then
    LC_ALL=C grep -nP '[^\x00-\x7F]' "$ROOT/$ps1" >&2
    fail "gate 4: $ps1 contains non-ASCII bytes - mis-parses under Windows PowerShell 5.1"
  fi
done
pass "gate 4: install.bat / install.ps1 / WinMCP.bat / test.bat / smoke_test.py / ps_bridge_search.ps1 / ps_bridge_onenote.ps1 are pure ASCII"
echo

# ── Gate 4b: no unescaped parentheses in .bat echo lines ───────────────────
# An unescaped ) inside a parenthesized if-block ends the block early and
# cmd aborts the whole script at parse time with "X was unexpected at this
# time" (bit us for real: WinMCP.bat's "(double-click it)" killed the MCP
# handshake in Claude Desktop). Escaped ^( ^) are allowed but simplest is
# to avoid parens in echo text entirely.
for entry in "${LAUNCHERS[@]}"; do
  src="${entry%%:*}"
  [[ "$src" == *.bat ]] || continue
  if grep -nE '^[[:space:]]*echo[ .].*[()]' "$ROOT/$src" | grep -vE '\^[()]' | grep -q .; then
    grep -nE '^[[:space:]]*echo[ .].*[()]' "$ROOT/$src" | grep -vE '\^[()]' >&2
    fail "gate 4b: $src has echo line(s) with unescaped parentheses - breaks cmd if-blocks"
  fi
done
pass "gate 4b: no unescaped parentheses in .bat echo lines"
echo

# ── Gate 5: install.ps1 parses cleanly (pwsh resolved independently of any
# one machine's paths) ──────────────────────────────────────────────────────
# Resolution order:
#   1. a system-installed `pwsh` on PATH
#   2. a portable pwsh already cached at $HOME/.local/share/pwsh-portable
#   3. download + install a pinned portable pwsh build to that same cache
#      dir (requires network on the machine running this script)
#   4. if all of the above fail (e.g. offline), warn and SKIP the gate -
#      this is a soft dependency, not a hard requirement to build the package.
PWSH_PORTABLE_DIR="$HOME/.local/share/pwsh-portable"
PWSH_VERSION="7.4.17"
PWSH_URL="https://github.com/PowerShell/PowerShell/releases/download/v${PWSH_VERSION}/powershell-${PWSH_VERSION}-linux-x64.tar.gz"
PWSH=""

if command -v pwsh >/dev/null 2>&1; then
  PWSH="$(command -v pwsh)"
  echo "gate 5: found system pwsh: $PWSH"
elif [[ -x "$PWSH_PORTABLE_DIR/pwsh" ]]; then
  PWSH="$PWSH_PORTABLE_DIR/pwsh"
  echo "gate 5: found cached portable pwsh: $PWSH"
else
  echo "gate 5: no pwsh found (system or cached portable) - attempting to download portable PowerShell $PWSH_VERSION..."
  DL_DIR="$(mktemp -d)"
  DL_TGZ="$DL_DIR/powershell-$PWSH_VERSION-linux-x64.tar.gz"
  if curl -fsSL --retry 2 -o "$DL_TGZ" "$PWSH_URL"; then
    mkdir -p "$PWSH_PORTABLE_DIR"
    if tar -xzf "$DL_TGZ" -C "$PWSH_PORTABLE_DIR"; then
      chmod +x "$PWSH_PORTABLE_DIR/pwsh"
      if "$PWSH_PORTABLE_DIR/pwsh" -NoProfile -Command 1 >/dev/null 2>&1; then
        PWSH="$PWSH_PORTABLE_DIR/pwsh"
        echo "gate 5: downloaded and verified portable pwsh $PWSH_VERSION at $PWSH"
      else
        echo "WARNING: gate 5: downloaded pwsh failed to execute - continuing without it (network may be unavailable)" >&2
      fi
    else
      echo "WARNING: gate 5: failed to extract downloaded pwsh archive - continuing without it (network may be unavailable)" >&2
    fi
  else
    echo "WARNING: gate 5: failed to download portable pwsh - continuing without it (network may be unavailable)" >&2
  fi
  rm -rf "$DL_DIR"
fi

if [[ -n "$PWSH" && -x "$PWSH" ]]; then
  ERRS=$("$PWSH" -NoProfile -Command \
    "\$e=\$null;\$t=\$null;\$null=[System.Management.Automation.Language.Parser]::ParseFile('$ROOT/deploy/install.ps1',[ref]\$t,[ref]\$e);\$e.Count")
  [[ "$ERRS" == "0" ]] || fail "gate 5: install.ps1 has $ERRS parse error(s) - fix before packaging"
  pass "gate 5: install.ps1 parses cleanly (0 errors) via $PWSH"
else
  echo "SKIP: gate 5: no pwsh available (system, cached portable, or download) - skipping .ps1 parse gate"
fi
echo

# ── Stage: copy into a clean WinMCP/ tree, enforcing CRLF on .bat/.ps1 ─────
# Stages $STAGED_MANIFEST (not the full $MANIFEST) so a share build's
# excluded dependency files are never copied into the tree at all
# (selective-deploy-packaging spec's "Dependency Files Are Omitted Only
# When No Owning Tool Is Selected" requirement) - identical to $MANIFEST
# in full mode.
STAGE="$(mktemp -d)"
CLEANUP_PATHS+=("$STAGE")
mkdir -p "$STAGE/WinMCP"
for f in "${STAGED_MANIFEST[@]}"; do
  mkdir -p "$(dirname "$STAGE/WinMCP/$f")"
  cp "$ROOT/$f" "$STAGE/WinMCP/$f"
done
for entry in "${LAUNCHERS[@]}"; do
  src="${entry%%:*}"
  dst="${entry##*:}"
  cp "$ROOT/$src" "$STAGE/WinMCP/$dst"
done
# tools/shipped-tools.json is a per-build generated manifest, not a
# checked-in source file, so it is staged directly here rather than
# through the MANIFEST array's Gate-1 existence check.
cp "$SHIPPED_TOOLS_JSON" "$STAGE/WinMCP/tools/shipped-tools.json"
for s in install.bat install.ps1 WinMCP.bat test.bat; do
  # normalize to CRLF regardless of how the working copy was checked out.
  # Deliberately NOT applied to smoke_test.py: it is a plain Python file
  # (LF is fine on both platforms) and forcing CRLF on it would just be
  # unnecessary churn - this loop stays a fixed .bat/.ps1 list on purpose.
  python3 - "$STAGE/WinMCP/$s" <<'EOF'
import sys
p = sys.argv[1]
data = open(p, 'rb').read().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
open(p, 'wb').write(data)
EOF
done
# ── Build stamp: build-info.json (add-server-info change) ──────────────────
# Read back by the `server_info` MCP tool so a deployment identifies
# ITSELF (package, build UTC, content fingerprint, mode) — requested from
# the cowork debugging mailbox after a round where the client could not
# tell which build was answering. buildId is a content fingerprint:
# sha256 over each staged file's sha256 (sorted by path), truncated to 12
# hex — two packages with identical code get the same id regardless of
# build time. Computed over the STAGED tree AFTER CRLF normalization, so
# it matches what actually ships.
BUILD_ID="$(cd "$STAGE/WinMCP" && find . -type f | sort | xargs sha256sum | sha256sum | cut -c1-12)"
BUILT_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "$STAGE/WinMCP/build-info.json" <<EOF
{"package": "$(basename "$OUT")", "builtUtc": "$BUILT_UTC", "buildId": "$BUILD_ID", "buildMode": "$BUILD_MODE"}
EOF
echo "build stamp: $(basename "$OUT") builtUtc=$BUILT_UTC buildId=$BUILD_ID mode=$BUILD_MODE"

echo "staged $((${#STAGED_MANIFEST[@]} + ${#LAUNCHERS[@]} + 2)) files (incl. tools/shipped-tools.json + build-info.json), CRLF enforced on .bat/.ps1"
if [[ "${#OMITTED_FROM_STAGING[@]}" -gt 0 ]]; then
  echo "share mode: omitted ${#OMITTED_FROM_STAGING[@]} excluded dependency file(s) from staging: ${OMITTED_FROM_STAGING[*]}"
fi
echo

# ── Wheels: build the project's own wheel + download every dependency ──────
# `pip download` (and any resolver) evaluates PEP 508 environment markers
# (e.g. pywin32's `sys_platform == 'win32'`, or keyring's dependency on
# pywin32-ctypes gated the same way) against the HOST interpreter's
# platform, not the --platform flag's target. On this Linux host
# `sys_platform` is "linux", so ANY Windows-only transitive dependency
# hidden behind such a marker would silently evaporate if we resolved
# against "." directly - which is exactly how pywin32-ctypes (needed by
# keyring) went missing before. We sidestep marker evaluation entirely by
# resolving the TRUE Windows dependency closure with `uv pip compile
# --python-platform windows` (which resolves for the target platform, not
# the host), then downloading each pinned "name==version" with --no-deps
# --platform win_amd64 (no marker evaluation happens once deps are pinned
# and --no-deps is passed - this is the crux of the fix).
WHEELS_DIR="$STAGE/WinMCP/wheels"
mkdir -p "$WHEELS_DIR"

echo "Building WinMCP's own wheel..."
# Build isolation is left on here (this is a normal build on the Linux dev
# host, which has network access): pip fetches its own setuptools/wheel
# build backend into a throwaway env as needed. This is unrelated to the
# offline install on the target Windows machine (install.ps1), which uses
# --no-build-isolation against the bundled wheels/ folder instead.
( cd "$ROOT" && "$VENV_PY" -m pip wheel . --no-deps -w "$WHEELS_DIR" ) \
  || fail "could not build the project's own wheel (pip wheel . --no-deps)"
echo

UV_BIN="/home/master/.local/bin/uv"
[[ -x "$UV_BIN" ]] || fail "uv not found at $UV_BIN - required to resolve the true Windows dependency closure"

# setuptools/wheel are NOT project runtime dependencies (they only appear
# in [build-system].requires), so `uv pip compile` on pyproject.toml never
# lists them - but install.ps1 explicitly does
# `pip install --no-index --find-links wheels setuptools wheel` before the
# --no-build-isolation project install, so they must be staged separately.
EXTRA_WHEEL_ONLY_PKGS=(setuptools wheel)

REQDIR="$(mktemp -d)"
CLEANUP_PATHS+=("$REQDIR")
REQ312="$REQDIR/requirements-win312.txt"
REQ313="$REQDIR/requirements-win313.txt"

echo "Resolving true Windows (win_amd64) dependency closure for Python 3.12 via uv..."
( cd "$ROOT" && "$UV_BIN" pip compile pyproject.toml \
    --python-platform windows --python-version 3.12 -o "$REQ312" ) \
  || fail "uv pip compile failed for Python 3.12 - cannot resolve the true Windows dependency closure"
pass "resolved $(grep -cE '^[A-Za-z0-9_.-]+==' "$REQ312") pinned package(s) for cp312/win_amd64"
echo

echo "Resolving true Windows (win_amd64) dependency closure for Python 3.13 via uv (best-effort)..."
if ( cd "$ROOT" && "$UV_BIN" pip compile pyproject.toml \
    --python-platform windows --python-version 3.13 -o "$REQ313" ); then
  echo "cp313 requirements resolved ($(grep -cE '^[A-Za-z0-9_.-]+==' "$REQ313") package(s))."
else
  echo "WARNING: uv pip compile failed for Python 3.13 - continuing without a 3.13-specific pass (312 pass is mandatory)." >&2
  rm -f "$REQ313"
fi
echo

# These downloads use --no-deps against PINNED "name==version" lines, so
# there is no marker re-evaluation left to go wrong. --only-binary=:all:
# means any package with no win_amd64/cp312 wheel (source-only) makes this
# command fail loudly with that package's name in pip's own output, rather
# than silently degrading to a missing wheel caught later by gate 6.
echo "Downloading Windows wheels for Python 3.12 (win_amd64, mandatory pass) from the resolved requirements..."
( cd "$ROOT" && "$VENV_PY" -m pip download \
    -r "$REQ312" \
    --no-deps \
    --dest "$WHEELS_DIR" \
    --platform win_amd64 \
    --python-version 312 \
    --implementation cp \
    --only-binary=:all: ) \
  || fail "pip download of pinned Python 3.12 requirements failed - see the package name in pip's output above (likely no win_amd64/cp312 wheel available)"
echo

echo "Downloading Windows wheels for setuptools/wheel (bootstrap tools install.ps1 installs before --no-build-isolation)..."
( cd "$ROOT" && "$VENV_PY" -m pip download \
    "${EXTRA_WHEEL_ONLY_PKGS[@]}" \
    --no-deps \
    --dest "$WHEELS_DIR" \
    --platform win_amd64 \
    --python-version 312 \
    --implementation cp \
    --only-binary=:all: ) \
  || fail "pip download of setuptools/wheel failed"
echo

if [[ -f "$REQ313" ]]; then
  echo "Downloading Windows wheels for Python 3.13 (win_amd64, best-effort pass) from the resolved requirements..."
  if ( cd "$ROOT" && "$VENV_PY" -m pip download \
      -r "$REQ313" \
      --no-deps \
      --dest "$WHEELS_DIR" \
      --platform win_amd64 \
      --python-version 313 \
      --implementation cp \
      --only-binary=:all: ); then
    echo "cp313 wheels downloaded."
  else
    echo "WARNING: cp313 wheel download failed or incomplete - continuing (312 pass is the mandatory one)." >&2
  fi
  echo
else
  echo "SKIP: no cp313 requirements (uv pip compile for 3.13 failed above) - skipping cp313 wheel download pass." >&2
  echo
fi

WHEEL_COUNT="$(find "$WHEELS_DIR" -maxdepth 1 -type f \( -name '*.whl' -o -name '*.tar.gz' \) | wc -l)"
echo "wheels/ now contains $WHEEL_COUNT distributable file(s)"
echo

# ── Gate 6: wheels coverage ──────────────────────────────────────────────
# Every "name==version" line resolved into the Windows closure (312, plus
# 313 if that pass succeeded) must have a matching staged wheel. Package
# names are normalized per PEP 503 (case-insensitive, runs of -_. treated
# as equivalent) before comparing the requirement name against the wheel
# filename's distribution segment.
[[ "$WHEEL_COUNT" -gt 0 ]] || fail "gate 6: wheels/ is empty after download"

MISSING="$(python3 - "$WHEELS_DIR" "$REQ312" "${REQ313:-}" <<'EOF'
import sys, re, os

def normalize(name):
    return re.sub(r'[-_.]+', '-', name).strip('-').lower()

wheels_dir = sys.argv[1]
req_files = [p for p in sys.argv[2:] if p and os.path.isfile(p)]

required = {}  # normalized name -> original requirement name
for rf in req_files:
    with open(rf) as f:
        for line in f:
            line = line.strip()
            m = re.match(r'^([A-Za-z0-9_.-]+)==', line)
            if m:
                required[normalize(m.group(1))] = m.group(1)

present = set()
for fn in os.listdir(wheels_dir):
    if not fn.endswith('.whl'):
        continue
    dist = fn.split('-')[0]
    present.add(normalize(dist))

for norm, orig in sorted(required.items()):
    if norm not in present:
        print(orig)
EOF
)"
if [[ -n "$MISSING" ]]; then
  echo "$MISSING" >&2
  fail "gate 6: missing wheel(s) for resolved requirement(s): $(echo "$MISSING" | tr '\n' ' ')"
fi
pass "gate 6: every resolved requirement (win312$( [[ -f "$REQ313" ]] && echo "+win313" )) has a matching staged wheel"

# Specifically call out the two packages that were silently dropped by the
# old marker-evaluation bug, IF they are actually part of the resolved
# closure (they legitimately might not be, depending on future dependency
# changes - don't hard-fail on their absence from the closure itself).
for check in "pywin32-ctypes:pywin32_ctypes" "colorama:colorama"; do
  reqname="${check%%:*}"
  wheelprefix="${check##*:}"
  if grep -qiE "^${reqname}==" "$REQ312" 2>/dev/null || { [[ -f "$REQ313" ]] && grep -qiE "^${reqname}==" "$REQ313"; }; then
    WHL="$(find "$WHEELS_DIR" -maxdepth 1 -type f -iname "${wheelprefix}*.whl" | head -1)"
    [[ -n "$WHL" ]] || fail "gate 6: $reqname is in the resolved Windows closure but no matching wheel was staged"
    pass "gate 6: $reqname is in the resolved closure and staged as $(basename "$WHL")"
  else
    echo "  ($reqname not in the resolved closure - nothing to check)"
  fi
done

SETUPTOOLS_WHL="$(find "$WHEELS_DIR" -maxdepth 1 -type f -iname 'setuptools-*.whl' | head -1)"
[[ -n "$SETUPTOOLS_WHL" ]] || fail "gate 6: no setuptools wheel found in wheels/ (required by install.ps1's bootstrap step)"
WHEEL_PKG_WHL="$(find "$WHEELS_DIR" -maxdepth 1 -type f -iname 'wheel-*.whl' | head -1)"
[[ -n "$WHEEL_PKG_WHL" ]] || fail "gate 6: no wheel-package wheel found in wheels/ (required by install.ps1's bootstrap step)"
pass "gate 6: setuptools/wheel bootstrap wheels staged ($(basename "$SETUPTOOLS_WHL"), $(basename "$WHEEL_PKG_WHL"))"

PYWIN32_WHL="$(find "$WHEELS_DIR" -maxdepth 1 -type f -iname 'pywin32*.whl' | head -1)"
[[ -n "$PYWIN32_WHL" ]] || fail "gate 6: no pywin32*.whl found in wheels/"
FASTMCP_WHL="$(find "$WHEELS_DIR" -maxdepth 1 -type f \( -iname 'fastmcp*.whl' -o -iname 'fastmcp*.tar.gz' \) | head -1)"
[[ -n "$FASTMCP_WHL" ]] || fail "gate 6: no fastmcp* wheel/sdist found in wheels/"
pass "gate 6: wheels/ has $WHEEL_COUNT files, including $(basename "$PYWIN32_WHL") and $(basename "$FASTMCP_WHL")"
echo

# ── Gate 7: name-set equality across catalog.yaml / server.py / manifest,
# staged-deps consistency, share-mode excluded-file absence, and a cheap
# import-graph completeness check ───────────────────────────────────────────
# Five checks (tool-catalog spec's "Catalog matches server.py's registered
# tools" scenario, enforced here at build time the same way
# tests/test_catalog.py enforces it at test time; selective-deploy-packaging
# spec's "Gate 7 Verifies Excluded-Dependency Absence" requirement):
#   1. name-set equality between catalog.yaml and server.py's registered
#      @app.tool names -- unconditional, both modes (server.py always
#      declares every catalog tool's @app.tool, regardless of runtime
#      registration gating).
#   2. catalog.yaml vs shipped-tools.json name-set equality -- MODE-AWARE.
#      Full build: unchanged (manifest lists every catalog tool). Share
#      build: manifest now lists ONLY the final selection, so this check
#      compares against $SELECTED_CSV instead of the full catalog.
#   3. every manifest ("shipped") tool's catalog `deps.modules`/`deps.ps1`
#      is present among the files this build actually staged
#      ($STAGED_MANIFEST) -- holds in both modes since $STAGED_MANIFEST
#      already reflects the resolved mode.
#   4. (share mode only) NEGATIVE check: no file in `excluded_files()` (the
#      same owner-set computation used to build $EXCLUDED_FILES above) may
#      appear anywhere among the staged files -- a single stray excluded
#      file fails the gate.
#   5. cheap import-graph completeness: for every catalog-declared
#      dependency module, grep its own column-0 `from tools.X import`/
#      `import tools.X` statements; any referenced tools/*.py file that is
#      itself family-owned (declared as a dep by ANY catalog tool) must
#      also be declared in the SAME tool's own deps.modules -- otherwise a
#      share build selecting that tool alone could physically omit a
#      module its own staged code imports unconditionally. ALSO (hard-
#      tool-exclusion Batch 4, closing verify-report.md WARNING 2): the
#      same completeness check for `.ps1` bridge scripts -- a `.ps1` file
#      is never statically imported, only referenced by a hardcoded
#      `Path(__file__).resolve().parent / "ps_bridge_X.ps1"`-style string
#      literal (e.g. `tools/onenote_adapter.py`'s `_PS_BRIDGE_ONENOTE_
#      SCRIPT`, `tools/file_search_adapter.py`'s `_PS_BRIDGE_SCRIPT`), so
#      it can never fail at import time -- only at runtime (subprocess
#      spawn), on the recipient's machine, in a partial-family share build
#      that omitted an undeclared bridge script. Greps each catalog-
#      declared dependency module's source for `ps_bridge_*.ps1` string
#      references; any such reference that is itself a catalog-tracked
#      bridge script (declared as a dep by ANY catalog tool) must also be
#      declared in the SAME tool's own deps.ps1. Runs unconditionally
#      (mode-independent catalog/source consistency, cheap).
MANIFEST_LIST="$BUILD_TMP/manifest-files.txt"
printf '%s\n' "${STAGED_MANIFEST[@]}" > "$MANIFEST_LIST"
if ! GATE7_OUT="$(cd "$ROOT" && "$VENV_PY" - "$CATALOG_YAML" "$ROOT/server.py" "$SHIPPED_TOOLS_JSON" "$MANIFEST_LIST" "$BUILD_MODE" "$SELECTED_CSV" <<'PYEOF'
import json
import re
import sys

from tools.catalog import excluded_files, load_catalog

catalog_path, server_path, manifest_path, staged_list_path, build_mode, selected_csv = sys.argv[1:7]
selected = set(selected_csv.split(",")) if selected_csv else set()

catalog = load_catalog(catalog_path)
catalog_names = {e["name"] for e in catalog}

server_src = open(server_path, encoding="utf-8").read()
server_names = set(re.findall(r'@app\.tool\(name="([^"]+)"\)', server_src))

manifest = json.load(open(manifest_path, encoding="utf-8"))
manifest_names = {t["name"] for fam in manifest["families"] for t in fam["tools"]}

staged_files = {
    line.strip()
    for line in open(staged_list_path, encoding="utf-8")
    if line.strip()
}

problems = []

# Check 1: catalog vs server.py -- unconditional, both modes.
if catalog_names != server_names:
    problems.append(
        "catalog vs server.py mismatch: "
        f"catalog-only={sorted(catalog_names - server_names)} "
        f"server-only={sorted(server_names - catalog_names)}"
    )

# Check 2: catalog/manifest name-set equality -- mode-aware.
if build_mode == "share":
    if manifest_names != selected:
        problems.append(
            "shipped-tools.json (share mode) does not match the final "
            f"selection: selection-only={sorted(selected - manifest_names)} "
            f"manifest-only={sorted(manifest_names - selected)}"
        )
else:
    if catalog_names != manifest_names:
        problems.append(
            "catalog vs shipped-tools.json mismatch: "
            f"catalog-only={sorted(catalog_names - manifest_names)} "
            f"manifest-only={sorted(manifest_names - catalog_names)}"
        )

# Check 3: every shipped tool's catalog deps are staged.
for entry in catalog:
    if entry["name"] not in manifest_names:
        continue  # unselected/unshipped in this mode -- not this check's concern
    missing = [
        dep
        for dep in (entry["deps"]["modules"] + entry["deps"]["ps1"])
        if dep not in staged_files
    ]
    if missing:
        problems.append(f"{entry['name']}: catalog dep(s) not staged: {missing}")

# Check 4 (share mode only): negative check -- no excluded file leaked into staging.
if build_mode == "share":
    excluded = excluded_files(catalog, selected)
    leaked = sorted(f for f in excluded if f in staged_files)
    if leaked:
        problems.append(f"share mode: excluded file(s) leaked into staging: {leaked}")

# Check 5: cheap import-graph completeness (mode-independent).
all_dep_modules = {f for e in catalog for f in e["deps"]["modules"]}
all_dep_ps1 = {f for e in catalog for f in e["deps"]["ps1"]}
_IMPORT_RE = re.compile(r"^(?:from tools\.(\w+) import|import tools\.(\w+))", re.MULTILINE)
_PS1_REF_RE = re.compile(r"ps_bridge_\w+\.ps1")
for entry in catalog:
    for dep in entry["deps"]["modules"]:
        try:
            dep_src = open(dep, encoding="utf-8").read()
        except OSError:
            continue  # a missing dep file is already reported by Check 3
        for m in _IMPORT_RE.finditer(dep_src):
            ref_mod = m.group(1) or m.group(2)
            ref_path = f"tools/{ref_mod}.py"
            if ref_path == dep or ref_path not in all_dep_modules:
                continue
            if ref_path not in entry["deps"]["modules"]:
                problems.append(
                    f"{entry['name']}: {dep} imports {ref_path} at module "
                    "level, which is catalog-tracked but not declared in "
                    f"{entry['name']}'s own deps.modules -- a partial-family "
                    "share build selecting only this tool could omit a "
                    "module it needs at import time"
                )
        for ps1_name in sorted(set(_PS1_REF_RE.findall(dep_src))):
            ref_ps1 = f"tools/{ps1_name}"
            if ref_ps1 not in all_dep_ps1:
                continue  # not a catalog-tracked bridge script -- e.g. a stray docstring mention
            if ref_ps1 not in entry["deps"]["ps1"]:
                problems.append(
                    f"{entry['name']}: {dep} references {ref_ps1}, which is "
                    "catalog-tracked but not declared in "
                    f"{entry['name']}'s own deps.ps1 -- a partial-family "
                    "share build selecting only this tool could omit a "
                    "bridge script it needs at runtime"
                )

if problems:
    print("\n".join(problems), file=sys.stderr)
    sys.exit(1)
print(
    f"{len(catalog_names)} tool names match across catalog.yaml and server.py; "
    f"shipped-tools.json ({build_mode} mode) is consistent; every shipped "
    "tool's catalog deps are staged; no excluded file leaked into staging; "
    "import-graph completeness OK (modules + .ps1 bridge scripts)"
)
PYEOF
)"; then
  fail "gate 7: mismatch/inconsistency between catalog.yaml / server.py / shipped-tools.json / staged files (see above)"
fi
pass "gate 7: $GATE7_OUT"
echo

# ── Zip it ──────────────────────────────────────────────────────────────────
mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
( cd "$STAGE" && zip -q -r -X "$OUT" . )

# ── Report ──────────────────────────────────────────────────────────────────
OUT_NAME="$(basename "$OUT")"
echo
echo "build id:   $STAMP"
echo "build mode: $BUILD_MODE ($( [[ "$BUILD_MODE" == "full" ]] && echo "all tools default_enabled=true" || echo "${#SELECTED_TOOL_NAMES[@]}/${#ALL_TOOL_NAMES[@]} tools default_enabled=true" ))"
echo "package:    $OUT"
if [[ "$BUILD_MODE" == "share" ]]; then
  echo
  echo "============================================================"
  echo "  SHARE PACKAGE READY: $OUT"
  echo "============================================================"
fi
echo
unzip -l "$OUT"
echo "sha256: $(sha256sum "$OUT" | cut -d' ' -f1)"
echo
echo "Next steps:"
if [[ "$BUILD_MODE" == "share" ]]; then
  echo "  1. Copy $OUT_NAME to the target machine."
else
  echo "  1. Copy the zip to the Windows machine."
fi
echo "  2. Right-click the zip -> Properties -> tick 'Unblock' -> OK"
echo "     (one gesture clears Mark-of-the-Web for the whole package)."
echo "  3. Extract it, e.g. to C:\\WinMCP."
echo "  4. Run install.bat (double-click it) and follow the prompts."
echo "  5. Paste the JSON snippet install.bat prints into Claude Desktop's"
echo "     claude_desktop_config.json (mcpServers section)."
echo "  6. Restart Claude Desktop."

# ── Interactive copy offer (share mode, TTY, genuinely-interactive picker
# only - not --tools=) ───────────────────────────────────────────────────────
# Non-TTY share (--tools=) just prints the path above and never prompts.
if [[ "$BUILD_MODE" == "share" && "$SHARE_INTERACTIVE" -eq 1 && -t 0 ]]; then
  echo
  DEFAULT_COPY_DEST="/mnt/c/usr/tmp"
  read -r -p "Copy $OUT_NAME now to a Windows-visible folder? [y/N]: " COPY_ANS
  case "$COPY_ANS" in
    y|Y)
      read -r -p "Destination directory [$DEFAULT_COPY_DEST]: " COPY_DEST
      COPY_DEST="${COPY_DEST:-$DEFAULT_COPY_DEST}"
      if mkdir -p "$COPY_DEST" && cp "$OUT" "$COPY_DEST/"; then
        WIN_DEST="$COPY_DEST"
        if [[ "$COPY_DEST" =~ ^/mnt/([a-zA-Z])(/.*)?$ ]]; then
          _DRIVE="${BASH_REMATCH[1]}"
          _REST="${BASH_REMATCH[2]}"
          _REST="${_REST//\//\\}"
          WIN_DEST="${_DRIVE^^}:${_REST}"
        fi
        echo "Copied to:    $COPY_DEST/$OUT_NAME"
        echo "Windows path: ${WIN_DEST}\\${OUT_NAME}"
      else
        echo "ERROR: copy to $COPY_DEST failed - package remains at $OUT" >&2
      fi
      ;;
    *)
      echo "Skipped - package remains at $OUT"
      ;;
  esac
fi
