---
name: cowork-debug
description: >
  Debug win-mcp cooperatively with a Claude Cowork session through the file mailbox
  at C:\usr\WinMCP\_chatCowork (WSL: /mnt/c/usr/WinMCP/_chatCowork). You are `cc`,
  the builder; `cowork` is the real MCP client that reports defects. Covers protocol
  v2 (per-conversation subfolders), message format, safety rules, and the 2-minute
  inbox watcher. Trigger: when the user says "debug with cowork", "check the mailbox",
  "reply to cowork", names _chatCowork, or asks to debug a win-mcp tool that cowork
  is testing (file_search, outlook, onenote).
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.0"
---

## When to Use

- A new bug report from `cowork` needs triage (`_CONVERSATIONS.md` shows an open topic)
- You are asked to reply, fix, ship a build, or answer questions in a mailbox conversation
- You need to wait for cowork's next message (use the watcher — never poll manually)

## The Environment

| actor | what it is | reach |
|-------|------------|-------|
| `cowork` | Claude Cowork session (cloud, via desktop bridge) | calls the deployed MCP tools like a real user; sees only the tool boundary |
| `cc` (**you**) | Claude Code on this machine | full repo `/home/master/WinMCP`, test suite, PS bridges from WSL, deploys |
| Carlos | owner | green-lights fixes, quits/restarts Claude Desktop, promotes |

Mailbox root: `/mnt/c/usr/WinMCP/_chatCowork/` (`C:\usr\WinMCP\_chatCowork`).
Canonical protocol: `0001-cowork-protocol-proposal.md` in that root (v2). Index:
`_CONVERSATIONS.md`. Cowork tests the **deployed** server (PRO `C:\usr\WinMCP`,
QA `C:\usr\WinMCP-qa`) — always check which package is live before blaming the repo.

## Critical Patterns — protocol v2

1. **One subfolder per conversation** (`onenote/`, `file_write/`, `meta/`). Sequence is
   local to the folder, starts at 0001. **cc takes EVEN numbers, cowork takes ODD.**
   Take the smallest even number above the folder's current max.
2. **Filename**: `NNNN-cc-<slug>.md`; replies prefix `re-NNNN-` (number in the same
   folder). Cross-folder references use the path: `file_write/0043`, never a bare number.
   The header's `reply-as:` field is **advisory** (meta/0003-0004): take the smallest
   free even number above the folder's current max regardless of what a message
   suggested — the `re-NNNN-` in the filename is the binding reference.
   Vocabulary: channel = chat = conversation = folder = topic (all mean one subfolder);
   *message* = one file, *round* = one probe batch + report, *mailbox* = the tree.
   A standing `general/` conversation exists for traffic control (redirection,
   availability, pointers) — never findings; findings always go in their topic folder.
3. **Header block** (mandatory):

        from:      cc
        to:        cowork
        utc:       <output of `date -u` AT WRITE TIME — never estimated>
        subject:   <one line>
        status:    OPEN | CLOSED
        reply-as:  NNNN-cowork-re-NNNN-<slug>.md
        conv:      <folder slug>
        build:     <buildId> @ <installRoot>   <- v2.1 rule 10 (meta/0006-0008, IN
                   FORCE): REQUIRED when the message reports tool calls; from a
                   server_info call in the SAME session as the probes (cc probing
                   below MCP states what it touched, e.g. "c40cb... @
                   C:\usr\WinMCP-qa (bridge invoked directly)" or "repo working
                   tree (unpackaged)"); literal "n/a - no tool calls" on
                   desk-reasoning messages; MANDATORY "unstamped
                   (pre-server_info) @ <root>" on pre-stamp deployments — a v2.1
                   message always states one of the three, never nothing

4. **After writing, touch the flag**: `touch <conv>/_INBOX-cowork.flag` — cowork stats
   that one file instead of scanning.
5. **Append-only.** Never edit or delete a cowork message. Corrections are a new
   message. Only the root protocol file and `_CONVERSATIONS.md` are living documents;
   changes to them are announced in `meta/`.
6. **Q/A labels**: cowork asks `Q1..Qn`; answer with the same labels `A1..An`.
7. **Timestamps from `date -u` at write time; timing claims anchored to file mtimes.**
   Estimated stamps once produced a wrong conclusion that cost twenty minutes.
8. **Closing**: closing message sets `status: CLOSED`; update the folder's line in
   `_CONVERSATIONS.md` with date + one-line outcome. Nothing is deleted.

## Safety rules (standing, learned the hard way)

- **OneNote writes touch only `z - Test Notebook`.** The server enforces an allowlist;
  never widen it to try something. The other notebooks are live business data.
- **Report before you retry.** The first observation is the evidence; a quietly-wrong
  tool result is worse than an error.
- Do the work before writing the report: verbatim args, verbatim responses, UTC per
  call, one retry to check reproducibility. One file per defect + a round summary.

## Promote notices (rule from onenote/0029-0031 — three falsifications in one day)

Never assert the reader's build state ("you are still on the old build", "restart
pending") — the writer knows an intention; only the reader can measure a fact.
A promote notice states: *promoted at HH:MMZ, buildId X; call `server_info` to see
whether your client has picked it up.* Nothing more.

## What makes a reply useful (from four working rounds)

- **Verbatim in, verbatim out** — paraphrased errors have cost hours.
- **A control group beats a theory** — show what works next to what fails.
- **State a prediction, then test it.**
- **Concede fast and in writing** when your hypothesis is refuted.
- Answer what only you can reach (source, logs, raw COM output, test suite) — that is
  the whole reason cc exists in this loop.

## Monitoring the mailbox (2-minute cadence, same as cowork)

While any conversation is active, run the watcher **in the background** (Bash
`run_in_background: true`). It watches the **whole mailbox** — every conversation
subfolder plus `_CONVERSATIONS.md` and new folders — not just the topic in hand, so
cowork can pull you to a different channel. It polls every 120 s and exits when
anything new from cowork lands, which re-invokes you. Never busy-poll inline.

```bash
# read the mailbox FIRST, then start the watcher (it reports only what arrives after)
bash .claude/skills/cowork-debug/assets/watch-cowork.sh /mnt/c/usr/WinMCP/_chatCowork
```

The since-marker defaults to watcher start time; pass a reference file as `$2` to
override (e.g. your last cc message, to catch anything you might have missed). When it
fires, read the new message(s) — in whichever conversation they landed — do the work,
reply with the next even number there, touch that folder's flag, and restart the
watcher while any conversation stays open.

## Commands

```bash
MB=/mnt/c/usr/WinMCP/_chatCowork

# state of play
cat $MB/_CONVERSATIONS.md
ls -lt $MB/<conv>/

# next even number for a folder (cc parity)
ls $MB/<conv>/ | grep -oP '^\d{4}' | sort -n | tail -1   # then next even above it

# write-time UTC for the header
date -u

# after writing a message
touch $MB/<conv>/_INBOX-cowork.flag

# wait for cowork — whole-mailbox watch (background, 120 s poll)
bash .claude/skills/cowork-debug/assets/watch-cowork.sh $MB
```

## Resources

- **Watcher**: [assets/watch-cowork.sh](assets/watch-cowork.sh)
- **Canonical protocol + report template**: `/mnt/c/usr/WinMCP/_chatCowork/`
  (`0001-cowork-protocol-proposal.md`, `_TEMPLATE-0001.md`, `README.md`)
