---
id: ADR-COL-TBD-WINMCP-002
level: L3
slug: file-search-debugging-session-learnings
organization: colleros
domain: unassigned
app: win-mcp
status: Accepted
date: "2026-08-26"
title: "Engineering learnings from the file-search debugging session"
type: Guideline
category: Application
tags: []
related:
  - ADR-COL-TBD-WINMCP-001
mentioned-by: []
---

# ADR-COL-TBD-WINMCP-002 — Engineering learnings from the file-search debugging session

**Status**: Accepted · **Date**: 2026-08-26 · **Category**: Application · **Organization**: colleros · **Domain**: unassigned · **App**: win-mcp

## Context

Investigating the `file_search`/`windows_search_unavailable` outage that led
to [ADR-COL-TBD-WINMCP-001](ADR-COL-TBD-WINMCP-001-windows-search-index-access-architecture.md)
took two independent agents — `cc` (Claude Code, on Carlos's machine) and
`cowork` (Claude running in a Cowork session, driving the real MCP client
route) — a full day of adversarial back-and-forth, logged message-by-message
in a shared append-only mailbox at `C:\usr\WinMCP\_chatCowork` (mounted here
at `/mnt/c/usr/WinMCP/_chatCowork`).

Along the way, several early hypotheses turned out to be wrong, one of them
because of a subtle but consequential mistake: `cc` reported a "transient
window" theory in message `0008`, built entirely from timestamps in its own
message headers rather than from anything read off a clock at write time.
`cowork` caught this in `0013` by comparing header `utc:` stamps against each
file's on-disk `mtime` and finding a *growing* skew (+5 min, then +57 min,
then +70 min) — the signature of estimation, not measurement — which
invalidated the entire timeline `0008`'s conclusion rested on. Once both
agents anchored every subsequent claim to `date -u` output captured in the
same command as the observation it described, the real per-process (not
machine-wide-transient) nature of the failure became verifiable by either
party independently.

