#!/bin/sh
# Stands in for agent-eta in tst_usage.qml: `config get --json` prints limits.json beside it, and
# `config set` appends its pairs, one per line, to $AGENT_ETA_FAKE_LOG.
here=$(dirname "$0")

case "$1 $2" in
    "config get")
        cat "$here/limits.json"
        ;;
    "config set")
        shift 2
        printf '%s\n' "$@" >> "$AGENT_ETA_FAKE_LOG"
        ;;
    *)
        echo "fake agent-eta: unexpected $*" >&2
        exit 2
        ;;
esac
