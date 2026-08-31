#!/usr/bin/env bash
# promote-pro.sh - promote a QA-validated WinMCP package zip to the live
# PRO install (C:\usr\WinMCP). Refuses to run while Claude Desktop still
# has WinMCP's PRO venv python.exe alive, and refuses to promote a zip that
# doesn't match what deploy-qa.sh's QA-VALIDATED.txt recorded (unless
# --force is passed).
#
# Usage:
#   ./promote-pro.sh [path/to/WinMCP-YYYYMMDD.zip] [--force]
#
# With no zip argument, the zip named in C:\usr\WinMCP-qa\QA-VALIDATED.txt
# is used (resolved against dist/). --force overrides the sha256-mismatch
# refusal; it does NOT override the live-process lock gate - that one is
# unconditional.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="$ROOT/dist"
QA_ROOT="/mnt/c/usr/WinMCP-qa"
INSTALL_ROOT="/mnt/c/usr"
PRO_DIR="$INSTALL_ROOT/WinMCP"
PRO_WIN_PATH='C:\usr\WinMCP'
ONEDRIVE_OUT="/mnt/c/co/od/_DEV/WinMCP/_OUT"

# ── Parse args: an optional zip path/name, and an optional --force flag ────
FORCE=0
ZIP_ARG=""
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    *) ZIP_ARG="$arg" ;;
  esac
done

# ── Read the QA marker (required: nothing is promoted without a QA run) ───
MARKER="$QA_ROOT/QA-VALIDATED.txt"
[[ -f "$MARKER" ]] || {
  echo "ERROR: no $MARKER found - run ./deploy-qa.sh and validate via test.bat first" >&2
  exit 1
}
MARKER_ZIP="$(sed -n 's/^zip: //p' "$MARKER")"
MARKER_SHA="$(sed -n 's/^sha256: //p' "$MARKER")"
[[ -n "$MARKER_ZIP" && -n "$MARKER_SHA" ]] || {
  echo "ERROR: $MARKER is malformed (missing zip/sha256 fields)" >&2
  exit 1
}

# ── Resolve the zip: explicit arg, or the marker's zip resolved in dist/ ──
if [[ -n "$ZIP_ARG" ]]; then
  ZIP="$ZIP_ARG"
  [[ -f "$ZIP" ]] || { echo "ERROR: zip not found: $ZIP" >&2; exit 1; }
else
  ZIP="$DIST/$MARKER_ZIP"
  [[ -f "$ZIP" ]] || { echo "ERROR: QA-validated zip not found at $ZIP (expected from marker: $MARKER_ZIP)" >&2; exit 1; }
fi
ZIP="$(cd "$(dirname "$ZIP")" && pwd)/$(basename "$ZIP")"
ZIP_NAME="$(basename "$ZIP")"
ZIP_SHA="$(sha256sum "$ZIP" | awk '{print $1}')"

echo "=== promote-pro.sh: $ZIP_NAME -> $PRO_WIN_PATH ==="
echo

# ── Refuse a zip that doesn't match what QA actually validated ────────────
if [[ "$ZIP_SHA" != "$MARKER_SHA" ]]; then
  if [[ "$FORCE" -eq 1 ]]; then
    echo "WARNING: $ZIP_NAME's sha256 does not match $MARKER (validated: $MARKER_ZIP / $MARKER_SHA)." >&2
    echo "WARNING: --force given - promoting an UN-QA-validated zip anyway." >&2
  else
    echo "ERROR: $ZIP_NAME's sha256 ($ZIP_SHA) does not match the QA-validated zip recorded in $MARKER" >&2
    echo "ERROR:   validated zip:   $MARKER_ZIP" >&2
    echo "ERROR:   validated sha256: $MARKER_SHA" >&2
    echo "ERROR: only what QA validated may be promoted. Re-run deploy-qa.sh + test.bat, or pass --force." >&2
    exit 1
  fi
fi

