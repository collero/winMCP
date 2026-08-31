"""Tests for deploy/smoke_test.py — the stdlib-only, no-Outlook-required
unit-testable slice of the smoke test: `aggregate_verdict()` (pure) and
`run_family()` (duck-typed stub server, no subprocess/win32com), per the
smoke-test-coverage spec.

Everything else in deploy/smoke_test.py (the real subprocess spawn, the
real MCP handshake against a real `WinMCP.bat`/Outlook) is manual-
verification-only and NOT exercised here — see spec.md's "Live Execution
Is Manual-Verification-Only" requirement.
"""
import asyncio
import itertools
import json

import pytest
from fastmcp import Client

from deploy import smoke_test
from deploy.smoke_test import (
    EXPECTED_TOOLS,
    FAMILIES,
    FILES_FAMILY_DENIED_PROBE_SCOPE,
    FILES_FAMILY_FILENAME_PATTERN,
    Family,
    StepFailed,
    aggregate_verdict,
    do_tools_list,
    format_summary,
    run_family,
    run_files_family,
)


class StubServer:
    """Duck-typed stand-in for `ServerProcess`'s `.send()`/`.read_line()`
    interface (no subprocess, no threads). Scripted per tool name: feed it
    `{tool_name: {"result": {...}}}` or `{tool_name: {"error": {...}}}` and
    it echoes back a matching JSON-RPC response (with the request's own
    "id") the next time `read_line()` is called. A tool name may also be
    scripted with a *list* of responses, consumed in order (one per call)
    - needed for the `files` family, which calls `file_search` twice
    (roots-policy check, then the live-index check) with different
    expected outcomes."""

    def __init__(self, responses):
        self.responses = responses
        self.sent = []
        self._pending = []

    def send(self, message):
        self.sent.append(message)
        if "id" not in message:
            return  # fire-and-forget notification (e.g. notifications/initialized) - no response
        method = message.get("method")
        if method == "tools/call":
            tool_name = message["params"]["name"]
            scripted = self.responses[tool_name]
        else:
            scripted = self.responses[method]
        if isinstance(scripted, list):
            scripted = scripted.pop(0)
        self._pending.append(
            json.dumps({"jsonrpc": "2.0", "id": message["id"], **scripted})
        )

    def read_line(self, timeout):
        if not self._pending:
            return None
        return self._pending.pop(0)


class _StubServerWithLifecycle(StubServer):
    """Extends StubServer with the close()/stderr_tail() no-ops that
    main()'s handshake-failure path invokes on a real ServerProcess (see
    deploy/smoke_test.py:518-546), so main() can be driven end-to-end via a
    monkeypatched ServerProcess constructor — without spawning a real
    subprocess."""

    def close(self):
        pass

    def stderr_tail(self, max_lines=40):
        return ""


def _hit_result(entry_id):
    """Scripted tools/call success carrying >=1 hit, in the CURRENT
    envelope shape search tools return post search-result-caps (BUG-002):
    `structuredContent` is the envelope itself (`{"results": [...],
    "resultsTruncated": ...}`), not the old bare-list-wrapped-in-"result"
    shape - see `_hit_result_legacy_bare_list()` for that back-compat
    shape."""
    return {
        "result": {
            "structuredContent": {
                "results": [{"entryId": entry_id, "subject": "x"}],
                "resultsTruncated": False,
            },
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"results": [{"entryId": entry_id}], "resultsTruncated": False}
                    ),
                }
            ],
        }
    }


def _hit_result_legacy_bare_list(entry_id):
    """Scripted tools/call success in the OLD pre-envelope shape (a bare
    list, wrapped by FastMCP under `structuredContent["result"]` since a
    bare `list[...]` return type is not itself a JSON object) - kept to
    prove `_extract_list_result()` stays backward compatible."""
    return {
        "result": {
            "structuredContent": {"result": [{"entryId": entry_id, "subject": "x"}]},
            "content": [{"type": "text", "text": json.dumps([{"entryId": entry_id}])}],
        }
    }


def _empty_result():
    return {
        "result": {
            "structuredContent": {"results": [], "resultsTruncated": False},
            "content": [{"type": "text", "text": json.dumps({"results": [], "resultsTruncated": False})}],
        }
    }


def _tool_error(text):
    return {
        "result": {
            "isError": True,
            "content": [{"type": "text", "text": text}],
        }
    }