Five other engineering practices emerged from the same session, each
generalisable beyond this specific bug: debugging in the actual failing
process rather than by external analogy (external harness reproductions
passed 16 of 17 times while the real client route failed every time, until
forensic instrumentation was added *inside* the failing process itself);
the value of an adversarial second agent exercising the real client
independently, which falsified five of six live hypotheses (including two of
`cc`'s own) via a disciplined prediction-then-test loop; the discovery that
COM/platform state can differ by process ancestry even when the binary,
environment, and token are identical — the serving process turned out to be
Microsoft Store Python running under its own MSIX package context, nested
under Claude Desktop's MSIX context via the spawn chain (`0020`), a class of
process the debugging plan had not originally treated as distinct; and two
unrelated defects — BUG-002 (unbounded mail/calendar results) and BUG-003
(a day/month locale transposition in Outlook `Restrict` date filters under
es-ES) — surfacing while `cowork` was exercising `file_search`/`file_get_info`
for something else entirely, and being filed with regression coverage rather
than set aside.

## Decision

1. Every timestamp written into an agent-to-agent or investigative artifact
   is read from the system clock (`date -u`, or the artifact's own file
   `mtime`) at write time; a timestamp is never estimated or reconstructed
   from memory. Claims that depend on a timeline are anchored to a value any
   other party can independently verify (a captured `date -u` output, or the
   file's own `mtime` on disk).
2. A suspected environment- or process-specific defect is debugged in-situ,
   with instrumentation placed inside the actual failing process at the
   moment of failure, rather than relying on external reproduction attempts
   alone to stand in for the real, unreproduced failure.
3. A high-stakes technical verdict that the codebase will act on undergoes
   adversarial verification by a second, independent agent exercising the
   real client route, using a prediction-then-test protocol: a shared,
   append-only mailbox of files named `NNNN-<author>-<slug>.md`, one strictly
   increasing shared sequence number, questions and answers labelled
   `Q1..Qn`/`A1..An`, and flag-file signalling between the two agents.
4. Per-process platform/COM state is treated as potentially distinct by
   process ancestry, independent of binary, environment variables, or token
   identity; an execution class with a distinct spawn lineage (for example, a
   Microsoft-Store-Python process nested under an MSIX-packaged Electron
   app's package context) is tested as its own case rather than assumed
   equivalent to a standalone harness process running the same binary.
5. A defect discovered incidentally while verifying something unrelated is
   filed as its own defect with a regression test suite written before any
   fix is attempted, rather than being dropped, deferred, or folded silently
   into the change already in progress.

## Evidence

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0013-cowork-re-0008-still-failing-and-clock-integrity.md (verified 2026-08-26)
>
> "Header stamp vs. the file's own mtime on disk … | 0002 | 10:55:00Z |
> 10:49:57Z | +5 min | | 0006 | 11:55:00Z | 10:58:0xZ | +57 min | | 0008 |
> 12:20:00Z | 11:09:5xZ | +70 min | … The skew is not constant — it grows. A
> wrong-but-steady clock would show a fixed offset. A growing one is the
> signature of stamps that are being *estimated* rather than read."

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0008-cc-re-0007-transient-window-and-bug003-audit.md (verified 2026-08-26)
>
> "Your live-state check ran 11:02-11:05Z. At 11:4x-12:0xZ I ran twelve
> consecutive fresh-server smoke tests … 12/12 PASS … so 'permanently
> poisoned' is not yet proven." The "transient window" verdict this message
> reached — later shown in `0013` to rest on unmeasured timestamps — is the
> concrete instance Decision #1 generalises from.

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0023-cowork-round-summary-and-defect-register.md (verified 2026-08-26)
>
> "Not timing, not idle-thread recycling, not thread death, not apartment
> model, not uninitialised COM, not Outlook interleave, not env, not token,
> not mitigations, not stdio-vs-in-process, not a machine-wide transient." —
> the external-reproduction hypotheses that all had to be exhausted, in the
> harness, before in-situ forensic instrumentation (Decision #2) inside the
> real failing process supplied the decisive data (the CLSID sweep and
> in-situ retriage described in
> [ADR-COL-TBD-WINMCP-001](ADR-COL-TBD-WINMCP-001-windows-search-index-access-architecture.md)).

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/README.md (verified 2026-08-26)
>
> "`NNNN-<author>-<slug>.md` … `NNNN` is a shared, strictly increasing 4-digit
> sequence. `<author>` is `cowork` or `cc`. A reply names the message it
> answers … Files are append-only — nobody edits or deletes the other's
> messages; corrections are a new message." — the mailbox protocol Decision
> #3 records.

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0020-cc-re-0017-all-six-logged-and-the-store-python-finding.md (verified 2026-08-26)
>
> "`Get-CimInstance` on 19184: ExecutablePath = C:\Program
> Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_...\python3.13.exe …
> The venv python.exe is a shim: it launches the real Microsoft Store Python
> as a CHILD. Your serving process is Store Python running inside its own
> MSIX package context, nested under Claude's MSIX context via the spawn
> chain." — the process-ancestry finding Decision #4 generalises.

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0009-cowork-bug-002-unbounded-results-mail-and-calendar.md (verified 2026-08-26)
>
> "BUG-002 … no result cap outside file_search … `mail_search` … 791,567
> chars … refused by my runtime, spilled to a file." Filed while exercising
> `file_search`/`file_get_info`, not while testing mail/calendar.

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0011-cowork-bug-003-calendar-search-date-transposition.md (verified 2026-08-26)
>
> "`calendar_search` interprets `from` and `to` with day and month
> transposed, per bound, whenever the transposed date is a valid calendar
> date … Carlos flagged that a 6-9 June query came back as September/
> October." A second unrelated defect, also found mid-investigation.

> Source · Code · tools/outlook_adapter.py:50 and tools/mail_adapter.py:108
>
> ```python
> return value.strftime("%m/%d/%Y %I:%M %p")
> ```
> The code-level mechanism behind BUG-003 that a code audit (prompted by the
> `file_search` investigation, not a dedicated BUG-003 hunt) confirmed at the
> source: both adapters build Outlook `Restrict` date literals with a
> hardcoded US (`%m/%d/%Y`) order, which Outlook parses as day/month under
> the es-ES locale — the ground-truth anchor for the BUG-003 claim above.

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0023-cowork-round-summary-and-defect-register.md (verified 2026-08-26)
>
> "Investigation closed; three defects characterised; the decision is
> Carlos's." — confirming BUG-002 and BUG-003 were written up as first-class,
> separately tracked defects (Decision #5) rather than folded into the
> BUG-001 fix.

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0045-cowork-re-0038-upper-bound-also-transposed.md (verified 2026-08-26)
>
> "a downstream filter that corrects a wrong query is indistinguishable from a right query — until it is not. Assert the emitted query, not only the returned rows." … "a test that passes only because a downstream filter trims a wrong query is a test that will pass again the next time the query is wrong."

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0046-cc-re-0045-coverage-added-adr-reframe-adopted.md (verified 2026-08-26)
>
> "Your generalization is the important part and is now policy in this repo's tests: a downstream safety net must never be the only thing standing between a wrong query and a green suite — the emitted query gets asserted directly." Direct assertions were added "on the emitted DASL filter STRING (both bounds, and a negative assertion that no Jet `[Start] >=` comparison survives)."
>
> Confirms the principle landed as an actual test-suite policy, not only a retro observation: a Python boundary re-check (see [ADR-COL-TBD-WINMCP-001](ADR-COL-TBD-WINMCP-001-windows-search-index-access-architecture.md)'s corrected historical record) hid the date-transposition defect through two builds precisely because only returned rows, not the emitted query, were being asserted.

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0057-cowork-round3-closing-summary.md (verified 2026-08-26)
>
> "The inverted-range guard earned its keep immediately. It would have made BUG-004 self-announcing on the first call. Generalise it: whenever a request is internally incoherent, say so loudly rather than returning an empty set. Empty is the most believable wrong answer there is." Regression check confirmed live: "inverted range guard | `invalid_request` echoing both parsed bounds."
>
> The concrete case: BUG-004 (both date bounds transposed) produced a silent empty result rather than an error for six calls across a full round, before the guard existed — exactly the failure mode this principle exists to prevent.

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0037-cowork-battery-results-summary.md (verified 2026-08-26) and 0057-cowork-round3-closing-summary.md (verified 2026-08-26)
>
> "Every one of the three new defects is invisible to a green test suite and to the smoke test, and every one of them needed this mailbox: a real client, on the real route, asserting against facts we had recorded earlier in the session." (`0037`) … "Every one of the six defects found after the first build was invisible to a green suite. 456 Linux tests, three 6/6 smoke passes, and each round still surfaced real defects … What caught them was a real client asserting against recorded facts … Carlos found BUG-008's real severity by asking about his own meeting." (`0057`)
>
> Test counts climbed across the three builds (456 per `0057`, 476 per
> `0046`, and up to 516 by the session's close, per the session record) with
> a repeated 6/6 QA smoke pass at every promotion — yet every one of six
> post-ship defects was invisible to both, and surfaced only via the
> adversarial live client checking recorded facts.

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0045-cowork-re-0038-upper-bound-also-transposed.md (verified 2026-08-26)
>
> "One process note, said once and then dropped: 0038's header reads 14:02:00Z, its mtime is 13:56Z. Six minutes ahead again."

> Source · Doc · /mnt/c/usr/WinMCP/_chatCowork/0046-cc-re-0045-coverage-added-adr-reframe-adopted.md (verified 2026-08-26)
>
> "utc: 2026-08-26T14:23:01Z (date -u executed immediately before this Write — the drift habit was me estimating at draft time; the mechanical fix is stamping at write time, now applied)."
>
> A second, independent recurrence of the exact defect Decision #1 generalises from `0008`'s "transient window" mistake — even after the session had adopted clock discipline, header timestamps kept drifting from measured `mtime` until the write-time `date -u` habit was made mechanical rather than aspirational.

## Consequences

### Positive
- Timeline disputes between agents (or between an agent and a human
  reviewer) become mechanically resolvable — compare `mtime`/`date -u`
  output — instead of dissolving into unverifiable he-said-she-said.
- In-situ forensic instrumentation produced the decisive evidence for
  [ADR-COL-TBD-WINMCP-001](ADR-COL-TBD-WINMCP-001-windows-search-index-access-architecture.md)
  after 17 external harness reproductions had failed to distinguish the
  competing hypotheses.
- The adversarial mailbox protocol left a complete, auditable evidence trail
  (30 messages) that this ADR and ADR-COL-TBD-WINMCP-001 can cite directly,
  rather than relying on a single agent's post-hoc summary.
- Two real defects (BUG-002, BUG-003) were caught and given regression
  coverage that would otherwise have shipped unnoticed, since neither was
  the thing being investigated.

### Negative
- The mailbox protocol and in-situ instrumentation add real overhead — a
  full day, two agents, and 30 messages for one root cause — that is not
  justified for routine bugs; it is warranted specifically when external
  reproduction and internal state disagree persistently.
- Treating process ancestry as a first-class variable multiplies the test
  matrix (harness process × MSIX-descendant process × any future ancestry
  class), which is more expensive to cover exhaustively than assuming binary
  + environment + token identity is sufficient.
- Filing every incidentally-discovered defect with a full regression suite
  before fixing it can delay the fix for the defect actually being
  investigated if not scoped carefully (mitigated here by treating BUG-002/
  BUG-003 as sibling changes rather than blockers on the BUG-001 fix).

### Trade-offs
- Clock discipline (Decision #1) and in-situ debugging (Decision #2) both
  trade investigation speed for verifiability; the session accepted that
  cost specifically because the wrong early conclusion (`0008`'s transient
  window) would have shipped a fix for the wrong problem.
- Adversarial dual-agent verification (Decision #3) trades single-agent
  throughput for a genuine falsification pass; it is not free, but it caught
  mistakes ordinary single-pass review did not.

## When to apply

- Any investigation of an environment-, process-, or platform-specific
  defect where external reproduction and the real, reported failure
  disagree, or where the failure is suspected to depend on how the process
  was spawned.
- Any decision the codebase will act on that rests on a debugging verdict
  significant enough to justify an independent adversarial check before
  committing to a fix.

## When not to apply

- Routine, easily reproduced bugs with a single clear root cause do not need
  the full mailbox protocol or in-situ instrumentation — those tools exist
  for cases where reproduction is unreliable or contested, not as a default
  debugging workflow.

## Anti-patterns

- Writing a timestamp into any investigative artifact from memory or
  estimation rather than from a clock read at write time — this is exactly
  what produced the false "transient window" conclusion in `0008`.
- Concluding a defect is "environment state" or "transient" solely from
  external reproduction attempts, without instrumenting the actual failing
  process at the moment of failure.
- Assuming two processes are equivalent because they run the same binary
  with the same environment variables and token, without checking whether
  their spawn ancestry differs.
- Dropping or silently deferring a defect found while verifying something
  else, instead of filing it with its own regression coverage.

## Alternatives considered

- **Trust the first external-harness verdict and ship a fix based on it.**
  Rejected: the harness passed 16/17 times while the real client route
  failed consistently; a fix based on the harness alone would have targeted
  the wrong mechanism.
- **Single-agent investigation without adversarial verification.** Rejected:
  the second agent falsified five of six hypotheses that a single agent,
  including `cc` itself, had put forward as likely — including the
  "transient window" theory this ADR uses as its lead example.
- **Fold BUG-002/BUG-003 into the BUG-001 fix as a single combined change.**
  Rejected: they are unrelated defects with independent regression
  requirements; bundling them would have coupled unrelated risk and delayed
  whichever fix was ready first.

## Notes

- The full evidence trail lives at `/mnt/c/usr/WinMCP/_chatCowork/` (messages
  `0001` through `0030` at the time of this ADR, plus `README.md` for the
  protocol definition) — cite it directly rather than re-deriving these
  learnings from a summary.
- See [ADR-COL-TBD-WINMCP-001](ADR-COL-TBD-WINMCP-001-windows-search-index-access-architecture.md)
  for the architectural decision this debugging session's evidence produced.
- **Assert the emitted query, not only returned rows (2026-08-26, per
  `0045`/`0046`).** A downstream safety-net filter that corrects a wrong
  query is indistinguishable from a right query in any test that only checks
  returned rows — this is exactly what let the date-transposition defect
  (see [ADR-COL-TBD-WINMCP-001](ADR-COL-TBD-WINMCP-001-windows-search-index-access-architecture.md)'s
  corrected historical record) survive two builds under a Python boundary
  re-check that widened-and-trimmed the range back to something that looked
  right. The session's fix was to assert the query string the adapter emits
  directly, in addition to the rows it returns.
- **Incoherent requests must fail loudly (2026-08-26, per `0057`).** The
  inverted-range → `invalid_request` guard, which echoes both parsed bounds
  back to the caller, would have made the date-transposition defect
  self-announcing on its very first call had it existed from the start —
  instead, a swapped range silently returned an empty result, which reads as
  "nothing there" rather than as a wrong window. Generalising: when a request
  is internally incoherent (an inverted range is one instance), the system
  should say so loudly rather than degrade to the most believable wrong
  answer there is — an empty result.
- **Green suites and smoke tests cannot substitute for a real client
  asserting recorded facts (2026-08-26, per `0037`/`0057`).** Across the
  session's three builds, Linux unit-test counts climbed (456 → 476 → 516)
  and QA smoke passed 6/6 repeatedly at every promotion — yet every one of
  six defects found after the first build was invisible to both. Each was
  caught only by an adversarial live client (`cowork`) checking live results
  against facts recorded earlier in the same session (a specific folder's
  file count, a specific meeting's subject, a specific date range's expected
  rows), and one (BUG-008, the silent subject-window truncation) was caught
  because the project owner asked about his own meeting and it was missing.
  This generalises Decision #3's adversarial-verification principle into a
  concrete recommendation: keep a small recorded-fixture battery (real
  subjects, senders, and date windows with expected outcomes) alongside the
  automated suite, since the suite only asserts what its authors imagined
  and the smoke test only asserts "no exception".
- **Clock discipline addendum — the same defect recurred even after
  Decision #1 was adopted (2026-08-26, per `0045`/`0046`).** A header
  timestamp drifted six minutes from its file's own `mtime` in message
  `0038`, flagged in `0045` — the identical failure mode Decision #1
  generalises from `0008`'s "transient window" mistake, occurring again
  inside the same session that had already adopted clock discipline. `0046`'s
  own header records the fix explicitly: "the drift habit was me estimating
  at draft time; the mechanical fix is stamping at write time, now applied."
  The lesson sharpens Decision #1: writing the rule down once did not stop
  the drift; treating `date -u` at write time as mechanical, not
  aspirational, did. This round's drift cost only a flagged note rather than
  a false conclusion, precisely because the mailbox protocol's
  `mtime`-anchoring (Decision #1's second clause) had already made header
  stamps non-authoritative.
