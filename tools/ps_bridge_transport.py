"""PsBridgeTransport — the use-case-agnostic PowerShell-bridge transport
shared by every adapter that talks to a pinned Windows PowerShell 5.1
child process (`file_search_adapter.py`'s `PowerShellSearchBridge` today,
`onenote_adapter.py`'s `OneNoteAdapter` from day one — see design.md's
"Extract shared PS-bridge transport" decision).

Owns everything about the CHILD-PROCESS PLUMBING: spawning a pinned,
absolute `powershell.exe` 5.1 with `-NoProfile -NonInteractive
-ExecutionPolicy Bypass -File`, writing a single JSON request to its
stdin and closing it (the dumb-executor contract — the deployed `.ps1`
script never receives caller values via argv or a `-Command`/
`-EncodedCommand` string), reading its stdout INCREMENTALLY as JSON Lines
off a background reader thread under an overall wall-clock deadline, the
truncation-vs-corruption distinction (a stream cut short mid-record is a
RESULT, not an error; a complete-but-invalid line that is NOT the last
line is genuine corruption), the `{"done": true}` sentinel, the
`(exit: ...; stderr: ...)` diagnostic suffix, and a config-gated generic
debug-log hook.

Ported, near-verbatim, out of `tools/file_search_adapter.py`'s
`PowerShellSearchBridge._invoke_impl` (bridge-streaming-hotfix/
ps-bridge-jsonl-hotfix/BUG-006/BUG-007's battle-hardened implementation)
— see design.md's Decision 1: two independent copies of this exact logic
drift out of sync exactly like the two-SQL-escapers problem this codebase
already rejected once, so this is the ONE shared implementation both
bridges call.

Deliberately domain-agnostic: this module knows nothing about SQL, OneNote
XML, or any adapter's own typed error taxonomy. It raises a single generic
`PsBridgeTransportError` — each adapter's thin wrapper catches that and
re-raises its own typed error (`WindowsSearchUnavailableError`,
`OneNoteUnavailableError`, ...) with the SAME message text (design.md
Decision 2). Message wording is parametrized by the caller-supplied
`log_label` so each adapter's error text reads naturally (e.g.
`log_label="search"` reproduces `PowerShellSearchBridge`'s exact,
already-tested wording byte-for-byte).
"""
import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

# Pinned to Windows PowerShell 5.1's absolute path — never a bare
# "powershell"/"pwsh" resolved via PATH, since System.Data.OleDb (and,
# for OneNote, some COM behaviors) are unreliable under PowerShell 7
# (pwsh) on the target hosts, per the powershell-search-bridge spec's
# "Host Pinning" requirement. Shared by every bridge transport instance.
_PS_EXE = r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"

# Sentinel object pushed onto a reader thread's queue to signal that the
# underlying stream reached clean EOF (or the read itself raised) — never
# mistaken for a real stdout line, which is always a `str`.
_STREAM_EOF = object()


class PsBridgeTransportError(Exception):
    """Generic failure raised by `PsBridgeTransport.invoke()` — spawn
    blocked, deadline/exit with no usable output, or genuinely corrupt
    (non-truncation) JSON Lines output. Domain-agnostic on purpose: every
    adapter's thin wrapper catches this and re-raises its own typed error
    with this exception's message text preserved verbatim (design.md
    Decision 2), so no caller should ever let this type itself escape to
    an MCP tool caller."""


class _CorruptLineSignal(Exception):
    """Internal-only signal: a complete stdout line (had every chance to
    be written in full) that still isn't valid JSON — genuine corruption,
    never a truncation artifact. Raised nowhere outside this module;
    `invoke()` catches it internally and re-raises `PsBridgeTransportError`
    with a distinctly-worded message."""


def _bridge_phrase(log_label: str) -> str:
    """Render the "PowerShell {label} bridge" phrase every parametrized
    failure message opens with — `log_label=""` (the default) reads as
    the bare "PowerShell bridge", never "PowerShell  bridge" (double
    space) or "PowerShell bridge bridge". `file_search_adapter.py` passes
    `log_label="search"` to reproduce `PowerShellSearchBridge`'s exact,
    already-tested wording byte-for-byte."""
    return f"PowerShell {log_label} bridge" if log_label else "PowerShell bridge"