def _rpc_error(message):
    return {"error": {"code": -32000, "message": message}}


def _file_hit_result(path):
    """`file_search`'s response envelope (`FileSearchResponse`) - same
    `{"results": [...], "resultsTruncated": ...}` shape as the mail/
    calendar/task envelopes, per design.md's "Response envelope shape"
    decision."""
    return {
        "result": {
            "structuredContent": {
                "results": [{"path": path, "name": "x"}],
                "resultsTruncated": False,
            },
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"results": [{"path": path}], "resultsTruncated": False}
                    ),
                }
            ],
        }
    }


def test_all_pass_yields_smoke_test_passed():
    result = aggregate_verdict({"calendar": "pass", "tasks": "pass"})

    assert result == "SMOKE TEST PASSED"


def test_warning_with_no_fail_degrades_the_verdict():
    result = aggregate_verdict(
        {"calendar": "pass", "tasks": "warning", "mail-inbox": "pass", "mail-sent": "pass"}
    )

    assert result == "SMOKE TEST PASSED WITH WARNINGS"


def test_any_fail_wins_over_warning():
    result = aggregate_verdict({"calendar": "pass", "tasks": "warning", "mail-inbox": "fail"})

    assert result == "SMOKE TEST FAILED"


def test_mixed_combo_all_three_present_fails():
    result = aggregate_verdict(
        {"a": "pass", "b": "warning", "c": "fail", "d": "pass", "e": "warning"}
    )

    assert result == "SMOKE TEST FAILED"


def _mail_family():
    return Family(
        name="mail-inbox",
        search_tool="mail_search",
        search_args_fn=lambda: {"folder": "inbox"},
        detail_tool="mail_get_message",
    )


def test_search_hit_chains_the_detail_call_on_entry_id():
    server = StubServer(
        {
            "mail_search": _hit_result("E1"),
            "mail_get_message": {"result": {"content": [{"type": "text", "text": "{}"}]}},
        }
    )
    id_gen = itertools.count(1)

    verdict, lines = run_family(server, id_gen, _mail_family())

    assert verdict == "pass"
    detail_calls = [
        m
        for m in server.sent
        if m.get("method") == "tools/call" and m["params"]["name"] == "mail_get_message"
    ]
    assert len(detail_calls) == 1
    assert detail_calls[0]["params"]["arguments"] == {"entryId": "E1"}
    assert lines  # some human-readable note was produced


def test_empty_search_result_passes_without_chaining():
    server = StubServer({"task_search": _empty_result()})
    id_gen = itertools.count(1)
    family = Family(
        name="tasks",
        search_tool="task_search",
        search_args_fn=lambda: {},
        detail_tool="task_get_task",
    )

    verdict, lines = run_family(server, id_gen, family)

    assert verdict == "pass"
    detail_calls = [
        m
        for m in server.sent
        if m.get("method") == "tools/call" and m["params"]["name"] == "task_get_task"
    ]
    assert detail_calls == []
    assert any("no items to chain" in line for line in lines)


def test_search_hit_chains_the_detail_call_on_entry_id_legacy_bare_list_shape():
    """Back-compat: a pre-envelope bare-list `structuredContent["result"]`
    response must still chain the detail call - `_extract_list_result()`
    must keep supporting the old shape, not just the new envelope."""
    server = StubServer(
        {
            "mail_search": _hit_result_legacy_bare_list("E1"),
            "mail_get_message": {"result": {"content": [{"type": "text", "text": "{}"}]}},
        }
    )
    id_gen = itertools.count(1)

    verdict, lines = run_family(server, id_gen, _mail_family())

    assert verdict == "pass"
    detail_calls = [
        m
        for m in server.sent
        if m.get("method") == "tools/call" and m["params"]["name"] == "mail_get_message"
    ]
    assert len(detail_calls) == 1
    assert detail_calls[0]["params"]["arguments"] == {"entryId": "E1"}


def test_extract_list_result_unwraps_new_envelope_from_structured_content():
    result = {"structuredContent": {"results": [{"entryId": "E1"}], "resultsTruncated": False}}

    hits = smoke_test._extract_list_result(result, "")

    assert hits == [{"entryId": "E1"}]