# ── HARD lock gate: refuse while PRO's venv python.exe is still running ───
# Claude Desktop keeps WinMCP's PRO server (python.exe under
# C:\usr\WinMCP\.venv) alive as a subprocess for as long as it's running.
# Overwriting files or reinstalling the venv underneath a live process is
# unsafe, so this gate is unconditional - NOT overridden by --force.
echo "Checking for a live PRO process (C:\\usr\\WinMCP\\.venv\\*)..."
# Single-quoted: bash passes this through byte-for-byte, so the backslashes
# below are exactly what PowerShell sees. PowerShell's -like does NOT treat
# backslash as an escape character (that's a Windows path separator here,
# not a regex/escape token), so a single backslash per separator is correct.
PS_QUERY='Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like "C:\usr\WinMCP\.venv\*" } | Select-Object -ExpandProperty ProcessId'
if ! LOCK_OUT="$(powershell.exe -NoProfile -NonInteractive -Command "$PS_QUERY" 2>&1)"; then
  echo "ERROR: failed to query Windows processes via powershell.exe Get-CimInstance - aborting promotion" >&2
  echo "$LOCK_OUT" >&2
  exit 1
fi
LOCK_PIDS="$(printf '%s\n' "$LOCK_OUT" | tr -d '\r' | grep -E '^[0-9]+$' || true)"
if [[ -n "$LOCK_PIDS" ]]; then
  echo "ERROR: WinMCP PRO is still running (python.exe PID(s): $(printf '%s' "$LOCK_PIDS" | tr '\n' ' ')) under C:\\usr\\WinMCP\\.venv" >&2
  echo "ERROR: quit Claude Desktop (it launches the PRO MCP server) and try again." >&2
  exit 1
fi
echo "No live PRO process found - safe to promote."
echo

# ── Extract onto PRO, preserving .venv, replacing wheels/ ─────────────────
# Same mechanics as the retired dist/deploy.sh: the zip's top-level WinMCP/
# folder matches C:\usr\WinMCP exactly, so unzip -o overwrites app files
# in place and leaves an existing .venv/ untouched. wheels/ is fully
# replaced first so a wheel dropped from the new package doesn't linger.
mkdir -p "$INSTALL_ROOT"
echo "Wiping $PRO_DIR/wheels..."
rm -rf "$PRO_DIR/wheels"
echo "Extracting $ZIP_NAME onto $PRO_DIR ($PRO_WIN_PATH)..."
unzip -q -o "$ZIP" -d "$INSTALL_ROOT"
echo

# ── Run the installer non-interactively ────────────────────────────────────
# Same stdin/UNC-warning rules as deploy-qa.sh: stdin MUST be redirected
# from /dev/null so install.ps1's trailing Read-Host doesn't hang, and any
# cosmetic UNC-cwd warning from cmd.exe is not treated as a failure - only
# the installer's own exit code decides success.
echo "Running installer non-interactively: $PRO_WIN_PATH\\install.bat"
if ! cmd.exe /c "${PRO_WIN_PATH}\\install.bat" < /dev/null; then
  echo "ERROR: installer failed (non-zero exit) for $PRO_WIN_PATH\\install.bat - see output above" >&2
  exit 1
fi
echo

# ── Copy the zip to the OneDrive _OUT audit folder ─────────────────────────
mkdir -p "$ONEDRIVE_OUT"
cp "$ZIP" "$ONEDRIVE_OUT/"
echo "Copied $ZIP_NAME -> $ONEDRIVE_OUT/"

# ── Write the PRO deployment marker (zip name + sha256 + UTC date) ────────
DEPLOYED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DEPLOYED_MARKER="$PRO_DIR/DEPLOYED.txt"
{
  echo "zip: $ZIP_NAME"
  echo "sha256: $ZIP_SHA"
  echo "deployed_utc: $DEPLOYED_UTC"
} > "$DEPLOYED_MARKER"
echo "Wrote marker -> $DEPLOYED_MARKER"
echo

# ── Restart reminder ────────────────────────────────────────────────────────
echo "=== promote-pro.sh complete ==="
echo "$ZIP_NAME is now live at $PRO_WIN_PATH."
echo
echo "NEXT STEP (manual): restart Claude Desktop to pick up the new PRO install."
