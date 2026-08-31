"""smoke_test.py - pre-Claude-Desktop smoke test for the WinMCP package.

Run this AFTER install.bat/install.ps1 have finished, BEFORE wiring WinMCP
into Claude Desktop's claude_desktop_config.json. It launches the server
the exact same way Claude Desktop does - as a stdio subprocess of
WinMCP.bat - and speaks the MCP JSON-RPC handshake to it directly, so a
broken install (bad venv, corrupted stdout, missing tools, no Outlook) is
caught here instead of showing up as a silent "server disconnected" in
Claude Desktop.

Stdlib only: subprocess, json, threading, queue, sys, os, re, time,
itertools, collections, argparse, datetime. No third-party imports (in
particular, no `yaml` and no importing `tools/catalog.py` -- see
`_read_installed_tools()`) - this script must run with nothing installed
beyond a plain Python 3.12/3.13 interpreter, since it is meant to work
even if the WinMCP .venv itself is broken.

Exercises one live step per registered tool family (calendar, tasks,
mail-inbox, mail-sent, mail-drafts) via the generic search-then-chain `run_family()`
helper, plus one more live step for the `files` family via the
special-cased `run_files_family()` (file_search/file_get_info don't fit
`run_family()`'s generic entryId-chaining shape - see that function's
docstring), aggregated into a single verdict by the pure
`aggregate_verdict()` - see the smoke-test-coverage spec for the full
per-family/aggregate verdict rules. All of those, plus `format_summary()`,
are unit-tested in `tests/test_smoke_test.py` against a stub server (no
subprocess, no win32com); the rest of this script (the real subprocess
spawn, the real MCP handshake) is manual-verification-only.

Usage (double-clicked via test.bat, or run directly):
    .venv\\Scripts\\python.exe smoke_test.py
    .venv\\Scripts\\python.exe smoke_test.py --command "cmd /c WinMCP.bat"

The optional --command flag overrides how the server subprocess is spawned.
It exists mainly for developing/testing this script itself on a non-Windows
host, e.g.:
    .venv/bin/python3.12 smoke_test.py --command "python3.12 server.py"
"""
import argparse
import itertools
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections import namedtuple
from datetime import datetime

DEFAULT_COMMAND = "cmd /c WinMCP.bat"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "winmcp-smoke-test"
CLIENT_VERSION = "1.0"

# selective-tool-deployment: the full 13-tool set, hardcoded here as the
# fallback used when the deployed copy has no `config/installed-tools.yaml`
# (back-compat with pre-selective-deploy behavior) - this is the same
# literal EXPECTED_TOOLS used before this change.
_DEFAULT_ALL_TOOLS = {
    "calendar_search",
    "calendar_get_event",
    "calendar_get_notes",
    "task_search",
    "task_get_task",
    "mail_search",
    "mail_get_message",
    "mail_write_draft",
    "file_search",
    "file_get_info",
    "onenote_search",
    "onenote_get_page",
    "onenote_list_sections",
    "onenote_list_pages",
    "onenote_create_page",
    "onenote_update_page",
    "server_info",
}

# `config/installed-tools.yaml` sits next to the deployed, flattened-to-
# package-root copy of this script (make-deploy-package.sh's MANIFEST
# stages `deploy/smoke_test.py` as `smoke_test.py` at the package root -
# see that script's Launchers comment), so `config/installed-tools.yaml`
# is a sibling of this file's own directory in the deployed layout.
_INSTALLED_TOOLS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config", "installed-tools.yaml"
)

# Matches a flat YAML list entry line like "  - calendar_search" - the
# same shape tools/settings.py::installed_tools() reads via PyYAML, but
# scraped with stdlib `re` only: this script must stay stdlib-only (see
# module docstring) and must never import `yaml` or `tools/catalog.py`.
_INSTALLED_TOOLS_LINE_RE = re.compile(r"^\s*-\s*(\w+)\s*$", re.MULTILINE)