def test_extract_list_result_unwraps_legacy_bare_list_from_structured_content():
    result = {"structuredContent": {"result": [{"entryId": "E1"}]}}

    hits = smoke_test._extract_list_result(result, "")

    assert hits == [{"entryId": "E1"}]


def test_extract_list_result_unwraps_new_envelope_from_text_fallback():
    text = json.dumps({"results": [{"entryId": "E1"}], "resultsTruncated": True})

    hits = smoke_test._extract_list_result({}, text)

    assert hits == [{"entryId": "E1"}]


def test_extract_list_result_unwraps_legacy_bare_list_from_text_fallback():
    text = json.dumps([{"entryId": "E1"}])

    hits = smoke_test._extract_list_result({}, text)

    assert hits == [{"entryId": "E1"}]


def test_extract_list_result_tolerates_snake_case_truncated_alias():
    """The truncation flag's key name (`resultsTruncated` vs
    `results_truncated`) must never affect unwrapping `results` -
    `_extract_list_result()` doesn't care about that field at all."""
    result = {
        "structuredContent": {"results": [{"entryId": "E1"}], "results_truncated": False}
    }

    hits = smoke_test._extract_list_result(result, "")

    assert hits == [{"entryId": "E1"}]


def test_extract_list_result_returns_empty_for_unparseable_input():
    hits = smoke_test._extract_list_result({}, "not json")

    assert hits == []


def test_extract_list_result_returns_empty_when_nothing_present():
    hits = smoke_test._extract_list_result({}, "")

    assert hits == []


def test_outlook_unavailable_error_yields_warning_not_fail():
    server = StubServer({"mail_search": _tool_error("win32com is not available")})
    id_gen = itertools.count(1)

    verdict, lines = run_family(server, id_gen, _mail_family())

    assert verdict == "warning"
    assert any("win32com is not available" in line for line in lines)


def test_other_error_yields_fail_not_warning():
    server = StubServer({"mail_search": _tool_error("Restrict() DASL syntax error")})
    id_gen = itertools.count(1)

    verdict, lines = run_family(server, id_gen, _mail_family())

    assert verdict == "fail"
    assert any("Restrict() DASL syntax error" in line for line in lines)


def test_step_failed_is_caught_inside_run_family_and_does_not_propagate():
    server = StubServer({"mail_search": _rpc_error("boom")})
    id_gen = itertools.count(1)

    # Must NOT raise StepFailed - it is caught internally and converted.
    try:
        verdict, lines = run_family(server, id_gen, _mail_family())
    except StepFailed:
        assert False, "run_family must catch StepFailed internally, not propagate it"

    assert verdict == "fail"
    assert lines and "boom" in lines[0]


def _mail_drafts_family():
    """Locate the real `mail-drafts` Family tuple from FAMILIES itself
    (rather than constructing one ad hoc, as `_mail_family()` does for
    mail-inbox) so these tests prove the actual FAMILIES wiring — folder,
    search tool, and detail tool — not just run_family()'s generic
    behavior (already covered by the mail-inbox tests above)."""
    matches = [family for family in FAMILIES if family.name == "mail-drafts"]
    assert len(matches) == 1, "expected exactly one 'mail-drafts' entry in FAMILIES"
    return matches[0]


def test_mail_drafts_family_present_with_correct_folder_and_detail_tool():
    """Per the smoke-test-coverage delta spec's "Per-Family Live Steps"
    requirement: a `mail-drafts` family must exist, searching
    folder="drafts" with a date bound and chaining mail_get_message —
    mirroring mail-inbox/mail-sent exactly."""
    family = _mail_drafts_family()

    assert family.search_tool == "mail_search"
    assert family.detail_tool == "mail_get_message"
    args = family.search_args_fn()
    assert args["folder"] == "drafts"
    assert "dateFrom" in args and "dateTo" in args


def test_mail_drafts_family_hit_chains_mail_get_message():
    server = StubServer(
        {
            "mail_search": _hit_result("D1"),
            "mail_get_message": {"result": {"content": [{"type": "text", "text": "{}"}]}},
        }
    )
    id_gen = itertools.count(1)

    verdict, lines = run_family(server, id_gen, _mail_drafts_family())

    assert verdict == "pass"
    detail_calls = [
        m
        for m in server.sent
        if m.get("method") == "tools/call" and m["params"]["name"] == "mail_get_message"
    ]
    assert len(detail_calls) == 1
    assert detail_calls[0]["params"]["arguments"] == {"entryId": "D1"}
    search_calls = [
        m
        for m in server.sent
        if m.get("method") == "tools/call" and m["params"]["name"] == "mail_search"
    ]
    assert search_calls[0]["params"]["arguments"]["folder"] == "drafts"


