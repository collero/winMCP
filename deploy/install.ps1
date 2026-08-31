# install.ps1 - one-time WinMCP installer for Windows.
#
# Run this AFTER unzipping the WinMCP package, from the same folder that
# contains WinMCP.bat and wheels\ (install.bat double-clicks this for you
# with an execution-policy bypass that affects only that one run).
#
# WHAT THIS DOES:
#   1. Finds a Windows Python 3.12 (or 3.13) interpreter (py launcher, or
#      plain "python" on PATH).
#   2. Creates a private virtual environment at .venv next to this script.
#   3. Installs WinMCP and all its dependencies from the bundled wheels\
#      folder -- no network access required or used.
#   4. Smoke-checks the install (imports server.py, imports win32com.client).
#   5. Prints the exact JSON snippet to paste into Claude Desktop's
#      claude_desktop_config.json.
#
# DEPLOYMENT NOTE: if this package was downloaded from email, SharePoint, or
# a network share, Windows may have tagged it with "Mark of the Web" (MOTW).
# If PowerShell refuses to run this script even via install.bat, right-click
# the zip file (before extracting) -> Properties -> tick "Unblock" -> OK,
# then re-extract. See README.md.

[CmdletBinding()]
param(
    # Path to a preset JSON file listing which tools to enable, e.g.
    # {"tools": ["calendar_search", "file_search"]}. When given, the
    # installer uses this selection unattended -- no prompt, no
    # IsInputRedirected check -- for scripted custom installs
    # (selective-tool-deployment change, design.md Decision 3: -Preset
    # takes priority over everything else). Tool names not present in
    # this package's tools\shipped-tools.json fail the install loudly.
    [string]$Preset
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExitCode = 0
$ok = $true

function Write-Info {
    param([string]$Message)
    Write-Host "  $Message"
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  OK: $Message" -ForegroundColor Green
}

function Write-Err {
    param([string]$Message)
    Write-Host "  ERROR: $Message" -ForegroundColor Red
}

function Find-WindowsPython {
    # Tries, in order: "py -3.12", "py -3.13", then plain "python" on PATH.
    # Returns a hashtable @{ Exe; LauncherArgs; Version } for the first
    # interpreter that answers with version 3.12.x or 3.13.x, or $null if
    # none qualify.
    $candidates = @(
        @{ Exe = 'py'; LauncherArgs = @('-3.12') },
        @{ Exe = 'py'; LauncherArgs = @('-3.13') },
        @{ Exe = 'python'; LauncherArgs = @() }
    )

    foreach ($candidate in $candidates) {
        $cmd = Get-Command $candidate.Exe -ErrorAction SilentlyContinue
        if (-not $cmd) {
            continue
        }

        try {
            $allArgs = @($candidate.LauncherArgs) + @('--version')
            $verOutput = & $candidate.Exe @allArgs 2>&1
            $exitCode = $LASTEXITCODE
        } catch {
            continue
        }
        if ($exitCode -ne 0) {
            continue
        }

        $verText = ($verOutput | Out-String).Trim()
        if ($verText -match 'Python (\d+)\.(\d+)') {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -eq 3 -and ($minor -eq 12 -or $minor -eq 13)) {
                return @{
                    Exe          = $candidate.Exe
                    LauncherArgs = $candidate.LauncherArgs
                    Version      = "$major.$minor"
                }
            }
        }
    }

    return $null
}

$scriptDir = $PSScriptRoot
if ([string]::IsNullOrEmpty($scriptDir)) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
Set-Location $scriptDir

Write-Host ""
Write-Host "  WinMCP installer" -ForegroundColor Cyan
Write-Host "  Install folder: $scriptDir"
Write-Host ""

# ---------------------------------------------------------------------------
# Step 1: locate a Windows Python 3.12/3.13 interpreter.
# ---------------------------------------------------------------------------
$python = $null
if ($ok) {
    Write-Info "Looking for Python 3.12 (or 3.13)..."
    $python = Find-WindowsPython
    if ($null -eq $python) {
        Write-Err "Python 3.12 was not found."
        Write-Host ""
        Write-Host "  Install Python 3.12 from python.org, and make sure to check"
        Write-Host "  'Add python.exe to PATH' during installation. Then run"
        Write-Host "  install.bat again."
        Write-Host ""
        $ok = $false
        $ExitCode = 1
    } else {
        Write-Ok "Found Python $($python.Version) ($($python.Exe) $($python.LauncherArgs -join ' '))"
    }
}

