#!/usr/bin/env bash
# deploy-qa.sh - install a WinMCP package zip into a disposable QA sandbox
# (C:\usr\WinMCP-qa) for human validation via test.bat, WITHOUT touching the
# live PRO install (C:\usr\WinMCP) or Claude Desktop's config.
#
# Usage:
#   ./deploy-qa.sh [path/to/WinMCP-YYYYMMDD.zip]
#
# With no argument, the newest dist/WinMCP-*.zip (by mtime) is used.
#
# After this script succeeds, a human must double-click test.bat inside
# C:\usr\WinMCP-qa and confirm the family lines (one per smoke-test family) + final verdict, then
# (separately) run ./promote-pro.sh to push the same zip to PRO.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="$ROOT/dist"
QA_ROOT="/mnt/c/usr/WinMCP-qa"
QA_WIN_PATH='C:\usr\WinMCP-qa'

# ── Resolve the zip: explicit arg or newest dist/WinMCP-*.zip by mtime ─────
if [[ $# -ge 1 ]]; then
  ZIP="$1"
  [[ -f "$ZIP" ]] || { echo "ERROR: zip not found: $ZIP" >&2; exit 1; }
else
  ZIP="$(ls -1t "$DIST"/WinMCP-*.zip 2>/dev/null | head -1)"
  [[ -n "$ZIP" ]] || { echo "ERROR: no WinMCP-*.zip in $DIST and no zip argument given" >&2; exit 1; }
fi
ZIP="$(cd "$(dirname "$ZIP")" && pwd)/$(basename "$ZIP")"
ZIP_NAME="$(basename "$ZIP")"
echo "=== deploy-qa.sh: $ZIP_NAME -> $QA_WIN_PATH ==="
echo

# ── Fully wipe any prior QA install (no stale .venv/wheels survive) ────────
mkdir -p "$(dirname "$QA_ROOT")"
echo "Wiping prior QA install at $QA_ROOT (if any)..."
rm -rf "$QA_ROOT"

# ── Extract to a scratch dir colocated with QA_ROOT, then rename ──────────
# The zip's top-level folder is always WinMCP/. Extracting straight into
# QA_ROOT would nest it as WinMCP-qa/WinMCP/, so we unzip to a throwaway
# scratch dir first and mv (rename) WinMCP/ -> WinMCP-qa. Scratch lives next
# to QA_ROOT so the final mv is a same-filesystem rename, not a copy.
SCRATCH="$(mktemp -d "$(dirname "$QA_ROOT")/.winmcp-qa-extract.XXXXXX")"
trap 'rm -rf "$SCRATCH"' EXIT

echo "Extracting $ZIP_NAME to scratch..."
unzip -q "$ZIP" -d "$SCRATCH"
[[ -d "$SCRATCH/WinMCP" ]] || { echo "ERROR: $ZIP_NAME has no top-level WinMCP/ folder - corrupt or wrong package" >&2; exit 1; }

mv "$SCRATCH/WinMCP" "$QA_ROOT"
echo "Extracted -> $QA_ROOT ($QA_WIN_PATH)"
echo

# ── Run the installer non-interactively ────────────────────────────────────
# install.ps1 ends in `Read-Host "Press Enter to exit"`, which blocks
# forever without an attached TTY - redirecting stdin from /dev/null is
# MANDATORY so it reads EOF and returns immediately instead of hanging.
#
# cmd.exe may print a cosmetic "UNC paths are not supported" warning here,
# because WSL invokes it with a \\wsl$\... (UNC) current directory. This is
# harmless: install.bat immediately does `cd /d "%~dp0"` using its own
# script path, so the warning never affects what actually runs. We only
# check the installer's exit code below - the warning text itself is never
# treated as a failure.
echo "Running installer non-interactively: $QA_WIN_PATH\\install.bat"
if ! cmd.exe /c "${QA_WIN_PATH}\\install.bat" < /dev/null; then
  echo "ERROR: installer failed (non-zero exit) for $QA_WIN_PATH\\install.bat - see output above" >&2
  exit 1
fi
echo

# ── Write the QA marker (zip name + sha256) ────────────────────────────────
ZIP_SHA="$(sha256sum "$ZIP" | awk '{print $1}')"
VALIDATED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
MARKER="$QA_ROOT/QA-VALIDATED.txt"
{
  echo "zip: $ZIP_NAME"
  echo "sha256: $ZIP_SHA"
  echo "validated_utc: $VALIDATED_UTC"
} > "$MARKER"
echo "Wrote marker -> $MARKER"
echo

# ── Manual validation instructions ─────────────────────────────────────────
echo "=== deploy-qa.sh complete ==="
echo "PRO (C:\\usr\\WinMCP) and Claude Desktop's config were NOT touched."
echo
echo "NEXT STEP (manual): on the Windows machine, double-click:"
echo "  $QA_WIN_PATH\\test.bat"
echo "and confirm the family lines (calendar/tasks/mail-inbox/mail-sent/mail-drafts)"
echo "plus the final verdict (SMOKE TEST PASSED[/ WITH WARNINGS] / FAILED)."
echo "Only after that passes, run ./promote-pro.sh to push $ZIP_NAME to PRO."