def _read_installed_tools(path):
    """Stdlib-`re`-only scrape of a flat `tools:` YAML list at `path`
    (mcp-server-bootstrap/smoke-test-coverage deltas, design.md Decision
    6). Returns `None` if `path` doesn't exist - the back-compat sentinel
    meaning "everything" - otherwise the set of `- name` line matches
    found anywhere in the file (an empty list yields an empty set, not
    `None` - that distinction matters: `None` means "no config file at
    all", not "a config file that enables nothing")."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read()
    return set(_INSTALLED_TOOLS_LINE_RE.findall(content))


def _compute_expected_tools(installed):
    """`installed`: `set[str] | None`, as returned by
    `_read_installed_tools()`. `None` -> the full `_DEFAULT_ALL_TOOLS`
    set (today's hardcoded literal, unchanged); otherwise exactly
    `installed` - the smoke-test-coverage delta's "Expected Tool Set
    Matches Registered Tools" requirement."""
    if installed is None:
        return set(_DEFAULT_ALL_TOOLS)
    return set(installed)


# The raw installed-tools source (None or a possibly-narrowed set),
# distinct from EXPECTED_TOOLS below: family-skip logic (run_family()/
# run_files_family()) needs the *raw* None-vs-set distinction ("config
# absent -> never skip any family" vs "config present -> skip a
# zero-enabled family"), which EXPECTED_TOOLS alone can't carry once
# `None` has been coalesced to the full default set.
_INSTALLED_TOOLS = _read_installed_tools(_INSTALLED_TOOLS_PATH)
EXPECTED_TOOLS = _compute_expected_tools(_INSTALLED_TOOLS)

# add-onenote-adapter change: the 5 OneNote tools are deliberately NOT
# added as a live FAMILIES entry here. This script's family-based live
# verification (run_family()) exercises Outlook/file-search tools that are
# always safe to read; OneNote's write tools (onenote_create_page/
# onenote_update_page) touch real notebook content, so their live
# round-trip is verified manually instead, per tasks.md's Phase 11
# ("Manual Verification (Windows host, not CI)") -- deploy-qa.sh's operator
# checks search/get_page live and confirms writes stay limited to the
# configured writable-notebook allowlist by hand.

STEP_TIMEOUT = 20.0
CALL_TIMEOUT = 60.0
# TOTAL_STEPS is computed below, once FAMILIES is defined: 3 fixed steps
# (initialize, notifications/initialized, tools/list) + one per family.

# Substrings (checked case-insensitively) that mark a tools/call failure as
# "Outlook/COM is not available right now" rather than a real MCP plumbing
# bug. Seen in practice: "[outlook_unavailable] win32com is not available
# on this platform".
OUTLOOK_UNAVAILABLE_HINTS = (
    "outlook",
    "win32com",
    "pywin32",
    "com error",
    "com is not available",
)


class StepFailed(Exception):
    """Raised to abort the smoke test with a clear, already-formatted reason."""


def aggregate_verdict(family_results):
    """Pure aggregation (no I/O): any "fail" -> overall FAIL; elif any
    "warning" -> overall WARN; else PASS. `family_results` maps family name
    -> per-family verdict string ("pass"/"warning"/"fail"). The three
    returned strings MUST stay verbatim - test.bat/install docs depend on
    them."""
    verdicts = family_results.values()
    if "fail" in verdicts:
        return "SMOKE TEST FAILED"
    if "warning" in verdicts:
        return "SMOKE TEST PASSED WITH WARNINGS"
    return "SMOKE TEST PASSED"


class ServerProcess:
    """Wraps the spawned MCP server subprocess: newline-delimited JSON-RPC
    writes on stdin, a background reader thread + queue for stdout lines
    (select() does not work on Windows pipes, hence the thread), and a
    separate reader thread that just accumulates stderr for display on
    failure."""

    def __init__(self, argv, cwd):
        self.proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self.stdout_q = queue.Queue()
        self.stderr_lines = []
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stdout(self):
        try:
            for line in self.proc.stdout:
                self.stdout_q.put(line)
        except Exception:
            pass
        self.stdout_q.put(None)  # EOF sentinel

    def _read_stderr(self):
        try:
            for line in self.proc.stderr:
                self.stderr_lines.append(line)
        except Exception:
            pass

    def send(self, message):
        data = json.dumps(message)
        self.proc.stdin.write(data + "\n")
        self.proc.stdin.flush()

    def read_line(self, timeout):
        """Return the next raw stdout line, or None on timeout/EOF."""
        try:
            return self.stdout_q.get(timeout=timeout)
        except queue.Empty:
            return None

    def stderr_tail(self, max_lines=40):
        lines = self.stderr_lines[-max_lines:]
        return "".join(lines)

    def close(self):
        """Close stdin first so a well-behaved server exits on EOF, then
        give it a moment, then escalate to terminate/kill."""
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
            return
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
            return
        except Exception:
            pass
        try:
            self.proc.kill()
            self.proc.wait(timeout=5)
        except Exception:
            pass
        # Best-effort: on Windows, "cmd /c WinMCP.bat" is a process tree
        # (cmd.exe -> python.exe); killing just the cmd.exe pid can leave
        # the python.exe server orphaned and still holding Outlook COM.
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
            except Exception:
                pass


def read_response(server, expected_id, timeout, step_name, first_line_check=False):
    """Read stdout lines until one parses as a JSON-RPC message whose "id"
    matches expected_id. Any non-JSON line is a hard failure - stdout is
    the MCP protocol channel and must never carry anything else."""
    deadline = time.time() + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise StepFailed(
                "timed out after {:.0f}s waiting for a response to '{}'".format(
                    timeout, step_name
                )
            )
        line = server.read_line(remaining)
        if line is None:
            raise StepFailed(
                "timed out after {:.0f}s waiting for a response to '{}' "
                "(server produced no more stdout - it may have exited early; "
                "see stderr below)".format(timeout, step_name)
            )
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            if first_line_check:
                raise StepFailed(
                    "server printed non-protocol output on stdout instead of "
                    "a JSON-RPC response to '{}'. This is the bug class that "
                    "kills Claude Desktop: stdout must carry ONLY newline-"
                    "delimited JSON-RPC messages. Raw line was:\n  {!r}".format(
                        step_name, line
                    )
                )
            raise StepFailed(
                "server printed non-JSON output on stdout while waiting for "
                "'{}'. Raw line was:\n  {!r}".format(step_name, line)
            )
        if isinstance(msg, dict) and msg.get("id") == expected_id:
            return msg
        # Anything else (notifications, out-of-order ids) is ignored and we
        # keep waiting for the response we asked for.
        first_line_check = False


def step_header(n, label):
    print("[{}/{}] {}...".format(n, TOTAL_STEPS, label), end=" ", flush=True)


def step_ok(extra=None):
    print("OK")
    if extra:
        for line in extra:
            print("      {}".format(line))


def do_initialize(server, id_gen):
    step_header(1, "MCP handshake (initialize)")
    call_id = next(id_gen)
    server.send(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        }
    )
    msg = read_response(server, call_id, STEP_TIMEOUT, "initialize", first_line_check=True)
    if "error" in msg:
        raise StepFailed("initialize returned a JSON-RPC error: {}".format(msg["error"]))
    result = msg.get("result") or {}
    server_info = result.get("serverInfo") or {}
    name = server_info.get("name", "<unknown>")
    version = server_info.get("version", "<unknown>")
    step_ok(["server: {} v{}".format(name, version)])

    # notifications/initialized: no response expected, fire-and-forget.
    server.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})


