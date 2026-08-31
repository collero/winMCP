@echo off
:: WinMCP.bat - launched by Claude Desktop as the MCP server subprocess.
::
:: CRITICAL: this file must print NOTHING to stdout. stdout is the JSON-RPC
:: stdio channel between Claude Desktop and this server; any extra byte on
:: stdout (a banner, a blank line, an "OK" message) corrupts the protocol
:: and Claude Desktop will fail to talk to the server. @echo off suppresses
:: command echoing; every diagnostic below goes to stderr (1>&2) only, and
:: only on the error path (missing .venv) -- the normal path execs Python
:: and prints nothing at all itself.
cd /d "%~dp0"

:: NOTE: no parentheses inside echo lines here -- an unescaped ) inside a
:: parenthesized if-block ends the block early and cmd aborts the whole
:: script with "X was unexpected at this time", killing the MCP handshake.
if not exist ".venv\Scripts\python.exe" (
    echo WinMCP is not installed in this folder. 1>&2
    echo Run install.bat first - double-click it - then restart Claude Desktop. 1>&2
    exit /b 1
)

set PYTHONUTF8=1

".venv\Scripts\python.exe" server.py