# ---------------------------------------------------------------------------
# Step 2: create .venv next to this script.
# ---------------------------------------------------------------------------
$venvDir = Join-Path $scriptDir '.venv'
if ($ok) {
    Write-Info "Creating virtual environment at $venvDir ..."
    try {
        $venvArgs = @($python.LauncherArgs) + @('-m', 'venv', $venvDir)
        & $python.Exe @venvArgs
        $venvExit = $LASTEXITCODE
    } catch {
        Write-Err "Failed to run the Python venv module: $($_.Exception.Message)"
        $ok = $false
        $ExitCode = 1
        $venvExit = 1
    }
    if ($ok -and $venvExit -ne 0) {
        Write-Err "Creating the virtual environment failed (exit code $venvExit)."
        $ok = $false
        $ExitCode = 1
    } elseif ($ok) {
        Write-Ok "Virtual environment created."
    }
}

$venvPython = Join-Path $venvDir 'Scripts\python.exe'

# ---------------------------------------------------------------------------
# Step 3: install WinMCP + dependencies offline from wheels\.
#
# The venv's own bundled pip/setuptools/wheel is usually recent enough to
# forward --no-index/--find-links into its build-isolation environment, but
# we install setuptools/wheel from the bundled wheels first and pass
# --no-build-isolation explicitly so the offline install does not depend on
# that behavior at all.
# ---------------------------------------------------------------------------
if ($ok) {
    $wheelsDir = Join-Path $scriptDir 'wheels'
    if (-not (Test-Path $wheelsDir)) {
        Write-Err "wheels folder not found at $wheelsDir -- the package looks incomplete."
        $ok = $false
        $ExitCode = 1
    }
}

if ($ok) {
    Write-Info "Installing build tools from bundled wheels (offline)..."
    & $venvPython -m pip install --no-index --find-links $wheelsDir --quiet setuptools wheel
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Could not install setuptools/wheel from the bundled wheels folder."
        $ok = $false
        $ExitCode = 1
    }
}

if ($ok) {
    Write-Info "Installing WinMCP and its dependencies from bundled wheels (offline)..."
    & $venvPython -m pip install --no-index --find-links $wheelsDir --no-build-isolation .
    if ($LASTEXITCODE -ne 0) {
        Write-Err "pip install failed. See the pip output above for details."
        Write-Host ""
        Write-Host "  This usually means a required wheel is missing from wheels\ for"
        Write-Host "  your Python version. Re-build the deployment package or contact"
        Write-Host "  whoever built it."
        Write-Host ""
        $ok = $false
        $ExitCode = 1
    } else {
        Write-Ok "WinMCP installed into .venv"
    }
}

# ---------------------------------------------------------------------------
# Step 4: smoke-check the install.
# ---------------------------------------------------------------------------
if ($ok) {
    Write-Info "Checking that server.py imports cleanly..."
    $serverImportOutput = & $venvPython -c "import server" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Err "server.py failed to import:"
        Write-Host ($serverImportOutput | Out-String)
        $ok = $false
        $ExitCode = 1
    } else {
        Write-Ok "server.py imports cleanly."
    }
}

if ($ok) {
    Write-Info "Checking that win32com.client (Outlook COM bridge) imports cleanly..."
    $win32ImportOutput = & $venvPython -c "import win32com.client" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Err "win32com.client failed to import:"
        Write-Host ($win32ImportOutput | Out-String)
        Write-Host ""
        Write-Host "  pywin32 did not install correctly. WinMCP will not be able to talk"
        Write-Host "  to Outlook. Re-run install.bat, and if it keeps failing, re-build"
        Write-Host "  the deployment package with a wheels\ folder that includes a"
        Write-Host "  pywin32 wheel matching this Python version."
        Write-Host ""
        $ok = $false
        $ExitCode = 1
    } else {
        Write-Ok "win32com.client imports cleanly."
    }
}