def do_notify_initialized_step():
    step_header(2, "notifications/initialized")
    # Sent as part of do_initialize() above (must follow the initialize
    # response immediately, before any other request); nothing to wait for.
    step_ok()


def do_tools_list(server, id_gen):
    step_header(3, "tools/list")
    call_id = next(id_gen)
    server.send({"jsonrpc": "2.0", "id": call_id, "method": "tools/list", "params": {}})
    msg = read_response(server, call_id, STEP_TIMEOUT, "tools/list")
    if "error" in msg:
        raise StepFailed("tools/list returned a JSON-RPC error: {}".format(msg["error"]))
    result = msg.get("result") or {}
    tools = result.get("tools") or []
    found = {t.get("name") for t in tools if isinstance(t, dict)}
    missing = EXPECTED_TOOLS - found
    extra = found - EXPECTED_TOOLS
    lines = ["found: {}".format(sorted(found) if found else "(none)")]
    if missing:
        raise StepFailed(
            "tools/list is missing expected tool(s): {}. {}".format(
                sorted(missing), lines[0]
            )
        )
    if extra:
        lines.append("note: unexpected extra tool(s) also present: {}".format(sorted(extra)))
    step_ok(lines)


def _today_bounds():
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return start.isoformat(), end.isoformat()


# A tool family driven through the generic search-then-chain helper below:
# `search_tool` is called with `search_args_fn()`'s return value; if it
# returns >=1 hit, `detail_tool` is chained on the first hit's entryId.
Family = namedtuple("Family", "name search_tool search_args_fn detail_tool")


