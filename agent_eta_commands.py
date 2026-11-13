"""Reconcile missed Codex command hooks with native completion evidence."""

import json


def completed_commands(path, wanted):
    """Return requested command IDs with a terminal native execution status.

    Stream the rollout rather than limiting this to its tail: a long active turn can
    leave old missed hooks far behind. Ignore command text and output entirely.
    Unknown, running, malformed and unreadable records never prove completion.
    """
    completed = set()
    try:
        with open(path, "rb") as handle:
            for line in handle:
                if b'CommandExecution' not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict) or record.get("type") != "event_msg":
                    continue
                payload = record.get("payload")
                if not isinstance(payload, dict) or payload.get("type") != "item_completed":
                    continue
                item = payload.get("item")
                if not isinstance(item, dict) or item.get("type") != "CommandExecution":
                    continue
                identifier = item.get("id")
                if not isinstance(identifier, str) or identifier not in wanted:
                    continue
                if item.get("status") in ("completed", "failed"):
                    completed.add(identifier)
                else:
                    completed.discard(identifier)
    except (OSError, TypeError):
        return set()
    return completed


def finished_tasks(directory, tasks, rollout):
    """Match pair-held Codex tasks only within their own thread's rollout.

    PID/lock holders and manual reminders have their own lifecycle. The callback
    resolves a thread to its native rollout; session records provide its path hint.
    """
    from pathlib import Path
    grouped = {}
    for task in tasks:
        thread = (task.get("session") or {}).get("id")
        identifier = task.get("id", "")
        if (task.get("agent") == "codex" and (task.get("holder") or {}).get("type") == "pair"
                and isinstance(thread, str) and isinstance(identifier, str) and identifier.startswith("codex-")):
            grouped.setdefault(thread, set()).add(identifier.removeprefix("codex-"))
    finished = set()
    for thread, wanted in grouped.items():
        hint = None
        # Never interpolate a transcript-provided thread ID into a filesystem path.
        if all(char.isalnum() or char in "-_" for char in thread):
            try:
                record = json.loads((Path(directory) / "sessions" / ("codex-" + thread + ".json")).read_text())
                hint = record.get("transcript") if isinstance(record, dict) else None
            except (OSError, ValueError):
                pass
        finished.update("codex-" + identifier for identifier in completed_commands(rollout(thread, hint), wanted))
    return finished