# ---------------------------------------------------------------------------
# Step 4b: tool selection (selective-tool-deployment change).
#
# Reads tools\shipped-tools.json (staged by make-deploy-package.sh) and
# resolves which tools to enable, then writes config\installed-tools.yaml
# into the installed copy. The installer is maturity-agnostic: it trusts
# only each tool's `default_enabled` flag from the manifest (never
# `maturity`, which is display-only here) -- design.md Decision 3.
#
# Priority: -Preset (explicit, scripted) > non-interactive default (no
# TTY: enable exactly the manifest's default_enabled=true set, never
# blocks) > interactive hierarchical family->tool prompt.
#
# If tools\shipped-tools.json is missing (an older package predating this
# change), this step is skipped entirely: no selection, no
# installed-tools.yaml written -- current/back-compat behavior exactly
# (server.py/smoke_test.py treat an absent file as "enable everything").
# ---------------------------------------------------------------------------
$manifestPath = Join-Path $scriptDir 'tools\shipped-tools.json'
$manifest = $null
if ($ok -and (Test-Path $manifestPath)) {
    try {
        $manifest = (Get-Content -Path $manifestPath -Raw) | ConvertFrom-Json
    } catch {
        Write-Err "Failed to parse $manifestPath : $($_.Exception.Message)"
        $ok = $false
        $ExitCode = 1
    }
}