def test_mail_drafts_family_zero_hits_passes_without_chaining():
    server = StubServer({"mail_search": _empty_result()})
    id_gen = itertools.count(1)

    verdict, lines = run_family(server, id_gen, _mail_drafts_family())

    assert verdict == "pass"
    detail_calls = [
        m
        for m in server.sent
        if m.get("method") == "tools/call" and m["params"]["name"] == "mail_get_message"
    ]
    assert detail_calls == []
    assert any("no items to chain" in line for line in lines)


def test_expected_tools_matches_server_registered_names():
    """EXPECTED_TOOLS must equal exactly the 17 tools server.py registers
    (per the smoke-test-coverage spec's "Expected Tool Set Matches
    Registered Tools" requirement) - checked against fake adapters so this
    is import-time verifiable on Linux, no win32com/subprocess needed."""
    import server
    from tools.fake_adapter import FakeCalendarAdapter
    from tools.fake_file_search_adapter import FakeFileSearchAdapter
    from tools.fake_mail_adapter import FakeMailAdapter
    from tools.fake_onenote_adapter import FakeOneNoteAdapter
    from tools.fake_task_adapter import FakeTaskAdapter

    app = server.create_server(
        adapter=FakeCalendarAdapter(events=[]),
        task_adapter=FakeTaskAdapter(tasks=[]),
        mail_adapter=FakeMailAdapter(inbox=[]),
        file_search_adapter=FakeFileSearchAdapter(files=[]),
        onenote_adapter=FakeOneNoteAdapter(pages=[]),
    )

    async def _list_names():
        async with Client(app) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    names = asyncio.run(_list_names())

    assert EXPECTED_TOOLS == names


def test_tools_list_missing_tool_fails_naming_it():
    server = StubServer(
        {
            "tools/list": {
                "result": {
                    "tools": [
                        {"name": name}
                        for name in sorted(EXPECTED_TOOLS)
                        if name != "mail_get_message"
                    ]
                }
            }
        }
    )
    id_gen = itertools.count(1)

    with pytest.raises(StepFailed, match="mail_get_message"):
        do_tools_list(server, id_gen)


def test_format_summary_one_line_per_family_and_final_verdict():
    family_results = {
        "calendar": "pass",
        "tasks": "warning",
        "mail-inbox": "pass",
        "mail-sent": "pass",
    }
    overall = aggregate_verdict(family_results)

    summary = format_summary(family_results, overall)

    output_lines = summary.splitlines()
    assert len(output_lines) == len(family_results) + 1
    for name in family_results:
        assert any(name in line for line in output_lines[:-1])
    assert output_lines[-1] == overall == "SMOKE TEST PASSED WITH WARNINGS"


def test_format_summary_all_pass_final_line():
    family_results = {"calendar": "pass", "tasks": "pass"}
    overall = aggregate_verdict(family_results)

    summary = format_summary(family_results, overall)

    assert summary.splitlines()[-1] == "SMOKE TEST PASSED"


def test_main_fails_before_any_family_step_when_initialize_errors(monkeypatch, capsys):
    """smoke-test-coverage spec's "Initialize failure short-circuits all
    families" scenario: deploy/smoke_test.py:518-546 wraps
    do_initialize/do_notify_initialized_step/do_tools_list in one try block
    whose `except StepFailed` returns before the FAMILIES loop (and thus
    before run_family/any tools/call for a family search tool) ever runs.
    `ServerProcess` is monkeypatched to hand main() a StubServer instead of
    spawning a real subprocess, so this exercises main() itself rather than
    just do_initialize() in isolation."""
    server = _StubServerWithLifecycle({"initialize": _rpc_error("boom")})
    monkeypatch.setattr(smoke_test, "ServerProcess", lambda argv, cwd: server)

    exit_code = smoke_test.main(["--command", "unused"])

    assert exit_code == 1
    called_tool_names = {
        message["params"]["name"]
        for message in server.sent
        if message.get("method") == "tools/call"
    }
    assert called_tool_names == set()  # no family step ever ran
    captured = capsys.readouterr()
    assert "SMOKE TEST FAILED" in captured.out


