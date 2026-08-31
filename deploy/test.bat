@echo off
:: test.bat - double-clickable pre-Claude-Desktop smoke test for WinMCP.
::
:: Run this AFTER install.bat has finished, BEFORE configuring Claude
:: Desktop. It launches WinMCP.bat exactly like Claude Desktop would and
:: speaks the MCP handshake to it directly (initialize, tools/list, and a
:: real calendar_search call), so a broken install is caught here instead
:: of showing up as a silent failure inside Claude Desktop.
::
:: NOTE: no parentheses inside echo lines here -- an unescaped ) inside a
:: parenthesized if-block ends the block early and cmd aborts the whole
:: script with "X was unexpected at this time".
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo WinMCP is not installed in this folder. 1>&2
    echo Run install.bat first - double-click it - then run test.bat again. 1>&2
    pause
    exit /b 1
)

".venv\Scripts\python.exe" smoke_test.py

pause