class _FamilyWarning(Exception):
    """Internal signal only (never escapes run_family): a tools/call error
    matched OUTLOOK_UNAVAILABLE_HINTS, so the family degrades to WARN
    instead of FAIL."""


def _call_tool(server, id_gen, tool_name, arguments):
    """Send one tools/call request (with a fresh id from `id_gen`) and
    return its (result_dict, first_text_block) on success. Raises
    `_FamilyWarning` for an Outlook-unavailable-hinted error, `StepFailed`
    for any other error."""
    call_id = next(id_gen)
    server.send(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
    )
    msg = read_response(server, call_id, CALL_TIMEOUT, "tools/call {}".format(tool_name))
    if "error" in msg:
        raise StepFailed(
            "tools/call {} returned a JSON-RPC error: {}".format(tool_name, msg["error"])
        )
    result = msg.get("result") or {}
    content = result.get("content") or []
    text = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
    if bool(result.get("isError")):
        lowered = text.lower()
        if any(hint in lowered for hint in OUTLOOK_UNAVAILABLE_HINTS):
            raise _FamilyWarning("Outlook/COM is not available right now: {}".format(text))
        raise StepFailed("tools/call {} failed: {}".format(tool_name, text))
    return result, text


def _extract_list_result(result, text):
    """Pull the list-of-hits out of a tools/call result: prefer the typed
    structuredContent, fall back to parsing the text block as JSON. Mirrors
    the original do_calendar_search's parsing precedent - a response that
    parses to neither is treated as zero hits, not a hard failure.

    Handles BOTH response shapes search tools can return:
      - the CURRENT envelope (search-result-caps/file-search-resilience
        changes): `MailSearchResult`/`CalendarSearchResult`/
        `TaskSearchResult`/`FileSearchResponse` all serialize to
        `{"results": [...], "resultsTruncated": <bool>}` - the hits live
        under the `results` key, sitting alongside (and never gated on) a
        `resultsTruncated`/`results_truncated` truncation flag this
        function doesn't otherwise care about.
      - the LEGACY pre-envelope shape: a bare `list[...]` return, which
        FastMCP wraps as `structuredContent["result"]` (singular) since a
        bare list isn't itself a JSON object; the text block is a plain
        JSON list too.
    Without this, an envelope response silently yields zero hits (neither
    "results" nor "result" is looked for), degrading every family to a
    false "no items to chain" pass instead of exercising the detail-chain
    call."""
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        if isinstance(structured.get("results"), list):
            return structured["results"]
        if isinstance(structured.get("result"), list):
            return structured["result"]
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and isinstance(parsed.get("results"), list):
            return parsed["results"]
    return []


def _family_enabled(tool_names, installed):
    """`tool_names`: the set of tool names a family exercises.
    `installed`: `set[str] | None`, the same raw source `EXPECTED_TOOLS`
    is derived from (`_INSTALLED_TOOLS` module constant in production).
    `None` (config file absent) means "everything" - a family is always
    enabled. Otherwise a family is enabled iff at least one of its tools
    is in `installed` - the smoke-test-coverage delta's "Per-Family Live
    Checks Scoped to Enabled Families" requirement (a family is only
    skipped when ALL of its tools are disabled)."""
    if installed is None:
        return True
    return bool(tool_names & installed)