if ($ok -and $null -ne $manifest) {
    $allManifestTools = @()
    foreach ($fam in $manifest.families) {
        foreach ($t in $fam.tools) {
            $allManifestTools += $t.name
        }
    }

    $enabledTools = @()

    if (-not [string]::IsNullOrEmpty($Preset)) {
        # ---- Preset mode: explicit, scripted, no prompt. ----
        if (-not (Test-Path $Preset)) {
            Write-Err "Preset file not found: $Preset"
            $ok = $false
            $ExitCode = 1
        } else {
            try {
                $presetObj = (Get-Content -Path $Preset -Raw) | ConvertFrom-Json
            } catch {
                Write-Err "Failed to parse preset file $Preset : $($_.Exception.Message)"
                $ok = $false
                $ExitCode = 1
            }
            if ($ok) {
                $presetNames = @($presetObj.tools)
                foreach ($name in $presetNames) {
                    if ($allManifestTools -notcontains $name) {
                        Write-Err "Preset: unknown tool name '$name' (not in this package's tools\shipped-tools.json)"
                        $ok = $false
                        $ExitCode = 1
                    }
                }
                if ($ok) {
                    $enabledTools = $presetNames
                    Write-Ok "Using preset selection from $Preset ($($enabledTools.Count) tool(s))."
                }
            }
        }
    } elseif ([Console]::IsInputRedirected) {
        # ---- Non-interactive default: manifest's default_enabled set, no prompt, never blocks. ----
        foreach ($fam in $manifest.families) {
            foreach ($t in $fam.tools) {
                if ($t.default_enabled) {
                    $enabledTools += $t.name
                }
            }
        }
        Write-Info "Non-interactive install: enabling this package's default tool set ($($enabledTools.Count) tool(s))."
    } else {
        # ---- Interactive hierarchical family -> tool selection. ----
        Write-Host ""
        Write-Host "  Tool selection" -ForegroundColor Cyan
        Write-Host "  Choose which tools to enable. The [default] shown is this package's"
        Write-Host "  recommended set -- press Enter to accept it, or type your own answer."
        Write-Host ""

        $confirmed = $false
        while (-not $confirmed) {
            $enabledTools = @()
            foreach ($fam in $manifest.families) {
                $famTools = $fam.tools
                $famNames = ($famTools | ForEach-Object { $_.name }) -join ', '
                $famAllDefault = -not @($famTools | Where-Object { -not $_.default_enabled })
                $famNoneDefault = -not @($famTools | Where-Object { $_.default_enabled })
                if ($famAllDefault) {
                    $famDefault = 'y'
                } elseif ($famNoneDefault) {
                    $famDefault = 'n'
                } else {
                    $famDefault = 's'
                }

                Write-Host "  -- family: $($fam.name) ($famNames) --"
                $famAns = Read-Host "     enable ALL tools in this family? [y]es/[n]o/[s]elect individually [$famDefault]"
                if ([string]::IsNullOrEmpty($famAns)) {
                    $famAns = $famDefault
                }
                $famAns = $famAns.Trim().ToLower()

                if ($famAns.StartsWith('y')) {
                    foreach ($t in $famTools) {
                        $enabledTools += $t.name
                    }
                } elseif ($famAns.StartsWith('s')) {
                    foreach ($t in $famTools) {
                        $toolDefault = 'n'
                        if ($t.default_enabled) {
                            $toolDefault = 'y'
                        }
                        while ($true) {
                            $tAns = Read-Host "       enable $($t.name)? [$toolDefault]"
                            if ([string]::IsNullOrEmpty($tAns)) {
                                $tAns = $toolDefault
                            }
                            $tAns = $tAns.Trim().ToLower()
                            if ($tAns -eq 'y') {
                                $enabledTools += $t.name
                                break
                            } elseif ($tAns -eq 'n') {
                                break
                            } else {
                                Write-Host "       please answer y or n"
                            }
                        }
                    }
                } else {
                    # 'n' (or anything else): skip the whole family.
                }
            }

            Write-Host ""
            Write-Host "  Selection summary:" -ForegroundColor Cyan
            if ($enabledTools.Count -eq 0) {
                Write-Host "    (no tools enabled)"
            } else {
                foreach ($name in $enabledTools) {
                    Write-Host "    - $name"
                }
            }
            Write-Host ""
            $confirmAns = Read-Host "  Proceed with this selection? [y]es/[r]edo [y]"
            if ([string]::IsNullOrEmpty($confirmAns) -or $confirmAns.Trim().ToLower().StartsWith('y')) {
                $confirmed = $true
            } else {
                Write-Host ""
                Write-Host "  Restarting tool selection..."
                Write-Host ""
            }
        }
    }

    if ($ok) {
        $configDir = Join-Path $scriptDir 'config'
        if (-not (Test-Path $configDir)) {
            New-Item -ItemType Directory -Path $configDir | Out-Null
        }
        $installedToolsPath = Join-Path $configDir 'installed-tools.yaml'
        $lines = @()
        $lines += '# Written by install.ps1 (selective-tool-deployment). Lists exactly the'
        $lines += '# tools this install has enabled. Delete this file (or clear its list) to'
        $lines += '# fall back to "all tools enabled" (the pre-selective-deploy default).'
        if ($enabledTools.Count -eq 0) {
            $lines += 'tools: []'
        } else {
            $lines += 'tools:'
            foreach ($name in $enabledTools) {
                $lines += "  - $name"
            }
        }
        Set-Content -Path $installedToolsPath -Value $lines -Encoding ASCII
        Write-Ok "Wrote $installedToolsPath ($($enabledTools.Count) tool(s) enabled)."
    }
}

# ---------------------------------------------------------------------------
# Step 5: print the Claude Desktop config snippet.
# ---------------------------------------------------------------------------
if ($ok) {
    $batPath = Join-Path $scriptDir 'WinMCP.bat'
    $jsonPath = $batPath -replace '\\', '\\'

    Write-Host ""
    Write-Host "  Install complete." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Add this to Claude Desktop's claude_desktop_config.json, under"
    Write-Host "  the top-level 'mcpServers' key (merge it in if the file already"
    Write-Host "  has other servers configured), then restart Claude Desktop:"
    Write-Host ""
    Write-Host "  {"
    Write-Host "    ""mcpServers"": {"
    Write-Host "      ""win-mcp"": {"
    Write-Host "        ""command"": ""$jsonPath"""
    Write-Host "      }"
    Write-Host "    }"
    Write-Host "  }"
    Write-Host ""
}

Write-Host ""
Read-Host "Press Enter to exit"
exit $ExitCode
