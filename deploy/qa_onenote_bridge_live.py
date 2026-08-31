#!/usr/bin/env python3
"""Invoke the DEPLOYED QA onenote bridge like PsBridgeTransport does:
one JSON request on stdin, JSON Lines out. Prints rows with pageXml
elided, errors verbatim."""
import json
import subprocess
import sys

PS = "/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe"
SCRIPT = r"C:\usr\WinMCP-qa\tools\ps_bridge_onenote.ps1"


def invoke(request: dict) -> None:
    proc = subprocess.run(
        [PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", SCRIPT],
        input=json.dumps(request),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    print(f"--- op={request.get('op')} exit={proc.returncode}")
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            print("UNPARSEABLE:", line[:200])
            continue
        if isinstance(row, dict) and "pageXml" in row:
            row["pageXml"] = f"<elided {len(row['pageXml'])} chars>"
        print(json.dumps(row, ensure_ascii=False))
    if proc.stderr.strip():
        print("STDERR:", proc.stderr.strip()[:400])


if __name__ == "__main__":
    invoke(json.loads(sys.argv[1]))


# ---------------------------------------------------------------------------
# Live QA battery (onenote/0006 mailbox round, 2026-08-28) — run each op
# manually against the DEPLOYED QA bridge; writes touch `z - Test Notebook`
# ONLY. This file is the PERMANENT replacement for the wiped
# _qa_onenote_live.py driver (master copy lives in the repo, deploy/).
#
#   V6='{A3889785-CF0F-455B-AECE-1BF3F7328CA1}{1}{E1950122788719412414971969681220232700161751}'
#   SEC='{A3889785-CF0F-455B-AECE-1BF3F7328CA1}{1}{B0}'
#   1. GetPageContent V6            -> lastModified == page-XML value + section/notebook ids
#   2. UpdatePageContent V6, expectedLastModified = the value step 1 returned
#                                   -> SUCCESS (the round trip that could never pass before)
#   3. UpdatePageContent V6, stale  -> conflict, "re-read and retry" direction, values untruncated
#   4. UpdatePageContent V6, future -> conflict, "NEWER" direction
#   5. UpdatePageContent V6, NO expectedLastModified -> SUCCESS (unguarded escape hatch)
#   6. CreateNewPage into SEC       -> SUCCESS, row carries sectionId/notebookId
#   7. FindPages "QA live verification" -> rows carry sectionId/notebookId
#
# All 7 verified PASS against the 2026-08-28 QA deploy before the promote.