def run_family(server, id_gen, family, installed=None):
    """Drive one Family end-to-end: search_tool -> (>=1 hit? chain
    detail_tool on the first hit's entryId : PASS with a "no items to
    chain" note). Returns (verdict, lines); verdict is one of
    "pass"/"warning"/"fail"/"skipped". Never raises - StepFailed/
    _FamilyWarning are caught here and converted, so one broken family
    cannot abort the run.

    `installed`: `set[str] | None` (default `None` - "all families run",
    the config-absent back-compat case). When given and none of this
    family's tools (`search_tool`/`detail_tool`) are in it, the family is
    skipped outright - verdict "skipped", no tools/call ever sent."""
    if not _family_enabled({family.search_tool, family.detail_tool}, installed):
        return "skipped", [
            "family {!r} has zero enabled tools - skipped".format(family.name)
        ]
    try:
        result, text = _call_tool(server, id_gen, family.search_tool, family.search_args_fn())
        hits = _extract_list_result(result, text)
        if not hits:
            return "pass", ["no items to chain (0 hits from {})".format(family.search_tool)]
        first = hits[0]
        entry_id = first.get("entryId") if isinstance(first, dict) else None
        if not entry_id:
            raise StepFailed(
                "{} returned a hit with no entryId to chain: {!r}".format(
                    family.search_tool, first
                )
            )
        _call_tool(server, id_gen, family.detail_tool, {"entryId": entry_id})
        return "pass", [
            "{} hit(s); chained {} on entryId={!r}".format(
                len(hits), family.detail_tool, entry_id
            )
        ]
    except _FamilyWarning as exc:
        return "warning", [str(exc)]
    except StepFailed as exc:
        return "fail", [str(exc)]


# `file_search`'s `filename` filter is a case-insensitive *substring*
# match on `System.FileName` (see the file-search spec's "Search Input
# Parameters" requirement) - NOT a glob, so a "*.ext" pattern would never
# literally match anything. ".lnk" (Windows shortcut files) is broad and
# likely to exist somewhere under a typical user profile (Desktop/Start
# Menu), while still tolerating zero hits like every other family.
FILES_FAMILY_FILENAME_PATTERN = ".lnk"

# Fixed synthetic `scope` for `_check_roots_policy()`'s out-of-root probe -
# not a real path, and never the smoke test's own install directory. The
# install directory used to double as this probe, but that broke once
# `file_search_allowed_roots` became non-empty and could list a root that
# contains the install dir (e.g. `config/settings.yaml` shipping `C:\usr`,
# with WinMCP installed under `C:\usr\WinMCP-qa`): the install dir would
# then fall INSIDE an allowed root and stop being refused. This check now
# assumes only that this fixed path is outside `file_search_allowed_roots`
# - true for any realistic config - and still fails closed if some config
# ever does allow it (e.g. someone allows `C:\` wholesale).
FILES_FAMILY_DENIED_PROBE_SCOPE = "C:\\winmcp-smoke-denied-probe"


def _check_roots_policy(server, id_gen, out_of_root_scope):
    """Deterministic check (design.md-equivalent for this family): a
    `file_search` call with `scope` set to a path outside the configured/
    default `file_search_allowed_roots` MUST be refused with a
    `search_root_not_allowed` tool error, before any adapter call - see
    the file-search spec's "Allowed-Roots Enforcement" requirement.

    This assumes `out_of_root_scope` (the fixed synthetic
    `FILES_FAMILY_DENIED_PROBE_SCOPE`, not the smoke test's own install
    directory - see that constant's comment for why) is outside
    `file_search_allowed_roots` - true for any realistic config, including
    the shipped `config/settings.yaml`.

    Returns `(ok, line)`: `ok` is False for an unexpected success OR an
    error with a different code (either one means the family FAILS);
    `line` is one human-readable string either way. Never raises -
    mirrors `run_family()`'s "one broken check cannot abort the run"
    contract."""
    call_id = next(id_gen)
    server.send(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {
                "name": "file_search",
                "arguments": {"filename": "x", "scope": out_of_root_scope},
            },
        }
    )
    msg = read_response(
        server, call_id, CALL_TIMEOUT, "tools/call file_search (roots-policy check)"
    )
    if "error" in msg:
        return False, (
            "roots-policy check: file_search returned a JSON-RPC error "
            "instead of a tool-level search_root_not_allowed error: {}".format(msg["error"])
        )
    result = msg.get("result") or {}
    content = result.get("content") or []
    text = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
    if not result.get("isError"):
        return False, (
            "roots-policy check: file_search unexpectedly SUCCEEDED for an "
            "out-of-root scope ({!r}) - this check assumes that fixed "
            "synthetic path is outside file_search_allowed_roots".format(
                out_of_root_scope
            )
        )
    if "search_root_not_allowed" not in text:
        return False, (
            "roots-policy check: file_search failed for the out-of-root "
            "scope, but not with search_root_not_allowed: {}".format(text)
        )
    return True, "roots-policy check: out-of-root scope correctly refused ({})".format(text)