def test_main_probes_roots_policy_with_fixed_synthetic_path_not_install_dir(monkeypatch):
    """main() must probe `_check_roots_policy` with the fixed synthetic
    `FILES_FAMILY_DENIED_PROBE_SCOPE`, never with the smoke test's own
    install directory (`script_dir`) - config/settings.yaml now ships a
    non-empty `file_search_allowed_roots` that includes `C:\\usr`, so an
    install under `C:\\usr\\...` would fall INSIDE an allowed root and the
    old install-dir probe would no longer be refused."""
    captured = {}

    def fake_run_files_family(
        server, id_gen, out_of_root_scope, filename_pattern=None, installed=None
    ):
        captured["scope"] = out_of_root_scope
        return "pass", []

    monkeypatch.setattr(smoke_test, "run_files_family", fake_run_files_family)
    responses = {
        "initialize": {"result": {"serverInfo": {}}},
        "tools/list": {
            "result": {"tools": [{"name": name} for name in sorted(EXPECTED_TOOLS)]}
        },
    }
    for family in FAMILIES:
        responses[family.search_tool] = _empty_result()
    server = _StubServerWithLifecycle(responses)
    monkeypatch.setattr(smoke_test, "ServerProcess", lambda argv, cwd: server)

    exit_code = smoke_test.main(["--command", "unused"])

    assert exit_code == 0
    assert captured["scope"] == FILES_FAMILY_DENIED_PROBE_SCOPE
    assert captured["scope"] == "C:\\winmcp-smoke-denied-probe"


def test_total_steps_accounts_for_families_plus_files_family():
    """`files` is driven by `run_files_family()` (a two-check special case),
    not a generic `Family` entry in FAMILIES, but it is still one live step
    - TOTAL_STEPS must count it."""
    assert smoke_test.TOTAL_STEPS == 3 + len(FAMILIES) + 1


def test_files_family_filename_pattern_is_a_plain_substring():
    """`file_search`'s `filename` is a case-insensitive *substring* match
    on `System.FileName`, not a glob - see the file-search spec's "Search
    Input Parameters" requirement and tools/file_search_adapter.py. A "*"
    would never literally appear in a filename, so the chosen pattern must
    not rely on glob syntax."""
    assert FILES_FAMILY_FILENAME_PATTERN
    assert "*" not in FILES_FAMILY_FILENAME_PATTERN


def test_files_family_passes_when_roots_refused_and_live_check_has_no_hits():
    server = StubServer(
        {
            "file_search": [
                _tool_error(
                    "[search_root_not_allowed] 'C:\\qa' is not contained "
                    "within an allowed search root"
                ),
                _empty_result(),
            ],
        }
    )
    id_gen = itertools.count(1)

    verdict, lines = run_files_family(server, id_gen, "C:\\qa")

    assert verdict == "pass"
    assert any("search_root_not_allowed" in line for line in lines)
    assert any("no items to chain" in line for line in lines)
    search_calls = [
        m
        for m in server.sent
        if m.get("method") == "tools/call" and m["params"]["name"] == "file_search"
    ]
    assert len(search_calls) == 2
    assert search_calls[0]["params"]["arguments"]["scope"] == "C:\\qa"
    assert "scope" not in search_calls[1]["params"]["arguments"]
    detail_calls = [
        m
        for m in server.sent
        if m.get("method") == "tools/call" and m["params"]["name"] == "file_get_info"
    ]
    assert detail_calls == []


def test_files_family_fails_when_out_of_root_scope_unexpectedly_succeeds():
    """If the probed out-of-root scope turns out to be inside an allowed
    root (this check's documented assumption breaks - e.g. someone allows
    `C:\\` wholesale), file_search must not silently succeed - the family
    FAILS, and the live-index check is never attempted."""
    server = StubServer({"file_search": [_empty_result()]})
    id_gen = itertools.count(1)

    verdict, lines = run_files_family(server, id_gen, "C:\\qa")

    assert verdict == "fail"
    assert any("succeed" in line.lower() for line in lines)
    search_calls = [
        m
        for m in server.sent
        if m.get("method") == "tools/call" and m["params"]["name"] == "file_search"
    ]
    assert len(search_calls) == 1