def _diagnostic_suffix(exit_desc: str, stderr_excerpt: str) -> str:
    """Render the "(exit: ...; stderr: ...)" suffix every bridge failure
    message ends with (bridge-streaming-hotfix requirement 4) — an
    operator seeing a bridge-unavailable error should never have to guess
    whether the child ran at all, finished, or was killed, nor whether it
    said anything on stderr before that happened."""
    if stderr_excerpt:
        return f" (exit: {exit_desc}; stderr: {stderr_excerpt})"
    return f" (exit: {exit_desc})"


def _pump_stdout(stream: Any, out_queue: "queue.Queue[Any]") -> None:
    """Background-thread target: read `stream` (the child's stdout,
    opened in text mode) one line at a time via `readline()` and push
    each line onto `out_queue` as it arrives, followed by a single
    `_STREAM_EOF` marker once the stream reports clean EOF (`readline()`
    returning `""`) or the read itself raises.

    Runs on its own daemon thread because a real Windows pipe's
    `readline()` has no per-call timeout — it blocks until a line is
    available or the pipe closes. The only way `invoke()`'s deadline loop
    can still bound its OWN wait is by polling this queue with a timeout
    instead of calling `readline()` directly on the main thread: a thread
    stuck in a blocking `readline()` against a hung child is harmless (it
    is killed along with the child, or simply abandoned as a daemon
    thread) as long as the main thread never waits on it past the
    deadline."""
    try:
        while True:
            line = stream.readline()
            if line == "":
                break
            out_queue.put(line)
    except Exception:
        pass
    finally:
        out_queue.put(_STREAM_EOF)


def _pump_stderr(stream: Any, sink: list[str]) -> None:
    """Background-thread target: drain `stream` (the child's stderr) to
    EOF and append whatever text it produced to `sink` — a same-shaped
    daemon-thread reader as `_pump_stdout`, so stderr is never left
    unread while the main thread is busy enforcing the stdout deadline.
    `sink` is a plain `list[str]` (at most one entry appended) rather
    than a `queue.Queue`: nothing needs to consume this incrementally,
    only read it once after the child has been reaped, for the failure
    message's stderr excerpt."""
    try:
        data = stream.read()
        if data:
            sink.append(data)
    except Exception:
        pass


def _reap(process: Any) -> None:
    """Best-effort: wait for the child to actually exit, killing it first
    if a bounded wait shows it is still alive. Every call is itself
    bounded so a child that somehow never exits can't hang `invoke()`
    indefinitely — by the time this runs, either the sentinel/EOF was
    already seen on stdout, or the child was already asked to die via
    `process.kill()`, so this is cleanup/reap, not the primary control
    flow."""
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        return
    try:
        process.kill()
    except Exception:
        pass
    try:
        process.wait(timeout=5)
    except Exception:
        pass