def _check_live_index_and_chain(server, id_gen, filename_pattern):
    """Tolerant live-index check: search with a broad `filename` substring
    (no `scope`, so default roots apply) and PASS on 0+ hits, mirroring
    the mail-drafts family's "0 hits is fine" tolerance; on >=1 hit, chain
    `file_get_info` on the first hit's `path` (files carry `path`, not
    `entryId`, so this cannot reuse `run_family()`'s generic chaining).
    Never raises - `_FamilyWarning`/`StepFailed` from `_call_tool()` are
    caught and converted, same as `run_family()`."""
    try:
        result, text = _call_tool(
            server, id_gen, "file_search", {"filename": filename_pattern}
        )
    except _FamilyWarning as exc:
        return "warning", [str(exc)]
    except StepFailed as exc:
        return "fail", [str(exc)]
    hits = _extract_list_result(result, text)
    if not hits:
        return "pass", [
            "no items to chain (0 hits from file_search filename={!r})".format(
                filename_pattern
            )
        ]
    first = hits[0]
    path = first.get("path") if isinstance(first, dict) else None
    if not path:
        return "fail", [
            "file_search returned a hit with no path to chain: {!r}".format(first)
        ]
    try:
        _call_tool(server, id_gen, "file_get_info", {"path": path})
    except _FamilyWarning as exc:
        return "warning", [str(exc)]
    except StepFailed as exc:
        return "fail", [str(exc)]
    return "pass", [
        "{} hit(s); chained file_get_info on path={!r}".format(len(hits), path)
    ]


def run_files_family(
    server,
    id_gen,
    out_of_root_scope,
    filename_pattern=FILES_FAMILY_FILENAME_PATTERN,
    installed=None,
):
    """Drive the `files` family: two checks combined into one verdict.

    1. `_check_roots_policy()` - deterministic; must fail closed on an
       out-of-root `scope`. If this check itself fails (unexpected
       success, or the wrong error code), the family FAILS outright and
       the live-index check below is never attempted.
    2. `_check_live_index_and_chain()` - tolerant; 0+ hits is a PASS, >=1
       hit chains `file_get_info`.

    Returns `(verdict, lines)` exactly like `run_family()`. Never raises.

    `installed`: same contract as `run_family()`'s - `None` (default)
    means "always run"; otherwise the family is skipped (verdict
    "skipped", no tools/call sent) when neither `file_search` nor
    `file_get_info` is enabled."""
    if not _family_enabled({"file_search", "file_get_info"}, installed):
        return "skipped", ["family 'files' has zero enabled tools - skipped"]
    roots_ok, roots_line = _check_roots_policy(server, id_gen, out_of_root_scope)
    if not roots_ok:
        return "fail", [roots_line]
    live_verdict, live_lines = _check_live_index_and_chain(server, id_gen, filename_pattern)
    return live_verdict, [roots_line] + live_lines


# One entry per registered tool family. `search_args_fn` is called fresh
# for each run (so "today"/date-bound args reflect the current time), and
# each mail family passes its own folder plus a today-bounded date filter,
# per the smoke-test-coverage spec's "Per-Family Live Steps" requirement.
FAMILIES = (
    Family(
        name="calendar",
        search_tool="calendar_search",
        search_args_fn=lambda: dict(zip(("from", "to"), _today_bounds())),
        detail_tool="calendar_get_event",
    ),
    Family(
        name="tasks",
        search_tool="task_search",
        search_args_fn=lambda: {},
        detail_tool="task_get_task",
    ),
    Family(
        name="mail-inbox",
        search_tool="mail_search",
        search_args_fn=lambda: dict(
            folder="inbox", **dict(zip(("dateFrom", "dateTo"), _today_bounds()))
        ),
        detail_tool="mail_get_message",
    ),
    Family(
        name="mail-sent",
        search_tool="mail_search",
        search_args_fn=lambda: dict(
            folder="sent", **dict(zip(("dateFrom", "dateTo"), _today_bounds()))
        ),
        detail_tool="mail_get_message",
    ),
    Family(
        name="mail-drafts",
        search_tool="mail_search",
        search_args_fn=lambda: dict(
            folder="drafts", **dict(zip(("dateFrom", "dateTo"), _today_bounds()))
        ),
        detail_tool="mail_get_message",
    ),
)