def test_files_family_fails_when_roots_check_error_has_wrong_code():
    server = StubServer(
        {"file_search": [_tool_error("[windows_search_unavailable] index down")]}
    )
    id_gen = itertools.count(1)

    verdict, lines = run_files_family(server, id_gen, "C:\\qa")

    assert verdict == "fail"
    assert any("search_root_not_allowed" in line for line in lines)
    search_calls = [
        m
        for m in server.sent
        if m.get("method") == "tools/call" and m["params"]["name"] == "file_search"
    ]
    assert len(search_calls) == 1  # live-index check never attempted


def test_files_family_live_hit_chains_file_get_info_on_path():
    server = StubServer(
        {
            "file_search": [
                _tool_error("[search_root_not_allowed] refused"),
                _file_hit_result("C:\\Users\\ana\\Desktop\\shortcut.lnk"),
            ],
            "file_get_info": {"result": {"content": [{"type": "text", "text": "{}"}]}},
        }
    )
    id_gen = itertools.count(1)

    verdict, lines = run_files_family(server, id_gen, "C:\\qa")

    assert verdict == "pass"
    detail_calls = [
        m
        for m in server.sent
        if m.get("method") == "tools/call" and m["params"]["name"] == "file_get_info"
    ]
    assert len(detail_calls) == 1
    assert detail_calls[0]["params"]["arguments"] == {
        "path": "C:\\Users\\ana\\Desktop\\shortcut.lnk"
    }


def test_files_family_live_check_detail_error_fails():
    server = StubServer(
        {
            "file_search": [
                _tool_error("[search_root_not_allowed] refused"),
                _file_hit_result("C:\\Users\\ana\\file.lnk"),
            ],
            "file_get_info": _tool_error("[file_not_found_in_index] boom"),
        }
    )
    id_gen = itertools.count(1)

    verdict, lines = run_files_family(server, id_gen, "C:\\qa")

    assert verdict == "fail"
    assert any("file_not_found_in_index" in line for line in lines)


# ---------------------------------------------------------------------------
# selective-tool-deployment Phase 5: derived EXPECTED_TOOLS +
# per-family skip-when-fully-disabled (smoke-test-coverage delta spec's
# "Expected Tool Set Matches Registered Tools" and "Per-Family Live
# Checks Scoped to Enabled Families" requirements).
#
# `_read_installed_tools(path)` is a stdlib-`re`-only scrape of the same
# flat `tools:` YAML list `tools/settings.py::installed_tools()` reads —
# deploy/smoke_test.py MUST NOT import `yaml` or `tools/catalog.py`
# (it must keep working even if the WinMCP .venv itself is broken), so it
# cannot reuse that accessor directly; this is the stdlib-only
# counterpart, parameterized by `path` (unlike `installed_tools()`,
# which reads a fixed location) so it's testable against a tmp_path file
# without touching the real filesystem.
# ---------------------------------------------------------------------------


def test_read_installed_tools_returns_none_when_file_absent(tmp_path):
    missing_path = tmp_path / "installed-tools.yaml"

    assert smoke_test._read_installed_tools(str(missing_path)) is None


def test_read_installed_tools_scrapes_flat_tools_list(tmp_path):
    path = tmp_path / "installed-tools.yaml"
    path.write_text("tools:\n  - calendar_search\n  - mail_search\n", encoding="utf-8")

    result = smoke_test._read_installed_tools(str(path))

    assert result == {"calendar_search", "mail_search"}


def test_read_installed_tools_returns_empty_set_for_empty_tools_list(tmp_path):
    """Triangulation: a present-but-empty `tools:` list (no `- name`
    lines at all) must scrape to an empty set, not `None` — `None` is
    reserved for the file being entirely absent."""
    path = tmp_path / "installed-tools.yaml"
    path.write_text("tools: []\n", encoding="utf-8")

    result = smoke_test._read_installed_tools(str(path))

    assert result == set()


def test_default_all_tools_is_the_full_17_tool_set():
    assert smoke_test._DEFAULT_ALL_TOOLS == EXPECTED_TOOLS
    assert len(smoke_test._DEFAULT_ALL_TOOLS) == 17


def test_compute_expected_tools_falls_back_to_default_when_installed_is_none():
    result = smoke_test._compute_expected_tools(None)

    assert result == smoke_test._DEFAULT_ALL_TOOLS