class PsBridgeTransport:
    """Spawns one `powershell.exe` child per `invoke()` call — never a
    persistent daemon (design.md Decision 4) — runs the given script,
    and returns `(rows, truncated)`. See the module docstring for the
    full contract."""

    def invoke(
        self,
        script_path: Path,
        request: dict[str, Any],
        *,
        timeout: float,
        debug_log_enabled: Callable[[], bool] | None = None,
        log_label: str = "",
        logger: Callable[[str, dict[str, Any]], None] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Spawn the pinned PowerShell child via `Popen` (never
        `subprocess.run`), write `request` as a single JSON object to its
        stdin and close it, then read its JSON-Lines stdout
        INCREMENTALLY, line-by-line, off a background reader thread via a
        `queue.Queue` polled with a per-iteration timeout — the only way
        to enforce an overall wall-clock deadline given that a real
        Windows pipe's `readline()` has no timeout of its own (see
        `_pump_stdout`).

        Returns `(rows, results_truncated)`:
        - the `{"done": true, ...}` sentinel is reached -> `(rows, False)`
        - the deadline is hit, or the child dies/closes its stdout,
          before the sentinel, but at least one row already parsed
          cleanly -> `(rows, True)` — a RESULT, not an error: "a killed
          child that already streamed N lines yields N results."
        - the same as above but ZERO rows parsed -> raises
          `PsBridgeTransportError` (ambiguous/unusable — nothing to hand
          back), with a message naming the exit condition (the child's
          real exit code, or `killed@Ns` when the deadline itself
          triggered the kill) and, when present, the first ~200 chars of
          stderr.
        - a line that is NOT the last line still fails to parse -> genuine
          corruption -> raises `PsBridgeTransportError` distinctly worded
          from the above, also carrying the same exit/stderr diagnostic
          suffix.

        `diagnostics`, when given, is mutated in place (regardless of
        whether this call returns or raises) with `rows_streamed`/
        `sentinel_seen`/`exit_condition`/`stderr_excerpt`/
        `error_line_first_200` — letting a caller with its own, richer
        domain-specific debug log (e.g. `file_search_adapter.py`'s
        `_log_bridge_invocation`, which also records the SQL text) build
        that log line without duplicating this method's own bookkeeping.

        `debug_log_enabled`/`log_label`/`logger` are this transport's OWN
        generic debug-log hook, entirely separate from `diagnostics`: when
        `debug_log_enabled` is given and returns `True`, and `logger` is
        given, `logger(log_label, record)` is called exactly once with the
        same diagnostic fields — for an adapter (like the OneNote one)
        that has no richer domain-specific logger of its own yet. Neither
        is required; both default to doing nothing.

        The ENTIRE spawn+read+parse sequence is wrapped in a blanket
        `except Exception` (bottom of this method) mapping anything
        unforeseen to `PsBridgeTransportError` — the specific `except`
        clauses above it exist only to give an operator a distinct,
        actionable message per failure shape; the blanket clause is the
        actual contract enforcement (BUG-007 hotfix precedent)."""
        record: dict[str, Any] = diagnostics if diagnostics is not None else {}
        record.setdefault("rows_streamed", 0)
        record.setdefault("sentinel_seen", False)
        record.setdefault("exit_condition", "unknown")
        record.setdefault("stderr_excerpt", "")
        record.setdefault("error_line_first_200", "")
        try:
            return self._invoke_impl(script_path, request, timeout, log_label, record)
        finally:
            if debug_log_enabled is not None and logger is not None:
                try:
                    if debug_log_enabled():
                        logger(log_label, dict(record))
                except Exception:
                    pass

    def _invoke_impl(
        self,
        script_path: Path,
        request: dict[str, Any],
        timeout: float,
        log_label: str,
        record: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], bool]:
        """The actual spawn+read+parse sequence — split out of `invoke()`
        purely so the latter can wrap this in a `finally` that fires the
        generic debug-log hook exactly once regardless of how this
        returns/raises. `record` is mutated in place with whatever
        diagnostic detail is known by the time each exit point is
        reached."""
        try:
            try:
                process = subprocess.Popen(
                    [
                        _PS_EXE,
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(script_path),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    # Both bridge scripts pin [Console]::OutputEncoding to
                    # UTF-8; decoding with the locale's preferred encoding
                    # instead (the text=True default) made the reader die
                    # at the first non-ASCII byte on the deployed Windows
                    # host, silently truncating the stream (live-QA defect,
                    # add-onenote-adapter). errors="replace" degrades a
                    # rogue byte to U+FFFD rather than killing the stream —
                    # stdin stays ASCII-only via json.dumps' ensure_ascii.
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                # The child process never started at all: missing
                # powershell.exe, AppLocker/Constrained Language Mode
                # denial, permissions, etc. Distinguished from a
                # deadline/exit failure below (different operator
                # response) even though both map to the same error TYPE.
                record["exit_condition"] = "spawn_blocked"
                record["stderr_excerpt"] = str(exc)[:200]
                raise PsBridgeTransportError(
                    f"PowerShell bridge blocked or unavailable: {exc}"
                ) from exc

            try:
                process.stdin.write(json.dumps(request))
                process.stdin.close()
            except Exception:
                # A write/close failure here surfaces via the read-loop's
                # own diagnostics below (zero rows, no sentinel, whatever
                # exit code/stderr the child produced) rather than as its
                # own distinct error class.
                pass

            stdout_queue: "queue.Queue[Any]" = queue.Queue()
            stderr_sink: list[str] = []
            stdout_thread = threading.Thread(
                target=_pump_stdout, args=(process.stdout, stdout_queue), daemon=True
            )
            stderr_thread = threading.Thread(
                target=_pump_stderr, args=(process.stderr, stderr_sink), daemon=True
            )
            stdout_thread.start()
            stderr_thread.start()

            deadline = time.monotonic() + timeout
            rows: list[dict[str, Any]] = []
            done = False
            killed_by_deadline = False
            corruption: _CorruptLineSignal | None = None
            error_line_text = ""

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    killed_by_deadline = True
                    break
                try:
                    item = stdout_queue.get(timeout=remaining)
                except queue.Empty:
                    killed_by_deadline = True
                    break
                if item is _STREAM_EOF:
                    break
                terminated = item.endswith("\n")
                line = item.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except (json.JSONDecodeError, TypeError) as exc:
                    if terminated:
                        # A complete line (had every chance to be written
                        # in full) that still isn't valid JSON is genuine
                        # corruption, never a truncation artifact.
                        corruption = _CorruptLineSignal(line)
                        corruption.__cause__ = exc
                    # else: the literal tail fragment at raw EOF -- drop
                    # silently as the expected shape of a truncated read.
                    break
                if isinstance(parsed, dict) and parsed.get("done") is True:
                    done = True
                    break
                if isinstance(parsed, dict) and "error" in parsed:
                    # The script's own top-level catch writes a single
                    # valid-JSON {"error": "..."} line to STDOUT (not
                    # stderr) before exiting nonzero when a catastrophic
                    # failure happens before/during the read loop. It is
                    # syntactically valid JSON and is NOT the {"done":...}
                    # sentinel, so it must never be counted as a parsed
                    # data row. Folded into the stderr excerpt below for
                    # diagnostics, then treated exactly like a child that
                    # died with no sentinel.
                    error_line_text = str(parsed["error"])
                    stderr_sink.append(f"script error: {parsed['error']}")
                    break
                rows.append(parsed)

            if killed_by_deadline or corruption is not None:
                try:
                    process.kill()
                except Exception:
                    pass
            _reap(process)
            # Best-effort only: diagnostics below use whatever stderr
            # already arrived, and the outcome (rows/done/killed) was
            # already decided by the read loop above.
            stderr_thread.join(timeout=0.2)
            stdout_thread.join(timeout=0.2)

            stderr_excerpt = "".join(stderr_sink).strip()[:200]
            record["rows_streamed"] = len(rows)
            record["sentinel_seen"] = done
            record["stderr_excerpt"] = stderr_excerpt
            record["error_line_first_200"] = error_line_text[:200]

            if corruption is not None:
                record["exit_condition"] = "corrupt_line"
                diag = _diagnostic_suffix("killed after corrupt line", stderr_excerpt)
                raise PsBridgeTransportError(
                    f"{_bridge_phrase(log_label)} returned unparseable output "
                    f"(not valid JSON Lines){diag}"
                ) from corruption

            exit_desc = (
                f"killed@{timeout:g}s" if killed_by_deadline else f"exit code {process.returncode}"
            )
            record["exit_condition"] = exit_desc

            truncated = not done
            if not done and not rows:
                diag = _diagnostic_suffix(exit_desc, stderr_excerpt)
                raise PsBridgeTransportError(
                    f"{_bridge_phrase(log_label)} produced no usable output{diag}"
                )
            return rows, truncated
        except PsBridgeTransportError:
            raise
        except Exception as exc:
            # Blanket mapping: anything unforeseen -- spawning, reading,
            # or parsing -- becomes the same typed error the rest of this
            # method already raises for the cases it DID anticipate.
            record["exit_condition"] = f"exception: {exc}"
            raise PsBridgeTransportError(
                f"{_bridge_phrase(log_label)} failed unexpectedly: {exc}"
            ) from exc