# 3 fixed handshake steps (initialize, notifications/initialized,
# tools/list) + one live step per FAMILIES entry + 1 for the
# special-cased `files` family (run_files_family(), not in FAMILIES).
TOTAL_STEPS = 3 + len(FAMILIES) + 1


def step_result(verdict, lines):
    """Print a family step's outcome using the same OK/WARNING/FAILED +
    indented-extra-lines shape as step_ok()'s existing convention."""
    if verdict == "fail":
        print("FAILED")
    elif verdict == "warning":
        print("WARNING")
    else:
        print("OK")
    for line in lines:
        print("      {}".format(line))


def format_summary(family_results, overall):
    """Pure (no I/O): render one line per family plus the final verdict
    line last, per the smoke-test-coverage spec's "Human-Eyeball-Friendly
    Output" requirement. `family_results` maps family name -> verdict
    string; `overall` is aggregate_verdict()'s return value."""
    lines = [
        "  {}: {}".format(name, verdict.upper()) for name, verdict in family_results.items()
    ]
    lines.append(overall)
    return "\n".join(lines)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Pre-Claude-Desktop smoke test for the WinMCP MCP server."
    )
    parser.add_argument(
        "--command",
        default=DEFAULT_COMMAND,
        help=(
            "override the command used to spawn the server "
            "(default: {!r}). Split on whitespace, no quoting/escaping "
            "supported - keep it simple.".format(DEFAULT_COMMAND)
        ),
    )
    return parser.parse_args(argv)


def _force_utf8_own_stdio():
    """Best-effort: reconfigure this script's own stdout/stderr to UTF-8.
    Without this, a Windows console's legacy codepage can re-mangle the
    correctly UTF-8-decoded accented subjects (from the server subprocess)
    when THIS script prints them for a human to read - a separate concern
    from decoding the subprocess pipe (already done via
    encoding="utf-8"/errors="replace" on the Popen call above). Guarded so
    it never raises if the stream does not support reconfigure."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass


def main(argv=None):
    _force_utf8_own_stdio()
    args = parse_args(argv)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    argv_cmd = args.command.split()
    if not argv_cmd:
        print("FAILED: empty --command", file=sys.stderr)
        return 1

    print("WinMCP smoke test")
    print("  working directory: {}".format(script_dir))
    print("  spawn command:     {}".format(" ".join(argv_cmd)))
    print()

    try:
        server = ServerProcess(argv_cmd, cwd=script_dir)
    except OSError as exc:
        print("FAILED: could not launch {!r}: {}".format(argv_cmd, exc), file=sys.stderr)
        return 1

    id_gen = itertools.count(1)
    try:
        do_initialize(server, id_gen)
        do_notify_initialized_step()
        do_tools_list(server, id_gen)
    except StepFailed as exc:
        # Handshake failure bypasses families and FAILS outright - the
        # families below assume a working MCP connection.
        print("FAILED")
        print()
        print("Reason: {}".format(exc))
        stderr_tail = server.stderr_tail()
        if stderr_tail.strip():
            print()
            print("---- server stderr (tail) ----")
            print(stderr_tail.rstrip())
            print("-------------------------------")
        server.close()
        print()
        print("SMOKE TEST FAILED")
        return 1

    family_results = {}
    for step_n, family in enumerate(FAMILIES, start=4):
        step_header(
            step_n, "tools/call {} (family: {})".format(family.search_tool, family.name)
        )
        verdict, lines = run_family(server, id_gen, family, installed=_INSTALLED_TOOLS)
        family_results[family.name] = verdict
        step_result(verdict, lines)

    files_step_n = 4 + len(FAMILIES)
    step_header(files_step_n, "tools/call file_search (family: files)")
    files_verdict, files_lines = run_files_family(
        server, id_gen, FILES_FAMILY_DENIED_PROBE_SCOPE, installed=_INSTALLED_TOOLS
    )
    family_results["files"] = files_verdict
    step_result(files_verdict, files_lines)

    server.close()
    overall = aggregate_verdict(family_results)
    print()
    print(format_summary(family_results, overall))
    return 0 if overall != "SMOKE TEST FAILED" else 1


if __name__ == "__main__":
    sys.exit(main())
