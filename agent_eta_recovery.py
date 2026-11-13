"""Read-only diagnosis of handoffs whose controller no longer owns its source lock."""

import fcntl
import os
import re


def controller_active(root, source):
    """True for a held source lock, False for no owner, None if ownership is unreadable.

    The kernel releases this lock on SIGKILL. No PID guess or timeout can establish
    the same fact. Never create a lock or modify a handoff record while listing.
    """
    match = re.fullmatch(r"(claude|codex):([A-Za-z0-9._-]+)", source or "")
    if not match:
        return None
    path = os.path.join(root, "locks", "%s-%s.lock" % match.groups())
    try:
        with open(path, "r") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
            return False
    except FileNotFoundError:
        return False
    except OSError:
        return None


def recovery_view(record, root):
    """Describe interrupted ownership without cancelling a destination or thawing a source."""
    unresolved = record.get("state") in ("prepared", "launched") or record.get("source_paused")
    if record.get("state") == "completed" or not unresolved:
        return record
    if controller_active(root, record.get("source")) is not False:
        return record
    status = os.path.join(root, str(record.get("id") or ""), "status.json")
    destination = record.get("destination_id") or "from the handoff record"
    message = ("The handoff controller ended. The source may still be paused. Inspect %s. "
               "Confirm destination %s has stopped before running resume_source from that record."
               % (status, destination))
    return dict(record, state="interrupted", source_paused=True, error=message,
                recovery_required=True)