def test_compute_expected_tools_narrows_to_exactly_the_installed_set():
    narrowed = {"calendar_search", "calendar_get_event", "calendar_get_notes", "file_search", "file_get_info"}

    result = smoke_test._compute_expected_tools(narrowed)

    assert result == narrowed


def test_expected_tools_module_constant_is_default_all_tools_when_config_absent():
    """`EXPECTED_TOOLS` (the module-level constant every other test in
    this file already relies on) is computed at import time from
    whatever `config/installed-tools.yaml` sits next to the deployed
    `smoke_test.py` — absent in this dev/test checkout, so it must equal
    the full default set, matching every pre-existing assertion in this
    file that treats `EXPECTED_TOOLS` as the full 13-tool set."""
    assert EXPECTED_TOOLS == smoke_test._DEFAULT_ALL_TOOLS


# ---------------------------------------------------------------------------
# Per-family skip: run_family()/run_files_family() take an optional
# `installed` parameter (`None` by default — "all families run", the
# config-absent back-compat case). A family whose tools are *all* absent
# from a given, non-None `installed` set is skipped (verdict "skipped",
# no tools/call sent at all) rather than attempted; a family with *at
# least one* enabled tool still runs normally.
# ---------------------------------------------------------------------------


def test_run_family_skips_when_none_of_its_tools_are_enabled():
    server = StubServer({})
    id_gen = itertools.count(1)

    verdict, lines = run_family(server, id_gen, _mail_family(), installed={"calendar_search"})

    assert verdict == "skipped"
    assert server.sent == []
    assert any("skip" in line.lower() for line in lines)


def test_run_family_runs_normally_when_installed_is_none():
    server = StubServer({"mail_search": _empty_result()})
    id_gen = itertools.count(1)

    verdict, lines = run_family(server, id_gen, _mail_family(), installed=None)

    assert verdict == "pass"
    assert server.sent  # tools/call was actually attempted


def test_run_family_runs_when_at_least_one_of_its_tools_is_enabled():
    server = StubServer({"mail_search": _empty_result()})
    id_gen = itertools.count(1)

    verdict, lines = run_family(server, id_gen, _mail_family(), installed={"mail_search"})

    assert verdict == "pass"


def test_run_files_family_skips_when_none_of_its_tools_are_enabled():
    server = StubServer({})
    id_gen = itertools.count(1)

    verdict, lines = run_files_family(
        server, id_gen, "C:\\qa", installed={"calendar_search"}
    )

    assert verdict == "skipped"
    assert server.sent == []
    assert any("skip" in line.lower() for line in lines)


def test_run_files_family_runs_normally_when_installed_is_none():
    server = StubServer(
        {
            "file_search": [
                _tool_error("[search_root_not_allowed] refused"),
                _empty_result(),
            ]
        }
    )
    id_gen = itertools.count(1)

    verdict, lines = run_files_family(server, id_gen, "C:\\qa", installed=None)

    assert verdict == "pass"
    assert server.sent


def test_run_files_family_runs_when_file_search_is_enabled_but_file_get_info_is_not():
    server = StubServer(
        {
            "file_search": [
                _tool_error("[search_root_not_allowed] refused"),
                _empty_result(),
            ]
        }
    )
    id_gen = itertools.count(1)

    verdict, lines = run_files_family(server, id_gen, "C:\\qa", installed={"file_search"})

    assert verdict == "pass"


def test_skipped_verdict_is_neutral_in_aggregate_verdict():
    """A "skipped" family must never push the aggregate toward WARN/FAIL —
    the smoke-test-coverage delta's "must not fail the run" requirement."""
    result = aggregate_verdict({"calendar": "pass", "tasks": "skipped"})

    assert result == "SMOKE TEST PASSED"


def test_files_family_live_check_outlook_unavailable_hint_degrades_to_warning():
    """Not a realistic file_search failure mode in practice, but
    `run_files_family()` reuses `_call_tool()`'s OUTLOOK_UNAVAILABLE_HINTS
    tolerance for its live-index check, same as every other family."""
    server = StubServer(
        {
            "file_search": [
                _tool_error("[search_root_not_allowed] refused"),
                _tool_error("win32com is not available"),
            ]
        }
    )
    id_gen = itertools.count(1)

    verdict, lines = run_files_family(server, id_gen, "C:\\qa")

    assert verdict == "warning"
