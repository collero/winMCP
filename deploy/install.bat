@echo off
:: install.bat - double-clickable entry point for installing WinMCP.
::
:: Run this ONCE, on the Windows machine, after unzipping the package, from
:: the same folder that contains WinMCP.bat and wheels\. It just hands off
:: to install.ps1 (the real installer) with an execution-policy bypass that
:: affects only this one invocation -- it does NOT change machine policy.
::
:: MARK-OF-THE-WEB WARNING:
::   If this package was downloaded from email/SharePoint/a network share,
::   Windows may have tagged the files with "Mark of the Web" and will
::   refuse to run them. Fix: right-click the zip (before extracting) ->
::   Properties -> tick "Unblock" -> OK, then extract. See README.md.
cd /d "%~dp0"

powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0install.ps1" %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo install.bat: installation did not complete successfully.
    echo See the messages above for details.
)
