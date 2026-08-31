#!/usr/bin/env bash
# watch-cowork.sh <mailbox-root> [since-file]
#
# Watches the WHOLE _chatCowork mailbox — every conversation subfolder plus the
# root index — polling every 120 seconds (same cadence as cowork's own inbox
# check). Exits 0 when anything new from cowork lands ANYWHERE, so the agent is
# re-invoked and can switch conversations if cowork opened or moved a topic.
#
# Fires on:
#   * a new/updated NNNN-cowork-*.md in any conversation subfolder
#   * an update to the root _CONVERSATIONS.md (new topic, status change)
#   * a brand-new conversation subfolder
#
# since-file: only events newer than this file's mtime count. Defaults to a
# marker created at watcher start (read the mailbox BEFORE starting the watcher;
# it only reports what arrives afterwards). Run in the background so the exit
# re-invokes the agent.

set -u
root="${1:?usage: watch-cowork.sh <mailbox-root> [since-file]}"
since="${2:-}"

if [ -z "$since" ]; then
  since="$(mktemp)"
  touch "$since"
fi

echo "watching mailbox: $root (all conversations)"
echo "since: $since ($(date -u -r "$since" +%Y-%m-%dT%H:%M:%SZ))"

while :; do
  events="$(
    find "$root" -mindepth 2 -maxdepth 2 -name '[0-9]*-cowork-*.md' -newer "$since" 2>/dev/null
    find "$root" -maxdepth 1 -name '_CONVERSATIONS.md' -newer "$since" 2>/dev/null
    find "$root" -mindepth 1 -maxdepth 1 -type d -newer "$since" 2>/dev/null
  )"
  events="$(echo "$events" | grep . | sort -u)"
  if [ -n "$events" ]; then
    echo "MAILBOX ACTIVITY (new since marker):"
    echo "$events"
    exit 0
  fi
  sleep 120
done
